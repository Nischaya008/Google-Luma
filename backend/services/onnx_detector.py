"""
ONNX Runtime Object Detector — Lightweight COCO detection without PyTorch.

WHY ONNX instead of torch+DETR:
  1. Eliminates WinError 1114 DLL conflicts on Windows (no torch dependency)
  2. ~7MB quantized model vs ~800MB torch+DETR memory footprint
  3. Fits within Render free tier (512MB RAM) constraints
  4. Faster cold-start: no torch runtime overhead
  5. Same COCO-80 detection quality (YOLOS-Tiny, DETR-style architecture)

Model: Xenova/yolos-tiny (ONNX export of hustvl/yolos-tiny)
  - Architecture: YOLOS (You Only Look at One Sequence) — ViT-based DETR variant
  - Training: COCO 2017 (80 object classes + 1 background)
  - Input: variable-size RGB images normalized with ImageNet statistics
  - Output: detection queries with class logits + bounding boxes

Auto-downloads from HuggingFace Hub on first use and caches locally.
"""
import os
import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
from PIL import Image

logger = logging.getLogger(__name__)

# ── COCO Label Map (DETR/YOLOS 92-entry format) ────────────────────────
# Indices correspond to COCO category IDs (not contiguous 0-79).
# Index 91 = "no object" (background) in DETR-style models.
# "N/A" entries are gaps in the COCO ID space (unused category slots).
COCO_ID2LABEL: Dict[int, str] = {
    0: "N/A", 1: "person", 2: "bicycle", 3: "car", 4: "motorcycle",
    5: "airplane", 6: "bus", 7: "train", 8: "truck", 9: "boat",
    10: "traffic light", 11: "fire hydrant", 12: "N/A", 13: "stop sign",
    14: "parking meter", 15: "bench", 16: "bird", 17: "cat", 18: "dog",
    19: "horse", 20: "sheep", 21: "cow", 22: "elephant", 23: "bear",
    24: "zebra", 25: "giraffe", 26: "N/A", 27: "backpack", 28: "umbrella",
    29: "N/A", 30: "N/A", 31: "handbag", 32: "tie", 33: "suitcase",
    34: "frisbee", 35: "skis", 36: "snowboard", 37: "sports ball",
    38: "kite", 39: "baseball bat", 40: "baseball glove", 41: "skateboard",
    42: "surfboard", 43: "tennis racket", 44: "bottle", 45: "N/A",
    46: "wine glass", 47: "cup", 48: "fork", 49: "knife", 50: "spoon",
    51: "bowl", 52: "banana", 53: "apple", 54: "sandwich", 55: "orange",
    56: "broccoli", 57: "carrot", 58: "hot dog", 59: "pizza", 60: "donut",
    61: "cake", 62: "chair", 63: "couch", 64: "potted plant", 65: "bed",
    66: "N/A", 67: "dining table", 68: "N/A", 69: "N/A", 70: "toilet",
    71: "N/A", 72: "tv", 73: "laptop", 74: "mouse", 75: "remote",
    76: "keyboard", 77: "cell phone", 78: "microwave", 79: "oven",
    80: "toaster", 81: "sink", 82: "refrigerator", 83: "N/A", 84: "book",
    85: "clock", 86: "vase", 87: "scissors", 88: "teddy bear",
    89: "hair drier", 90: "toothbrush",
}

# ImageNet normalization constants (required by YOLOS/DETR pre-processing)
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
    """Numerically stable softmax (avoids overflow with max subtraction)."""
    e = np.exp(x - x.max(axis=axis, keepdims=True))
    return e / e.sum(axis=axis, keepdims=True)


