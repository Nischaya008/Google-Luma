"""
LLM Safety Evaluator — Groq/Llama integration for real-time contextual safety evaluations.

Feeds the LLM actual per-step safety data, road names, coordinates, and regional
context so it can produce specific, evidence-based comparative analysis rather
than generic filler.
"""
import logging
import json
from typing import Dict, List
from groq import AsyncGroq

from core.config import settings

logger = logging.getLogger(__name__)


class LLMSafetyEvaluator:
    """
    Evaluates routes using Groq (Llama 3.1) to provide qualitative
    contextual reasoning with real data backing.
    """

    def __init__(self):
        self.api_key = settings.GROQ_API_KEY
        self.enabled = bool(self.api_key)

        if self.enabled:
            self.client = AsyncGroq(api_key=self.api_key)
            self.model_name = "llama-3.1-8b-instant"
            logger.info(f"LLMSafetyEvaluator initialized with Groq model {self.model_name}.")
        else:
            logger.warning("GROQ_API_KEY not found. LLM Safety Evaluator is disabled.")

    def _build_route_summary(self, route: Dict) -> str:
        """Build a data-rich summary string for a single route."""
        mode = route.get("mode", "route")
        total_dist = route.get("distance_meters", 0) / 1000.0
        duration_mins = route.get("duration_seconds", 0) / 60.0
        raw_safety = route.get("raw_safety_score", 0.5)

        steps = route.get("steps", [])
        step_details = route.get("step_details", [])

        # Build segment table with actual safety data
        segment_lines = []
        for i, step in enumerate(steps):
            name = step.get("name", "").strip()
            ref = step.get("ref", "").strip()
            dist_m = step.get("distance_m", 0)
            road_label = name or ref or "unnamed road"

            # Get safety score for this step from step_details
            step_safety = None
            if i < len(step_details):
                step_safety = step_details[i].get("safety_score")

            # Only include segments > 200m for readability
            if dist_m >= 200:
                safety_str = f", safety={step_safety:.2f}" if step_safety is not None else ""
                segment_lines.append(f"  - {road_label} ({dist_m/1000:.1f}km{safety_str})")

        # Get start/end coordinates for region context
        geom = route.get("geometry", [])
        start_coord = f"({geom[0][0]:.4f}, {geom[0][1]:.4f})" if geom else "unknown"
        end_coord = f"({geom[-1][0]:.4f}, {geom[-1][1]:.4f})" if geom else "unknown"

        segments_text = "\n".join(segment_lines[:15]) if segment_lines else "  - All unnamed local roads"

        travel = route.get("travel_profile", "driving")
        travel_label = "walking" if travel == "foot" else "driving"
        return (
            f"Route ({mode.upper()}, {travel_label}):\n"
            f"- From: {start_coord} → To: {end_coord}\n"
            f"- Distance: {total_dist:.1f} km | Time: {duration_mins:.1f} min\n"
            f"- Overall Safety Score: {raw_safety:.2f}/1.00\n"
            f"- Road segments:\n{segments_text}\n"
        )

    async def evaluate_all_routes(self, routes: List[Dict]) -> None:
        """
        Evaluate all labeled routes together with real data context.
        Modifies routes in-place with ai_insight and adjusted safety_score.
        """
        if not self.enabled or not routes:
            for r in routes:
                r["ai_insight"] = ""
                r["safety_score"] = r.get("raw_safety_score", 0.5)
            return

        num_routes = len(routes)

        # Build data-rich prompt
        route_summaries = "\n".join(
            self._build_route_summary(r) for r in routes
        )

        prompt = f"""You are an expert navigation safety analyst. Analyze these {num_routes} route option(s) using the ACTUAL safety data provided.

{route_summaries}

IMPORTANT RULES:
- Reference the ACTUAL road names and safety scores shown above.
- If roads are unnamed, say "unnamed local roads" and reference the safety score.
- Explain WHY this route scores the way it does (e.g., "NH61 scores 0.60 due to national highway classification" or "the unnamed 8.5km stretch drags safety down to 0.49").
- If comparing multiple routes, explain the specific tradeoff (e.g., "saves 3 minutes but passes through a 0.46-scoring unnamed stretch").
- Do NOT fabricate road names that aren't in the data above.

Respond in valid JSON with key "evaluations" — a list of exactly {num_routes} objects, each with:
1. "ai_insight": 1-2 specific sentences using the real data above. Cite actual road names and scores.
2. "contextual_modifier": float between -0.10 and +0.10 (fine-tune the safety score based on your geographic knowledge)."""

        try:
            logger.info("Requesting Groq comparative evaluation...")
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.15,
                response_format={"type": "json_object"},
            )

            text = response.choices[0].message.content.strip()
            data = json.loads(text)
            evals = data.get("evaluations", [])

            for idx, r in enumerate(routes):
                if idx < len(evals):
                    insight = evals[idx].get("ai_insight", "")
                    mod = float(evals[idx].get("contextual_modifier", 0.0))
                    mod = max(-0.10, min(0.10, mod))  # Bound tightly

                    r["ai_insight"] = insight
                    r["safety_score"] = max(0.0, min(1.0, r.get("raw_safety_score", 0.5) + mod))
                    logger.info(f"LLM [{r.get('mode', '?')}]: \"{insight}\" (mod: {mod:+.2f})")
                else:
                    r["ai_insight"] = ""
                    r["safety_score"] = r.get("raw_safety_score", 0.5)
        except Exception as e:
            logger.warning(f"LLM Comparative Evaluation failed: {e}")
            for r in routes:
                r["ai_insight"] = ""
                r["safety_score"] = r.get("raw_safety_score", 0.5)
