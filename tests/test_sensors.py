"""
Unit tests for sensor modules (PIR and Camera stubs).
"""

import os
import time
from pathlib import Path

import numpy as np
import pytest

from src.sensors.pir import PIRSensor
from src.sensors.camera import Camera, StubCamera


class TestPIRSensor:
    def test_callback_registered_and_called(self):
        pir = PIRSensor(pin=17)
        fired = []
        pir.register_callback(lambda: fired.append(1))
        pir.simulate_motion()
        assert fired == [1]
        pir.close()

    def test_multiple_callbacks(self):
        pir = PIRSensor(pin=17)
        a, b = [], []
        pir.register_callback(lambda: a.append(1))
        pir.register_callback(lambda: b.append(1))
        pir.simulate_motion()
        assert a == [1]
        assert b == [1]
        pir.close()

    def test_motion_count_increments(self):
        pir = PIRSensor(pin=17)
        assert pir.motion_count == 0
        pir.simulate_motion()
        pir.simulate_motion()
        assert pir.motion_count == 2
        pir.close()

    def test_callback_exception_does_not_crash(self):
        pir = PIRSensor(pin=17)
        def bad_cb():
            raise RuntimeError("test error")

        pir.register_callback(bad_cb)
        pir.simulate_motion()   # Should not raise
        pir.close()


class TestStubCamera:
    def test_synthetic_frame_shape(self):
        cam = StubCamera(resolution=(640, 480))
        frame = cam.capture_frame()
        assert frame.shape == (480, 640, 3)
        assert frame.dtype == np.uint8

    def test_frame_from_image_file(self, tmp_path):
        from PIL import Image
        img = Image.new("RGB", (100, 100), color=(200, 100, 50))
        path = tmp_path / "test.jpg"
        img.save(path)

        cam = StubCamera(resolution=(200, 150), source_path=str(path))
        frame = cam.capture_frame()
        assert frame.shape == (150, 200, 3)

    def test_frame_from_directory(self, tmp_path):
        from PIL import Image
        for i in range(3):
            img = Image.new("RGB", (80, 60), color=(i * 80, 0, 0))
            img.save(tmp_path / f"img_{i:02d}.jpg")

        cam = StubCamera(resolution=(80, 60), source_path=str(tmp_path))
        assert len(cam._source_frames) == 3
        # Cycles through frames
        frames = [cam.capture_frame() for _ in range(6)]
        assert len(frames) == 6


class TestCamera:
    def test_stub_camera_burst(self):
        cam = Camera(resolution=(320, 240), stub_source=None)
        # No real picamera2 → stub
        frames = cam.capture_burst(n_frames=3, interval_s=0)
        assert len(frames) == 3
        for f in frames:
            assert isinstance(f, np.ndarray)
        cam.close()

    def test_stub_recording_does_not_raise(self, tmp_path):
        cam = Camera(stub_source=None)
        clip_path = str(tmp_path / "clips" / "test.h264")
        cam.start_recording(clip_path, duration_seconds=1)
        cam.close()
