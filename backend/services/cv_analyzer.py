"""
Computer Vision Safety Analyzer — Real-time frame analysis using ONNX Runtime.

Architecture:
  - Object Detection: YOLOS-Tiny ONNX model (COCO-80 class detection)
  - Brightness: HSV color space analysis via Pillow + NumPy
  - Anomaly Detection: scikit-learn IsolationForest on rolling feature window

WHY ONNX Runtime instead of PyTorch + DETR:
  1. No DLL conflicts on Windows (eliminates WinError 1114)
  2. ~7MB quantized model vs ~800MB torch+DETR in memory
  3. Fits within Render free tier (512MB RAM) constraints
  4. Faster inference on CPU — no torch overhead
  5. Same detection quality (YOLOS = DETR-style, COCO-80)

GRACEFUL DEGRADATION:
  If the ONNX model cannot load (network issue, disk space, etc.),
  the analyzer falls back to brightness-only mode. Object counts
  default to zero, but brightness analysis still provides useful
  safety signal (dark areas = lower safety score).
"""
import logging
import numpy as np
from typing import Dict, List, Tuple, Optional
from PIL import Image
from sklearn.ensemble import IsolationForest

from core.config import settings
from services.onnx_detector import ONNXDetector

logger = logging.getLogger(__name__)


