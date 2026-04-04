"""
Real-world ambient context from OpenStreetMap via the public Overpass API.

Uses live OSM data (police, hospitals, shops, restaurants, street lamps, etc.)
within a radius of a route corridor center. This captures **surroundings** that
VIIRS/crime alone miss: formal guardians, commercial bustle, and mapped lighting.

Assumptions:
  * OSM coverage varies by region; sparse mapping yields a lower score, not a
    moral judgment about the place — we treat missing data cautiously.
  * Overpass is rate-limited; we cache aggressively by quantized lat/lon.
"""
from __future__ import annotations

import logging
import math
from functools import lru_cache
from typing import Any, Dict, Tuple

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


def _quantize(ll: float) -> float:
    """~100 m quantization for cache keys (stable across tiny jitter)."""
    return round(ll, 3)


def _counts_to_ambient_score(counts: Dict[str, int]) -> float:
    """
    Map raw POI counts to [0, 1].

    WHY these caps: a single police node is meaningful; shops need scale to
    represent a "busy" corridor; lamps are under-mapped in OSM so we cap high.
    """
    police = min(1.0, counts.get("police", 0) / 2.0)
    medical = min(1.0, counts.get("medical", 0) / 2.0)
    shop = min(1.0, counts.get("shop", 0) / 28.0)
    food = min(1.0, counts.get("food", 0) / 18.0)
    lamp = min(1.0, counts.get("lamp", 0) / 24.0)
    fuel = min(1.0, counts.get("fuel", 0) / 6.0)

    return float(
        0.20 * police
        + 0.18 * medical
        + 0.22 * shop
        + 0.18 * food
        + 0.12 * lamp
        + 0.10 * fuel
    )


class AmbientOverpassService:
    """
    Fetches OSM context around a point. Thread-safe for use via asyncio.to_thread.
    """

    _instance: "AmbientOverpassService | None" = None

    def __init__(self) -> None:
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=min(10.0, settings.OVERPASS_TIMEOUT_S),
                read=settings.OVERPASS_TIMEOUT_S,
                write=10.0,
                pool=10.0,
            )
        )

    @classmethod
    def get_instance(cls) -> "AmbientOverpassService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _build_query(self, lat: float, lon: float, radius_m: int) -> str:
        # Nodes only — fast; avoids heavy way/relation geometry.
        return f"""[out:json][timeout:10];
(
  node["amenity"="police"](around:{radius_m},{lat},{lon});
  node["amenity"="hospital"](around:{radius_m},{lat},{lon});
  node["amenity"="clinic"](around:{radius_m},{lat},{lon});
  node["amenity"="pharmacy"](around:{radius_m},{lat},{lon});
  node["shop"](around:{radius_m},{lat},{lon});
  node["amenity"="restaurant"](around:{radius_m},{lat},{lon});
  node["amenity"="cafe"](around:{radius_m},{lat},{lon});
  node["amenity"="fuel"](around:{radius_m},{lat},{lon});
  node["highway"="street_lamp"](around:{radius_m},{lat},{lon});
);
out;
"""

    def _parse_elements(self, elements: list[Dict[str, Any]]) -> Dict[str, int]:
        counts = {
            "police": 0,
            "medical": 0,
            "shop": 0,
            "food": 0,
            "lamp": 0,
            "fuel": 0,
        }
        for el in elements:
            if el.get("type") != "node":
                continue
            tags = el.get("tags") or {}
            amenity = tags.get("amenity")
            highway = tags.get("highway")
            if amenity == "police":
                counts["police"] += 1
            elif amenity in ("hospital", "clinic", "pharmacy"):
                counts["medical"] += 1
            elif tags.get("shop"):
                counts["shop"] += 1
            elif amenity in ("restaurant", "cafe"):
                counts["food"] += 1
            elif amenity == "fuel":
                counts["fuel"] += 1
            elif highway == "street_lamp":
                counts["lamp"] += 1
        return counts

    def fetch_raw_counts(self, lat: float, lon: float) -> Tuple[Dict[str, int], float]:
        """
        Query Overpass and return tag counts plus the computed ambient score.

        On failure, returns empty counts and a neutral-bounded score (~0.35).
        """
        if not settings.AMBIENT_OVERPASS_ENABLED:
            return {}, 0.35

        radius = max(120, int(settings.AMBIENT_RADIUS_M))
        q = self._build_query(lat, lon, radius)
        try:
            resp = self._client.post(
                settings.OVERPASS_API_URL,
                content=q,
                headers={"Content-Type": "text/plain; charset=utf-8"},
            )
            if resp.status_code >= 400:
                logger.warning("Overpass HTTP %s", resp.status_code)
                return {}, 0.35
            data = resp.json()
            elements = data.get("elements") or []
            counts = self._parse_elements(elements)
            score = _counts_to_ambient_score(counts)
            # Slight floor so totally empty OSM does not read as "maximum danger"
            if not elements:
                score = max(score, 0.22)
            return counts, float(max(0.0, min(1.0, score)))
        except Exception as e:
            logger.warning("Overpass ambient fetch failed: %s", e)
            return {}, 0.35


@lru_cache(maxsize=512)
def _cached_ambient_score(lat_q: int, lon_q: int) -> float:
    """
    Process-wide cache on quantized integer coords (millidegrees).

    WHY integers: avoids float hashing quirks and bounds memory.
    """
    lat = lat_q / 1000.0
    lon = lon_q / 1000.0
    svc = AmbientOverpassService.get_instance()
    _, score = svc.fetch_raw_counts(lat, lon)
    if math.isnan(score):
        return 0.35
    return score


def corridor_ambient_score(lat: float, lon: float) -> float:
    """
    Public entry: ambient score [0,1] for route corridor center (or any point).

    Cached per ~100m cell for fast repeated scoring.
    """
    lat_q = int(round(_quantize(lat) * 1000))
    lon_q = int(round(_quantize(lon) * 1000))
    return _cached_ambient_score(lat_q, lon_q)
