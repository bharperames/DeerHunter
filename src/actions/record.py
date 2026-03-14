"""
Video/snapshot recording action.

For recording, this module delegates to camera.py's start_recording().
Snapshots (single frames) are saved as JPEG directly here.

Config keys:
  duration_seconds  - video clip length (record action)
  _frame            - numpy RGB frame injected by rules engine
"""

import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import numpy as np

logger = logging.getLogger(__name__)

_clips_dir: str = "storage/clips"
_snapshots_dir: str = "storage/snapshots"
_camera = None   # Set by main.py via configure()


def configure(camera, clips_dir: str = "storage/clips",
              snapshots_dir: str = "storage/snapshots") -> None:
    global _camera, _clips_dir, _snapshots_dir
    _camera = camera
    _clips_dir = clips_dir
    _snapshots_dir = snapshots_dir


def _timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def save_snapshot(frame: np.ndarray) -> Optional[str]:
    """Save a JPEG snapshot. Returns path on success."""
    try:
        from PIL import Image
        os.makedirs(_snapshots_dir, exist_ok=True)
        path = os.path.join(_snapshots_dir, f"snap_{_timestamp()}.jpg")
        Image.fromarray(frame).save(path, format="JPEG", quality=90)
        logger.info("Snapshot saved: %s", path)
        return path
    except Exception as e:
        logger.error("Failed to save snapshot: %s", e)
        return None


def record_clip(config: dict) -> None:
    """Action handler: save snapshot and start video recording."""
    duration = int(config.get("duration_seconds", 30))
    frame: Optional[np.ndarray] = config.get("_frame")

    # Always save a snapshot at trigger time
    if frame is not None:
        save_snapshot(frame)

    if _camera is None:
        logger.warning("Camera not configured in record action — snapshot only")
        return

    os.makedirs(_clips_dir, exist_ok=True)
    clip_path = os.path.join(_clips_dir, f"clip_{_timestamp()}.h264")
    _camera.start_recording(clip_path, duration_seconds=duration)
