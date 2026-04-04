"""
3-Tier Cache Manager for Google Luma.

Orchestrates the cache hierarchy:
  Tier 0: In-memory GraphRegistry (instant, per-process)
  Tier 1: Upstash Redis (hot, ephemeral, <50ms)
  Tier 2: Supabase Postgres + Storage (warm/cold, persistent, <2s)
  Fallback: Compute from scratch (OSMnx, VIIRS, KDE, etc.)

Key optimization: Stores ANNOTATED graphs in memory with their
time_context and weather_bucket. If the context hasn't changed,
subsequent requests skip the entire ML pipeline and go straight
to A* routing (<1s instead of ~30s).

Thread-safety:
  - GraphRegistry uses per-region asyncio.Lock to prevent duplicate downloads
  - Concurrent requests for the SAME region share one computation
  - Concurrent requests for DIFFERENT regions proceed in parallel
  - LRU eviction ensures bounded memory usage
"""
import asyncio
import logging
import math
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any, List

import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd

from core.config import settings
from cache.redis_client import RedisClient
from db.supabase_client import SupabaseClient
from services.storage_service import StorageService

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# In-Memory Graph Registry (LRU, thread-safe)
# ══════════════════════════════════════════════════════════════════════════════


class GraphRegistry:
    """
    In-memory LRU cache for loaded NetworkX graphs, features, and annotation state.

    Extended to cache:
    - graph: The NetworkX MultiDiGraph (potentially annotated with safety scores)
    - graph_id: Supabase UUID
    - static_features: Cached static features DataFrame
    - gdf_edges: Cached edge GeoDataFrame (expensive to compute repeatedly)
    - annotation_context: {time_context, weather_bucket} if annotated, else None
    """

    def __init__(self, max_size: int = None):
        self._max_size = max_size or settings.MAX_CACHED_GRAPHS
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._region_locks: Dict[str, asyncio.Lock] = {}
        self._meta_lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[dict]:
        """Get a cached entry, promoting it to most-recently-used."""
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    async def acquire_lock(self, key: str) -> asyncio.Lock:
        """Get or create a per-region lock (prevents duplicate computation)."""
        async with self._meta_lock:
            if key not in self._region_locks:
                self._region_locks[key] = asyncio.Lock()
            return self._region_locks[key]

    async def put(self, key: str, entry: dict):
        """Store an entry, evicting LRU if over capacity."""
        while len(self._cache) >= self._max_size:
            evicted_key, _ = self._cache.popitem(last=False)
            logger.info(f"LRU evicted graph region: {evicted_key}")
        self._cache[key] = entry
        self._cache.move_to_end(key)

    async def update(self, key: str, updates: dict):
        """Update fields of an existing entry without eviction."""
        if key in self._cache:
            self._cache[key].update(updates)
            self._cache.move_to_end(key)

    def current_size(self) -> int:
        return len(self._cache)


# ══════════════════════════════════════════════════════════════════════════════
# Cache Manager
# ══════════════════════════════════════════════════════════════════════════════


