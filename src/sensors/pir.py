"""
PIR motion sensor handler using GPIO interrupt via gpiozero.

On a Raspberry Pi Zero 2W, the HC-SR501 PIR sensor connects to a GPIO pin.
Default pin: GPIO 17 (BCM numbering).
"""

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Try to import gpiozero; fall back to a stub for development on non-Pi hardware
try:
    from gpiozero import MotionSensor
    _GPIO_AVAILABLE = True
except (ImportError, Exception):
    _GPIO_AVAILABLE = False
    logger.warning("gpiozero not available — using stub PIR sensor")


class StubMotionSensor:
    """Stub for development/testing on non-Pi hardware."""

    def __init__(self, pin: int):
        self.pin = pin
        self.when_motion = None
        self.when_no_motion = None
        self._active = False

    def simulate_motion(self):
        if self.when_motion:
            self.when_motion()

    def close(self):
        pass


class PIRSensor:
    """Wraps gpiozero MotionSensor with callback registration and thread safety."""

    def __init__(self, pin: int = 17, queue_timeout: float = 0.0):
        self._pin = pin
        self._callbacks: list[Callable] = []
        self._lock = threading.Lock()
        self._motion_count = 0

        if _GPIO_AVAILABLE:
            self._sensor = MotionSensor(pin, queue_len=1, sample_rate=10,
                                        threshold=0.5)
            self._sensor.when_motion = self._on_motion
            self._sensor.when_no_motion = self._on_no_motion
        else:
            self._sensor = StubMotionSensor(pin)
            self._sensor.when_motion = self._on_motion

        logger.info("PIR sensor initialized on GPIO pin %d", pin)

    def register_callback(self, cb: Callable) -> None:
        """Register a function to call when motion is detected."""
        with self._lock:
            self._callbacks.append(cb)

    def _on_motion(self) -> None:
        with self._lock:
            self._motion_count += 1
            count = self._motion_count
            callbacks = list(self._callbacks)

        logger.debug("PIR motion detected (event #%d)", count)
        for cb in callbacks:
            try:
                cb()
            except Exception:
                logger.exception("Error in PIR callback")

    def _on_no_motion(self) -> None:
        logger.debug("PIR: no motion")

    def simulate_motion(self) -> None:
        """Manually fire a motion event (useful for testing)."""
        if isinstance(self._sensor, StubMotionSensor):
            self._sensor.simulate_motion()
        else:
            self._on_motion()

    def close(self) -> None:
        self._sensor.close()
        logger.info("PIR sensor closed")

    @property
    def motion_count(self) -> int:
        return self._motion_count
