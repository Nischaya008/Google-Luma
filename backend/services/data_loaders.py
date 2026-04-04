"""
Data Loaders for real crime datasets, OSM POI extraction, and geocoding.

Handles:
- dataset_4.csv: 40K individual crime incidents across 29 Indian cities
- dataset_2.csv: District-level crime rates (Crime_Rate_per_100k)
- dataset_3.csv: State-level aggregate crime statistics
- dataset_1.csv: Global country-level crime index
- OSM Overpass API: Real-time POI extraction for commercial activity
"""
import os
import logging
import numpy as np
import pandas as pd
import osmnx as ox
from typing import List, Tuple, Dict, Optional
from functools import lru_cache
from core.config import settings

logger = logging.getLogger(__name__)


class CrimeDataLoader:
    """
    Loads and geocodes all 4 crime datasets into a unified spatial representation.
    Produces weighted (lat, lon) coordinates suitable for KDE fitting.
    """

    def __init__(self):
        self._incidents_df: Optional[pd.DataFrame] = None
        self._district_rates: Optional[Dict[str, float]] = None
        self._state_rates: Optional[Dict[str, float]] = None
        self._india_global_rate: float = 1.0

    def load_all(self) -> None:
        """Load and parse all 4 datasets into memory."""
        self._load_incidents()
        self._load_district_rates()
        self._load_state_rates()
        self._load_global_index()

    # ── Dataset 4: Individual Crime Incidents ────────────────────────────────

    def _load_incidents(self) -> None:
        """Parse dataset_4.csv (40K incidents with City, Crime Domain, Time)."""
        path = settings.CRIME_INCIDENTS_PATH
        if not os.path.exists(path):
            logger.warning(f"Crime incidents file not found: {path}")
            return

        try:
            self._incidents_df = pd.read_csv(path)
            logger.info(f"Loaded {len(self._incidents_df)} crime incidents from {path}")
        except Exception as e:
            logger.error(f"Failed to load crime incidents: {e}")

    def geocode_incidents(self) -> List[Tuple[float, float, float]]:
        """
        Convert city-level incidents to (lat, lon, weight) tuples.

        Each incident is placed at its city centroid with a small Gaussian
        jitter (~4.4 km) to spatially distribute crimes across the city.
        The weight is determined by the crime severity category.

        Returns:
            List of (lat, lon, severity_weight) tuples.
        """
        if self._incidents_df is None:
            self._load_incidents()
        if self._incidents_df is None or self._incidents_df.empty:
            logger.warning("No crime incidents available for geocoding.")
            return []

        coords = []
        rng = np.random.default_rng(seed=42)  # Deterministic jitter

        for _, row in self._incidents_df.iterrows():
            city = str(row.get("City", "")).strip()
            if city not in settings.CITY_COORDINATES:
                continue

            base_lat, base_lon = settings.CITY_COORDINATES[city]

            # Deterministic Gaussian jitter around city centroid
            jitter_lat = rng.normal(0, settings.CITY_RADIUS_DEG)
            jitter_lon = rng.normal(0, settings.CITY_RADIUS_DEG)

            crime_domain = str(row.get("Crime Domain", "Other Crime"))
            weight = settings.CRIME_SEVERITY_WEIGHTS.get(crime_domain, 1.0)

            coords.append((
                base_lat + jitter_lat,
                base_lon + jitter_lon,
                weight,
            ))

        logger.info(f"Geocoded {len(coords)} crime incidents across {len(settings.CITY_COORDINATES)} cities.")
        return coords

    def get_crime_coordinates_for_kde(self) -> List[Tuple[float, float]]:
        """
        Returns weighted crime coordinates for KDE fitting.
        Violent crimes are repeated proportionally to their severity weight
        so the KDE kernel naturally places more density around them.
        """
        weighted = self.geocode_incidents()
        if not weighted:
            return []

        kde_coords = []
        for lat, lon, weight in weighted:
            # Repeat point by integer weight so KDE concentrates density there
            repeat_count = max(1, int(round(weight)))
            for _ in range(repeat_count):
                kde_coords.append((lat, lon))

        logger.info(f"Produced {len(kde_coords)} KDE input points (severity-weighted).")
        return kde_coords

    def get_kde_model(self) -> Optional["KernelDensity"]:
        """
        Returns a fitted KernelDensity model.
        Caches the model to Supabase Storage to avoid the ~3s refit on server restarts.
        """
        from sklearn.neighbors import KernelDensity
        from cache.cache_manager import CacheManager
        import hashlib

        # 1. Hash the dataset files + bandwidth to determine data version
        # Including bandwidth ensures cache invalidation when bandwidth changes
        hasher = hashlib.md5()
        for path in [
            settings.CRIME_INCIDENTS_PATH,
            settings.CRIME_DISTRICT_PATH,
            settings.CRIME_STATE_PATH,
        ]:
            if os.path.exists(path):
                hasher.update(str(os.path.getmtime(path)).encode())
        hasher.update(str(settings.KDE_BANDWIDTH).encode())
        data_hash = hasher.hexdigest()

        cache = CacheManager.get_instance()

        # 2. Check Supabase for cached model
        if cache._enabled and cache.supabase.is_available:
            record = cache.supabase._client.table("kde_models").select("*").eq("data_hash", data_hash).execute()
            if record.data:
                logger.info("KDE Model HIT [Supabase]")
                model = cache.storage.download_model(record.data[0]["storage_path"])
                if model:
                    return model

        # 3. Fit new model
        kde_coords = self.get_crime_coordinates_for_kde()
        if not kde_coords:
            return None

        logger.info(f"Fitting Crime KDE on {len(kde_coords)} input points...")
        model = KernelDensity(kernel="gaussian", bandwidth=settings.KDE_BANDWIDTH)
        model.fit(np.array(kde_coords))

        # 4. Cache to Supabase
        if cache._enabled and cache.supabase.is_available:
            storage_path = f"kde/{data_hash}.pkl.gz"
            if cache.storage.upload_model(model, storage_path):
                cache.supabase._client.table("kde_models").upsert({
                    "data_hash": data_hash,
                    "bandwidth": settings.KDE_BANDWIDTH,
                    "point_count": len(kde_coords),
                    "storage_path": storage_path,
                }, on_conflict="data_hash").execute()

        return model

    # ── Dataset 2: District-Level Crime Rates ────────────────────────────────

    def _load_district_rates(self) -> None:
        """Parse dataset_2.csv for district-level Crime_Rate_per_100k."""
        path = settings.CRIME_DISTRICT_PATH
        if not os.path.exists(path):
            logger.warning(f"District crime rates file not found: {path}")
            return

        try:
            df = pd.read_csv(path)
            # Use the most recent year available per district
            latest = df.sort_values("Year", ascending=False).drop_duplicates(
                subset=["State", "District"], keep="first"
            )
            # Aggregate across crime types per district
            agg = latest.groupby(["State", "District"])["Crime_Rate_per_100k"].sum().reset_index()

            self._district_rates = {}
            for _, row in agg.iterrows():
                key = f"{row['State'].strip().lower()}_{row['District'].strip().lower()}"
                self._district_rates[key] = float(row["Crime_Rate_per_100k"])

            logger.info(f"Loaded crime rates for {len(self._district_rates)} districts.")
        except Exception as e:
            logger.error(f"Failed to load district crime rates: {e}")

    # ── Dataset 3: State-Level Crime Rates ───────────────────────────────────

    def _load_state_rates(self) -> None:
        """Parse dataset_3.csv for state-level IPC crime rate 2022."""
        path = settings.CRIME_STATE_PATH
        if not os.path.exists(path):
            logger.warning(f"State crime rates file not found: {path}")
            return

        try:
            df = pd.read_csv(path)
            self._state_rates = {}
            for _, row in df.iterrows():
                state = str(row["State/UT"]).strip().lower()
                rate = float(row["Rate of Cognizable Crimes (IPC) (2022)"])
                self._state_rates[state] = rate

            logger.info(f"Loaded crime rates for {len(self._state_rates)} states.")
        except Exception as e:
            logger.error(f"Failed to load state crime rates: {e}")

    # ── Dataset 1: Global Crime Index ────────────────────────────────────────

    def _load_global_index(self) -> None:
        """Parse dataset_1.csv — extract India's latest crime index."""
        path = settings.CRIME_GLOBAL_PATH
        if not os.path.exists(path):
            return

        try:
            df = pd.read_csv(path)
            if "India" in df.columns:
                # Use the most recent year's value
                self._india_global_rate = float(df["India"].dropna().iloc[-1])
                logger.info(f"India global crime index: {self._india_global_rate}")
        except Exception as e:
            logger.error(f"Failed to load global crime index: {e}")

    # ── Regional Crime Multiplier ────────────────────────────────────────────

    def get_regional_crime_multiplier(self, city_name: str) -> float:
        """
        Returns a crime multiplier for a given city relative to the national average.
        Falls back through: district → state → national level.

        This multiplier scales the KDE output so cities with higher real crime
        rates produce proportionally higher crime_density scores.
        """
        if self._district_rates is None or self._state_rates is None:
            self.load_all()

        city_lower = city_name.strip().lower()

        # Try district-level match first
        if self._district_rates:
            for key, rate in self._district_rates.items():
                if city_lower in key:
                    # Normalize against national average (~300 per 100k is typical India average)
                    return min(rate / 300.0, 3.0)

        # Fallback to state-level
        if self._state_rates:
            for state, rate in self._state_rates.items():
                if city_lower in state or state in city_lower:
                    return min(rate / 300.0, 3.0)

        # National-level fallback
        return 1.0

    def identify_nearest_city(self, lat: float, lon: float) -> str:
        """
        Finds the nearest known city to a given coordinate using Haversine distance.
        Used to determine which regional crime multiplier to apply.
        """
        from math import radians, cos, sin, asin, sqrt

        def haversine(lat1, lon1, lat2, lon2):
            lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
            return 2 * asin(sqrt(a)) * 6371  # km

        best_city = "Delhi"
        best_dist = float("inf")

        for city, (clat, clon) in settings.CITY_COORDINATES.items():
            d = haversine(lat, lon, clat, clon)
            if d < best_dist:
                best_dist = d
                best_city = city

        return best_city


