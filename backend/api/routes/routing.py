"""
Routing endpoints — V3: OSRM + Per-Segment Safety Scoring.

Pipeline:
  1. Check Redis/Supabase cache → instant if hit (<200ms)
  2. OSRM: Get 3 distinct routes with step-level road metadata (~500ms)
  3. Scorer: Per-step safety scoring using VIIRS + Crime KDE + Road Class (~300ms)
  4. Cache: Store in Redis + Supabase for future requests
  5. Return: Routes with accurate ETA/distance/safety

Performance:
  - Cached request: <200ms
  - Fresh request: <3s
  - No graph download needed for routing

Heatmap: Still uses OSMnx graph (lazy, on-demand when user toggles).
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Literal

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from core.config import settings
from models.schemas import (
    CompareRoutesResponse,
    Coordinate,
    RoutePayload,
    RouteRequest,
)
from services.osrm_router import OSRMRouter
from services.route_scorer import RouteSafetyScorer

logger = logging.getLogger(__name__)

router = APIRouter()


def _validate_wgs84_point(lat: float, lng: float, context: str = "coordinates") -> None:
    """
    Reject out-of-range points early so OSRM/OSMnx never see absurd lon/lat
    (common when clients swap or corrupt GeoJSON order).
    """
    if lat is None or lng is None:
        raise HTTPException(status_code=400, detail=f"{context}: lat and lng required")
    if not (-90.0 <= lat <= 90.0):
        raise HTTPException(
            status_code=400,
            detail=f"{context}: invalid latitude {lat} (expected -90..90)",
        )
    if not (-180.0 <= lng <= 180.0):
        raise HTTPException(
            status_code=400,
            detail=(
                f"{context}: invalid longitude {lng} (expected -180..180). "
                "If values look like 10085, latitude and longitude may be swapped or a bad geocode."
            ),
        )


# ── Lazy Singletons ─────────────────────────────────────────────────────


def _get_weather_service():
    if not hasattr(_get_weather_service, "_svc"):
        from services.weather_service import WeatherService
        _get_weather_service._svc = WeatherService()
    return _get_weather_service._svc


def _get_cache():
    from cache.cache_manager import CacheManager
    return CacheManager.get_instance()


# ── Init Endpoint ────────────────────────────────────────────────────────


@router.post("/init")
async def init_system(lat: float, lng: float):
    """
    Pre-load safety data (KDE + VIIRS) for fast scoring.
    With OSRM routing, this is instant — no graph download.
    """
    _validate_wgs84_point(lat, lng, "init location")
    try:
        scorer = RouteSafetyScorer.get_instance()
        await asyncio.to_thread(scorer.ensure_initialized)
        return {"status": "ready"}
    except Exception as e:
        logger.exception("POST /init failed")
        raise HTTPException(status_code=500, detail=str(e))


# ── Route Comparison (Main Endpoint) ─────────────────────────────────────


@router.get("/routes/compare", response_model=CompareRoutesResponse)
async def compare_routes(
    src_lat: float, src_lon: float,
    dest_lat: float, dest_lon: float,
    travel_profile: Literal["driving", "foot"] = Query(
        "driving",
        description="OSRM routing profile: driving (car) or foot (walking)",
    ),
):
    """
    Return 3 distinct routes: fastest, balanced, and safest.

    Each route has:
      - Accurate geometry (follows real roads or foot paths)
      - Accurate ETA (from OSRM, matches Google Maps ±10%)
      - Real safety score (VIIRS + Crime + Road + Weather)
    """
    _validate_wgs84_point(src_lat, src_lon, "origin")
    _validate_wgs84_point(dest_lat, dest_lon, "destination")

    cache = _get_cache()
    scorer = RouteSafetyScorer.get_instance()

    # ── Time context ──────────────────────────────────────────────────
    center_lat = (src_lat + dest_lat) / 2.0
    center_lon = (src_lon + dest_lon) / 2.0
    is_night = scorer.compute_is_night(center_lat, center_lon)
    time_context = "night" if is_night else "day"

    # ── Check cache ───────────────────────────────────────────────────
    try:
        cached_routes = await cache.find_cached_routes(
            src_lat, src_lon, dest_lat, dest_lon, time_context, travel_profile,
        )
        if cached_routes:
            logger.info("Route comparison served from cache ✓")
            return _build_response_from_cache(
                src_lat, src_lon, dest_lat, dest_lon, cached_routes, travel_profile,
            )
    except Exception as e:
        logger.warning(f"Cache lookup failed (continuing without): {e}")

    # ── Fresh computation ─────────────────────────────────────────────
    try:
        # Step 1: Get 3 routes from OSRM (instant, accurate)
        osrm = OSRMRouter.get_instance()
        raw_routes = await asyncio.to_thread(
            osrm.get_routes,
            (src_lat, src_lon),
            (dest_lat, dest_lon),
            travel_profile,
        )

        logger.info(f"OSRM returned {len(raw_routes)} distinct routes")

        # Step 2: Get weather (live, parallel with scoring)
        weather = _get_weather_service()
        weather_penalty = weather.compute_weather_penalty(center_lat, center_lon)

        # Step 3: Score and rank routes (per-step analysis)
        labeled = await scorer.score_and_rank_routes_async(
            raw_routes,
            weather_penalty,
            is_night,
            travel_profile=travel_profile,
            corridor_center=(center_lat, center_lon),
        )

        # Step 4: Build response
        payload_routes = []
        cache_data = []

        for r in labeled:
            coords = [Coordinate(lat=p[0], lon=p[1]) for p in r["geometry"]]

            payload_routes.append(RoutePayload(
                mode=r["mode"],
                route_geometry=coords,
                estimated_time_seconds=r["duration_seconds"],
                distance_meters=r["distance_meters"],
                average_safety_score=r["safety_score"],
                total_cost=r["duration_seconds"],
                ai_insight=r.get("ai_insight", ""),
            ))

            cache_data.append({
                "mode": r["mode"],
                "route_geometry": [{"lat": c.lat, "lon": c.lon} for c in coords],
                "estimated_time_seconds": r["duration_seconds"],
                "distance_meters": r["distance_meters"],
                "average_safety_score": r["safety_score"],
                "total_cost": r["duration_seconds"],
                "ai_insight": r.get("ai_insight", ""),
            })

        # Step 5: Cache for future requests
        try:
            weather_bucket = cache.get_weather_bucket(weather_penalty)
            await cache.store_route_cache(
                src_lat, src_lon, dest_lat, dest_lon,
                time_context, weather_bucket, cache_data, None, travel_profile,
            )
        except Exception as e:
            logger.warning(f"Route cache storage failed: {e}")

        return CompareRoutesResponse(
            origin=Coordinate(lat=src_lat, lon=src_lon),
            destination=Coordinate(lat=dest_lat, lon=dest_lon),
            routes=payload_routes,
            rankings=_compute_rankings(cache_data),
            tradeoff_metrics=_compute_tradeoffs(cache_data),
            travel_profile=travel_profile,
        )

    except RuntimeError as e:
        logger.warning("GET /routes/compare routing rejected: %s", e)
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        logger.exception("GET /routes/compare failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ── Single Route Endpoint ────────────────────────────────────────────────


@router.post("/route", response_model=RoutePayload)
async def calculate_single_route(request: RouteRequest):
    """Compute a single route for the requested mode."""
    src_lat, src_lon = request.source
    dest_lat, dest_lon = request.destination
    _validate_wgs84_point(src_lat, src_lon, "origin")
    _validate_wgs84_point(dest_lat, dest_lon, "destination")

    try:
        profile = request.travel_profile if request.travel_profile in ("driving", "foot") else "driving"
        osrm = OSRMRouter.get_instance()
        routes = await asyncio.to_thread(
            osrm.get_routes,
            (src_lat, src_lon),
            (dest_lat, dest_lon),
            profile,
        )

        scorer = RouteSafetyScorer.get_instance()
        center_lat = (src_lat + dest_lat) / 2.0
        center_lon = (src_lon + dest_lon) / 2.0

        weather = _get_weather_service()
        weather_penalty = weather.compute_weather_penalty(center_lat, center_lon)
        is_night = scorer.compute_is_night(center_lat, center_lon)

        labeled = await scorer.score_and_rank_routes_async(
            routes,
            weather_penalty,
            is_night,
            travel_profile=profile,
            corridor_center=(center_lat, center_lon),
        )

        # Find the requested mode
        target = next(
            (r for r in labeled if r["mode"] == request.mode),
            labeled[0],
        )

        coords = [Coordinate(lat=p[0], lon=p[1]) for p in target["geometry"]]
        return RoutePayload(
            mode=target["mode"],
            route_geometry=coords,
            estimated_time_seconds=target["duration_seconds"],
            distance_meters=target["distance_meters"],
            average_safety_score=target["safety_score"],
            total_cost=target["duration_seconds"],
            ai_insight=target.get("ai_insight", ""),
        )

    except RuntimeError as e:
        logger.warning("POST /route routing rejected: %s", e)
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        logger.exception("POST /route failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ── Heatmap Endpoint (Graph-based, lazy on-demand) ───────────────────────


@router.get("/heatmap")
async def get_safety_heatmap(lat: float = None, lng: float = None):
    """
    Safety heatmap overlay: every road segment with safety score.

    This is the ONLY endpoint using OSMnx. Downloads 5km graph on first
    request for the area, cached in Supabase for subsequent requests.
    """
    if lat is None or lng is None:
        raise HTTPException(status_code=400, detail="lat and lng required")

    _validate_wgs84_point(lat, lng, "heatmap center")

    cache = _get_cache()
    scorer = RouteSafetyScorer.get_instance()
    is_night = scorer.compute_is_night(lat, lng)
    time_context = "night" if is_night else "day"

    c_lat, c_lon, r_km = cache.compute_region_params(lat, lng)
    rk = cache.region_key(c_lat, c_lon, r_km)

    # Check Redis cache
    cached = cache.get_cached_heatmap(rk, time_context)
    if cached:
        logger.info("Heatmap served from cache ✓")
        return cached

    # Download graph + compute features + annotate (on-demand)
    try:
        import osmnx as ox

        G, region_key, graph_id = await cache.get_or_load_graph(lat, lng)

        # Compute features and annotate
        static_features = await cache.get_or_compute_static_features(
            G, graph_id, region_key,
        )

        weather = _get_weather_service()
        weather_penalty = weather.compute_weather_penalty(lat, lng)

        from services.feature_engineering import SafetyFeatureEngineer
        temp_eng = SafetyFeatureEngineer.__new__(SafetyFeatureEngineer)
        midpoints = np.array([[lat, lng]])
        is_night_val = temp_eng._compute_time_context(
            datetime.now(timezone.utc), midpoints,
        )

        cached_entry = await cache.graph_registry.get(region_key)
        gdf_edges_cache = cached_entry.get("gdf_edges") if cached_entry else None

        full_features = cache.merge_dynamic_features(
            static_features, G, weather_penalty, is_night_val,
            gdf_edges_cache=gdf_edges_cache,
        )

        # Train/load model + annotate
        from services.safety_model import SafetyScoringModel
        cached_model = await cache.get_or_load_model(region_key)

        model = SafetyScoringModel.__new__(SafetyScoringModel)
        model.target_path = settings.MODEL_PATH

        if cached_model is not None:
            model.model = cached_model
        else:
            model.model = None
            model.train_dynamic_model(full_features)

        G = model.annotate_graph_with_safety(G, full_features)

        # Build heatmap response
        lines = []
        for u, v, key, data in G.edges(keys=True, data=True):
            if "geometry" in data:
                coords = [[lat, lon] for lon, lat in data["geometry"].coords]
            else:
                coords = [
                    [G.nodes[u]["y"], G.nodes[u]["x"]],
                    [G.nodes[v]["y"], G.nodes[v]["x"]],
                ]
            lines.append({
                "u": u, "v": v, "key": key,
                "safety_score": float(data.get("safety_score", 0.5)),
                "geometry": coords,
            })

        result = {"total_edges": len(lines), "edges": lines}
        cache.store_heatmap(rk, time_context, result)
        return result

    except Exception as e:
        logger.exception("GET /heatmap failed")
        raise HTTPException(status_code=500, detail=str(e))


# ── Explainability ───────────────────────────────────────────────────────


@router.get("/explain")
async def explain_safety(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    """Feature breakdown for a geographic point."""
    scorer = RouteSafetyScorer.get_instance()

    try:
        point_light, area_light = scorer.sample_lighting_context(lat, lon)
        crime = scorer.sample_crime(lat, lon)
        is_night = scorer.compute_is_night(lat, lon)

        weather = _get_weather_service()
        weather_penalty = weather.compute_weather_penalty(lat, lon)

        # Create a mock step for scoring
        mock_step = {
            "geometry": [(lat, lon)],
            "road_class": 0.5,
            "distance_m": 100,
        }
        safety, features = scorer.score_step(mock_step, weather_penalty, is_night)

        return {
            "location": {"lat": lat, "lon": lon},
            "safety_score": round(safety, 4),
            "features": {
                "lighting": round(point_light, 4),
                "area_brightness": round(area_light, 4),
                "crime_density": round(crime, 4),
                "footfall_proxy": round(features.get("footfall_proxy", 0), 4),
                "local_hour_approx": round(features.get("local_hour_approx", 0), 2),
                "temporal_risk": round(features.get("temporal_risk", 0), 4),
                "is_night": is_night,
                "weather_risk": round(weather_penalty, 4),
            },
            "interpretation": _interpret(point_light, crime, is_night, weather_penalty),
        }
    except Exception as e:
        logger.exception("GET /explain failed")
        raise HTTPException(status_code=500, detail=str(e))


# ── Helpers ──────────────────────────────────────────────────────────────


def _build_response_from_cache(
    src_lat, src_lon, dest_lat, dest_lon, cached_routes, travel_profile: str = "driving",
) -> CompareRoutesResponse:
    """Build response from cached route data."""
    payload_routes = [
        RoutePayload(
            mode=r["mode"],
            route_geometry=[
                Coordinate(lat=p["lat"], lon=p["lon"])
                for p in r["route_geometry"]
            ],
            estimated_time_seconds=r["estimated_time_seconds"],
            distance_meters=r.get("distance_meters", 0.0),
            average_safety_score=r["average_safety_score"],
            total_cost=r["total_cost"],
            ai_insight=r.get("ai_insight", ""),
        )
        for r in cached_routes
    ]
    return CompareRoutesResponse(
        origin=Coordinate(lat=src_lat, lon=src_lon),
        destination=Coordinate(lat=dest_lat, lon=dest_lon),
        routes=payload_routes,
        rankings=_compute_rankings(cached_routes),
        tradeoff_metrics=_compute_tradeoffs(cached_routes),
        travel_profile=travel_profile,
    )


def _compute_rankings(routes: list) -> dict:
    by_safety = sorted(routes, key=lambda x: x.get("average_safety_score", 0), reverse=True)
    by_speed = sorted(routes, key=lambda x: x.get("estimated_time_seconds", 0))
    return {
        "highest_safety": [r["mode"] for r in by_safety],
        "fastest_time": [r["mode"] for r in by_speed],
    }


def _compute_tradeoffs(routes: list) -> dict:
    fastest = next((r for r in routes if r["mode"] == "fastest"), routes[0])
    base_time = fastest.get("estimated_time_seconds", 0)
    base_safety = fastest.get("average_safety_score", 0)

    return {
        r["mode"]: {
            "time_penalty_seconds": round(
                r.get("estimated_time_seconds", 0) - base_time, 1
            ),
            "safety_gain_absolute": round(
                r.get("average_safety_score", 0) - base_safety, 4
            ),
        }
        for r in routes
    }


def _interpret(lighting, crime, is_night, weather_risk) -> str:
    factors = []
    if lighting > 0.6:
        factors.append("well-lit area")
    elif lighting < 0.3:
        factors.append("poorly lit area")
    if crime > 0.6:
        factors.append("higher crime density")
    elif crime < 0.3:
        factors.append("low crime area")
    if is_night:
        factors.append("nighttime conditions")
    if weather_risk > 0.3:
        factors.append("adverse weather")
    return ("Key factors: " + ", ".join(factors)) if factors else "Average safety conditions"
