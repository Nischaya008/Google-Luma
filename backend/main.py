"""
Main FastAPI entrypoint for the Google Luma Geospatial ML System.

Architecture: OSRM + Safety Overlay
  - Routing: OSRM public server (instant, accurate, free)
  - Safety: Point-sampling with VIIRS + Crime KDE + Weather
  - Heatmap: On-demand OSMnx graph (lazy, only when user requests)

Startup lifecycle:
  1. Initialize Supabase and Redis clients (for caching)
  2. Pre-load safety data (KDE + VIIRS) in background
  3. Start serving requests immediately
"""


import asyncio
import logging

from contextlib import asynccontextmanager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Silence verbose HTTP/2 trace logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("hpack").setLevel(logging.WARNING)

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from core.config import settings

logger = logging.getLogger(__name__)


# ── Bomb-proof CORS Middleware ───────────────────────────────────────────
# Replaces Starlette's CORSMiddleware which silently breaks with certain
# allow_origins / allow_credentials combos across Starlette versions.
# This unconditionally injects CORS headers on EVERY response.

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH, HEAD",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With, Accept, Origin",
    "Access-Control-Max-Age": "86400",
}


class RawCORSMiddleware(BaseHTTPMiddleware):
    """Unconditionally inject CORS headers on every response, including errors."""

    async def dispatch(self, request: Request, call_next):
        # Handle preflight OPTIONS immediately — no need to hit the app
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS_HEADERS)

        # Normal request — forward to app, then inject headers
        response = await call_next(request)
        for key, value in CORS_HEADERS.items():
            response.headers[key] = value
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifecycle manager.

    On startup: Initialize cache + pre-load safety data.
    On shutdown: Clean up connections.
    """
    # ── STARTUP ──────────────────────────────────────────────────────────
    logger.info("═══ Google Luma Starting ═══")

    # Initialize cache clients (fails gracefully if credentials missing)
    try:
        from cache.cache_manager import CacheManager
        cache = CacheManager.get_instance()
        logger.info(
            f"Cache system initialized — "
            f"Supabase: {'✓' if cache.supabase.is_available else '✗'}, "
            f"Redis: {'✓' if cache.redis.is_available else '✗'}"
        )
    except Exception as e:
        logger.warning(f"Cache initialization failed (will operate without cache): {e}")

    async def _sequential_preload():
        import gc
        try:
            from services.route_scorer import RouteSafetyScorer
            scorer = RouteSafetyScorer.get_instance()
            await _preload_safety_data(scorer)
            logger.info("Safety data pre-loading complete.")
        except Exception as e:
            logger.warning(f"Safety data pre-load failed: {e}")

        # Aggressively collect garbage from KDE/Pandas DataFrame loading
        gc.collect()

        try:
            from services.cv_analyzer import CVSafetyAnalyzer
            cv = CVSafetyAnalyzer.get_instance()
            await _preload_cv_model(cv)
            logger.info("CV model pre-loading complete.")
        except Exception as e:
            logger.warning(f"CV model pre-load skipped: {e}")

        gc.collect()

    # Launch the sequential preload background task
    asyncio.create_task(_sequential_preload())
    logger.info("Sequential data & model pre-loading launched (background).")

    logger.info("═══ Google Luma Ready ═══")

    yield  # Server is running

    # ── SHUTDOWN ─────────────────────────────────────────────────────────
    logger.info("═══ Google Luma Shutting Down ═══")
    logger.info("═══ Google Luma Stopped ═══")


async def _preload_safety_data(scorer):
    """Pre-load KDE and VIIRS in a background thread."""
    try:
        await asyncio.to_thread(scorer.ensure_initialized)
        logger.info("Safety data pre-loaded ✓ (KDE + VIIRS ready)")
    except Exception as e:
        logger.warning(f"Safety data pre-load error: {e}")


async def _preload_cv_model(cv_analyzer):
    """Pre-load ONNX YOLOS-Tiny model from HuggingFace in a background thread."""
    try:
        await asyncio.to_thread(cv_analyzer.ensure_loaded)
        logger.info("CV model pre-loaded ✓ (ONNX YOLOS-Tiny ready)")
    except Exception as e:
        logger.warning(f"CV model pre-load error: {e}")


def create_app() -> FastAPI:
    """Initialize and configure the FastAPI application."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description="Multi-objective routing system optimizing for safety.",
        lifespan=lifespan,
    )

    # Bomb-proof CORS — injects headers on every response including errors.
    # Replaces Starlette CORSMiddleware which silently breaks with certain
    # allow_credentials + wildcard combinations across versions.
    app.add_middleware(RawCORSMiddleware)

    # Root endpoint — prevents 404 on Render's initial HEAD / port probe
    @app.get("/")
    async def root():
        return {"status": "ok", "service": "Google Luma"}

    # Include routers — imported here (not top-level) so that uvicorn
    # binds the port BEFORE heavy numpy/sklearn/PIL/onnx imports execute.
    # This prevents Render's port-scan timeout from cancelling deploys.
    from api.routes import health, routing, cv
    app.include_router(health.router, prefix="/api/v1/health", tags=["Health"])
    app.include_router(routing.router, prefix="/api/v1/routing", tags=["Routing"])
    app.include_router(cv.router, prefix="/api/v1/routing", tags=["Computer Vision"])

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

