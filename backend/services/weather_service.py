"""
Real-time weather integration via OpenWeatherMap free tier.

Weather data is ALWAYS real-time — it is the primary dynamic feature
that must never be served stale. Caching is limited to:
- Redis: 5-minute TTL (shared across all server instances)
- In-memory: fallback if Redis is unavailable

This service is intentionally NOT cached in Supabase Postgres because
weather data changes too rapidly for persistent storage to be useful.
"""
import logging
import time
from typing import Dict, Optional, Tuple
from core.config import settings

logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:
    requests = None
    logger.warning("requests library not installed. Weather service disabled.")


class WeatherService:
    """
    Weather service with Redis-backed shared cache.

    Cache hierarchy for weather:
    1. Redis (5-min TTL, shared across instances) — Primary
    2. In-memory dict (5-min TTL, per-instance) — Fallback
    3. OpenWeatherMap API (live) — Source of truth
    """

    def __init__(self):
        self._local_cache: Dict[str, Tuple[float, dict]] = {}
        self._enabled = bool(settings.OWM_API_KEY and requests)
        self._redis = None

        # Lazy-init Redis to avoid circular imports at module load time
        if self._enabled:
            logger.info("WeatherService initialized with OpenWeatherMap API key.")
        else:
            logger.warning("WeatherService disabled — no OWM_API_KEY in .env")

    def _get_redis(self):
        """Lazy-load Redis client (avoids import at module init time)."""
        if self._redis is None:
            try:
                from cache.redis_client import RedisClient
                self._redis = RedisClient.get_instance()
            except Exception:
                self._redis = False  # Sentinel: don't retry
        return self._redis if self._redis is not False else None

    def _cache_key(self, lat: float, lon: float) -> str:
        """Round coordinates to 2 decimal places for cache grouping (~1km grid)."""
        return f"weather:{round(lat, 2)}_{round(lon, 2)}"

    def _check_local_cache(self, key: str) -> Optional[dict]:
        """Check in-memory cache (fallback when Redis unavailable)."""
        if key in self._local_cache:
            ts, data = self._local_cache[key]
            if (time.time() - ts) < settings.WEATHER_CACHE_TTL:
                return data
            del self._local_cache[key]
        return None

    def get_current_weather(self, lat: float, lon: float) -> Optional[dict]:
        """
        Fetch current weather conditions. Cache hierarchy:
        1. Redis (shared, 5-min TTL)
        2. Local dict (per-instance, 5-min TTL)
        3. OWM API (live)
        """
        if not self._enabled:
            return None

        key = self._cache_key(lat, lon)

        # Tier 1: Redis (shared across instances)
        redis = self._get_redis()
        if redis and redis.is_available:
            cached = redis.get_json(key)
            if cached:
                return cached

        # Tier 2: Local in-memory
        cached = self._check_local_cache(key)
        if cached:
            return cached

        # Tier 3: Live API call
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {
            "lat": lat,
            "lon": lon,
            "appid": settings.OWM_API_KEY,
            "units": "metric",
        }

        try:
            resp = requests.get(url, params=params, timeout=5)
            resp.raise_for_status()
            raw = resp.json()

            data = {
                "temp": raw.get("main", {}).get("temp", 25.0),
                "humidity": raw.get("main", {}).get("humidity", 50),
                "visibility_m": raw.get("visibility", 10000),
                "wind_speed": raw.get("wind", {}).get("speed", 0.0),
                "weather_main": raw.get("weather", [{}])[0].get("main", "Clear"),
                "weather_description": raw.get("weather", [{}])[0].get("description", ""),
            }

            # Store in both caches
            ttl = settings.WEATHER_CACHE_TTL
            if redis and redis.is_available:
                redis.set_json(key, data, ttl)
            self._local_cache[key] = (time.time(), data)

            logger.info(
                f"Weather for ({lat:.2f}, {lon:.2f}): {data['weather_main']}, "
                f"visibility={data['visibility_m']}m"
            )
            return data

        except Exception as e:
            logger.error(f"Weather API call failed: {e}")
            return None

    def compute_weather_penalty(self, lat: float, lon: float) -> float:
        """
        Compute a weather-based safety penalty in [0.0, 1.0].
        0.0 = perfect conditions, 1.0 = worst conditions.
        """
        weather = self.get_current_weather(lat, lon)
        if weather is None:
            return 0.0  # No data → neutral (no penalty)

        penalty = 0.0

        # Visibility penalty
        visibility = weather["visibility_m"]
        if visibility < 1000:
            penalty += 0.5
        elif visibility < 3000:
            penalty += 0.3
        elif visibility < 5000:
            penalty += 0.15

        # Precipitation penalty
        main = weather["weather_main"].lower()
        if "thunderstorm" in main:
            penalty += 0.4
        elif "rain" in main or "drizzle" in main:
            penalty += 0.2
        elif "snow" in main:
            penalty += 0.3
        elif "fog" in main or "mist" in main or "haze" in main:
            penalty += 0.25

        # Wind penalty
        if weather["wind_speed"] > 15:
            penalty += 0.1

        return min(penalty, 1.0)

    def get_weather_bucket(self, lat: float, lon: float) -> str:
        """Classify current weather into a cache bucket."""
        penalty = self.compute_weather_penalty(lat, lon)
        if penalty < 0.1:
            return "clear"
        elif penalty < 0.3:
            return "mild"
        elif penalty < 0.6:
            return "rain"
        else:
            return "storm"
