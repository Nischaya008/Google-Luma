"""
Supabase client singleton for database and storage operations.

Provides a thread-safe, fault-tolerant wrapper around the Supabase Python client.
All methods return None/False on failure — callers cascade to the next cache tier.
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta

from core.config import settings

logger = logging.getLogger(__name__)

# Lazy import: supabase package may not be installed in all environments
_Client = None


def _get_client_class():
    global _Client
    if _Client is None:
        from supabase import Client as C
        _Client = C
    return _Client


class SupabaseClient:
    """
    Singleton wrapper for Supabase Postgres + Storage.

    Usage:
        client = SupabaseClient.get_instance()
        record = client.find_region_graph(28.62, 77.22, 5)
    """

    _instance: Optional["SupabaseClient"] = None

    def __init__(self):
        raise RuntimeError("Use SupabaseClient.get_instance()")

    @classmethod
    def get_instance(cls) -> "SupabaseClient":
        if cls._instance is None:
            instance = object.__new__(cls)
            instance._client = None
            instance._init_client()
            cls._instance = instance
        return cls._instance

    def _init_client(self):
        url = settings.SUPABASE_URL
        key = settings.SUPABASE_SERVICE_ROLE_KEY
        if not url or not key:
            logger.warning("Supabase credentials missing — persistent cache disabled.")
            return
        try:
            from supabase import create_client
            self._client = create_client(url, key)
            self._ensure_bucket()
            logger.info("Supabase client initialized successfully.")
        except Exception as e:
            logger.error(f"Supabase init failed: {e}")
            self._client = None

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def _ensure_bucket(self):
        """Create storage bucket if it doesn't exist (idempotent)."""
        if not self.is_available:
            return
        try:
            self._client.storage.create_bucket(
                settings.SUPABASE_STORAGE_BUCKET,
                options={"public": False}
            )
            logger.info(f"Storage bucket '{settings.SUPABASE_STORAGE_BUCKET}' created.")
        except Exception:
            # Bucket already exists — this is fine
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # Region Graph CRUD
    # ══════════════════════════════════════════════════════════════════════════

    def find_region_graph(
        self, center_lat: float, center_lon: float, radius_km: int
    ) -> Optional[dict]:
        """Look up a cached graph by its rounded center + radius."""
        if not self.is_available:
            return None
        try:
            result = (
                self._client.table("region_graphs")
                .select("*")
                .eq("center_lat", center_lat)
                .eq("center_lon", center_lon)
                .eq("radius_km", radius_km)
                .gte("expires_at", datetime.now(timezone.utc).isoformat())
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"find_region_graph failed: {e}")
            return None

    def upsert_region_graph(
        self,
        center_lat: float,
        center_lon: float,
        radius_km: int,
        storage_path: str,
        node_count: int,
        edge_count: int,
        file_size_bytes: int = 0,
    ) -> Optional[dict]:
        """Insert or update a graph record. Returns the record or None."""
        if not self.is_available:
            return None
        try:
            expires = datetime.now(timezone.utc) + timedelta(seconds=settings.GRAPH_CACHE_TTL)
            data = {
                "center_lat": center_lat,
                "center_lon": center_lon,
                "radius_km": radius_km,
                "storage_path": storage_path,
                "node_count": node_count,
                "edge_count": edge_count,
                "file_size_bytes": file_size_bytes,
                "expires_at": expires.isoformat(),
            }
            result = (
                self._client.table("region_graphs")
                .upsert(data, on_conflict="center_lat,center_lon,radius_km")
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"upsert_region_graph failed: {e}")
            return None

    # ══════════════════════════════════════════════════════════════════════════
    # Cached Features CRUD
    # ══════════════════════════════════════════════════════════════════════════

    def find_cached_features(self, graph_id: str) -> Optional[dict]:
        if not self.is_available:
            return None
        try:
            result = (
                self._client.table("cached_features")
                .select("*")
                .eq("graph_id", graph_id)
                .gte("expires_at", datetime.now(timezone.utc).isoformat())
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"find_cached_features failed: {e}")
            return None

    def upsert_cached_features(
        self, graph_id: str, storage_path: str, edge_count: int
    ) -> Optional[dict]:
        if not self.is_available:
            return None
        try:
            expires = datetime.now(timezone.utc) + timedelta(seconds=settings.FEATURES_CACHE_TTL)
            data = {
                "graph_id": graph_id,
                "storage_path": storage_path,
                "edge_count": edge_count,
                "expires_at": expires.isoformat(),
            }
            result = (
                self._client.table("cached_features")
                .upsert(data, on_conflict="graph_id")
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"upsert_cached_features failed: {e}")
            return None

    # ══════════════════════════════════════════════════════════════════════════
    # Route Cache CRUD
    # ══════════════════════════════════════════════════════════════════════════

    def find_cached_route(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        mode: str,
        time_context: str,
    ) -> Optional[dict]:
        if not self.is_available:
            return None
        try:
            result = (
                self._client.table("route_cache")
                .select("*")
                .eq("origin_lat", origin_lat)
                .eq("origin_lon", origin_lon)
                .eq("dest_lat", dest_lat)
                .eq("dest_lon", dest_lon)
                .eq("mode", mode)
                .eq("time_context", time_context)
                .gte("expires_at", datetime.now(timezone.utc).isoformat())
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"find_cached_route failed: {e}")
            return None

    def insert_route_cache(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        mode: str,
        time_context: str,
        weather_bucket: str,
        route_geometry: list,
        estimated_time_seconds: float,
        average_safety_score: float,
        total_cost: float,
        graph_id: Optional[str] = None,
    ) -> Optional[dict]:
        if not self.is_available:
            return None
        try:
            expires = datetime.now(timezone.utc) + timedelta(seconds=settings.ROUTE_CACHE_TTL)
            data = {
                "origin_lat": origin_lat,
                "origin_lon": origin_lon,
                "dest_lat": dest_lat,
                "dest_lon": dest_lon,
                "mode": mode,
                "time_context": time_context,
                "weather_bucket": weather_bucket,
                "route_geometry": route_geometry,
                "estimated_time_seconds": estimated_time_seconds,
                "average_safety_score": average_safety_score,
                "total_cost": total_cost,
                "expires_at": expires.isoformat(),
            }
            # Only include graph_id if it's a valid UUID (not None or arbitrary string)
            if graph_id is not None:
                data["graph_id"] = graph_id
            result = self._client.table("route_cache").insert(data).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"insert_route_cache failed: {e}")
            return None

    # ══════════════════════════════════════════════════════════════════════════
    # POI Cache CRUD
    # ══════════════════════════════════════════════════════════════════════════

    def find_poi_cache(self, bbox_key: str) -> Optional[dict]:
        if not self.is_available:
            return None
        try:
            result = (
                self._client.table("poi_cache")
                .select("*")
                .eq("bbox_key", bbox_key)
                .gte("expires_at", datetime.now(timezone.utc).isoformat())
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"find_poi_cache failed: {e}")
            return None

    def upsert_poi_cache(
        self, bbox_key: str, poi_data: list, poi_count: int
    ) -> Optional[dict]:
        if not self.is_available:
            return None
        try:
            expires = datetime.now(timezone.utc) + timedelta(seconds=settings.POI_CACHE_TTL)
            data = {
                "bbox_key": bbox_key,
                "poi_data": poi_data,
                "poi_count": poi_count,
                "expires_at": expires.isoformat(),
            }
            result = (
                self._client.table("poi_cache")
                .upsert(data, on_conflict="bbox_key")
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"upsert_poi_cache failed: {e}")
            return None

    # ══════════════════════════════════════════════════════════════════════════
    # ML Model Registry
    # ══════════════════════════════════════════════════════════════════════════

    def find_ml_model(self, region_key: str) -> Optional[dict]:
        if not self.is_available:
            return None
        try:
            result = (
                self._client.table("ml_models")
                .select("*")
                .eq("region_key", region_key)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"find_ml_model failed: {e}")
            return None

    def upsert_ml_model(
        self,
        region_key: str,
        storage_path: str,
        training_edges: int,
        feature_importance: Optional[dict] = None,
    ) -> Optional[dict]:
        if not self.is_available:
            return None
        try:
            data = {
                "region_key": region_key,
                "model_type": "xgboost",
                "storage_path": storage_path,
                "training_edges": training_edges,
                "feature_importance": feature_importance or {},
            }
            result = (
                self._client.table("ml_models")
                .upsert(data, on_conflict="region_key,model_type")
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"upsert_ml_model failed: {e}")
            return None

    # ══════════════════════════════════════════════════════════════════════════
    # VIIRS Tiles
    # ══════════════════════════════════════════════════════════════════════════

    def find_viirs_tile(self, city_name: str) -> Optional[dict]:
        if not self.is_available:
            return None
        try:
            result = (
                self._client.table("viirs_tiles")
                .select("*")
                .eq("city_name", city_name.strip().lower())
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"find_viirs_tile failed: {e}")
            return None

    # ══════════════════════════════════════════════════════════════════════════
    # Storage Operations (Supabase Storage / S3-compatible)
    # ══════════════════════════════════════════════════════════════════════════

    def upload_file(self, path: str, data: bytes) -> bool:
        """Upload binary data to Supabase Storage. Overwrites existing."""
        if not self.is_available:
            return False
        bucket = settings.SUPABASE_STORAGE_BUCKET
        try:
            # Remove existing file first (Supabase doesn't overwrite by default)
            try:
                self._client.storage.from_(bucket).remove([path])
            except Exception:
                pass
            self._client.storage.from_(bucket).upload(
                path=path,
                file=data,
                file_options={"content-type": "application/octet-stream"},
            )
            logger.info(f"Uploaded {len(data):,} bytes → {bucket}/{path}")
            return True
        except Exception as e:
            logger.error(f"Storage upload failed ({path}): {e}")
            return False

    def download_file(self, path: str) -> Optional[bytes]:
        """Download binary data from Supabase Storage."""
        if not self.is_available:
            return None
        bucket = settings.SUPABASE_STORAGE_BUCKET
        try:
            data = self._client.storage.from_(bucket).download(path)
            logger.info(f"Downloaded {len(data):,} bytes ← {bucket}/{path}")
            return data
        except Exception as e:
            logger.error(f"Storage download failed ({path}): {e}")
            return None
