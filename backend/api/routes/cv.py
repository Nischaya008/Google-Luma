"""
Computer Vision safety analysis endpoint.

POST /api/v1/routing/cv/analyze
  - Accepts base64-encoded JPEG frame from mobile camera
  - Returns real-time safety analysis with AI explanation

POST /api/v1/routing/cv/reset
  - Clears anomaly detection history for a fresh session

Designed for real-time use: targets <500ms response on CPU.
"""
import base64
import io
import logging
import asyncio

from PIL import Image
from fastapi import APIRouter, HTTPException

from core.config import settings
from models.schemas import CVAnalyzeRequest, CVAnalyzeResponse
from services.cv_analyzer import CVSafetyAnalyzer
from services.cv_explainer import CVExplainer

logger = logging.getLogger(__name__)

router = APIRouter()

# Frame size limit: 2MB base64 ≈ 1.5MB binary image
MAX_FRAME_BYTES = 2 * 1024 * 1024


@router.post("/cv/analyze", response_model=CVAnalyzeResponse)
async def analyze_camera_frame(request: CVAnalyzeRequest):
    """
    Analyze a single camera frame for real-time safety scoring.

    Pipeline:
      1. Decode base64 → PIL Image
      2. CV analysis (DETR object detection + brightness)
      3. Compute cv_safety_score
      4. Blend with route safety: final = 0.7*ML + 0.3*CV
      5. Generate AI explanation referencing detected elements
      6. Return structured response
    """
    frame_data = request.frame_base64
    if len(frame_data) > MAX_FRAME_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Frame too large ({len(frame_data)} bytes). "
                f"Maximum: {MAX_FRAME_BYTES} bytes."
            ),
        )

    # Step 1: Decode base64 → PIL Image
    try:
        # Handle both raw base64 and data URI format (data:image/jpeg;base64,...)
        raw = frame_data
        if "," in raw:
            raw = raw.split(",", 1)[1]

        image_bytes = base64.b64decode(raw)
        image = Image.open(io.BytesIO(image_bytes))
    except Exception as e:
        logger.warning(f"Frame decode failed: {e}")
        raise HTTPException(
            status_code=400,
            detail="Invalid image data. Expected base64-encoded JPEG/PNG.",
        )

    try:
        # Step 2-3: CV analysis (DETR + brightness) — offloaded to thread pool
        analyzer = CVSafetyAnalyzer.get_instance()
        cv_result = await asyncio.to_thread(analyzer.analyze, image)

        cv_score = cv_result["cv_safety_score"]

        # Step 4: Blend with pre-computed route safety score (if provided)
        route_score = request.route_safety_score
        if route_score is not None:
            final_score = (
                settings.ML_BLEND_WEIGHT * route_score
                + settings.CV_BLEND_WEIGHT * cv_score
            )
        else:
            # No route context — use pure CV score
            final_score = cv_score

        final_score = round(max(0.0, min(1.0, final_score)), 4)

        # Step 5: Generate explanation referencing detected elements
        explanation = CVExplainer.generate_explanation(cv_result, cv_score)

        anomaly_label = ""
        if cv_result["is_anomaly"]:
            anomaly_label = CVExplainer.generate_anomaly_label(cv_result)

        # Step 6: Return structured response
        return CVAnalyzeResponse(
            cv_safety_score=cv_score,
            final_blended_score=final_score,
            brightness=cv_result["brightness"],
            brightness_uniformity=cv_result["brightness_uniformity"],
            crowd_count=cv_result["crowd_count"],
            vehicle_count=cv_result["vehicle_count"],
            infrastructure_count=cv_result["infrastructure_count"],
            is_anomaly=cv_result["is_anomaly"],
            anomaly_label=anomaly_label,
            ai_explanation=explanation,
            features={
                "crowd_score": cv_result["crowd_score"],
                "vehicle_score": cv_result["vehicle_score"],
                "structure_score": cv_result["structure_score"],
                "anomaly_score": cv_result["anomaly_score"],
                "detection_count": len(cv_result["detections"]),
            },
        )

    except RuntimeError as e:
        logger.error(f"CV analysis failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("POST /cv/analyze failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cv/reset")
async def reset_anomaly_history():
    """
    Reset the anomaly detection history.
    Call when starting a new route/session to clear stale frame data.
    """
    try:
        analyzer = CVSafetyAnalyzer.get_instance()
        analyzer.reset_anomaly_history()
        return {"status": "ok", "message": "Anomaly history cleared"}
    except Exception as e:
        logger.exception("POST /cv/reset failed")
        raise HTTPException(status_code=500, detail=str(e))
