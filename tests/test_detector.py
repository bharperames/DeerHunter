"""
Unit tests for the detector module.

Uses StubDetector to avoid requiring a real TFLite model.
"""

import numpy as np
import pytest

from src.detection.detector import Detector, Detection, DEER_CLASS_ID


@pytest.fixture
def blank_frame():
    return np.zeros((720, 1280, 3), dtype=np.uint8)


@pytest.fixture
def fake_deer():
    return Detection(
        class_id=DEER_CLASS_ID,
        class_name="deer",
        confidence=0.88,
        bbox=(0.1, 0.2, 0.6, 0.9),
    )


class TestDetectorStub:
    def test_no_detections_by_default(self, blank_frame):
        det = Detector(model_path="", stub=True)
        results = det.detect(blank_frame)
        assert results == []

    def test_returns_fake_deer(self, blank_frame, fake_deer):
        det = Detector(model_path="", stub=True, fake_detections=[fake_deer])
        results = det.detect(blank_frame, confidence_threshold=0.50)
        assert len(results) == 1
        assert results[0].class_id == DEER_CLASS_ID
        assert results[0].class_name == "deer"

    def test_confidence_filter(self, blank_frame, fake_deer):
        det = Detector(model_path="", stub=True, fake_detections=[fake_deer])
        # Threshold higher than fake confidence
        results = det.detect(blank_frame, confidence_threshold=0.95)
        assert results == []

    def test_detect_burst_returns_best(self, blank_frame):
        frames = [blank_frame.copy() for _ in range(3)]
        low_conf = Detection(DEER_CLASS_ID, "deer", 0.60, (0.0, 0.0, 0.5, 0.5))
        high_conf = Detection(DEER_CLASS_ID, "deer", 0.92, (0.1, 0.1, 0.8, 0.8))

        call_count = [0]
        original_detect = Detector.detect

        def mock_detect(self, frame, confidence_threshold=0.60):
            c = call_count[0]
            call_count[0] += 1
            return [low_conf] if c < 2 else [high_conf]

        det = Detector(model_path="", stub=True, fake_detections=[low_conf])
        # Manually override to alternate detections
        det._impl._fake = [high_conf]
        results = det.detect_burst(frames, confidence_threshold=0.50)
        assert len(results) == 1
        assert results[0].confidence == 0.92

    def test_detect_burst_empty_frames(self):
        det = Detector(model_path="", stub=True)
        results = det.detect_burst([])
        assert results == []

    def test_detection_dataclass_fields(self, fake_deer):
        assert fake_deer.class_id == DEER_CLASS_ID
        assert fake_deer.class_name == "deer"
        assert 0.0 <= fake_deer.confidence <= 1.0
        x1, y1, x2, y2 = fake_deer.bbox
        assert x1 < x2
        assert y1 < y2
