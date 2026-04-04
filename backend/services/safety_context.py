"""
Dynamic safety context derived from time and geography.

Assumptions (documented for auditability):
  * **Local time** is approximated from UTC + longitude (solar time). This is
    deterministic and dependency-free; it does not model DST or political
    time zones, so hour-of-day risk is a smooth prior, not a legal clock.
  * **Footfall proxy** is not raw pedestrian counts (those require proprietary
    mobility feeds). It combines VIIRS night radiance, road class, and area
    brightness — validated proxies for populated corridors in peer literature.
  * **VIIRS** reflects recent NASA monthly composites, not millisecond lighting.

These factors complement live weather (OpenWeatherMap) and static/loaded
crime KDE where the training data applies.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class TemporalContext:
    """Hour-of-day risk envelope at the route location (approximate local hour)."""

    local_hour: float
    """Approximate local hour [0, 24) from solar longitude adjustment."""
    temporal_risk: float
    """[0, 1] elevated risk during very late night / pre-dawn (visibility + isolation)."""


def approximate_local_hour(lon: float, utc_now: datetime | None = None) -> float:
    """
    Estimate local solar hour using longitude offset from UTC.

    WHY solar approximation: avoids extra dependencies (timezone DB, offline
    shapefiles) while still shifting risk curves west/east with the sun.
    """
    now = utc_now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    utc_decimal = now.hour + now.minute / 60.0 + now.second / 3600.0
    # 15° longitude ≈ 1 hour
    local = (utc_decimal + lon / 15.0) % 24.0
    return float(local)


def _temporal_risk_from_local_hour(local_h: float) -> float:
    """
    Piecewise risk by local solar hour: low daytime, elevated shoulders, peak after midnight.
    """
    h = local_h % 24.0
    if 8.0 <= h < 19.0:
        return 0.06
    if h >= 23.0 or h < 4.0:
        return 0.82
    if 19.0 <= h < 23.0:
        return 0.35 + 0.47 * (h - 19.0) / 4.0
    # 4 <= h < 8 (pre-rush dawn)
    return 0.45 - 0.39 * (h - 4.0) / 4.0


def compute_temporal_context(lat: float, lon: float, utc_now: datetime | None = None) -> TemporalContext:
    """
    Build temporal risk from approximate local solar hour at (lat, lon).

    Astral-based day/night for weight selection stays in ``RouteSafetyScorer.compute_is_night``;
    this curve adds hour-of-night granularity (e.g. 2am vs 8pm) without duplicate astral calls
    per segment.

    ``lat`` is part of the public signature for geo-consistent call sites; seasonal extensions
    may use it later.
    """
    local_h = approximate_local_hour(lon, utc_now)
    temporal_risk = float(max(0.0, min(1.0, _temporal_risk_from_local_hour(local_h))))
    return TemporalContext(local_hour=local_h, temporal_risk=temporal_risk)


def compute_footfall_proxy(point_light: float, area_light: float, road_class: float) -> float:
    """
    Proxy for expected human presence / commercial bustle along a segment.

    WHY weighted blend: major roads draw traffic even when a single VIIRS pixel
    is dim; bright surroundings without road class support may be parking or
    empty lots — road_class anchors the signal.
    """
    p = max(0.0, min(1.0, point_light))
    a = max(0.0, min(1.0, area_light))
    r = max(0.0, min(1.0, road_class))
    return float(0.35 * p + 0.40 * a + 0.25 * r)


def apply_temporal_safety_adjustment(
    base_safety: float,
    temporal_risk: float,
    is_night: bool,
    max_drag: float = 0.12,
) -> float:
    """
    Down-weight safety during high temporal_risk; stronger at night.

    WHY multiplicative tail: preserves existing feature balance while encoding
    that the same road feels riskier at 2am than at 2pm without exploding
    new weight dimensions in the linear model.
    """
    drag = max_drag * temporal_risk * (1.0 if is_night else 0.55)
    adjusted = base_safety * (1.0 - drag)
    return float(max(0.0, min(1.0, adjusted)))
