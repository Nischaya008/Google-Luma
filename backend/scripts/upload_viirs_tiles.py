"""
Pre-sample VIIRS night-lights GeoTIFF into per-city .npz tiles
and upload them to Supabase Storage (luma-cache/viirs-tiles/).

Also populates the `viirs_tiles` Postgres table so the cache manager
can look them up by city name.

Usage:
    cd backend
    .\\venv\\Scripts\\python.exe scripts/upload_viirs_tiles.py

Requires: rasterio, numpy, supabase (already in your venv)
"""
import sys
import os
import io
import logging

# Add backend to path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import rasterio
from rasterio.windows import from_bounds
from core.config import settings
from db.supabase_client import SupabaseClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Grid resolution: 200x200 pixels per city tile (~50m resolution for 10km area)
GRID_SIZE = 200
# Radius in degrees around each city center (~0.15° ≈ 16.5km)
TILE_RADIUS_DEG = 0.15


def sample_viirs_tile(dataset, lat: float, lon: float, radius: float = TILE_RADIUS_DEG) -> dict:
    """
    Extract a brightness grid from the VIIRS GeoTIFF for one city.
    
    Returns:
        dict with 'brightness' (2D numpy array) and 'bbox' ([north, south, east, west])
    """
    north = lat + radius
    south = lat - radius
    east = lon + radius
    west = lon - radius

    try:
        window = from_bounds(west, south, east, north, dataset.transform)
        data = dataset.read(1, window=window)

        # Clamp negative values (VIIRS uses fill values like -999)
        data = np.maximum(data, 0.0).astype(np.float32)

        # Resize to fixed grid size for consistent storage
        if data.shape[0] > 0 and data.shape[1] > 0:
            from scipy.ndimage import zoom
            zoom_y = GRID_SIZE / data.shape[0]
            zoom_x = GRID_SIZE / data.shape[1]
            data = zoom(data, (zoom_y, zoom_x), order=1)
        else:
            data = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.float32)

        return {
            "brightness": data,
            "bbox": np.array([north, south, east, west]),
        }
    except Exception as e:
        logger.error(f"Failed to sample VIIRS at ({lat}, {lon}): {e}")
        return {
            "brightness": np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.float32),
            "bbox": np.array([north, south, east, west]),
        }


def main():
    viirs_path = settings.VIIRS_DATA_PATH
    if not os.path.exists(viirs_path):
        logger.error(f"VIIRS GeoTIFF not found at {viirs_path}")
        sys.exit(1)

    logger.info(f"Opening VIIRS GeoTIFF: {viirs_path}")
    dataset = rasterio.open(viirs_path)
    logger.info(f"  Shape: {dataset.shape}, CRS: {dataset.crs}")

    supabase = SupabaseClient.get_instance()
    if not supabase.is_available:
        logger.error("Supabase not available. Check credentials in .env")
        sys.exit(1)

    cities = settings.CITY_COORDINATES
    bucket = settings.SUPABASE_STORAGE_BUCKET

    success_count = 0
    for city_name, (lat, lon) in cities.items():
        city_key = city_name.strip().lower()
        logger.info(f"Sampling {city_name} ({lat}, {lon})...")

        tile = sample_viirs_tile(dataset, lat, lon)
        brightness = tile["brightness"]

        logger.info(
            f"  Brightness: min={brightness.min():.2f}, max={brightness.max():.2f}, "
            f"mean={brightness.mean():.2f}, shape={brightness.shape}"
        )

        # Serialize to .npz in memory
        buf = io.BytesIO()
        np.savez_compressed(buf, brightness=tile["brightness"], bbox=tile["bbox"])
        npz_bytes = buf.getvalue()

        storage_path = f"viirs-tiles/{city_key}.npz"

        # Upload to Supabase Storage
        uploaded = supabase.upload_file(storage_path, npz_bytes)
        if not uploaded:
            logger.error(f"  Upload FAILED for {city_name}")
            continue

        logger.info(f"  Uploaded {len(npz_bytes):,} bytes → {bucket}/{storage_path}")

        # Upsert into viirs_tiles table
        try:
            supabase._client.table("viirs_tiles").upsert({
                "city_name": city_key,
                "storage_path": storage_path,
                "grid_size": GRID_SIZE,
                "radius_deg": TILE_RADIUS_DEG,
                "brightness_min": float(brightness.min()),
                "brightness_max": float(brightness.max()),
                "brightness_mean": float(brightness.mean()),
            }, on_conflict="city_name").execute()
            logger.info(f"  ✓ {city_name} complete")
            success_count += 1
        except Exception as e:
            logger.warning(f"  Table upsert failed for {city_name}: {e}")
            logger.info(f"  ✓ {city_name} uploaded (table entry skipped)")
            success_count += 1

    dataset.close()
    logger.info(f"\nDone! {success_count}/{len(cities)} cities uploaded to Supabase.")


if __name__ == "__main__":
    main()
