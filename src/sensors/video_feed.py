"""
VideoFeedCamera: a Camera-compatible class that reads frames from a video file.

Designed for use on macOS (or any non-Pi machine) to simulate a live camera
feed during development and testing. Supports:
  - Looping a video file as if it were a live stream
  - Controlled playback speed (real-time, N×, or as-fast-as-possible)
  - Drop-in replacement for Camera — same public API
  - Frame-differencing motion detection that fires callbacks like a real PIR

Usage:
    from src.sensors.video_feed import VideoFeedCamera
    cam = VideoFeedCamera("test_footage/backyard.mp4", loop=True, realtime=True)
    cam.register_motion_callback(lambda: print("motion!"))
    frames = cam.capture_burst(n_frames=5)
    cam.close()

Or from the CLI:
    python src/main.py --video-feed test_footage/backyard.mp4 --stub-detector --fake-deer
"""

import collections
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False
    logger.warning("opencv-python not installed — VideoFeedCamera unavailable. "
                   "Install with: pip install opencv-python-headless")


class VideoFeedCamera:
    """
    Simulates a live camera by reading frames from a video file via OpenCV.

    Implements the same public interface as Camera:
      - capture_frame() -> np.ndarray  (H, W, 3) RGB
      - capture_burst(n_frames, interval_s) -> list[np.ndarray]
      - start_recording(output_path, duration_seconds) -> None  (no-op / log only)
      - stop_recording() -> None
      - close() -> None

    Also provides PIR-style motion detection via frame differencing:
      - register_motion_callback(cb) — fired when motion exceeds threshold
      - motion_level  — float 0–1 (mean pixel diff, normalised)
      - motion_active — bool (level ≥ threshold)
      - motion_history — list of recent motion levels (for sparkline)

    Args:
        source: Path to video file (mp4, avi, mov, etc.) or integer for webcam index.
        resolution: Resize output frames to (width, height). None = native resolution.
        loop: If True, seek back to start when the video ends.
        realtime: If True, sleep between frames to match the video's native FPS.
                  If False, return frames as fast as possible.
        start_frame: Start playback at this frame number (0-indexed).
        motion_threshold: Mean normalised pixel diff (0–1) to count as motion.
                          Typical values: 0.008 (sensitive) – 0.025 (coarse).
        motion_cooldown_s: Minimum seconds between motion callback firings.
    """

    def __init__(
        self,
        source,
        resolution: Optional[tuple[int, int]] = None,
        loop: bool = True,
        realtime: bool = True,
        start_frame: int = 0,
        motion_threshold: float = 0.012,
        motion_cooldown_s: float = 1.5,
    ):
        if not _CV2_AVAILABLE:
            raise ImportError(
                "opencv-python is required for VideoFeedCamera. "
                "Install with: pip install opencv-python-headless"
            )

        self._source = source
        self._resolution = resolution   # (width, height)
        self._loop = loop
        self._realtime = realtime
        self._lock = threading.Lock()
        self._closed = False

        self._cap = cv2.VideoCapture(str(source) if isinstance(source, Path) else source)
        if not self._cap.isOpened():
            raise IOError(f"Cannot open video source: {source!r}")

        self._native_fps = self._cap.get(cv2.CAP_PROP_FPS) or 25.0
        self._frame_interval = 1.0 / self._native_fps
        self._total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._last_frame_time = 0.0
        self._frame_index = 0

        if start_frame > 0:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            self._frame_index = start_frame

        w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        logger.info(
            "VideoFeedCamera: %s | %dx%d @ %.1f fps | loop=%s realtime=%s",
            source, w, h, self._native_fps, loop, realtime,
        )

        # --- Motion detection state ---
        self._motion_threshold = motion_threshold
        self._motion_cooldown_s = motion_cooldown_s
        self._prev_gray: Optional[np.ndarray] = None
        self._motion_level: float = 0.0
        self._motion_active: bool = False
        self._motion_callbacks: list[Callable] = []
        # 120 samples ≈ 8 s at ~15 fps stream rate
        self._motion_history: collections.deque = collections.deque(maxlen=120)
        self._last_motion_fire: float = 0.0

    # ------------------------------------------------------------------
    # Motion detection
    # ------------------------------------------------------------------

    def register_motion_callback(self, cb: Callable) -> None:
        """Register a function called (in a daemon thread) when motion is detected."""
        self._motion_callbacks.append(cb)

    def _update_motion(self, rgb: np.ndarray) -> None:
        """
        Compute frame-to-frame pixel difference and fire motion callbacks.

        Downsamples to 160×90 for speed; mean absolute diff / 255 gives a
        0–1 motion level that mirrors the HC-SR501's analogue output.
        """
        small = cv2.resize(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), (160, 90))
        level = 0.0
        if self._prev_gray is not None:
            diff = cv2.absdiff(small, self._prev_gray)
            level = float(diff.mean()) / 255.0
        self._prev_gray = small
        self._motion_level = level
        self._motion_history.append(level)
        active = level >= self._motion_threshold
        self._motion_active = active

        if active:
            now = time.monotonic()
            if (now - self._last_motion_fire) >= self._motion_cooldown_s:
                self._last_motion_fire = now
                for cb in list(self._motion_callbacks):
                    threading.Thread(target=cb, daemon=True).start()

    @property
    def motion_level(self) -> float:
        """Current normalised motion level (0–1)."""
        return self._motion_level

    @property
    def motion_active(self) -> bool:
        """True when current motion level ≥ threshold."""
        return self._motion_active

    @property
    def motion_history(self) -> list[float]:
        """Copy of the recent motion level history (oldest → newest)."""
        return list(self._motion_history)

    @property
    def motion_threshold(self) -> float:
        return self._motion_threshold

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_next_frame(self) -> Optional[np.ndarray]:
        """Read one frame from the video, looping if enabled."""
        with self._lock:
            if self._closed:
                return None

            ret, bgr = self._cap.read()

            if not ret:
                if self._loop and self._total_frames > 0:
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self._frame_index = 0
                    ret, bgr = self._cap.read()
                    if not ret:
                        return None
                else:
                    logger.info("VideoFeedCamera: end of video (loop=False)")
                    return None

            self._frame_index += 1

        # BGR → RGB
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

        if self._resolution is not None:
            rgb = cv2.resize(rgb, self._resolution, interpolation=cv2.INTER_LINEAR)

        return rgb

    def _pace(self) -> None:
        """Sleep to maintain real-time playback pace if requested."""
        if not self._realtime:
            return
        now = time.monotonic()
        elapsed = now - self._last_frame_time
        sleep_for = self._frame_interval - elapsed
        if sleep_for > 0:
            time.sleep(sleep_for)
        self._last_frame_time = time.monotonic()

    # ------------------------------------------------------------------
    # Public API (matches Camera)
    # ------------------------------------------------------------------

    def capture_frame(self) -> np.ndarray:
        """Return one RGB frame as a numpy array (H, W, 3) and update motion state."""
        self._pace()
        frame = self._read_next_frame()
        if frame is None:
            h = self._resolution[1] if self._resolution else 480
            w = self._resolution[0] if self._resolution else 640
            return np.zeros((h, w, 3), dtype=np.uint8)
        self._update_motion(frame)
        return frame

    def capture_burst(self, n_frames: int = 5,
                      interval_s: float = 0.0) -> list[np.ndarray]:
        """Return N consecutive frames, optionally with a sleep between each."""
        frames = []
        for i in range(n_frames):
            frames.append(self.capture_frame())
            if interval_s > 0 and i < n_frames - 1:
                time.sleep(interval_s)
        return frames

    def start_recording(self, output_path: str,
                        duration_seconds: int = 30) -> None:
        """No-op stub — recording from a video feed is not meaningful."""
        logger.info("[VideoFeedCamera] start_recording called (no-op): %s", output_path)

    def seek_to_start(self) -> None:
        """Rewind the video to frame 0 and reset motion state."""
        with self._lock:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self._frame_index = 0
            self._last_frame_time = 0.0
        self._prev_gray = None
        self._motion_level = 0.0
        self._motion_active = False
        self._motion_history.clear()
        logger.info("VideoFeedCamera rewound to start")

    def stop_recording(self) -> None:
        pass

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._cap.release()
                self._closed = True
                logger.info("VideoFeedCamera closed")

    # ------------------------------------------------------------------
    # Extra: frame generator for testing harness / replay scripts
    # ------------------------------------------------------------------

    def frame_generator(self):
        """Yield frames one at a time until the video ends (or forever if loop=True)."""
        while not self._closed:
            frame = self.capture_frame()
            if frame is None:
                break
            yield frame

    @property
    def frame_size(self) -> tuple[int, int]:
        """Return (width, height) of video frames."""
        import cv2 as _cv2
        w = int(self._cap.get(_cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self._cap.get(_cv2.CAP_PROP_FRAME_HEIGHT))
        return w, h

    @property
    def fps(self) -> float:
        return self._native_fps

    @property
    def frame_count(self) -> int:
        return self._total_frames

    @property
    def current_frame(self) -> int:
        return self._frame_index
