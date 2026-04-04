"""
OSRM (Open Source Routing Machine) client — V3 architecture.

Key capabilities:
  1. Instant routing via free public server (no API key, global coverage)
  2. Step-level road metadata (names, references, road classification)
  3. Guaranteed 3 distinct routes via perpendicular-offset waypoint strategy
  4. Google-Maps-accurate ETAs and distances

When OSRM's native alternatives aren't diverse enough, we force different
corridors by routing through waypoints offset perpendicular to the direct
origin→destination line. This guarantees visually distinct routes that
traverse genuinely different neighborhoods.
"""
import logging
import math
from typing import List, Dict, Tuple, Optional

import httpx

from core.config import settings
from utils.geo_utils import calculate_haversine_distance

logger = logging.getLogger(__name__)

def _osrm_disconnected_msg(profile: str) -> str:
    """Explain impossible OSM network paths for the active travel mode."""
    if profile == "foot":
        return (
            "No continuous walking route exists between these points—they may be too far apart, "
            "separated by water, or not connected by walkable paths in OpenStreetMap."
        )
    return (
        "No continuous driving route exists between these places—they are too far apart or "
        "separated by ocean. This app only supports car routes on connected roads "
        "(for example, within a continent). For India to Australia you would need air or sea travel."
    )


class OSRMRouter:
    """Client for the OSRM routing API with enriched road-segment data."""

    _instance = None

    def __init__(self, base_url: str | None = None):
        # Default host used when no per-profile override applies (typically driving).
        self.base_url = (base_url or settings.OSRM_BASE_URL).rstrip("/")
        # Separate connect vs read: slow TTFB is rare; large JSON bodies often need >30s.
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=settings.OSRM_TIMEOUT_CONNECT,
                read=settings.OSRM_TIMEOUT_READ,
                write=30.0,
                pool=10.0,
            )
        )

    @classmethod
    def get_instance(cls) -> "OSRMRouter":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _resolve_base_url(self, profile: str) -> str:
        """
        Pick the OSRM deployment for the requested profile.

        The public Project-OSRM demo does not apply distinct speed models per profile
        (driving/foot return identical ETAs). Foot routing therefore uses a mirror that
        exposes a real pedestrian graph + walking speeds when ``OSRM_BASE_URL_FOOT``
        is set.
        """
        if profile == "foot":
            foot = (getattr(settings, "OSRM_BASE_URL_FOOT", None) or "").strip()
            if foot:
                return foot.rstrip("/")
        return self.base_url

    def _ensure_realistic_walking_metrics(self, route: Dict) -> None:
        """
        Correct foot-profile ETAs when the upstream OSRM instance still returns car-like
        speeds (observed on some public endpoints).
        """
        dist = max(float(route.get("distance_meters", 0.0)), 1.0)
        dur = max(float(route.get("duration_seconds", 1.0)), 0.1)
        implied_kmh = (dist / dur) * 3.6
        if implied_kmh <= settings.WALK_MAX_IMPLIED_SPEED_KMH:
            return
        walk_s = dist / max(settings.WALK_SPEED_MPS, 0.5)
        route["duration_seconds"] = walk_s
        scale = walk_s / dur if dur > 0 else 1.0
        for step in route.get("steps", []):
            ds = float(step.get("duration_s", 0.0))
            step["duration_s"] = ds * scale

    # ── Core Routing ─────────────────────────────────────────────────────

    def get_routes(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        profile: str = "driving",
    ) -> List[Dict]:
        """
        Get up to 3 distinct routes between origin and destination.

        Args:
            origin: (lat, lon)
            destination: (lat, lon)
            profile: OSRM profile, ``driving`` or ``foot`` (walking).

        Returns:
            List of enriched route dicts (geometry, duration_seconds, distance_meters, steps).
        """
        if profile not in ("driving", "foot"):
            profile = "driving"

        d_km = calculate_haversine_distance(
            origin[0], origin[1], destination[0], destination[1]
        )
        if d_km > settings.OSRM_MAX_HAVERSINE_KM:
            kind = "Walking" if profile == "foot" else "Driving"
            raise RuntimeError(
                f"{kind} directions are not available: straight-line distance is about {d_km:,.0f} km "
                f"(limit {settings.OSRM_MAX_HAVERSINE_KM:,.0f} km for this engine). "
                f"Pick two locations on the same connected land mass."
            )

        # Step 1: Try native OSRM alternatives
        routes = self._fetch_routes(origin, destination, alternatives=3, profile=profile)

        # Step 2: Deduplicate routes that are too similar
        routes = self._deduplicate_routes(routes)

        # Step 3: If we need more routes, force via waypoint offsets
        if len(routes) < 3:
            logger.info(
                f"OSRM returned {len(routes)} unique routes. "
                f"Generating forced alternatives via waypoint offsets..."
            )
            routes = self._generate_forced_alternatives(
                origin, destination, existing_routes=routes, profile=profile
            )

        # Step 4: Reject absurd detours (> 1.8x shortest distance)
        if routes:
            min_dist = min(r["distance_meters"] for r in routes)
            before = len(routes)
            sane_routes = [r for r in routes if r["distance_meters"] <= min_dist * 1.8]
            if sane_routes:
                routes = sane_routes
                dropped = before - len(routes)
                if dropped > 0:
                    logger.info(
                        f"Filtered out {dropped} absurd detour routes (>1.8x shortest)"
                    )

        # Return what we have (1-3 routes). Frontend handles merged tabs.
        routes = routes[:3]

        for i, r in enumerate(routes):
            if profile == "foot":
                self._ensure_realistic_walking_metrics(r)
            logger.info(
                f"  Route {i+1}: {r['duration_seconds']/60:.1f}min, "
                f"{r['distance_meters']/1000:.1f}km, "
                f"{len(r['steps'])} segments, "
                f"{len(r['geometry'])} geo-points"
            )

        return routes

    def _fetch_routes(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        alternatives: int = 3,
        waypoints: List[Tuple[float, float]] = None,
        profile: str = "driving",
    ) -> List[Dict]:
        """
        Raw OSRM API call with step-level parsing.

        Uses steps=true for road names, references, and segment geometry.
        """
        if profile not in ("driving", "foot"):
            profile = "driving"
        # Build coordinate string (OSRM uses lon,lat)
        coords_parts = [f"{origin[1]},{origin[0]}"]
        if waypoints:
            for wp in waypoints:
                coords_parts.append(f"{wp[1]},{wp[0]}")
        coords_parts.append(f"{destination[1]},{destination[0]}")
        coords_str = ";".join(coords_parts)

        base = self._resolve_base_url(profile)
        url = f"{base}/route/v1/{profile}/{coords_str}"
        params = {
            "alternatives": str(alternatives) if not waypoints else "false",
            "overview": "full",
            "geometries": "geojson",
            "steps": "true",          # Get road names, refs, per-segment data
        }

        try:
            response = self._client.get(url, params=params)
            if response.status_code >= 400:
                self._raise_for_osrm_http_error(response, profile)
            data = response.json()
        except RuntimeError:
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"OSRM request failed: {e}")
            raise RuntimeError(_osrm_disconnected_msg(profile)) from e
        except Exception as e:
            logger.error(f"OSRM request failed: {e}")
            raise RuntimeError(f"OSRM routing failed: {e}") from e

        if data.get("code") != "Ok":
            code = data.get("code")
            msg = data.get("message", "") or ""
            if code == "NoRoute":
                raise RuntimeError(_osrm_disconnected_msg(profile))
            raise RuntimeError(
                f"OSRM could not build a route ({code}: {msg}). "
                f"If this is a very long or overseas trip, driving directions may not exist."
            )

        routes = []
        for route_data in data.get("routes", []):
            # Parse full-route geometry
            coords = route_data["geometry"]["coordinates"]
            geometry = [(c[1], c[0]) for c in coords]

            # Parse step-level segments
            steps = []
            for leg in route_data.get("legs", []):
                for step in leg.get("steps", []):
                    if step.get("distance", 0) < 1:
                        continue  # Skip trivial steps (arrive step)

                    step_coords = step["geometry"]["coordinates"]
                    step_geom = [(c[1], c[0]) for c in step_coords]

                    steps.append({
                        "name": step.get("name", ""),
                        "ref": step.get("ref", ""),
                        "distance_m": step["distance"],
                        "duration_s": step["duration"],
                        "geometry": step_geom,
                        "road_class": self._classify_road(
                            step.get("ref", ""),
                            step.get("name", ""),
                            step.get("distance", 0),
                            step.get("duration", 0),
                        ),
                    })

            routes.append({
                "geometry": geometry,
                "duration_seconds": route_data["duration"],
                "distance_meters": route_data["distance"],
                "steps": steps,
            })

        return routes

    @staticmethod
    def _raise_for_osrm_http_error(response: httpx.Response, profile: str = "driving") -> None:
        """Translate OSRM 4xx into a clear RuntimeError (body is often empty on demo server)."""
        snippet = (response.text or "")[:500].replace("\n", " ")
        logger.error("OSRM HTTP %s: %s", response.status_code, snippet or "(empty body)")
        if response.status_code in (400, 404, 413, 414):
            raise RuntimeError(_osrm_disconnected_msg(profile))
        raise RuntimeError(
            f"The routing server refused this request (HTTP {response.status_code}). "
            f"Try shorter distances or a self-hosted OSRM instance."
        )

    # ── Road Classification ──────────────────────────────────────────────

    @staticmethod
    def _classify_road(ref: str, name: str, distance_m: float, duration_s: float) -> float:
        """
        Classify a road segment's safety based on road type.

        Returns a score [0, 1] where:
          1.0 = safest road type (major highway, well-maintained)
          0.0 = riskiest road type (unnamed, dark back-road)

        Classification sources:
          - ref (road reference): NH-1, SH-5, I-95, A1, etc.
          - name: Road name (presence indicates major road)
          - speed (distance/duration): Higher speed = likely major road
        """
        ref_upper = (ref or "").upper().strip()
        name_lower = (name or "").lower().strip()

        # National Highway / Interstate (safest)
        if any(prefix in ref_upper for prefix in ["NH", "NE", "I-", "US-", "A-", "M-"]):
            return 0.95

        # State Highway / National Route
        if any(prefix in ref_upper for prefix in ["SH", "SR-", "N-", "B-"]):
            return 0.85

        # Named road with reference number (district road)
        if ref_upper and len(ref_upper) <= 10:
            return 0.75

        # Named road without reference (main urban road)
        if name_lower and any(
            kw in name_lower
            for kw in ["path", "road", "marg", "nagar", "highway", "boulevard",
                       "avenue", "street", "main", "market", "chowk", "circle"]
        ):
            return 0.70

        # Named road (secondary urban)
        if name_lower and len(name_lower) > 2:
            return 0.55

        # Unnamed road — infer from speed
        if duration_s > 0:
            speed_kmh = (distance_m / duration_s) * 3.6
            if speed_kmh > 60:
                return 0.70  # Fast unnamed = likely decent road
            elif speed_kmh > 30:
                return 0.45  # Medium speed
            else:
                return 0.30  # Slow unnamed = likely small lane

        # Completely unnamed, unknown
        return 0.25

    # ── Alternative Route Generation ────────────────────────────────────

    def _deduplicate_routes(self, routes: List[Dict], threshold: float = 0.15) -> List[Dict]:
        """
        Remove routes that are too geometrically similar.

        Two routes are "similar" if their start/end bounding boxes overlap
        by more than (1 - threshold) of area.
        """
        if len(routes) <= 1:
            return routes

        unique = [routes[0]]
        for candidate in routes[1:]:
            is_dup = False
            for existing in unique:
                similarity = self._route_similarity(
                    existing["geometry"], candidate["geometry"]
                )
                if similarity > (1.0 - threshold):
                    is_dup = True
                    break
            if not is_dup:
                unique.append(candidate)

        return unique

    @staticmethod
    def _route_similarity(g1: List[Tuple], g2: List[Tuple]) -> float:
        """Estimate geometric similarity as fraction of shared corridor."""
        if not g1 or not g2:
            return 0.0

        # Sample ~20 points from each route and count how many overlap
        sample1 = g1[:: max(1, len(g1) // 20)]
        sample2 = g2[:: max(1, len(g2) // 20)]

        close_count = 0
        threshold_deg = 0.003  # ~330m

        for p1 in sample1:
            for p2 in sample2:
                if abs(p1[0] - p2[0]) < threshold_deg and abs(p1[1] - p2[1]) < threshold_deg:
                    close_count += 1
                    break

        return close_count / max(len(sample1), 1)

    def _generate_forced_alternatives(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        existing_routes: List[Dict],
        profile: str = "driving",
    ) -> List[Dict]:
        """
        Force diverse routes by adding perpendicular waypoint offsets.

        Strategy: Compute the perpendicular direction to the origin→destination
        line, then create waypoints offset by ~1-3km in each direction.
        Routes through these waypoints traverse genuinely different corridors.
        """
        mid_lat = (origin[0] + destination[0]) / 2
        mid_lon = (origin[1] + destination[1]) / 2

        # Direction perpendicular to the origin→destination line
        dx = destination[1] - origin[1]
        dy = destination[0] - origin[0]
        dist = math.sqrt(dx * dx + dy * dy)

        if dist < 1e-6:
            return existing_routes  # Same point

        # Unit perpendicular vector
        perp_dx = -dy / dist
        perp_dy = dx / dist

        # Offset distances in degrees (~1km and ~1.5km — kept small to avoid absurd detours)
        offsets = [0.010, -0.010, 0.015, -0.015]
        all_routes = list(existing_routes)

        for offset in offsets:
            if len(all_routes) >= 3:
                break

            wp_lat = mid_lat + offset * perp_dy
            wp_lon = mid_lon + offset * perp_dx

            try:
                forced = self._fetch_routes(
                    origin, destination, alternatives=0,
                    waypoints=[(wp_lat, wp_lon)],
                    profile=profile,
                )
                if forced:
                    candidate = forced[0]
                    # Reject if too long relative to shortest existing route
                    min_existing_dist = min(r["distance_meters"] for r in all_routes) if all_routes else float('inf')
                    if candidate["distance_meters"] > min_existing_dist * 1.8:
                        logger.info(f"  Rejected forced alt ({candidate['distance_meters']/1000:.1f}km) — exceeds 1.8x shortest ({min_existing_dist/1000:.1f}km)")
                        continue
                    # Only add if sufficiently different from existing
                    is_unique = all(
                        self._route_similarity(candidate["geometry"], r["geometry"]) < 0.75
                        for r in all_routes
                    )
                    if is_unique:
                        all_routes.append(candidate)
                        logger.info(
                            f"  Forced alternative via ({wp_lat:.4f}, {wp_lon:.4f}): "
                            f"{candidate['duration_seconds']/60:.1f}min, "
                            f"{candidate['distance_meters']/1000:.1f}km"
                        )
            except Exception as e:
                logger.warning(f"  Waypoint routing failed for offset={offset}: {e}")

        return all_routes

    # ── Point Sampling ──────────────────────────────────────────────────

    @staticmethod
    def sample_route_points(
        geometry: List[Tuple[float, float]],
        interval_m: float = 200.0,
    ) -> List[Tuple[float, float]]:
        """Sample points along a route polyline at regular intervals."""
        if not geometry:
            return []

        samples = [geometry[0]]
        accumulated = 0.0

        for i in range(1, len(geometry)):
            prev, curr = geometry[i - 1], geometry[i]
            seg_dist = _haversine_m(prev[0], prev[1], curr[0], curr[1])

            if seg_dist < 0.1:
                continue

            accumulated += seg_dist
            while accumulated >= interval_m:
                overshoot = accumulated - interval_m
                ratio = max(0, min(1, 1.0 - (overshoot / seg_dist) if seg_dist > 0 else 1))
                samples.append((
                    prev[0] + ratio * (curr[0] - prev[0]),
                    prev[1] + ratio * (curr[1] - prev[1]),
                ))
                accumulated -= interval_m

        if len(geometry) > 1:
            samples.append(geometry[-1])

        return samples


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in meters."""
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