class ONNXDetector:
    """
    ONNX Runtime-based COCO object detector.

    Uses YOLOS-Tiny model (Xenova ONNX export) for real-time detection of
    people, vehicles, and infrastructure elements in camera frames.

    Lifecycle:
      1. load() — downloads model from HuggingFace (cached after first download)
      2. detect(image) — runs inference, returns filtered detections
      3. Graceful degradation: if model fails to load, detect() returns []
    """

    # ── Model Source Configuration ────────────────────────────────────────
    # Primary: Xenova ONNX exports (maintained for Transformers.js, works with any ORT)
    HF_REPO_ID = "Xenova/yolos-tiny"
    # Model variants ordered by preference (smallest first for Render free tier)
    MODEL_VARIANTS = [
        "onnx/model_quantized.onnx",  # ~7MB  INT8 quantized (recommended)
        "onnx/model_uint8.onnx",      # ~7MB  UINT8 quantized (alternative)
        "onnx/model.onnx",            # ~25MB FP32 full precision (fallback)
    ]

    def __init__(self) -> None:
        self.session: Optional[object] = None
        self._loaded: bool = False
        self._input_name: Optional[str] = None
        self._output_names: Optional[List[str]] = None

    @property
    def is_loaded(self) -> bool:
        """Whether the ONNX model is loaded and ready for inference."""
        return self._loaded

    # ── Model Loading ────────────────────────────────────────────────────

    def load(self, prefer_quantized: bool = True) -> None:
        """
        Download and load the ONNX detection model.

        Downloads from HuggingFace Hub on first call (cached by huggingface_hub).
        Subsequent calls load from local cache instantly.

        Args:
            prefer_quantized: Try INT8 quantized model first (smaller, faster on CPU).

        Raises:
            RuntimeError: If no model variant can be downloaded or loaded.
        """
        import onnxruntime as ort

        model_path = self._download_model(prefer_quantized)

        # Session options tuned for low-memory CPU environments (Render free tier)
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = 2   # Conservative thread count
        opts.inter_op_num_threads = 1   # Single inter-op thread to reduce memory
        opts.enable_mem_pattern = True   # Reuse memory allocations

        self.session = ort.InferenceSession(
            model_path,
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )

        # Cache I/O metadata to avoid repeated lookups during inference
        inputs = self.session.get_inputs()
        outputs = self.session.get_outputs()
        self._input_name = inputs[0].name
        self._output_names = [o.name for o in outputs]

        model_size_mb = os.path.getsize(model_path) / (1024 * 1024)
        logger.info(
            f"ONNX detector loaded: {os.path.basename(model_path)} "
            f"({model_size_mb:.1f}MB, input={self._input_name}, "
            f"outputs={self._output_names})"
        )
        self._loaded = True

    def _download_model(self, prefer_quantized: bool) -> str:
        """
        Download model from HuggingFace Hub with cascading fallback.

        Tries model variants in order of preference (quantized first for size).
        HuggingFace Hub caches models locally, so subsequent loads are instant.

        Returns:
            Local filesystem path to the downloaded ONNX model file.

        Raises:
            RuntimeError: If all download attempts fail.
        """
        from huggingface_hub import hf_hub_download

        # Order variants by preference
        variants = list(self.MODEL_VARIANTS)
        if not prefer_quantized:
            variants.reverse()

        for filename in variants:
            try:
                path = hf_hub_download(
                    repo_id=self.HF_REPO_ID,
                    filename=filename,
                )
                logger.info(f"Model ready: {self.HF_REPO_ID}/{filename} → {path}")
                return path
            except Exception as e:
                logger.debug(f"Variant {filename} unavailable: {e}")
                continue

        raise RuntimeError(
            f"Could not download any ONNX model variant from {self.HF_REPO_ID}. "
            f"Tried: {variants}. Check network connectivity."
        )

    # ── Inference ────────────────────────────────────────────────────────

    def detect(
        self,
        image: Image.Image,
        threshold: float = 0.5,
        target_size: int = 512,
    ) -> List[Dict]:
        """
        Run COCO object detection on a PIL image.

        Pipeline:
          1. Resize to target_size (maintaining aspect ratio)
          2. Normalize with ImageNet mean/std
          3. ONNX inference
          4. Softmax + threshold filtering
          5. Convert boxes from normalized [cx,cy,w,h] to pixel [x1,y1,x2,y2]

        Args:
            image: RGB PIL Image from camera frame.
            threshold: Minimum confidence to keep a detection (0-1).
            target_size: Max dimension to resize to before inference.

        Returns:
            List of detection dicts: {"label": str, "confidence": float, "box": [x1,y1,x2,y2]}
        """
        if not self._loaded:
            return []

        # Pre-process: resize, normalize, transpose to NCHW
        pixel_values = self._preprocess(image, target_size)

        # Run ONNX inference
        outputs = self.session.run(
            self._output_names,
            {self._input_name: pixel_values},
        )

        # Post-process: DETR-style decode
        # YOLOS/DETR output: logits [1, num_queries, num_classes], pred_boxes [1, num_queries, 4]
        logits = outputs[0]
        pred_boxes = outputs[1]

        return self._postprocess(logits, pred_boxes, image.size, threshold)

    # ── Pre-processing ───────────────────────────────────────────────────

    def _preprocess(self, image: Image.Image, target_size: int) -> np.ndarray:
        """
        YOLOS/DETR image pre-processing (pure numpy, no torch).

        Steps:
          1. Resize to fit within target_size (preserving aspect ratio)
          2. Convert to float32 [0, 1]
          3. Normalize with ImageNet mean/std
          4. Transpose from HWC to NCHW layout

        Returns:
            np.ndarray of shape [1, 3, H, W], float32
        """
        # Resize maintaining aspect ratio
        w, h = image.size
        scale = target_size / max(w, h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        image = image.resize((new_w, new_h), Image.Resampling.BILINEAR)
        image = image.convert("RGB")

        # To float32 [0, 1]
        arr = np.array(image, dtype=np.float32) / 255.0

        # ImageNet normalization (per-channel)
        arr = (arr - IMAGENET_MEAN) / IMAGENET_STD

        # HWC → CHW → NCHW (batch dimension)
        arr = arr.transpose(2, 0, 1)[np.newaxis, ...]

        return arr.astype(np.float32)

    # ── Post-processing ──────────────────────────────────────────────────

    def _postprocess(
        self,
        logits: np.ndarray,
        pred_boxes: np.ndarray,
        original_size: Tuple[int, int],
        threshold: float,
    ) -> List[Dict]:
        """
        DETR/YOLOS post-processing: decode logits + boxes into detections.

        The model outputs:
          - logits: [1, N, num_classes+1] — last class = "no object"
          - pred_boxes: [1, N, 4] — normalized [center_x, center_y, width, height]

        Returns:
            Filtered list of detection dicts with pixel-space bounding boxes.
        """
        # Apply softmax to get class probabilities
        probs = _softmax(logits[0], axis=-1)

        # Exclude "no object" class (last index in DETR-style models)
        class_probs = probs[:, :-1]

        # Best class per detection query
        scores = class_probs.max(axis=-1)
        label_ids = class_probs.argmax(axis=-1)

        # Filter by confidence threshold
        mask = scores > threshold

        detections: List[Dict] = []
        orig_w, orig_h = original_size

        for idx in np.where(mask)[0]:
            label_id = int(label_ids[idx])
            label_name = COCO_ID2LABEL.get(label_id, "unknown")

            # Skip unused COCO ID slots
            if label_name in ("N/A", "unknown"):
                continue

            confidence = float(scores[idx])

            # Convert normalized [cx, cy, w, h] → pixel [x1, y1, x2, y2]
            cx, cy, bw, bh = pred_boxes[0, idx]
            x1 = float((cx - bw / 2) * orig_w)
            y1 = float((cy - bh / 2) * orig_h)
            x2 = float((cx + bw / 2) * orig_w)
            y2 = float((cy + bh / 2) * orig_h)

            detections.append({
                "label": label_name,
                "confidence": round(confidence, 3),
                "box": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
            })

        return detections
