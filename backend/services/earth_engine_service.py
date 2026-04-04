"""
Google Earth Engine integration for vegetation isolation scoring.

Uses NDVI (Normalized Difference Vegetation Index) from Sentinel-2 imagery.
High vegetation + low POI density = isolated/rural area = lower safety at night.

This service is OPTIONAL — if GEE credentials are not configured, it gracefully
returns neutral scores (0.0) and the rest of the pipeline continues normally.

Setup required:
1. Create a Google Cloud project at https://console.cloud.google.com
2. Enable the Earth Engine API
3. Create a service account and download the JSON key file
4. Set GEE_PROJECT_ID and GEE_SERVICE_ACCOUNT_KEY in your .env file
"""
import logging
import numpy as np
from typing import Optional
from core.config import settings

logger = logging.getLogger(__name__)

# GEE is optional — import only if credentials are configured
_ee = None
_gee_initialized = False


def _init_gee() -> bool:
    """Attempt to initialize Google Earth Engine. Returns True if successful."""
    global _ee, _gee_initialized

    if _gee_initialized:
        return _ee is not None

    _gee_initialized = True

    if not settings.GEE_PROJECT_ID or not settings.GEE_SERVICE_ACCOUNT_KEY:
        logger.info("GEE credentials not configured. Vegetation isolation scoring disabled.")
        return False

    try:
        import ee
        credentials = ee.ServiceAccountCredentials(
            email=None,  # Will be read from the key file
            key_file=settings.GEE_SERVICE_ACCOUNT_KEY,
        )
        ee.Initialize(credentials=credentials, project=settings.GEE_PROJECT_ID)
        _ee = ee
        logger.info("Google Earth Engine initialized successfully.")
        return True
    except ImportError:
        logger.warning("earthengine-api not installed. Run: pip install earthengine-api")
        return False
    except Exception as e:
        logger.error(f"Failed to initialize Google Earth Engine: {e}")
        return False


class EarthEngineService:
    """
    Fetches NDVI (vegetation density) from Google Earth Engine.
    High NDVI + low POI = isolated rural area → reduced safety at night.
    """

    def __init__(self):
        self.enabled = _init_gee()

    def get_ndvi_for_bbox(
        self, north: float, south: float, east: float, west: float
    ) -> Optional[np.ndarray]:
        """
        Fetch mean NDVI for a bounding box from recent Sentinel-2 imagery.

        Returns:
            2D numpy array of NDVI values, or None if GEE is unavailable.
        """
        if not self.enabled or _ee is None:
            return None

        try:
            # Use Sentinel-2 Surface Reflectance, last 30 days
            from datetime import datetime as _dt, timedelta as _td
            end_date = _dt.utcnow().strftime("%Y-%m-%d")
            start_date = (_dt.utcnow() - _td(days=30)).strftime("%Y-%m-%d")

            collection = (
                _ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                .filterBounds(_ee.Geometry.Rectangle([west, south, east, north]))
                .filterDate(start_date, end_date)
                .filter(_ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 30))
                .median()
            )

            # Compute NDVI = (NIR - Red) / (NIR + Red)
            ndvi = collection.normalizedDifference(["B8", "B4"]).rename("NDVI")

            # Sample at ~100m resolution
            region = _ee.Geometry.Rectangle([west, south, east, north])
            result = ndvi.reduceRegion(
                reducer=_ee.Reducer.mean(),
                geometry=region,
                scale=100,
                maxPixels=1e8,
            ).getInfo()

            mean_ndvi = result.get("NDVI", 0.3)
            logger.info(f"GEE NDVI for bbox: {mean_ndvi:.3f}")
            return mean_ndvi

        except Exception as e:
            logger.error(f"GEE NDVI fetch failed: {e}")
            return None

    def compute_vegetation_isolation(
        self, midpoints: np.ndarray, poi_density: np.ndarray
    ) -> np.ndarray:
        """
        Compute vegetation isolation score per edge midpoint.

        Logic:
        - High vegetation (NDVI > 0.4) + low POI density → isolated area → score ~1.0
        - Low vegetation or high POI density → urban area → score ~0.0

        If GEE is unavailable, returns all zeros (neutral — no impact on safety).

        Args:
            midpoints: (N, 2) array of [lat, lon]
            poi_density: (N,) array of normalized POI density [0, 1]

        Returns:
            (N,) array of isolation scores [0, 1]
        """
        if not self.enabled or len(midpoints) == 0:
            return np.zeros(len(midpoints))

        try:
            # Get regional NDVI
            north, south = midpoints[:, 0].max(), midpoints[:, 0].min()
            east, west = midpoints[:, 1].max(), midpoints[:, 1].min()

            mean_ndvi = self.get_ndvi_for_bbox(north, south, east, west)
            if mean_ndvi is None:
                return np.zeros(len(midpoints))

            # Isolation = high vegetation * low commercial activity
            # NDVI > 0.4 is heavily vegetated; scale [0, 0.8] -> [0, 1]
            veg_score = np.clip((mean_ndvi - 0.1) / 0.7, 0.0, 1.0)

            # Combine: isolation is high when vegetation is high AND POIs are low
            isolation = veg_score * (1.0 - poi_density)

            return np.clip(isolation, 0.0, 1.0)

        except Exception as e:
            logger.error(f"Vegetation isolation computation failed: {e}")
            return np.zeros(len(midpoints))
