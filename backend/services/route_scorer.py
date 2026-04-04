"""
Route safety scorer — V3 architecture with per-segment analysis.

Instead of uniform point-sampling (which gives identical scores for similar
routes), this module scores each OSRM step (road segment) individually using:

  1. VIIRS satellite lighting — actual light intensity at segment midpoints
  2. Crime kernel density — real crime data at 40K+ incidents (India KDE)
  3. Road classification — NH/SH/primary/residential/unnamed from OSRM step data
  4. Commercial activity proxy — VIIRS brightness in surrounding area
  5. Weather + time-of-day — real-time adjustments

Safety is computed PER-STEP and LENGTH-WEIGHTED:
  route_score = Σ(step_safety × step_distance) / Σ(step_distance)

This ensures highways contribute more than short connectors, and genuinely
different corridors produce genuinely different safety scores.
"""
import logging
import math
import os
from datetime import datetime, timezone
from typing import List, Tuple, Dict, Optional
import asyncio

import numpy as np

from core.config import settings
from services.ambient_overpass import corridor_ambient_score
from services.safety_context import (
    TemporalContext,
    apply_temporal_safety_adjustment,
    compute_footfall_proxy,
    compute_temporal_context,
)

logger = logging.getLogger(__name__)


class RouteSafetyScorer:
    """
    Scores route safety via per-segment analysis.

    Singleton — lazily loads KDE and VIIRS on first use.
    """

    _instance = None

    # ── Scoring Weights ──────────────────────────────────────────────────
    # These are calibrated to reflect the problem statement priorities:
    # "lighting intensity, commercial activity, footfall density"

    # Day-time weights — ``ambient`` is real OSM POI/lamp density (Overpass).
    WEIGHTS_DAY = {
        "lighting":     0.12,
        "crime":        0.22,
        "road_class":   0.13,
        "commercial":   0.09,
        "footfall":     0.14,
        "weather":      0.08,
        "ambient":      0.22,
    }

    # Night-time weights (lighting still leads; ambient captures lit retail corridors)
    WEIGHTS_NIGHT = {
        "lighting":     0.26,
        "crime":        0.19,
        "road_class":   0.10,
        "commercial":   0.06,
        "footfall":     0.17,
        "weather":      0.07,
        "ambient":      0.15,
    }

    # VIIRS normalization: 80th percentile cap (nW/cm²/sr)
    # Values > 80 are extreme outliers (stadiums, industrial zones)
    VIIRS_CAP = 80.0

    # Crime KDE normalization bounds (log-density)
    # The KDE is built from ~40K incidents across ~29 Indian cities.
    # Log-density values:
    #   - Rural areas (no crime data nearby):  < -20 → normalizes to 0.0
    #   - City outskirts:                      ~-12 → normalizes to ~0.4
    #   - Dense urban core:                    ~-3  → normalizes to ~0.85
    #   - Crime hotspot centroid:              ~0   → normalizes to 1.0
    # Previous CRIME_LOG_HIGH=-5 caused ALL city points to saturate to 1.0.
    CRIME_LOG_LOW = -20.0
    CRIME_LOG_HIGH = 0.0

    def __init__(self):
        self.kde_model = None
        self.viirs_dataset = None
        self._kde_loaded = False
        self._viirs_loaded = False
        self.earth_engine = None
        self._gee_loaded = False

    @classmethod
    def get_instance(cls) -> "RouteSafetyScorer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Lazy Loading ─────────────────────────────────────────────────────

    def ensure_initialized(self):
        """Pre-load data sources. Called by /init and startup."""
        self._ensure_kde()
        self._ensure_viirs()
        self._ensure_gee()

    def _ensure_gee(self):
        if self._gee_loaded:
            return
            
        # Ensure LLM is fully Instantiated for Real-Time Metrics
        if not getattr(self, 'llm_evaluator', None):
            try:
                from services.llm_safety_evaluator import LLMSafetyEvaluator
                self.llm_evaluator = LLMSafetyEvaluator()
            except Exception as e:
                logger.error(f"Failed to instantiate LLMSafetyEvaluator: {e}", exc_info=True)
        
        try:
            from services.earth_engine_service import EarthEngineService
            self.earth_engine = EarthEngineService()
            logger.info("Earth Engine Service loaded for vegetation isolation ✓")
        except Exception as e:
            logger.warning(f"Failed to load Earth Engine Service: {e}")

        self._gee_loaded = True


    def _ensure_kde(self):
        if self._kde_loaded:
            return
        try:
            from services.data_loaders import CrimeDataLoader
            loader = CrimeDataLoader()
            self.kde_model = loader.get_kde_model()
            if self.kde_model:
                logger.info("Crime KDE model loaded for route scoring ✓")
        except Exception as e:
            logger.warning(f"Failed to load crime KDE: {e}")
        self._kde_loaded = True

    def _ensure_viirs(self):
        if self._viirs_loaded:
            return
        try:
            viirs_path = settings.VIIRS_DATA_PATH
            if os.path.exists(viirs_path):
                import rasterio
                self.viirs_dataset = rasterio.open(viirs_path)
                logger.info(f"VIIRS raster loaded: {self.viirs_dataset.shape} ✓")
            else:
                logger.warning(f"VIIRS not found at {viirs_path}")
        except Exception as e:
            logger.warning(f"VIIRS load failed: {e}")
        self._viirs_loaded = True

    # ── Point-Level Features ─────────────────────────────────────────────

    def sample_lighting(self, lat: float, lon: float) -> float:
        """
        VIIRS satellite radiance at a point. Returns [0, 1].
        Higher = brighter = safer.
        """
        self._ensure_viirs()
        if self.viirs_dataset is None:
            return 0.4  # Fallback: moderate

        try:
            row, col = self.viirs_dataset.index(lon, lat)
            if 0 <= row < self.viirs_dataset.height and 0 <= col < self.viirs_dataset.width:
                val = float(
                    self.viirs_dataset.read(1, window=((row, row + 1), (col, col + 1)))[0, 0]
                )
                return min(1.0, max(0.0, val) / self.VIIRS_CAP)
        except Exception:
            pass
        return 0.3

    def sample_lighting_context(self, lat: float, lon: float) -> Tuple[float, float]:
        """
        Sample VIIRS brightness at a point AND its surrounding area.

        Returns:
            (point_brightness, area_brightness)

        area_brightness is the average of 8 surrounding points at ~500m offset.
        This gives us a "commercial activity / populated area" proxy:
        - High area brightness = busy, populated zone
        - Low area brightness = isolated, dark area
        """
        center_val = self.sample_lighting(lat, lon)

        # Sample 8 surrounding points (~500m offset = ~0.0045 degrees)
        offset = 0.0045
        surrounding = []
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dy == 0 and dx == 0:
                    continue
                surrounding.append(
                    self.sample_lighting(lat + dy * offset, lon + dx * offset)
                )

        area_val = sum(surrounding) / len(surrounding) if surrounding else center_val
        return center_val, area_val

    def sample_crime(self, lat: float, lon: float) -> float:
        """
        Crime density at a point from KDE. Returns [0, 1].
        Higher = more crime = MORE DANGEROUS.
        """
        self._ensure_kde()
        if self.kde_model is None:
            return 0.3  # Fallback: low-moderate

        try:
            point = np.array([[lat, lon]])
            log_density = self.kde_model.score_samples(point)[0]
            norm = (log_density - self.CRIME_LOG_LOW) / (
                self.CRIME_LOG_HIGH - self.CRIME_LOG_LOW
            )
            return max(0.0, min(1.0, norm))
        except Exception:
            return 0.3

    @staticmethod
    def compute_is_night(lat: float, lon: float) -> bool:
        """Check nighttime using Astral sun position."""
        try:
            from astral import LocationInfo
            from astral.sun import sun
            loc = LocationInfo(latitude=lat, longitude=lon)
            s = sun(loc.observer, date=datetime.now(timezone.utc).date())
            now = datetime.now(timezone.utc)
            return now < s["sunrise"] or now > s["sunset"]
        except Exception:
            hour = datetime.now(timezone.utc).hour
            return hour < 1 or hour > 13

    # ── Per-Step Scoring ─────────────────────────────────────────────────

    @staticmethod
    def _pedestrian_exposure_penalty(step: Dict, travel_profile: str) -> float:
        """
        Extra risk for people on foot near high-speed or major highway-class roads.

        Driving and walking share the same OSRM step names sometimes; refs that look
        like national highways are penalized for *pedestrians* because conflict with
        fast traffic dominates perceived safety.
        """
        if travel_profile != "foot":
            return 0.0
        ref_upper = (step.get("ref") or "").upper()
        name_lower = (step.get("name") or "").lower()
        penalty = 0.0
        if any(p in ref_upper for p in ("NH", "NE-", "I-", "US-", "E-")):
            penalty += 0.14
        if any(p in ref_upper for p in ("SH", "SR-", "M-", "STATE")):
            penalty += 0.08
        if "expressway" in name_lower or "motorway" in name_lower:
            penalty += 0.12
        return min(0.35, penalty)

    def score_step(
        self,
        step: Dict,
        weather_penalty: float,
        is_night: bool,
        route_temporal: Optional[TemporalContext] = None,
        travel_profile: str = "driving",
        corridor_ambient: float = 0.45,
    ) -> Tuple[float, Dict]:
        """
        Score a single road segment's safety.

        Uses the step's midpoint for geospatial features (VIIRS, crime)
        and the step's metadata for road classification.

        Returns:
            (safety_score, features_dict)
        where safety_score is [0, 1] and features_dict contains the raw metrics.
        """
        # Get midpoint of this step's geometry
        geom = step.get("geometry", [])
        if not geom:
            return 0.5, {}  # No geometry = neutral

        mid_idx = len(geom) // 2
        mid_lat, mid_lon = geom[mid_idx]

        # Feature 1: Lighting (VIIRS satellite)
        point_light, area_light = self.sample_lighting_context(mid_lat, mid_lon)

        # Feature 2: Crime density (KDE)
        crime = self.sample_crime(mid_lat, mid_lon)

        # Feature 3: Road classification (from OSRM step metadata)
        road_class = step.get("road_class", 0.5)

        # Feature 4: Commercial activity proxy (area brightness)
        commercial = area_light

        # Feature 5: Footfall proxy — deterministic blend (not raw pedestrian counts)
        footfall = compute_footfall_proxy(point_light, area_light, road_class)

        # Feature 6: Weather (live OWM when configured)
        weather_factor = 1.0 - weather_penalty

        # Feature 7: Temporal context at segment (route-level center by default)
        tc = route_temporal or compute_temporal_context(mid_lat, mid_lon)

        # Select weights based on day/night
        w = self.WEIGHTS_NIGHT if is_night else self.WEIGHTS_DAY

        # Crime inversion: allow the full dynamic range (previous 0.4 floor crushed variance).
        crime_factor = max(0.05, min(1.0, 1.0 - crime * 0.95))

        linear_safety = (
            w["lighting"] * point_light
            + w["crime"] * crime_factor
            + w["road_class"] * road_class
            + w["commercial"] * commercial
            + w["footfall"] * footfall
            + w["weather"] * weather_factor
            + w["ambient"] * max(0.0, min(1.0, corridor_ambient))
        )

        safety = apply_temporal_safety_adjustment(
            linear_safety,
            tc.temporal_risk,
            is_night,
            max_drag=settings.SAFETY_TEMPORAL_MAX_DRAG,
        )

        ped_pen = self._pedestrian_exposure_penalty(step, travel_profile)
        if ped_pen > 0:
            safety = safety * (1.0 - ped_pen)

        features = {
            "point_light": point_light,
            "crime": crime,
            "crime_factor": crime_factor,
            "road_class": road_class,
            "commercial": commercial,
            "footfall_proxy": footfall,
            "weather_factor": weather_factor,
            "local_hour_approx": tc.local_hour,
            "temporal_risk": tc.temporal_risk,
            "weights": w,
            "raw_safety": linear_safety,
            "after_temporal_safety": safety,
            "corridor_ambient": corridor_ambient,
            "pedestrian_exposure_penalty": ped_pen,
            "travel_profile": travel_profile,
        }

        return max(0.0, min(1.0, safety)), features

    # ── Route-Level Scoring ──────────────────────────────────────────────

    def score_route(
        self,
        route: Dict,
        weather_penalty: float = 0.0,
        is_night: bool = False,
        travel_profile: str = "driving",
        corridor_ambient: float = 0.45,
    ) -> Tuple[float, List[Dict]]:
        """
        Score a route's safety using LENGTH-WEIGHTED per-step scoring.

        Returns:
            (avg_safety_score, per_step_details)

        Length-weighting ensures a 5km highway segment contributes more
        to the overall score than a 200m connector.
        """
        steps = route.get("steps", [])
        if not steps:
            return 0.5, []

        self._ensure_gee()
            
        # Pre-pass: Gather midpoints and commercial proxy for bulk GEE vegetative isolation query
        midpoints = []
        poi_densities = []
        
        for step in steps:
            geom = step.get("geometry", [])
            distance = step.get("distance_m", 0)
            if geom and distance >= 1:
                mid_idx = len(geom) // 2
                mid_lat, mid_lon = geom[mid_idx]
                _, area_light = self.sample_lighting_context(mid_lat, mid_lon)
                midpoints.append([mid_lat, mid_lon])
                poi_densities.append(area_light)
                
        # Bulk GEE Inference (Single network call per route)
        isolation_scores = np.zeros(len(steps))
        if midpoints and getattr(self, "earth_engine", None) and self.earth_engine.enabled:
            iso_array = self.earth_engine.compute_vegetation_isolation(np.array(midpoints), np.array(poi_densities))
            # Map back to steps (handling skipped steps)
            iso_idx = 0
            for i, step in enumerate(steps):
                if step.get("geometry", []) and step.get("distance_m", 0) >= 1:
                    isolation_scores[i] = iso_array[iso_idx]
                    iso_idx += 1

        # Single temporal envelope for the corridor (fast; avoids per-step astral calls)
        route_temporal: Optional[TemporalContext] = None
        if midpoints:
            arr = np.asarray(midpoints, dtype=float)
            route_temporal = compute_temporal_context(
                float(np.mean(arr[:, 0])),
                float(np.mean(arr[:, 1])),
            )

        total_weighted_safety = 0.0
        total_distance = 0.0
        step_details = []
        
        logger.info(f"--- Scoring Route (Distance: {route.get('distance_meters', 0)/1000:.1f}km) ---")

        for i, step in enumerate(steps):
            distance = step.get("distance_m", 0)
            if distance < 1:
                continue

            safety, features = self.score_step(
                step,
                weather_penalty,
                is_night,
                route_temporal=route_temporal,
                travel_profile=travel_profile,
                corridor_ambient=corridor_ambient,
            )

            # Apply GEE Vegetative Isolation penalty strictly at night
            isolation_penalty = isolation_scores[i]
            if is_night and isolation_penalty > 0:
                safety = safety * (1.0 - (0.3 * isolation_penalty))
                safety = max(0.0, min(1.0, safety))

            total_weighted_safety += safety * distance
            total_distance += distance
            
            name = step.get("name", "")
            ref = step.get("ref", "")
            r_class = step.get("road_class", 0.5)
            
            # VERBOSE MATHEMATICAL LOGGING FOR TRACEABILITY
            if features:
                w = features["weights"]
                logger.info(
                    f"[Step Calculation] {name} {ref} (Dist: {distance:.1f}m): "
                    f"Light({features['point_light']:.3f}*{w['lighting']}) + "
                    f"Crime({features['crime_factor']:.3f}*{w['crime']}) + "
                    f"RoadClass({features['road_class']:.3f}*{w['road_class']}) + "
                    f"Comm({features['commercial']:.3f}*{w['commercial']}) + "
                    f"Footfall({features['footfall_proxy']:.3f}*{w['footfall']}) + "
                    f"Weather({features['weather_factor']:.3f}*{w['weather']}) = "
                    f"Lin({features['raw_safety']:.3f}) | "
                    f"TempR={features.get('temporal_risk', 0):.2f} | "
                    f"Night={is_night} IsoPen={isolation_penalty:.3f} => {safety:.3f}"
                )
            else:
                logger.info(
                    f"[Step Calculation] {name} {ref} (Dist: {distance:.1f}m): "
                    f"No geometry, neutral score => FINAL SCORE: {safety:.3f}"
                )

            step_details.append({
                "name": name,
                "ref": ref,
                "distance_m": distance,
                "safety_score": round(safety, 4),
                "road_class": r_class,
            })

        avg_safety = total_weighted_safety / total_distance if total_distance > 0 else 0.5
        
        # Risk-averse aggregation strategy
        sorted_steps = sorted(step_details, key=lambda s: s["safety_score"])
        bottom_20_dist = total_distance * 0.20
        bottom_20_sum = 0.0
        curr_dist = 0.0
        
        for step in sorted_steps:
            dist = step["distance_m"]
            if curr_dist + dist <= bottom_20_dist:
                bottom_20_sum += step["safety_score"] * dist
                curr_dist += dist
            else:
                rem = bottom_20_dist - curr_dist
                if rem > 0:
                    bottom_20_sum += step["safety_score"] * rem
                    curr_dist += rem
                break
                
        bottom_20_avg = bottom_20_sum / max(1.0, bottom_20_dist)

        # Softened risk-averse aggregation: 75% mean + 25% bottom-20%
        # Previous 60/40 was too aggressive — the bottom-20% worst segments
        # were dragging the entire route score down by 5-10% unnecessarily.
        risk_averse_safety = (0.75 * avg_safety) + (0.25 * bottom_20_avg)

        logger.info(
            f"--- Route Score Aggregated --- | Mean: {avg_safety:.3f} | "
            f"Bottom-20% Mean: {bottom_20_avg:.3f} | "
            f"Risk-Averse (75/25): {risk_averse_safety:.3f}"
        )
        
        return round(risk_averse_safety, 4), step_details

    # ── Multi-Route Ranking ──────────────────────────────────────────────

    async def score_and_rank_routes_async(
        self,
        routes: List[Dict],
        weather_penalty: float = 0.0,
        is_night: bool = False,
        travel_profile: str = "driving",
        corridor_center: Tuple[float, float] | None = None,
    ) -> List[Dict]:
        """
        Score all routes, label as fastest / balanced / safest,
        and run LLM evaluation concurrently providing comparative insight.
        
        Handles 1-3 routes gracefully. If only 1 route exists, all three
        modes point to the same physical path (frontend merges tabs).
        """
        if not routes:
            return []

        amb_lat = corridor_center[0] if corridor_center else 0.0
        amb_lon = corridor_center[1] if corridor_center else 0.0
        corridor_ambient = 0.45
        if corridor_center is not None:
            corridor_ambient = await asyncio.to_thread(
                corridor_ambient_score, amb_lat, amb_lon
            )

        # Score each route
        scored = []
        for i, route in enumerate(routes):
            avg_safety, step_details = self.score_route(
                route,
                weather_penalty,
                is_night,
                travel_profile=travel_profile,
                corridor_ambient=corridor_ambient,
            )
            scored.append({
                **route,
                "safety_score": avg_safety,
                "raw_safety_score": avg_safety,
                "step_details": step_details,
                "original_index": i,
                "ai_insight": "",
                "travel_profile": travel_profile,
            })

        logger.info(
            "Route safety scores: "
            + " | ".join(
                f"R{s['original_index']+1}: "
                f"safety={s['raw_safety_score']:.3f}, "
                f"time={s['duration_seconds']/60:.1f}min, "
                f"dist={s['distance_meters']/1000:.1f}km"
                for s in scored
            )
        )

        # Pareto-optimal route mapping
        import copy
        labeled = []

        # Identify best candidates
        fastest_idx = min(range(len(scored)), key=lambda i: scored[i]["duration_seconds"])
        safest_idx = max(range(len(scored)), key=lambda i: scored[i]["raw_safety_score"])
        
        # Balance metric: normalize both dimensions and sum
        min_time = min(r["duration_seconds"] for r in scored)
        max_time = max(r["duration_seconds"] for r in scored)
        time_range = max_time - min_time if max_time > min_time else 1.0

        min_safety = min(r["raw_safety_score"] for r in scored)
        max_safety = max(r["raw_safety_score"] for r in scored)
        safety_range = max_safety - min_safety if max_safety > min_safety else 1.0

        for r in scored:
            norm_time = 1.0 - ((r["duration_seconds"] - min_time) / time_range)
            norm_safety = (r["raw_safety_score"] - min_safety) / safety_range
            r["balance_metric"] = norm_safety + norm_time

        balanced_idx = max(range(len(scored)), key=lambda i: scored[i]["balance_metric"])

        # Build labeled list
        fastest = copy.deepcopy(scored[fastest_idx])
        fastest["mode"] = "fastest"
        labeled.append(fastest)

        balanced = copy.deepcopy(scored[balanced_idx])
        balanced["mode"] = "balanced"
        labeled.append(balanced)

        safest = copy.deepcopy(scored[safest_idx])
        safest["mode"] = "safest"
        labeled.append(safest)

        # Run Comparative LLM Evaluation on physically distinct routes only
        unique_labeled = []
        seen_indices = set()
        for r in labeled:
            if r["original_index"] not in seen_indices:
                unique_labeled.append(r)
                seen_indices.add(r["original_index"])

        if getattr(self, 'llm_evaluator', None) and unique_labeled:
            await self.llm_evaluator.evaluate_all_routes(unique_labeled)

        # Map evaluations back to duplicate modes
        for r in labeled:
            ref = next((u for u in unique_labeled if u["original_index"] == r["original_index"]), None)
            if ref:
                r["ai_insight"] = ref["ai_insight"]
                r["safety_score"] = ref["safety_score"]

        # Log final assignment
        for r in labeled:
            logger.info(
                f"  {r['mode']:>10}: safety={r['safety_score']:.3f}, "
                f"time={r['duration_seconds']/60:.1f}min, "
                f"dist={r['distance_meters']/1000:.1f}km"
            )

        return labeled