class POILoader:
    """Extracts real Points of Interest from OpenStreetMap Overpass API."""

    @staticmethod
    def extract_osm_pois(G) -> List[Tuple[float, float]]:
        """
        Extracts POI features (shops, restaurants, cafes, banks) from OSM
        within the bounding box of the given graph.

        Returns:
            List of (lat, lon) tuples for each POI centroid.
        """
        logger.info("Downloading real POI data from OpenStreetMap Overpass API...")

        nodes = ox.graph_to_gdfs(G, edges=False)
        north, south = nodes["y"].max(), nodes["y"].min()
        east, west = nodes["x"].max(), nodes["x"].min()

        tags = {
            "amenity": ["cafe", "restaurant", "bank", "hospital", "pharmacy", "police"],
            "shop": True,
        }

        try:
            pois = ox.features_from_bbox(bbox=(north, south, east, west), tags=tags)

            if pois.empty:
                logger.warning("No POIs found in bounding box.")
                return []

            centroids = pois.geometry.centroid
            result = list(zip(centroids.y, centroids.x))
            logger.info(f"Extracted {len(result)} real POIs from OSM.")
            return result

        except Exception as e:
            logger.error(f"OSM POI extraction failed: {e}")
            try:
                # Fallback: older osmnx signature
                pois = ox.features_from_bbox(north, south, east, west, tags=tags)
                if pois.empty:
                    return []
                centroids = pois.geometry.centroid
                return list(zip(centroids.y, centroids.x))
            except Exception as e2:
                logger.error(f"POI extraction secondary fallback also failed: {e2}")
                return []