class CacheManager:
    """
    Orchestrates 3-tier cache for graphs, features, routes, and models.

    Key performance optimization: Tracks annotation context to skip the
    entire ML pipeline when the same graph is queried with the same
    time_context and weather_bucket. This reduces repeat-request latency
    from ~30s to <1s.
    """

    _instance: Optional["CacheManager"] = None

    def __init__(self):
        self.redis = RedisClient.get_instance()
        self.supabase = SupabaseClient.get_instance()
        self.storage = StorageService()
        self.graph_registry = GraphRegistry()
        self._enabled = settings.CACHE_ENABLED

    @classmethod
    def get_instance(cls) -> "CacheManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Key Generation ────────────────────────────────────────────────────────

    @staticmethod
    def region_key(center_lat: float, center_lon: float, radius_km: int) -> str:
        """Deterministic cache key for a geographic region."""
        return f"{center_lat}_{center_lon}_{radius_km}km"

    @staticmethod
    def route_key(
        src_lat: float, src_lon: float,
        dst_lat: float, dst_lon: float,
        mode: str, time_context: str,
    ) -> str:
        """Deterministic cache key for a computed route."""
        return (
            f"route:{round(src_lat,3)}_{round(src_lon,3)}_"
            f"{round(dst_lat,3)}_{round(dst_lon,3)}:{mode}:{time_context}"
        )

    @staticmethod
    def compute_region_params(
        lat1: float, lon1: float,
        lat2: float = None, lon2: float = None,
    ) -> Tuple[float, float, int]:
        """Compute rounded center and radius for a route request."""
        if lat2 is not None and lon2 is not None:
            center_lat = round((lat1 + lat2) / 2.0, 2)
            center_lon = round((lon1 + lon2) / 2.0, 2)
            R = 6371.0
            dlat = math.radians(lat2 - lat1)
            dlon = math.radians(lon2 - lon1)
            a = (
                math.sin(dlat / 2) ** 2
                + math.cos(math.radians(lat1))
                * math.cos(math.radians(lat2))
                * math.sin(dlon / 2) ** 2
            )
            dist_km = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            # 0.75x multiplier ensures both endpoints are covered (each is dist/2 from center)
            # Cap at 15km to prevent absurdly large downloads (21 tiles max)
            radius_km = max(5, min(15, int(math.ceil(dist_km * 0.75))))
        else:
            center_lat = round(lat1, 2)
            center_lon = round(lon1, 2)
            # 5km covers the user's immediate area — fast single-tile download
            radius_km = 5

        return center_lat, center_lon, radius_km

    @staticmethod
    def get_weather_bucket(weather_penalty: float) -> str:
        """Classify weather penalty into a bucket for cache keying."""
        if weather_penalty < 0.1:
            return "clear"
        elif weather_penalty < 0.3:
            return "mild"
        elif weather_penalty < 0.6:
            return "rain"
        else:
            return "storm"

    @staticmethod
    def get_time_context(is_night: int) -> str:
        return "night" if is_night == 1 else "day"

    # ══════════════════════════════════════════════════════════════════════════
    # Graph Loading (3-tier with per-region locking)
    # ══════════════════════════════════════════════════════════════════════════

    async def get_or_load_graph(
        self,
        lat1: float, lon1: float,
        lat2: float = None, lon2: float = None,
    ) -> Tuple[nx.MultiDiGraph, str, Optional[str]]:
        """
        Load a road network graph from the fastest available source.
        Returns: (graph, region_key, graph_id)
        """
        center_lat, center_lon, radius_km = self.compute_region_params(
            lat1, lon1, lat2, lon2
        )
        key = self.region_key(center_lat, center_lon, radius_km)

        # Tier 0: In-memory
        cached = await self.graph_registry.get(key)
        if cached:
            logger.info(f"Graph HIT [memory]: {key}")
            return cached["graph"], key, cached.get("graph_id")

        # Per-region lock: only one coroutine downloads; others wait
        lock = await self.graph_registry.acquire_lock(key)
        async with lock:
            # Double-check after acquiring lock
            cached = await self.graph_registry.get(key)
            if cached:
                logger.info(f"Graph HIT [memory, post-lock]: {key}")
                return cached["graph"], key, cached.get("graph_id")

            graph_id = None
            G = None

            # Tier 2: Supabase Postgres → Storage
            if self._enabled and self.supabase.is_available:
                record = await asyncio.to_thread(
                    self.supabase.find_region_graph,
                    center_lat, center_lon, radius_km,
                )
                if record:
                    graph_id = record["id"]
                    logger.info(f"Graph metadata HIT [Supabase]: {key}")
                    G = await asyncio.to_thread(
                        self.storage.download_graph, record["storage_path"]
                    )
                    if G is not None:
                        G = await asyncio.to_thread(
                            self._ensure_graph_attributes, G
                        )

            # Tier 3: Download from OSMnx (expensive — last resort)
            if G is None:
                logger.info(f"Graph MISS — downloading from OSMnx: {key}")
                G = await asyncio.to_thread(
                    self._download_fresh_graph,
                    center_lat, center_lon, lat1, lon1, lat2, lon2, radius_km,
                )

                # Persist to Supabase for future users
                if self._enabled and self.supabase.is_available and G is not None:
                    storage_path = f"graphs/{key}.graphml.gz"
                    uploaded = await asyncio.to_thread(
                        self.storage.upload_graph, G, storage_path
                    )
                    if uploaded:
                        record = await asyncio.to_thread(
                            self.supabase.upsert_region_graph,
                            center_lat, center_lon, radius_km,
                            storage_path, len(G.nodes), len(G.edges), 0,
                        )
                        if record:
                            graph_id = record["id"]

            if G is None:
                raise RuntimeError(
                    f"Failed to load graph for region {key}. "
                    "Check network connectivity and coordinate validity."
                )

            # Pre-compute gdf_edges (expensive — cache alongside graph)
            gdf_edges = await asyncio.to_thread(
                lambda: ox.graph_to_gdfs(G, nodes=False)
            )

            # Store in memory
            await self.graph_registry.put(key, {
                "graph": G,
                "graph_id": graph_id,
                "gdf_edges": gdf_edges,
                "static_features": None,
                "annotation_context": None,
            })

            logger.info(
                f"Graph loaded: {key} — {len(G.nodes)} nodes, "
                f"{len(G.edges)} edges (memory: {self.graph_registry.current_size()}/{settings.MAX_CACHED_GRAPHS})"
            )
            return G, key, graph_id

    def _download_fresh_graph(
        self, center_lat, center_lon, lat1, lon1, lat2, lon2, radius_km
    ):
        """Synchronous graph download via GraphManager (runs in thread pool)."""
        from data.graph_manager import GraphManager

        gm = GraphManager(cache_dir=settings.GRAPH_DATA_DIR)
        return gm.load_graph_dynamically(lat1, lon1, lat2, lon2, radius_km_override=radius_km)

    def _ensure_graph_attributes(self, G):
        """Ensure speed/travel_time attributes exist."""
        edges = list(G.edges(data=True))
        if edges and "travel_time" not in edges[0][2]:
            logger.info("Imputing missing speed/travel_time on cached graph...")
            G = ox.add_edge_speeds(G)
            G = ox.add_edge_travel_times(G)
        return G

    # ══════════════════════════════════════════════════════════════════════════
    # Static Feature Loading (lighting, crime, POI, vegetation)
    # ══════════════════════════════════════════════════════════════════════════

    async def get_or_compute_static_features(
        self,
        G: nx.MultiDiGraph,
        graph_id: Optional[str],
        region_key: str,
    ) -> pd.DataFrame:
        """
        Load or compute STATIC safety features (excludes weather and time).
        Checks in-memory cache first for maximum speed.
        """
        # Check in-memory first
        cached = await self.graph_registry.get(region_key)
        if cached and cached.get("static_features") is not None:
            logger.info(f"Static features HIT [memory]: {region_key}")
            return cached["static_features"]

        # Tier 2: Supabase — check for persisted features
        if self._enabled and graph_id and self.supabase.is_available:
            record = await asyncio.to_thread(
                self.supabase.find_cached_features, graph_id
            )
            if record:
                logger.info(f"Static features HIT [Supabase]: {region_key}")
                df = await asyncio.to_thread(
                    self.storage.download_features, record["storage_path"]
                )
                if df is not None:
                    # Cache in memory
                    await self.graph_registry.update(region_key, {"static_features": df})
                    return df

        # Compute from scratch
        logger.info(f"Static features MISS — computing: {region_key}")
        df = await asyncio.to_thread(
            self._compute_static_features, G, region_key
        )

        # Cache in memory
        await self.graph_registry.update(region_key, {"static_features": df})

        # Persist for future use
        if self._enabled and graph_id and self.supabase.is_available and df is not None:
            storage_path = f"features/{region_key}.parquet.gz"
            uploaded = await asyncio.to_thread(
                self.storage.upload_features, df, storage_path
            )
            if uploaded:
                await asyncio.to_thread(
                    self.supabase.upsert_cached_features,
                    graph_id, storage_path, len(df),
                )

        return df

    def _compute_static_features(
        self, G: nx.MultiDiGraph, region_key: str
    ) -> pd.DataFrame:
        """Compute only the STATIC features that can be cached."""
        from services.feature_engineering import SafetyFeatureEngineer
        from services.data_loaders import CrimeDataLoader, POILoader

        # 1. Crime KDE data
        crime_loader = CrimeDataLoader()
        kde_model = crime_loader.get_kde_model()

        # 2. POI data (check Supabase cache first)
        poi_coords = self._get_cached_or_fresh_pois(G)

        # 3. Identify region from graph node coordinates (fast, no CRS warning)
        nodes_df = ox.graph_to_gdfs(G, edges=False)
        center_lat = float(nodes_df["y"].mean())
        center_lon = float(nodes_df["x"].mean())
        nearest_city = crime_loader.identify_nearest_city(center_lat, center_lon)
        regional_multiplier = crime_loader.get_regional_crime_multiplier(nearest_city)

        # 4. VIIRS Data — try Supabase table, then direct storage path fallback
        viirs_tile = None
        if self._enabled and self.supabase.is_available:
            # Method 1: Look up in viirs_tiles table
            record = self.supabase.find_viirs_tile(nearest_city)
            if record:
                try:
                    viirs_tile = self.storage.download_numpy(record["storage_path"])
                    if viirs_tile is not None:
                        logger.info(f"VIIRS tile loaded for {nearest_city} [table lookup]")
                    else:
                        logger.warning(f"VIIRS tile download returned None for {nearest_city}")
                except Exception as e:
                    logger.warning(f"Failed to load VIIRS tile from table: {e}")

            # Method 2: Try direct convention-based path if table lookup failed
            if viirs_tile is None:
                direct_path = f"viirs-tiles/{nearest_city.strip().lower()}.npz"
                try:
                    viirs_tile = self.storage.download_numpy(direct_path)
                    if viirs_tile is not None:
                        logger.info(f"VIIRS tile loaded for {nearest_city} [direct path: {direct_path}]")
                except Exception:
                    logger.info(f"No VIIRS tile found at {direct_path} — using road-type lighting")

        # 5. Build feature engineer with static data only
        # Get cached gdf_edges for this region
        cached_entry = None
        # Synchronous access since we're already in a thread
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in asyncio.to_thread — can't await, use direct dict access
                for key, entry in self.graph_registry._cache.items():
                    if key == region_key:
                        cached_entry = entry
                        break
        except RuntimeError:
            pass

        gdf_edges_cache = cached_entry.get("gdf_edges") if cached_entry else None

        engineer = SafetyFeatureEngineer(
            kde_model=kde_model,
            poi_coords=poi_coords,
            viirs_tile=viirs_tile,
            weather_penalty=0.0,
            regional_crime_multiplier=regional_multiplier,
        )

        features_df = engineer.generate_edge_features(
            G, current_time=None, gdf_edges_cache=gdf_edges_cache
        )

        # Keep only the static columns
        static_cols = [
            "lighting_score", "crime_density", "poi_density",
            "vegetation_isolation", "length_m",
        ]
        available = [c for c in static_cols if c in features_df.columns]
        static_df = features_df[available].copy()

        logger.info(f"Static features computed: {len(static_df)} edges, columns={available}")
        return static_df

    def _get_cached_or_fresh_pois(self, G) -> list:
        """Check POI cache in Supabase before hitting the Overpass API."""
        from services.data_loaders import POILoader

        nodes = ox.graph_to_gdfs(G, edges=False)
        north = round(nodes["y"].max(), 2)
        south = round(nodes["y"].min(), 2)
        east = round(nodes["x"].max(), 2)
        west = round(nodes["x"].min(), 2)
        bbox_key = f"{north}_{south}_{east}_{west}"

        # Check Supabase
        if self._enabled and self.supabase.is_available:
            record = self.supabase.find_poi_cache(bbox_key)
            if record and record.get("poi_data"):
                logger.info(f"POI HIT [Supabase]: {bbox_key} ({record['poi_count']} POIs)")
                return [(p["lat"], p["lon"]) for p in record["poi_data"]]

        # Fresh download from Overpass
        poi_coords = POILoader.extract_osm_pois(G)

        # Cache in Supabase
        if self._enabled and self.supabase.is_available and poi_coords:
            poi_data = [{"lat": lat, "lon": lon} for lat, lon in poi_coords]
            self.supabase.upsert_poi_cache(bbox_key, poi_data, len(poi_data))

        return poi_coords

    # ══════════════════════════════════════════════════════════════════════════
    # Dynamic Feature Merging (weather + time — always live)
    # ══════════════════════════════════════════════════════════════════════════

    def merge_dynamic_features(
        self,
        static_features: pd.DataFrame,
        G: nx.MultiDiGraph,
        weather_penalty: float,
        is_night: int,
        gdf_edges_cache=None,
    ) -> pd.DataFrame:
        """
        Merge cached static features with live dynamic features.
        Uses cached gdf_edges when available to avoid expensive re-computation.
        """
        full = static_features.copy()

        # Inject live weather
        full["weather_risk"] = weather_penalty

        # Inject live time context
        full["is_night"] = is_night

        # Recompute footfall_proxy (depends on POI density + road type + is_night)
        if gdf_edges_cache is not None:
            gdf_edges = gdf_edges_cache
        else:
            gdf_edges = ox.graph_to_gdfs(G, nodes=False)

        highway_series = (
            gdf_edges["highway"]
            if "highway" in gdf_edges.columns
            else pd.Series(["residential"] * len(full))
        )
        # Align index
        highway_series.index = full.index

        from services.feature_engineering import SafetyFeatureEngineer
        engineer = SafetyFeatureEngineer.__new__(SafetyFeatureEngineer)
        full["footfall_proxy"] = engineer._compute_footfall_proxy(
            full["poi_density"].values, highway_series, is_night
        )

        return full

    # ══════════════════════════════════════════════════════════════════════════
    # Annotation Context Check (skip re-annotation when possible)
    # ══════════════════════════════════════════════════════════════════════════

    async def check_annotation_context(
        self, region_key: str, time_context: str, weather_bucket: str
    ) -> Optional[dict]:
        """
        Check if the cached graph is already annotated for the current context.
        Returns the cached entry if annotation is still valid, else None.
        """
        cached = await self.graph_registry.get(region_key)
        if cached is None:
            return None

        ctx = cached.get("annotation_context")
        if ctx is None:
            return None

        if ctx.get("time_context") == time_context and ctx.get("weather_bucket") == weather_bucket:
            logger.info(
                f"Annotation context HIT [memory]: {region_key} "
                f"({time_context}/{weather_bucket})"
            )
            return cached

        # Context changed — need re-annotation
        logger.info(
            f"Annotation context STALE: {region_key} "
            f"(cached={ctx.get('time_context')}/{ctx.get('weather_bucket')} "
            f"→ current={time_context}/{weather_bucket})"
        )
        return None

    async def update_annotation_context(
        self, region_key: str, time_context: str, weather_bucket: str
    ):
        """Mark the cached graph as annotated for the given context."""
        await self.graph_registry.update(region_key, {
            "annotation_context": {
                "time_context": time_context,
                "weather_bucket": weather_bucket,
            }
        })

    # ══════════════════════════════════════════════════════════════════════════
    # ML Model Cache
    # ══════════════════════════════════════════════════════════════════════════

    async def get_or_load_model(self, region_key: str):
        """Load a pre-trained XGBoost model from Supabase, or return None."""
        if not self._enabled or not self.supabase.is_available:
            return None
        try:
            record = await asyncio.to_thread(
                self.supabase.find_ml_model, region_key
            )
            if record:
                logger.info(f"ML model HIT [Supabase]: {region_key}")
                model = await asyncio.to_thread(
                    self.storage.download_model, record["storage_path"]
                )
                return model
        except Exception as e:
            logger.warning(f"Model cache lookup failed: {e}")
        return None

    async def store_model(
        self, model, region_key: str, training_edges: int,
        feature_importance: dict = None,
    ):
        """Persist a trained model to Supabase Storage."""
        if not self._enabled or not self.supabase.is_available:
            return
        try:
            storage_path = f"models/{region_key}.pkl.gz"
            uploaded = await asyncio.to_thread(
                self.storage.upload_model, model, storage_path
            )
            if uploaded:
                await asyncio.to_thread(
                    self.supabase.upsert_ml_model,
                    region_key, storage_path, training_edges,
                    feature_importance,
                )
        except Exception as e:
            logger.warning(f"Model store failed: {e}")

    # ══════════════════════════════════════════════════════════════════════════
    # Route Cache
    # ══════════════════════════════════════════════════════════════════════════

    async def find_cached_routes(
        self,
        src_lat: float, src_lon: float,
        dst_lat: float, dst_lon: float,
        time_context: str,
        travel_profile: str = "driving",
    ) -> Optional[List[dict]]:
        """Look up pre-computed routes for all 3 modes."""
        s_lat, s_lon = round(src_lat, 3), round(src_lon, 3)
        d_lat, d_lon = round(dst_lat, 3), round(dst_lon, 3)

        # Check Redis first (fastest) — profile avoids mixing car vs walk geometry
        redis_key = f"routes:{s_lat}_{s_lon}_{d_lat}_{d_lon}:{time_context}:{travel_profile}"
        if self.redis.is_available:
            cached = self.redis.get_json(redis_key)
            if cached:
                logger.info(f"Route HIT [Redis]: {redis_key}")
                return cached

        # Postgres cache has no travel_profile column — only use for legacy driving rows
        if travel_profile != "driving":
            return None

        # Check Supabase
        if self._enabled and self.supabase.is_available:
            routes = []
            for mode in ["fastest", "balanced", "safest"]:
                record = await asyncio.to_thread(
                    self.supabase.find_cached_route,
                    s_lat, s_lon, d_lat, d_lon, mode, time_context,
                )
                if record:
                    routes.append(record)
                else:
                    break

            if len(routes) == 3:
                logger.info(f"Route HIT [Supabase]: {redis_key}")
                self.redis.set_json(redis_key, routes, settings.ROUTE_CACHE_TTL)
                return routes

        return None

    async def store_route_cache(
        self,
        src_lat: float, src_lon: float,
        dst_lat: float, dst_lon: float,
        time_context: str,
        weather_bucket: str,
        routes_data: list,
        graph_id: Optional[str] = None,
        travel_profile: str = "driving",
    ):
        """Persist computed routes to both Redis and Supabase."""
        s_lat, s_lon = round(src_lat, 3), round(src_lon, 3)
        d_lat, d_lon = round(dst_lat, 3), round(dst_lon, 3)

        redis_key = f"routes:{s_lat}_{s_lon}_{d_lat}_{d_lon}:{time_context}:{travel_profile}"
        self.redis.set_json(redis_key, routes_data, settings.ROUTE_CACHE_TTL)

        if self._enabled and self.supabase.is_available and travel_profile == "driving":
            for route in routes_data:
                await asyncio.to_thread(
                    self.supabase.insert_route_cache,
                    s_lat, s_lon, d_lat, d_lon,
                    route.get("mode", "balanced"),
                    time_context, weather_bucket,
                    route.get("route_geometry", []),
                    route.get("estimated_time_seconds", 0),
                    route.get("average_safety_score", 0),
                    route.get("total_cost", 0),
                    graph_id,
                )

    # ══════════════════════════════════════════════════════════════════════════
    # Heatmap Cache
    # ══════════════════════════════════════════════════════════════════════════

    def get_cached_heatmap(self, region_key: str, time_context: str) -> Optional[dict]:
        """Check Redis for a cached heatmap payload."""
        redis_key = f"heatmap:{region_key}:{time_context}"
        return self.redis.get_json(redis_key)

    def store_heatmap(self, region_key: str, time_context: str, data: dict):
        """Cache a heatmap payload in Redis."""
        redis_key = f"heatmap:{region_key}:{time_context}"
        self.redis.set_json(redis_key, data, settings.HEATMAP_CACHE_TTL)
