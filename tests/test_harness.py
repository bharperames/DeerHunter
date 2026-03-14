"""
Tests for the macOS testing harness components.
"""

import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


class TestVideoFeedCamera:
    """Tests for VideoFeedCamera using a synthetic video written by OpenCV."""

    @pytest.fixture
    def synthetic_video(self, tmp_path):
        """Create a short synthetic .mp4 for testing."""
        cv2 = pytest.importorskip("cv2", reason="opencv-python required")
        path = str(tmp_path / "test.mp4")
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(path, fourcc, 10.0, (320, 240))
        for i in range(30):
            frame = np.full((240, 320, 3), i * 8, dtype=np.uint8)
            writer.write(frame)
        writer.release()
        return path

    def test_capture_frame_returns_ndarray(self, synthetic_video):
        from src.sensors.video_feed import VideoFeedCamera
        cam = VideoFeedCamera(synthetic_video, realtime=False)
        frame = cam.capture_frame()
        assert isinstance(frame, np.ndarray)
        assert frame.ndim == 3
        assert frame.shape[2] == 3
        cam.close()

    def test_capture_burst_length(self, synthetic_video):
        from src.sensors.video_feed import VideoFeedCamera
        cam = VideoFeedCamera(synthetic_video, realtime=False)
        burst = cam.capture_burst(n_frames=5, interval_s=0)
        assert len(burst) == 5
        cam.close()

    def test_resolution_override(self, synthetic_video):
        from src.sensors.video_feed import VideoFeedCamera
        cam = VideoFeedCamera(synthetic_video, resolution=(160, 120), realtime=False)
        frame = cam.capture_frame()
        assert frame.shape == (120, 160, 3)
        cam.close()

    def test_loop_restarts(self, synthetic_video):
        from src.sensors.video_feed import VideoFeedCamera
        cam = VideoFeedCamera(synthetic_video, loop=True, realtime=False)
        # Read more frames than the video has
        for _ in range(40):
            f = cam.capture_frame()
            assert f is not None
        cam.close()

    def test_no_loop_returns_black_at_end(self, synthetic_video):
        from src.sensors.video_feed import VideoFeedCamera
        cam = VideoFeedCamera(synthetic_video, loop=False, realtime=False)
        frames = list(cam.frame_generator())
        # After the generator ends, capture_frame returns black
        black = cam.capture_frame()
        assert black.shape[2] == 3
        cam.close()

    def test_close_is_idempotent(self, synthetic_video):
        from src.sensors.video_feed import VideoFeedCamera
        cam = VideoFeedCamera(synthetic_video, realtime=False)
        cam.close()
        cam.close()   # Should not raise

    def test_fps_property(self, synthetic_video):
        from src.sensors.video_feed import VideoFeedCamera
        cam = VideoFeedCamera(synthetic_video, realtime=False)
        assert cam.fps > 0
        cam.close()

    def test_start_recording_is_noop(self, synthetic_video, tmp_path):
        from src.sensors.video_feed import VideoFeedCamera
        cam = VideoFeedCamera(synthetic_video, realtime=False)
        cam.start_recording(str(tmp_path / "out.h264"), duration_seconds=5)
        # No exception, no file created
        cam.close()

    def test_invalid_source_raises(self):
        pytest.importorskip("cv2")
        from src.sensors.video_feed import VideoFeedCamera
        with pytest.raises(IOError):
            VideoFeedCamera("/nonexistent/file.mp4", realtime=False)


class TestHarnessComponents:
    """Test that the harness wires up without Pi hardware."""

    def test_harness_dry_run_no_crash(self, tmp_path):
        """Full harness run with stub detector + dry-run should complete cleanly."""
        import shutil
        import sys

        # Copy config to tmp_path
        shutil.copy("config/rules.yaml", tmp_path / "rules.yaml")

        cv2 = pytest.importorskip("cv2", reason="opencv-python required")
        # Create a tiny test video
        path = str(tmp_path / "test.mp4")
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(path, fourcc, 10.0, (320, 240))
        for i in range(60):
            writer.write(np.full((240, 320, 3), 100, dtype=np.uint8))
        writer.release()

        import argparse
        from src.harness import run_harness

        args = argparse.Namespace(
            video=path,
            config=str(tmp_path / "rules.yaml"),
            model=None,
            stub_detector=True,
            fake_deer=False,
            fake_confidence=0.88,
            dry_run=True,
            loop=False,
            realtime=False,
            fps=None,
            burst=2,
            trigger_every=10,
            preview=False,
            save_snapshots=False,
        )
        run_harness(args)   # Should not raise
