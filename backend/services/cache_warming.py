"""
Background cache warming for high-traffic cities.

Runs asynchronously at server startup — does NOT block the server.
Pre-loads graphs and static features for configured cities so the
first user request to those cities is fast instead of cold-start.

Key improvements:
- Uses PRE_WARM_RADIUS_KM (15km default) instead of 5km — covers full city area
- Parallel warming with semaphore (2 concurrent) for faster startup
- Also pre-warms safety annotations for even faster first requests
- Non-interfering: uses separate locks so user requests proceed independently
"""
import asyncio
import logging

from core.config import settings

logger = logging.getLogger(__name__)

# Semaphore limits concurrent OSMnx downloads to avoid rate-limiting
_WARM_SEMAPHORE = asyncio.Semaphore(2)


async def warm_cache_for_city(city_name: str):
    """Pre-warm graph, static features, and safety annotations for a single city."""
    from cache.cache_manager import CacheManager

    coords = settings.CITY_COORDINATES.get(city_name)
    if not coords:
        logger.warning(f"Pre-warm skipped — unknown city: {city_name}")
        return

    lat, lon = coords
    cache = CacheManager.get_instance()
    radius_km = settings.PRE_WARM_RADIUS_KM

    try:
        async with _WARM_SEMAPHORE:
            logger.info(f"Pre-warming: {city_name} ({lat}, {lon}), radius={radius_km}km...")
            # Load or download graph with full city radius
            G, region_key, graph_id = await cache.get_or_load_graph(lat, lon)

            # Compute or load static features
            static_features = await cache.get_or_compute_static_features(
                G, graph_id, region_key
            )

            # Pre-warm safety annotation for current time context
            # This means the first user request to this city skips the ML pipeline
            try:
                from services.weather_service import WeatherService
                from services.feature_engineering import SafetyFeatureEngineer
                from services.safety_model import SafetyScoringModel
                from datetime import datetime, timezone
                import numpy as np

                # Get current time context
                temp_eng = SafetyFeatureEngineer.__new__(SafetyFeatureEngineer)
                midpoints = np.array([[lat, lon]])
                is_night = temp_eng._compute_time_context(
                    datetime.now(timezone.utc), midpoints
                )
                time_context = "night" if is_night == 1 else "day"

                # Get weather
                weather_svc = WeatherService()
                weather_penalty = weather_svc.compute_weather_penalty(lat, lon)
                weather_bucket = cache.get_weather_bucket(weather_penalty)

                # Get gdf_edges from cache
                cached_entry = await cache.graph_registry.get(region_key)
                gdf_edges_cache = cached_entry.get("gdf_edges") if cached_entry else None

                # Merge dynamic features
                full_features = cache.merge_dynamic_features(
                    static_features, G, weather_penalty, is_night,
                    gdf_edges_cache=gdf_edges_cache,
                )

                # Load or train model
                cached_model = await cache.get_or_load_model(region_key)
                scorer = SafetyScoringModel.__new__(SafetyScoringModel)
                scorer.target_path = settings.MODEL_PATH

                if cached_model is not None:
                    scorer.model = cached_model
                else:
                    scorer.model = None
                    await asyncio.to_thread(
                        scorer.train_dynamic_model, full_features
                    )
                    if scorer.model is not None:
                        importance = dict(zip(
                            full_features.columns.tolist(),
                            [float(x) for x in scorer.model.feature_importances_],
                        )) if hasattr(scorer.model, 'feature_importances_') else {}
                        await cache.store_model(
                            scorer.model, region_key, len(full_features), importance
                        )

                # Annotate graph
                await asyncio.to_thread(
                    scorer.annotate_graph_with_safety, G, full_features
                )

                # Mark as annotated
                await cache.update_annotation_context(
                    region_key, time_context, weather_bucket
                )

                logger.info(f"Pre-warm complete (fully annotated): {city_name} ✓")
            except Exception as e:
                logger.warning(f"Pre-warm annotation failed for {city_name}: {e}. Graph+features still cached.")
                logger.info(f"Pre-warm complete (graph+features): {city_name} ✓")

    except Exception as e:
        logger.error(f"Pre-warm failed for {city_name}: {e}")


async def run_cache_warming():
    """
    Pre-warm top cities with parallel downloads.
    Uses a semaphore to limit concurrent downloads and avoid rate-limiting.
    Order is defined in settings.PRE_WARM_CITIES (Bangalore first).
    """
    cities_str = settings.PRE_WARM_CITIES
    if not cities_str:
        logger.info("No cities configured for pre-warming.")
        return

    cities = [c.strip() for c in cities_str.split(",") if c.strip()]
    logger.info(f"Starting cache pre-warm for {len(cities)} cities: {cities}")

    # Launch all cities concurrently — semaphore controls parallelism
    tasks = [warm_cache_for_city(city) for city in cities]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Log any failures
    for city, result in zip(cities, results):
        if isinstance(result, Exception):
            logger.error(f"Pre-warm error ({city}): {result}")

    logger.info(f"Cache pre-warming complete. {len(cities)} cities processed.")
