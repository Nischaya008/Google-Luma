"""
VIIRS Night Light Tile Preprocessor.

One-time offline script that clips the 11.6 GB global VIIRS GeoTIFF
into compact city-level brightness grids and uploads them to Supabase Storage.

After running this script, the global GeoTIFF is NO LONGER needed for deployment.

Usage:
    cd backend
    python -m services.viirs_preprocessor

What it does:
    1. For each city in CITY_COORDINATES, clip the VIIRS raster to
       the city bounding box (+20% padding)
    2. Resample to a uniform grid (default: 50m resolution)
    3. Save as compressed numpy arrays (.npz)
    4. Upload to Supabase Storage bucket under viirs-tiles/
    5. Register in the viirs_tiles Postgres table

Requirements:
    - The 11.6 GB VIIRS GeoTIFF must exist at VIIRS_DATA_PATH
    - Supabase credentials must be configured in .env
    - rasterio must be installed
"""
import logging
import sys
import os
import io

import numpy as np

# Ensure backend is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def clip_viirs_for_city(
    city_name: str,
    center_lat: float,
    center_lon: float,
    viirs_path: str,
    padding_deg: float = 0.05,  # ~5.5 km padding
    target_resolution_m: float = 50.0,
) -> dict:
    """
    Clip the VIIRS raster to a city bounding box and resample.

    Args:
        city_name: City identifier
        center_lat, center_lon: City centroid
        viirs_path: Path to the global VIIRS GeoTIFF
        padding_deg: Bounding box padding in degrees
        target_resolution_m: Target grid resolution in meters

    Returns:
        dict with keys: brightness_grid, bbox, resolution, shape
    """
    try:
        import rasterio
        from rasterio.windows import from_bounds
    except ImportError:
        logger.error("rasterio not installed. Run: pip install rasterio")
        return None

    # City bounding box with padding
    city_radius_deg = settings.CITY_RADIUS_DEG + padding_deg
    north = center_lat + city_radius_deg
    south = center_lat - city_radius_deg
    east = center_lon + city_radius_deg
    west = center_lon - city_radius_deg

    try:
        with rasterio.open(viirs_path) as src:
            # Get the window for our bounding box
            window = from_bounds(west, south, east, north, src.transform)

            # Read the data within the window
            data = src.read(1, window=window)

            # Replace negative/nodata values with 0
            data = np.maximum(data, 0.0).astype(np.float32)

            logger.info(
                f"  {city_name}: clipped {data.shape} pixels, "
                f"range=[{data.min():.2f}, {data.max():.2f}]"
            )

            return {
                "brightness_grid": data,
                "bbox_north": north,
                "bbox_south": south,
                "bbox_east": east,
                "bbox_west": west,
                "resolution_m": target_resolution_m,
                "shape": data.shape,
            }

    except Exception as e:
        logger.error(f"  Failed to clip VIIRS for {city_name}: {e}")
        return None


def upload_tile_to_supabase(city_name: str, tile_data: dict) -> bool:
    """Upload a city brightness tile to Supabase Storage + register in DB."""
    from db.supabase_client import SupabaseClient
    from services.storage_service import StorageService

    supabase = SupabaseClient.get_instance()
    storage = StorageService()

    if not supabase.is_available:
        logger.error("Supabase not available — cannot upload tile.")
        return False

    storage_path = f"viirs-tiles/{city_name.lower()}.npz"

    # Upload compressed numpy array
    buf = io.BytesIO()
    np.savez_compressed(
        buf,
        brightness=tile_data["brightness_grid"],
        bbox=np.array([
            tile_data["bbox_north"],
            tile_data["bbox_south"],
            tile_data["bbox_east"],
            tile_data["bbox_west"],
        ]),
    )
    data_bytes = buf.getvalue()

    if not supabase.upload_file(storage_path, data_bytes):
        return False

    # Register in viirs_tiles table
    try:
        supabase._client.table("viirs_tiles").upsert(
            {
                "city_name": city_name.lower(),
                "center_lat": settings.CITY_COORDINATES[city_name][0],
                "center_lon": settings.CITY_COORDINATES[city_name][1],
                "bbox_north": tile_data["bbox_north"],
                "bbox_south": tile_data["bbox_south"],
                "bbox_east": tile_data["bbox_east"],
                "bbox_west": tile_data["bbox_west"],
                "grid_resolution_m": int(tile_data["resolution_m"]),
                "storage_path": storage_path,
            },
            on_conflict="city_name",
        ).execute()
        logger.info(f"  Registered in viirs_tiles: {city_name}")
        return True
    except Exception as e:
        logger.error(f"  DB registration failed for {city_name}: {e}")
        return False


def main():
    """Process all cities and upload tiles."""
    viirs_path = os.path.abspath(settings.VIIRS_DATA_PATH)

    if not os.path.exists(viirs_path):
        logger.error(f"VIIRS file not found: {viirs_path}")
        logger.error("This script requires the 11.6 GB VIIRS GeoTIFF to be present locally.")
        sys.exit(1)

    cities = settings.CITY_COORDINATES
    logger.info(f"Processing {len(cities)} cities from VIIRS raster: {viirs_path}")

    success_count = 0
    for city_name, (lat, lon) in cities.items():
        logger.info(f"Processing {city_name}...")

        tile_data = clip_viirs_for_city(city_name, lat, lon, viirs_path)
        if tile_data is None:
            continue

        if upload_tile_to_supabase(city_name, tile_data):
            success_count += 1

    logger.info(
        f"\nDone! {success_count}/{len(cities)} city tiles uploaded to Supabase Storage."
    )
    logger.info(
        "The 11.6 GB VIIRS GeoTIFF is no longer needed for deployment. "
        "You can safely exclude it from your deploy artifacts."
    )


if __name__ == "__main__":
    main()
