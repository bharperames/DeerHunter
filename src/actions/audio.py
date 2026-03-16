"""
Audio deterrent action: plays a .wav file via afplay (macOS), pygame, or aplay (Linux).

Config keys:
  file      - filename relative to sounds/ directory
  volume    - 0-100
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

SOUNDS_DIR = Path(__file__).resolve().parents[2] / "sounds"

_PYGAME_AVAILABLE = False
if sys.platform != "darwin":
    try:
        import pygame
        pygame.mixer.init()
        _PYGAME_AVAILABLE = True
    except Exception:
        logger.warning("pygame not available — will use aplay fallback")


def play_audio(config: dict) -> None:
    """Action handler: play deterrent audio file."""
    filename = config.get("file", "")
    volume = int(config.get("volume", 80))
    sound_path = SOUNDS_DIR / filename

    if not sound_path.exists():
        logger.error("Audio file not found: %s", sound_path)
        return

    logger.info("Playing audio: %s at volume %d%%", filename, volume)

    # macOS: afplay
    if sys.platform == "darwin":
        vol_arg = str(volume / 100.0 * 2.0)  # afplay -v range 0-2
        try:
            subprocess.run(["afplay", "-v", vol_arg, str(sound_path)], check=True)
        except Exception as e:
            logger.error("afplay failed: %s", e)
        return

    # Linux: try pygame first, then aplay
    if _PYGAME_AVAILABLE:
        try:
            pygame.mixer.music.load(str(sound_path))
            pygame.mixer.music.set_volume(volume / 100.0)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.wait(100)
            return
        except Exception as e:
            logger.warning("pygame playback failed (%s), trying aplay", e)

    try:
        subprocess.run(
            ["amixer", "sset", "Master", f"{volume}%"],
            capture_output=True, check=False
        )
        subprocess.run(["aplay", str(sound_path)], check=True)
    except FileNotFoundError:
        logger.error("aplay not found — cannot play audio on this system")
    except subprocess.CalledProcessError as e:
        logger.error("aplay failed: %s", e)
