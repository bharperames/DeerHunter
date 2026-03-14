"""
Camera module: frame capture using picamera2.

Provides burst capture for still-frame ML inference and H264 video recording.
Falls back to stub/file-based capture on non-Pi hardware.
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    from picamera2 import Picamera2
    from picamera2.encoders import H264Encoder
    from picamera2.outputs import FileOutput
    _PICAMERA2_AVAILABLE = True
except ImportError:
    _PICAMERA2_AVAILABLE = False
    logger.warning("picamera2 not available — using stub camera")

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


class StubCamera:
    """Returns synthetic or file-based frames for development/testing."""

    def __init__(self, resolution: tuple[int, int] = (1280, 720),
                 source_path: Optional[str] = None):
        self.resolution = resolution
        self.source_path = source_path
        self._frame_index = 0
        self._source_frames: list[np.ndarray] = []

        if source_path and os.path.isfile(source_path) and _PIL_AVAILABLE:
            self._load_image_source(source_path)
        elif source_path and os.path.isdir(source_path) and _PIL_AVAILABLE:
            self._load_directory_source(source_path)

    def _load_image_source(self, path: str) -> None:
        img = Image.open(path).convert("RGB").resize(self.resolution)
        self._source_frames = [np.array(img)]
        logger.info("StubCamera loaded image: %s", path)

    def _load_directory_source(self, path: str) -> None:
        exts = {".jpg", ".jpeg", ".png", ".bmp"}
        files = sorted(
            p for p in Path(path).iterdir()
            if p.suffix.lower() in exts
        )
        for f in files:
            try:
                img = Image.open(f).convert("RGB").resize(self.resolution)
                self._source_frames.append(np.array(img))
            except Exception:
                logger.warning("Could not load image: %s", f)
        logger.info("StubCamera loaded %d frames from directory: %s",
                    len(self._source_frames), path)

    def capture_frame(self) -> np.ndarray:
        if self._source_frames:
            frame = self._source_frames[self._frame_index % len(self._source_frames)]
            self._frame_index += 1
            return frame.copy()
        # Return a grey synthetic frame
        w, h = self.resolution
        return np.full((h, w, 3), 128, dtype=np.uint8)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


class Camera:
    """Wraps picamera2 for burst capture and video recording."""

    def __init__(self, resolution: tuple[int, int] = (1280, 720),
                 framerate: int = 10,
                 stub_source: Optional[str] = None):
        self._resolution = resolution
        self._framerate = framerate
        self._recording = False

        if _PICAMERA2_AVAILABLE and stub_source is None:
            self._cam = Picamera2()
            config = self._cam.create_still_configuration(
                main={"size": resolution, "format": "RGB888"},
                lores={"size": (320, 240), "format": "YUV420"},
                display="lores",
            )
            self._cam.configure(config)
            self._cam.start()
            self._stub = None
            logger.info("picamera2 initialized at %dx%d", *resolution)
        else:
            self._cam = None
            self._stub = StubCamera(resolution, stub_source)
            logger.info("Using stub camera (source=%s)", stub_source or "synthetic")

    def capture_frame(self) -> np.ndarray:
        """Capture a single RGB frame as a numpy array (H, W, 3)."""
        if self._stub:
            return self._stub.capture_frame()
        return self._cam.capture_array("main")

    def capture_burst(self, n_frames: int = 5,
                      interval_s: float = 0.2) -> list[np.ndarray]:
        """Capture N frames with a short interval between them."""
        frames = []
        for _ in range(n_frames):
            frames.append(self.capture_frame())
            if interval_s > 0 and _ < n_frames - 1:
                time.sleep(interval_s)
        return frames

    def start_recording(self, output_path: str,
                        duration_seconds: int = 30) -> None:
        """Start H264 recording in a background thread (Pi only)."""
        if self._stub:
            logger.info("[stub] Would record %ds to %s", duration_seconds, output_path)
            return

        if self._recording:
            logger.warning("Already recording; ignoring start_recording call")
            return

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        encoder = H264Encoder(bitrate=4_000_000)
        output = FileOutput(output_path)
        self._cam.start_recording(encoder, output)
        self._recording = True
        logger.info("Recording started → %s", output_path)

        # Stop automatically after duration
        import threading
        def _stop_after():
            time.sleep(duration_seconds)
            self.stop_recording()

        threading.Thread(target=_stop_after, daemon=True).start()

    def stop_recording(self) -> None:
        if self._stub or not self._recording:
            return
        self._cam.stop_recording()
        self._recording = False
        logger.info("Recording stopped")

    def close(self) -> None:
        if self._stub:
            self._stub.close()
        elif self._cam:
            if self._recording:
                self.stop_recording()
            self._cam.close()
