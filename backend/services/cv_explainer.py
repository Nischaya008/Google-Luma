"""
CV Safety Explainer — Generates human-readable safety explanations from CV features.

Uses rule-based contextual templates to produce real-time explanations that
specifically reference elements detected in the camera feed.

WHY rule-based instead of LLM:
  1. Deterministic output — no hallucination risk for safety-critical info
  2. Sub-millisecond latency — critical for 2-second frame cycle budget
  3. No external API dependency — works offline / no rate limits
  4. Consistent quality regardless of server load
  5. References actual detected objects (people, vehicles, infrastructure)
"""
import logging
from typing import Dict

logger = logging.getLogger(__name__)


class CVExplainer:
    """
    Generates contextual safety explanations from CV analysis features.

    References specific detected elements (e.g., "3 pedestrians", "2 cars")
    to help users correlate the explanation with what they see in the camera.
    """

    @staticmethod
    def generate_explanation(features: Dict, cv_score: float) -> str:
        """
        Generate a natural-language safety explanation from CV features.

        Pattern: [Assessment] — [positive factors]. [concerns].
        Always references specific detected elements visible in the feed.
        """
        brightness = features.get("brightness", 0.5)
        uniformity = features.get("brightness_uniformity", 0.5)
        people = features.get("crowd_count", 0)
        vehicles = features.get("vehicle_count", 0)
        infra = features.get("infrastructure_count", 0)
        is_anomaly = features.get("is_anomaly", False)
        detections = features.get("detections", [])

        positive = []
        concerns = []

        # ── Brightness Assessment ─────────────────────────────────────
        if brightness >= 0.7:
            positive.append("well-lit environment")
        elif brightness >= 0.45:
            positive.append("adequate ambient lighting")
        elif brightness >= 0.25:
            concerns.append("dim lighting — reduced visibility")
        else:
            concerns.append("very dark area — poor visibility")

        if uniformity < 0.3 and brightness < 0.5:
            concerns.append("uneven lighting with dark patches")

        # ── Crowd Presence ────────────────────────────────────────────
        if people >= 6:
            positive.append(f"busy sidewalk with {people} people visible")
        elif people >= 3:
            positive.append(f"moderate foot traffic ({people} pedestrians)")
        elif people >= 1:
            positive.append(
                f"{people} pedestrian{'s' if people > 1 else ''} nearby"
            )
        else:
            if brightness < 0.4:
                concerns.append("no pedestrians in a dark area — isolated")
            else:
                concerns.append("no pedestrians detected")

        # ── Vehicle Density ───────────────────────────────────────────
        # Build specific description from actual detections
        vehicle_types: Dict[str, int] = {}
        for d in detections:
            if d["label"] in {"car", "bus", "truck", "motorcycle", "bicycle"}:
                vehicle_types[d["label"]] = vehicle_types.get(d["label"], 0) + 1

        if vehicles >= 4:
            desc = ", ".join(
                f"{cnt} {vt}{'s' if cnt > 1 else ''}"
                for vt, cnt in vehicle_types.items()
            )
            positive.append(f"active traffic ({desc})")
        elif vehicles >= 1:
            desc = ", ".join(
                f"{cnt} {vt}{'s' if cnt > 1 else ''}"
                for vt, cnt in vehicle_types.items()
            )
            positive.append(f"some traffic ({desc})")
        else:
            if brightness < 0.4 and people == 0:
                concerns.append("no traffic on a deserted stretch")
            else:
                concerns.append("no vehicles detected nearby")

        # ── Infrastructure ────────────────────────────────────────────
        if infra >= 2:
            infra_types = list(set(
                d["label"] for d in detections
                if d["label"] in {
                    "traffic light", "fire hydrant", "stop sign",
                    "parking meter", "bench",
                }
            ))
            positive.append(
                f"infrastructure present ({', '.join(infra_types[:3])})"
            )
        elif infra == 1:
            infra_type = next(
                (d["label"] for d in detections
                 if d["label"] in {
                     "traffic light", "fire hydrant", "stop sign",
                     "parking meter", "bench",
                 }),
                "safety marker",
            )
            positive.append(f"{infra_type} detected nearby")

        # ── Build Final Explanation ───────────────────────────────────
        if cv_score >= 0.7:
            prefix = "Safe corridor"
        elif cv_score >= 0.5:
            prefix = "Moderate safety"
        elif cv_score >= 0.3:
            prefix = "Below-average safety"
        else:
            prefix = "Elevated risk area"

        parts = []
        if positive:
            parts.append(", ".join(positive))
        if concerns:
            parts.append("Concern: " + ", ".join(concerns))

        explanation = (
            f"{prefix} — {'. '.join(parts)}."
            if parts else f"{prefix} — analyzing environment."
        )

        if is_anomaly:
            explanation = f"⚠ POTENTIAL RISK ZONE — {explanation}"

        return explanation

    @staticmethod
    def generate_anomaly_label(features: Dict) -> str:
        """Generate a specific label explaining why this frame is anomalous."""
        brightness = features.get("brightness", 0.5)
        people = features.get("crowd_count", 0)
        vehicles = features.get("vehicle_count", 0)

        reasons = []
        if brightness < 0.25:
            reasons.append("extremely dark")
        if people == 0 and vehicles == 0:
            reasons.append("no human or vehicle activity")
        if brightness < 0.3 and people == 0:
            reasons.append("isolated dark stretch")

        if reasons:
            return f"Potential Risk Zone: {', '.join(reasons)}"
        return "Potential Risk Zone: unusual environmental pattern detected"
