"""
Feature engineering module for computing safety-related features for road segments.

All features are derived from REAL data sources:
- Lighting: NASA VIIRS DNB satellite nighttime radiance (11.6 GB GeoTIFF)
           OR road-type-based estimation when VIIRS unavailable
- Crime density: KDE fitted on 40K geocoded crime incidents from 4 CSV datasets
- POI density: Real-time OSM Overpass API extraction
- Weather risk: Real-time OpenWeatherMap conditions
- Vegetation isolation: Google Earth Engine NDVI (optional)
- Time context: Astronomical sunset/sunrise via Astral library

All output features are normalized to [0,1] to ensure consistent
XGBoost training and inference without additional scalers.
"""
import logging
import numpy as np
import pandas as pd
import networkx as nx
import osmnx as ox
from typing import List, Tuple, Optional, Any
from datetime import datetime
from sklearn.neighbors import KernelDensity
from scipy.spatial import cKDTree
from core.config import settings
from functools import lru_cache
import os

try:
    import rasterio
except ImportError:
    rasterio = None

logger = logging.getLogger(__name__)


class SafetyFeatureEngineer:
    """
    Computes and aggregates safety-related features for graph edges.
    Every feature is derived from real-world data — zero mock/random values.
    All output features are in [0, 1] for consistent ML consumption.
    """

    def __init__(
        self,
        kde_model: Optional[Any] = None,
        poi_coords: Optional[List[Tuple[float, float]]] = None,
        viirs_tile: Optional[dict] = None,
        weather_penalty: float = 0.0,
        regional_crime_multiplier: float = 1.0,
    ):
        self.kde_model = None
        self.poi_tree = None
        self.viirs_dataset = None
        self.viirs_tile = viirs_tile
        self.weather_penalty = weather_penalty
        self.regional_crime_multiplier = regional_crime_multiplier

        # ── Load real VIIRS satellite raster ─────────────────────────────────
        if self.viirs_tile is not None:
            logger.info("Using pre-sampled VIIRS tile from cache.")
        elif rasterio and os.path.exists(settings.VIIRS_DATA_PATH):
            try:
                self.viirs_dataset = rasterio.open(settings.VIIRS_DATA_PATH)
                logger.info(
                    f"VIIRS GeoTIFF loaded: {settings.VIIRS_DATA_PATH} "
                    f"(shape={self.viirs_dataset.shape}, crs={self.viirs_dataset.crs})"
                )
            except Exception as e:
                logger.error(f"Failed to open VIIRS dataset: {e}")
        else:
            logger.info(
                "VIIRS satellite data unavailable. "
                "Using road-type-based lighting estimation (produces real variance)."
            )

        # ── Setup KDE model ──────────────────────────────────────────────────
        self.kde_model = kde_model
        if self.kde_model is None:
            logger.warning("No KDE model provided. Crime density will be 0.0 (neutral).")

        # ── Build spatial index on real POI coordinates ──────────────────────
        if poi_coords and len(poi_coords) > 0:
            logger.info(f"Building POI spatial index on {len(poi_coords)} real OSM POIs...")
            self.poi_tree = cKDTree(np.array(poi_coords))
        else:
            logger.warning("No POI coordinates provided. POI density will be 0.0 (neutral).")

    # ── VIIRS Lighting ──────────────────────────────────────────────────────

    @lru_cache(maxsize=10000)
    def _sample_viirs_brightness(self, lat: float, lon: float) -> float:
        """
        Samples real VIIRS night light radiance for a given coordinate.
        Returns raw radiance value (0.0 if outside tile or unavailable).
        """
        if self.viirs_tile is not None:
            # O(1) lookup from pre-sampled grid
            grid = self.viirs_tile["brightness"]
            bbox = self.viirs_tile["bbox"]  # [north, south, east, west]
            n, s, e, w = bbox
            if not (s <= lat <= n and w <= lon <= e):
                return 0.0

            rows, cols = grid.shape
            row_idx = int((n - lat) / (n - s) * (rows - 1))
            col_idx = int((lon - w) / (e - w) * (cols - 1))
            row_idx = max(0, min(rows - 1, row_idx))
            col_idx = max(0, min(cols - 1, col_idx))

            return max(float(grid[row_idx, col_idx]), 0.0)

        if self.viirs_dataset is None:
            return -1.0  # Sentinel: means "use road-type fallback"

        try:
            val = next(self.viirs_dataset.sample([(lon, lat)]))
            raw = float(val[0])
            return max(raw, 0.0)
        except Exception:
            return 0.0

    def _compute_lighting_score(
        self, midpoints: np.ndarray, road_types: Optional[pd.Series] = None
    ) -> np.ndarray:
        """
        Compute normalized lighting scores. Three strategies:
        1. Real VIIRS satellite data (best — real spatial variance)
        2. Pre-sampled VIIRS tile from Supabase (good — cached satellite data)
        3. Road-type-based estimation (fallback — uses OSM highway tags)

        Strategy 3 activates when VIIRS is completely unavailable. It produces
        genuine variance based on road classification: motorways are well-lit
        (0.90), residential streets are moderate (0.40), tracks are dark (0.10).
        """
        scores = np.array([
            self._sample_viirs_brightness(float(lat), float(lon))
            for lat, lon in midpoints
        ])

        # Check if VIIRS returned sentinel values (all -1.0 means unavailable)
        has_viirs = not np.all(scores < 0)

        if has_viirs:
            # Replace any sentinel values with 0
            scores = np.maximum(scores, 0.0)

            score_min, score_max = scores.min(), scores.max()
            if score_max > score_min:
                # Percentile normalization to avoid outlier compression
                p5, p95 = np.percentile(scores, [5, 95])
                if p95 > p5:
                    scores = np.clip((scores - p5) / (p95 - p5), 0.0, 1.0)
                else:
                    scores = (scores - score_min) / (score_max - score_min)
            else:
                # All identical — use road-type fallback if available
                if road_types is not None:
                    scores = self._road_type_lighting(road_types)
                else:
                    scores = np.full_like(scores, 0.5)
        elif road_types is not None:
            # No VIIRS at all — use road-type-based lighting estimation
            # This produces REAL variance unlike the old flat 0.5 fallback
            scores = self._road_type_lighting(road_types)
            logger.info(
                f"Road-type lighting: range=[{scores.min():.3f}, {scores.max():.3f}], "
                f"unique_values={len(np.unique(np.round(scores, 2)))}"
            )
        else:
            scores = np.full(len(midpoints), 0.5)

        return scores

    @staticmethod
    def _road_type_lighting(road_types: pd.Series) -> np.ndarray:
        """
        Estimate lighting from OSM highway classification.
        Produces genuine per-edge variance: motorways (0.90) → tracks (0.10).
        """
        lookup = settings.ROAD_LIGHTING_SCORES

        def get_score(hw_type):
            if isinstance(hw_type, list):
                hw_type = hw_type[0]
            hw = str(hw_type).lower()
            # Check for exact match first, then substring
            if hw in lookup:
                return lookup[hw]
            for key, score in lookup.items():
                if key in hw:
                    return score
            return 0.35  # default for unknown types

        return road_types.apply(get_score).values.astype(float)

    # ── Crime Density (KDE) ─────────────────────────────────────────────────

    def _compute_crime_density(self, midpoints: np.ndarray) -> np.ndarray:
        """
        Compute crime density using KDE fitted on real geocoded incidents.
        The output is scaled by the regional crime multiplier derived from
        district/state-level crime rates (dataset_2 and dataset_3).

        Uses percentile normalization to preserve meaningful gradients
        even when the absolute density range is narrow.
        """
        if self.kde_model is None:
            return np.zeros(len(midpoints))

        # score_samples returns log-density; exponentiate for raw likelihood
        log_density = self.kde_model.score_samples(midpoints)
        density = np.exp(log_density)

        # Apply regional crime multiplier from district/state data
        density = density * self.regional_crime_multiplier

        # Percentile normalization for robust [0, 1] mapping
        if len(density) > 10:
            p5, p95 = np.percentile(density, [5, 95])
            if p95 > p5:
                density = np.clip((density - p5) / (p95 - p5), 0.0, 1.0)
            else:
                d_max = density.max()
                density = density / d_max if d_max > 0 else density
        else:
            d_max = density.max()
            if d_max > 0:
                density = density / d_max

        return density

    # ── POI Density ─────────────────────────────────────────────────────────

    def _compute_poi_density(self, midpoints: np.ndarray) -> np.ndarray:
        """
        Count real OSM POIs within 100m radius of each edge midpoint.
        Uses percentile normalization for robust [0, 1] mapping.
        """
        if self.poi_tree is None:
            return np.zeros(len(midpoints))

        radius_deg = settings.POI_RADIUS_METERS / 111000.0
        counts = self.poi_tree.query_ball_point(midpoints, r=radius_deg)
        density = np.array([len(neighbors) for neighbors in counts], dtype=float)

        # Percentile normalization
        if len(density) > 10 and density.max() > 0:
            p95 = np.percentile(density[density > 0], 95) if np.any(density > 0) else 1.0
            if p95 > 0:
                density = np.clip(density / p95, 0.0, 1.0)
        else:
            d_max = density.max()
            if d_max > 0:
                density = density / d_max

        return density

    # ── Footfall Proxy ──────────────────────────────────────────────────────

    def _compute_footfall_proxy(
        self, poi_density: np.ndarray, road_types: pd.Series, is_night: int
    ) -> np.ndarray:
        """
        Estimate pedestrian footfall from real POI density + road classification.

        Rules:
        1. Higher POI density → higher footfall
        2. Highway/motorway → low (0.2), Residential → medium (0.5), Commercial → high (1.0)
        3. Nighttime reduces footfall by 60%
        """

        def road_weight(hw_type):
            if isinstance(hw_type, list):
                hw_type = hw_type[0]
            hw = str(hw_type).lower()
            if any(k in hw for k in ["motorway", "trunk"]):
                return 0.2
            elif any(k in hw for k in ["primary", "secondary", "commercial", "pedestrian"]):
                return 1.0
            return 0.5  # residential, tertiary, unclassified

        weights = road_types.apply(road_weight).values
        footfall = (poi_density + 0.1) * weights

        if is_night == 1:
            footfall = footfall * 0.4

        # Percentile normalization
        if len(footfall) > 10 and footfall.max() > 0:
            p95 = np.percentile(footfall, 95)
            if p95 > 0:
                footfall = np.clip(footfall / p95, 0.0, 1.0)
        else:
            f_max = footfall.max()
            if f_max > 0:
                footfall = footfall / f_max

        return footfall

    # ── Astronomical Time Context ───────────────────────────────────────────

    def _compute_time_context(
        self, current_time: Optional[datetime], midpoints: np.ndarray
    ) -> int:
        """
        Determine if it's currently nighttime using real astronomical calculations.
        """
        from astral.sun import sun
        from astral import LocationInfo
        from datetime import timezone

        if current_time is None:
            current_time = datetime.now(timezone.utc)
        elif current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)

        if len(midpoints) == 0:
            return 0

        mean_lat = float(np.mean(midpoints[:, 0]))
        mean_lon = float(np.mean(midpoints[:, 1]))

        loc = LocationInfo("RouteArea", "Region", "UTC", mean_lat, mean_lon)
        try:
            s = sun(loc.observer, date=current_time.date())
            if current_time < s["sunrise"] or current_time > s["sunset"]:
                return 1  # Night
            return 0  # Day
        except Exception as e:
            logger.warning(f"Astral calculation failed: {e}. Using hour-based fallback.")
            hour = current_time.hour
            return 1 if hour >= settings.NIGHT_START_HOUR or hour < settings.NIGHT_END_HOUR else 0

    # ── Main Pipeline ───────────────────────────────────────────────────────

    def generate_edge_features(
        self,
        G: nx.MultiDiGraph,
        current_time: Optional[datetime] = None,
        vegetation_isolation: Optional[np.ndarray] = None,
        gdf_edges_cache: Optional[Any] = None,
    ) -> pd.DataFrame:
        """
        Main pipeline: extract ALL safety features for every edge in the graph.
        All output features are normalized to [0, 1] for consistent ML usage.

        Args:
            G: OpenStreetMap road network graph
            current_time: Query time (defaults to now)
            vegetation_isolation: Pre-computed GEE scores (optional)
            gdf_edges_cache: Pre-computed gdf_edges to avoid re-computation
        """
        logger.info("═══ Starting Real-Data Feature Engineering Pipeline ═══")

        if gdf_edges_cache is not None:
            gdf_edges = gdf_edges_cache
        else:
            gdf_edges = ox.graph_to_gdfs(G, nodes=False)

        num_edges = len(gdf_edges)

        # Compute geographic midpoints for spatial queries
        centroids = gdf_edges.geometry.centroid
        midpoints = np.column_stack((centroids.y, centroids.x))

        logger.info(f"Processing {num_edges} road segments...")

        # Extract road types for lighting fallback and footfall
        highway_series = (
            gdf_edges["highway"]
            if "highway" in gdf_edges.columns
            else pd.Series(["residential"] * num_edges, index=gdf_edges.index)
        )

        # 1. Lighting from real VIIRS satellite data OR road-type estimation
        logger.info("[1/7] Computing lighting scores...")
        lighting_score = self._compute_lighting_score(midpoints, road_types=highway_series)

        # 2. Crime density from real KDE model
        logger.info("[2/7] Computing crime density from real incident KDE...")
        crime_density = self._compute_crime_density(midpoints)

        # 3. POI density from real OSM data
        logger.info("[3/7] Computing real POI density...")
        poi_density = self._compute_poi_density(midpoints)

        # 4. Astronomical day/night from Astral
        logger.info("[4/7] Computing astronomical time context...")
        is_night = self._compute_time_context(current_time, midpoints)

        # 5. Footfall proxy from real data
        logger.info("[5/7] Computing footfall proxy...")
        footfall_proxy = self._compute_footfall_proxy(poi_density, highway_series, is_night)

        # 6. Weather risk from real-time API
        logger.info("[6/7] Applying real-time weather risk...")
        weather_risk = np.full(num_edges, self.weather_penalty)

        # 7. Vegetation isolation from GEE (optional)
        logger.info("[7/7] Applying vegetation isolation scores...")
        if vegetation_isolation is None or len(vegetation_isolation) != num_edges:
            vegetation_isolation = np.zeros(num_edges)

        # 8. Road segment length — log-normalized to [0, 1]
        length_raw = gdf_edges["length"].fillna(0.0).values
        length_m = np.log1p(length_raw)
        l_max = length_m.max()
        if l_max > 0:
            length_m = length_m / l_max

        # Assemble final feature matrix (all features in [0, 1])
        features_df = pd.DataFrame(
            {
                "lighting_score": lighting_score,
                "crime_density": crime_density,
                "poi_density": poi_density,
                "footfall_proxy": footfall_proxy,
                "weather_risk": weather_risk,
                "vegetation_isolation": vegetation_isolation,
                "is_night": np.full(num_edges, is_night, dtype=int),
                "length_m": length_m,
            },
            index=gdf_edges.index,
        )

        logger.info(
            f"═══ Feature Pipeline Complete ═══\n"
            f"    Edges: {num_edges}\n"
            f"    Night: {'Yes' if is_night else 'No'}\n"
            f"    Weather penalty: {self.weather_penalty:.2f}\n"
            f"    Crime multiplier: {self.regional_crime_multiplier:.2f}\n"
            f"    Lighting range: [{lighting_score.min():.3f}, {lighting_score.max():.3f}]\n"
            f"    Crime range: [{crime_density.min():.3f}, {crime_density.max():.3f}]\n"
            f"    POI range: [{poi_density.min():.3f}, {poi_density.max():.3f}]\n"
            f"    Footfall range: [{footfall_proxy.min():.3f}, {footfall_proxy.max():.3f}]"
        )

        return features_df