class CVSafetyAnalyzer:
    """
    Singleton computer vision analyzer for real-time street safety estimation.

    Uses YOLOS-Tiny ONNX model for object detection and
    HSV brightness analysis for lighting estimation.

    Safety Score Components (configurable weights in config.py):
      - Brightness (35%): HSV V-channel mean normalized to [0, 1]
      - Crowd Presence (30%): Person count normalized [0, 1]
      - Vehicle Density (20%): Vehicle count normalized [0, 1]
      - Infrastructure (15%): Traffic lights, signs normalized [0, 1]
    """

    _instance = None

    # COCO label categories relevant to street safety assessment
    PEOPLE_LABELS = frozenset({"person"})
    VEHICLE_LABELS = frozenset({"car", "bus", "truck", "motorcycle", "bicycle"})
    INFRASTRUCTURE_LABELS = frozenset({
        "traffic light", "fire hydrant", "stop sign",
        "parking meter", "bench",
    })
    # Union of all monitored labels for filtering
    ALL_SAFETY_LABELS = PEOPLE_LABELS | VEHICLE_LABELS | INFRASTRUCTURE_LABELS

    def __init__(self):
        self._detector = ONNXDetector()
        self._loaded = False
        # Anomaly detection state — per-session rolling window
        self._anomaly_detector: Optional[IsolationForest] = None
        self._feature_history: List[List[float]] = []

    @classmethod
    def get_instance(cls) -> "CVSafetyAnalyzer":
        """Thread-safe singleton accessor matching existing service pattern."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Model Loading ────────────────────────────────────────────────────

    def ensure_loaded(self) -> None:
        """
        Load the ONNX object detection model.

        Downloads YOLOS-Tiny from HuggingFace Hub on first call.
        If download/loading fails, the system degrades to brightness-only mode
        (object counts will be zero, but brightness analysis still works).
        """
        if self._loaded:
            return
        try:
            self._detector.load(prefer_quantized=True)
            self._loaded = True
            logger.info("CV Safety Analyzer ready (ONNX YOLOS-Tiny) ✓")
        except Exception as e:
            # Graceful degradation: brightness-only mode
            logger.warning(
                f"Object detection model unavailable: {e} — "
                "CV analyzer will use brightness-only mode."
            )
            # Mark as loaded to avoid repeated download attempts
            self._loaded = True

    # ── Image Processing ─────────────────────────────────────────────────

    def _preprocess_image(self, image: Image.Image) -> Image.Image:
        """Resize image to bounded dimensions for faster inference."""
        max_dim = settings.CV_FRAME_MAX_SIZE
        w, h = image.size
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            image = image.resize(
                (int(w * scale), int(h * scale)),
                Image.Resampling.LANCZOS,
            )
        return image.convert("RGB")

    def _analyze_brightness(self, image: Image.Image) -> Tuple[float, float]:
        """
        Extract brightness metrics from HSV color space.

        Returns:
            (brightness_mean, brightness_uniformity)
            Both normalized to [0, 1]. Higher = brighter / more uniform.
        """
        hsv = np.array(image.convert("HSV"), dtype=np.float32)
        v_channel = hsv[:, :, 2]  # V = brightness/value in HSV

        mean_brightness = float(v_channel.mean() / 255.0)
        # Uniformity: low std = evenly lit (good), high std = patchy (bad)
        std_brightness = float(v_channel.std() / 255.0)
        uniformity = max(0.0, 1.0 - std_brightness * 2.0)

        return mean_brightness, uniformity

    # ── Object Detection ─────────────────────────────────────────────────

    def _detect_objects(self, image: Image.Image) -> List[Dict]:
        """
        Run object detection on the image using the ONNX model.

        Returns list of safety-relevant detections with labels,
        confidence scores, and bounding boxes.

        Falls back to empty list if the detector is not loaded.
        """
        if not self._detector.is_loaded:
            return []

        all_detections = self._detector.detect(
            image,
            threshold=settings.CV_DETECTION_CONFIDENCE,
            target_size=settings.CV_FRAME_MAX_SIZE,
        )

        # Filter to safety-relevant detections only
        return [
            d for d in all_detections
            if d["label"] in self.ALL_SAFETY_LABELS
        ]

    # ── Anomaly Detection ────────────────────────────────────────────────

    def _check_anomaly(self, features: List[float]) -> Tuple[bool, float]:
        """
        Check if current frame features are anomalous using Isolation Forest.

        Requires >= CV_ANOMALY_MIN_FRAMES frames in history before activation.
        Uses a rolling window of the last CV_ANOMALY_WINDOW_SIZE frames.

        Returns:
            (is_anomaly, anomaly_score) where score < 0 indicates anomaly
        """
        self._feature_history.append(features)

        # Bound the rolling window
        max_history = settings.CV_ANOMALY_WINDOW_SIZE
        if len(self._feature_history) > max_history:
            self._feature_history = self._feature_history[-max_history:]

        # Cold start guard — need minimum data before detection is meaningful
        if len(self._feature_history) < settings.CV_ANOMALY_MIN_FRAMES:
            return False, 0.0

        # Fit Isolation Forest on the accumulated window
        X = np.array(self._feature_history)
        self._anomaly_detector = IsolationForest(
            contamination=settings.CV_ANOMALY_CONTAMINATION,
            random_state=42,
            n_estimators=50,  # Fewer trees for speed — real-time constraint
        )
        self._anomaly_detector.fit(X)

        # Score the current (latest) frame
        current = np.array([features])
        prediction = self._anomaly_detector.predict(current)[0]
        score = self._anomaly_detector.score_samples(current)[0]

        is_anomaly = prediction == -1
        return is_anomaly, round(float(score), 4)

    # ── Main Analysis Pipeline ───────────────────────────────────────────

    def analyze(self, image: Image.Image) -> Dict:
        """
        Full safety analysis of a single camera frame.

        Pipeline:
          1. Preprocess (resize to max dim)
          2. Brightness extraction (HSV V-channel)
          3. Object detection (YOLOS ONNX — people, vehicles, infrastructure)
          4. Feature normalization to [0,1]
          5. CV safety score computation (weighted sum)
          6. Anomaly detection (Isolation Forest on rolling window)

        Returns:
            dict with cv_safety_score, raw features, detections, anomaly info
        """
        self.ensure_loaded()

        # Step 1: Preprocess
        image = self._preprocess_image(image)

        # Step 2: Brightness from HSV
        brightness, uniformity = self._analyze_brightness(image)

        # Step 3: Object detection (ONNX)
        detections = self._detect_objects(image)

        # Step 4: Count and normalize safety-relevant objects
        people_count = sum(1 for d in detections if d["label"] in self.PEOPLE_LABELS)
        vehicle_count = sum(1 for d in detections if d["label"] in self.VEHICLE_LABELS)
        infra_count = sum(1 for d in detections if d["label"] in self.INFRASTRUCTURE_LABELS)

        crowd_score = min(1.0, people_count / settings.CV_CROWD_NORM_DIVISOR)
        vehicle_score = min(1.0, vehicle_count / settings.CV_VEHICLE_NORM_DIVISOR)
        structure_score = min(1.0, infra_count / settings.CV_INFRA_NORM_DIVISOR)

        # Step 5: Weighted CV safety score
        cv_score = (
            settings.CV_BRIGHTNESS_WEIGHT * brightness
            + settings.CV_CROWD_WEIGHT * crowd_score
            + settings.CV_VEHICLE_WEIGHT * vehicle_score
            + settings.CV_STRUCTURE_WEIGHT * structure_score
        )
        cv_score = max(0.0, min(1.0, cv_score))

        # Step 6: Anomaly detection
        feature_vector = [
            brightness,
            float(people_count),
            float(vehicle_count),
            float(infra_count),
        ]
        is_anomaly, anomaly_score = self._check_anomaly(feature_vector)

        logger.info(
            f"[CV Frame] brightness={brightness:.2f} people={people_count} "
            f"vehicles={vehicle_count} infra={infra_count} → "
            f"cv_score={cv_score:.3f} anomaly={is_anomaly}"
        )

        return {
            "cv_safety_score": round(cv_score, 4),
            "brightness": round(brightness, 4),
            "brightness_uniformity": round(uniformity, 4),
            "crowd_count": people_count,
            "vehicle_count": vehicle_count,
            "infrastructure_count": infra_count,
            "crowd_score": round(crowd_score, 4),
            "vehicle_score": round(vehicle_score, 4),
            "structure_score": round(structure_score, 4),
            "is_anomaly": is_anomaly,
            "anomaly_score": anomaly_score,
            "detections": detections,
        }

    def reset_anomaly_history(self) -> None:
        """Clear the rolling feature history (e.g., when starting a new route)."""
        self._feature_history.clear()
        self._anomaly_detector = None
        logger.info("CV anomaly detection history cleared ✓")
