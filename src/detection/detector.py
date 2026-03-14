"""
Deer detector — multiple backend support.

Backends (tried in order based on availability):
  1. UltralyticsDetector  — YOLOv8/YOLOWorld via PyTorch, works on macOS
  2. TFLite interpreter   — INT8 model, target for Raspberry Pi
  3. StubDetector         — configurable fake output for tests

NOTE on COCO classes: standard YOLOv8n (80-class COCO) does NOT include deer.
Use --yolo-world (default on macOS when ultralytics is available) which runs
YOLOWorld with an open-vocabulary "deer" text prompt.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

DEER_CLASS_ID = 93   # Kept for compatibility; actual matching is done by name


@dataclass
class Detection:
    class_id: int
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]   # (x1, y1, x2, y2) normalized [0,1]


# ---------------------------------------------------------------------------
# Stub
# ---------------------------------------------------------------------------
class StubDetector:
    def __init__(self, fake_detections: Optional[list] = None):
        self._fake = fake_detections or []

    def detect(self, frame: np.ndarray, confidence_threshold: float = 0.60):
        return [d for d in self._fake if d.confidence >= confidence_threshold]


# ---------------------------------------------------------------------------
# Ultralytics backend (macOS / dev machine)
# ---------------------------------------------------------------------------
class UltralyticsDetector:
    """
    Uses YOLOWorld (open-vocabulary) to detect deer by name.
    Falls back to standard YOLOv8n and searches class names for 'deer'.

    YOLOWorld model: ~87MB, downloaded automatically on first use.
    """

    # Map from model type to default model file
    _WORLD_MODEL = "yolov8s-worldv2.pt"
    _STANDARD_MODEL = "yolov8n.pt"

    def __init__(self, model_path: Optional[str] = None,
                 target_classes: Optional[list[str]] = None,
                 use_world: bool = True):
        from ultralytics import YOLO

        self._target = [c.lower() for c in (target_classes or ["deer"])]

        if use_world:
            try:
                model_file = model_path or self._WORLD_MODEL
                self._model = YOLO(model_file)
                self._model.set_classes(self._target)
                self._world = True
                logger.info("YOLOWorld loaded: %s | classes=%s", model_file, self._target)
                return
            except Exception as e:
                logger.warning("YOLOWorld unavailable (%s), falling back to yolov8n", e)

        model_file = model_path or self._STANDARD_MODEL
        self._model = YOLO(model_file)
        self._world = False

        # Check whether the model actually knows about deer
        all_classes = list(self._model.names.values())
        matches = [c for c in all_classes if any(t in c.lower() for t in self._target)]
        if not matches:
            logger.warning(
                "Model %r has no class matching %s — detections will always be empty. "
                "Use --yolo-world for open-vocabulary detection.",
                model_file, self._target,
            )
        else:
            logger.info("YOLOv8 standard model loaded. Matching classes: %s", matches)

        self._class_ids = {
            idx for idx, name in self._model.names.items()
            if any(t in name.lower() for t in self._target)
        }

    def detect(self, frame: np.ndarray,
               confidence_threshold: float = 0.60) -> list[Detection]:
        import cv2
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        results = self._model.predict(
            bgr,
            conf=confidence_threshold,
            verbose=False,
            stream=False,
        )

        detections = []
        h, w = frame.shape[:2]

        for r in results:
            for box in r.boxes:
                cls_id = int(box.cls[0])
                cls_name = self._model.names.get(cls_id, str(cls_id)).lower()

                # World model: all results match the set classes
                # Standard model: filter by class id
                if not self._world and cls_id not in self._class_ids:
                    continue

                conf = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxyn[0].tolist()  # normalized

                detections.append(Detection(
                    class_id=cls_id,
                    class_name=cls_name,
                    confidence=conf,
                    bbox=(
                        max(0.0, x1), max(0.0, y1),
                        min(1.0, x2), min(1.0, y2),
                    ),
                ))

        return detections


# ---------------------------------------------------------------------------
# TFLite backend (Raspberry Pi)
# ---------------------------------------------------------------------------
def _load_tflite_interpreter(model_path: str, use_coral: bool = False):
    if use_coral:
        try:
            from pycoral.utils.edgetpu import make_interpreter
            interp = make_interpreter(model_path)
            interp.allocate_tensors()
            logger.info("Coral Edge TPU delegate loaded")
            return interp
        except Exception as e:
            logger.warning("Coral unavailable (%s)", e)

    for pkg in ("tflite_runtime.interpreter", "tensorflow.lite"):
        try:
            if pkg == "tflite_runtime.interpreter":
                import tflite_runtime.interpreter as tflite
                interp = tflite.Interpreter(model_path=model_path)
            else:
                import tensorflow as tf
                interp = tf.lite.Interpreter(model_path=model_path)
            interp.allocate_tensors()
            logger.info("TFLite interpreter loaded: %s", model_path)
            return interp
        except ImportError:
            continue

    return None


class _TFLiteDetector:
    def __init__(self, interp, input_size: int = 640):
        self._interp = interp
        self._input_size = input_size
        details_in = interp.get_input_details()
        details_out = interp.get_output_details()
        self._in_idx = details_in[0]["index"]
        self._out_idx = details_out[0]["index"]
        self._in_dtype = details_in[0]["dtype"]

    def detect(self, frame: np.ndarray,
               confidence_threshold: float = 0.60) -> list[Detection]:
        from PIL import Image
        img = Image.fromarray(frame).resize(
            (self._input_size, self._input_size), Image.BILINEAR
        )
        arr = np.array(img)
        tensor = (arr[np.newaxis].astype(np.uint8) if self._in_dtype == np.uint8
                  else (arr / 255.0)[np.newaxis].astype(np.float32))

        self._interp.set_tensor(self._in_idx, tensor)
        self._interp.invoke()
        output = self._interp.get_tensor(self._out_idx)

        preds = output[0].T
        detections = []
        for pred in preds:
            cx, cy, w, h = pred[:4]
            class_scores = pred[4:]
            class_id = int(np.argmax(class_scores))
            confidence = float(class_scores[class_id])
            if confidence < confidence_threshold or class_id != DEER_CLASS_ID:
                continue
            x1, y1 = cx - w / 2, cy - h / 2
            x2, y2 = cx + w / 2, cy + h / 2
            detections.append(Detection(
                class_id=class_id, class_name="deer", confidence=confidence,
                bbox=(max(0.0, float(x1)), max(0.0, float(y1)),
                      min(1.0, float(x2)), min(1.0, float(y2))),
            ))
        return detections


# ---------------------------------------------------------------------------
# Public Detector facade
# ---------------------------------------------------------------------------
class Detector:
    """
    Unified detector that auto-selects backend:
      stub=True          → StubDetector (tests / fake-deer mode)
      yolo_world=True    → UltralyticsDetector with YOLOWorld (macOS default)
      model_path=*.pt    → UltralyticsDetector with standard YOLO
      model_path=*.tflite → TFLite backend (Pi)
    """

    def __init__(self,
                 model_path: str = "",
                 input_size: int = 640,
                 use_coral: bool = False,
                 stub: bool = False,
                 fake_detections: Optional[list] = None,
                 yolo_world: bool = False,
                 target_classes: Optional[list[str]] = None):

        self._stub_flag = stub

        if stub:
            self._impl = StubDetector(fake_detections)
            logger.info("Detector: stub mode")
            return

        # YOLOWorld / ultralytics path
        if yolo_world or (model_path.endswith(".pt") or model_path == ""):
            try:
                self._impl = UltralyticsDetector(
                    model_path=model_path or None,
                    target_classes=target_classes,
                    use_world=yolo_world,
                )
                return
            except ImportError:
                logger.warning("ultralytics not available — trying TFLite")

        # TFLite path
        if model_path.endswith(".tflite"):
            interp = _load_tflite_interpreter(model_path, use_coral)
            if interp:
                self._impl = _TFLiteDetector(interp, input_size)
                return
            logger.warning("TFLite load failed — falling back to stub")

        self._impl = StubDetector(fake_detections)
        self._stub_flag = True
        logger.warning("Detector: no backend available, using stub")

    @property
    def is_stub(self) -> bool:
        return self._stub_flag

    def detect(self, frame: np.ndarray,
               confidence_threshold: float = 0.60) -> list[Detection]:
        t0 = time.monotonic()
        results = self._impl.detect(frame, confidence_threshold)
        elapsed_ms = (time.monotonic() - t0) * 1000
        if results:
            logger.debug("Inference %.0fms → %d detections", elapsed_ms, len(results))
        return results

    def detect_burst(self, frames: list[np.ndarray],
                     confidence_threshold: float = 0.60) -> list[Detection]:
        best: dict[int, Detection] = {}
        for frame in frames:
            for det in self.detect(frame, confidence_threshold):
                if det.class_id not in best or det.confidence > best[det.class_id].confidence:
                    best[det.class_id] = det
        return list(best.values())
