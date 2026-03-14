"""
Audio deterrent action: plays a .wav file via pygame or aplay.

Config keys:
  file      - filename relative to sounds/ directory
  volume    - 0-100 (pygame) or passed to aplay via amixer
"""

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

SOUNDS_DIR = Path(__file__).resolve().parents[3] / "sounds"

try:
    import pygame
    pygame.mixer.init()
    _PYGAME_AVAILABLE = True
except Exception:
    _PYGAME_AVAILABLE = False
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

    if _PYGAME_AVAILABLE:
        try:
            pygame.mixer.music.load(str(sound_path))
            pygame.mixer.music.set_volume(volume / 100.0)
            pygame.mixer.music.play()
            # Block until done so thread lifecycle is clean
            while pygame.mixer.music.get_busy():
                pygame.time.wait(100)
            return
        except Exception as e:
            logger.warning("pygame playback failed (%s), trying aplay", e)

    # aplay fallback
    try:
        # Set volume via amixer (best-effort)
        subprocess.run(
            ["amixer", "sset", "Master", f"{volume}%"],
            capture_output=True, check=False
        )
        subprocess.run(["aplay", str(sound_path)], check=True)
    except FileNotFoundError:
        logger.error("aplay not found — cannot play audio on this system")
    except subprocess.CalledProcessError as e:
        logger.error("aplay failed: %s", e)
