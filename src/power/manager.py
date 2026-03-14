"""
Power management: reduces idle current draw on Raspberry Pi Zero 2W.

Called once at startup. Between events the main loop sleeps, relying on
the PIR interrupt to wake it (via gpiozero's event system).
"""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)

_IS_PI = os.path.exists("/proc/device-tree/model")


def _run(cmd: str, description: str) -> None:
    if not _IS_PI:
        logger.debug("[non-Pi skip] %s: %s", description, cmd)
        return
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("Power: %s", description)
        else:
            logger.warning("Power cmd failed (%s): %s", description, result.stderr.strip())
    except Exception as e:
        logger.warning("Power cmd exception (%s): %s", description, e)


def apply_power_savings() -> None:
    """
    Disable HDMI output, set CPU to powersave governor, and disable
    unused USB controller to reduce idle current draw.
    """
    # Disable HDMI (saves ~20mA)
    _run("tvservice -o", "HDMI disabled")

    # CPU powersave governor
    _run("cpufreq-set -g powersave", "CPU governor → powersave")

    # Disable USB (saves ~5-10mA when no devices attached)
    # Note: disabling USB kills the USB camera; only do this if using CSI camera
    _run(
        "echo '1-1' | tee /sys/bus/usb/drivers/usb/unbind 2>/dev/null || true",
        "USB controller unbound",
    )

    # Disable Wi-Fi power management (keep WiFi awake for web dashboard)
    # If web dashboard disabled, uncomment below to save ~20mA:
    # _run("iw dev wlan0 set power_save on", "WiFi power save enabled")

    logger.info("Power savings applied")


def restore_power() -> None:
    """Re-enable HDMI (useful for debugging; not called in normal operation)."""
    _run("tvservice -p", "HDMI re-enabled")
    _run("cpufreq-set -g ondemand", "CPU governor → ondemand")
