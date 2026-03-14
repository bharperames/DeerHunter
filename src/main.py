"""
DeerHunter main orchestrator.

Wires together PIR sensor, camera, ML detector, rules engine, and actions.
Runs the event loop; web server is a separate systemd service.

Usage:
    python src/main.py [--dry-run] [--config config/rules.yaml]
                       [--stub-camera PATH] [--stub-detector]
                       [--simulate-motion]
"""

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Bootstrap path so local imports work regardless of CWD
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.sensors.pir import PIRSensor
from src.sensors.camera import Camera
from src.detection.detector import Detector, Detection
from src.rules.engine import RulesEngine
from src.actions import audio, notify, record
from src.power.manager import apply_power_savings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("deerhunter.main")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DeerHunter IoT controller")
    p.add_argument("--config", default="config/rules.yaml",
                   help="Path to rules.yaml config file")
    p.add_argument("--dry-run", action="store_true",
                   help="Log actions without executing them")
    p.add_argument("--stub-camera", metavar="PATH", default=None,
                   help="Use stub camera with images from PATH (file or directory)")
    p.add_argument("--stub-detector", action="store_true",
                   help="Use stub detector (no ML model required)")
    p.add_argument("--fake-deer", action="store_true",
                   help="Stub detector returns a fake deer detection (implies --stub-detector)")
    p.add_argument("--simulate-motion", action="store_true",
                   help="Fire one simulated PIR trigger then exit after processing")
    p.add_argument("--gpio-pin", type=int, default=17,
                   help="GPIO BCM pin number for PIR sensor")
    p.add_argument("--burst-frames", type=int, default=None,
                   help="Override number of camera burst frames")
    return p.parse_args()


class DeerHunter:
    def __init__(self, args: argparse.Namespace):
        self._args = args
        self._dry_run = args.dry_run
        self._running = False
        self._processing = threading.Lock()

        # Load config
        with open(args.config) as f:
            self._config = yaml.safe_load(f)

        cam_cfg = self._config.get("camera", {})
        det_cfg = self._config.get("detector", {})
        ntfy_cfg = self._config.get("notifications", {})
        stor_cfg = self._config.get("storage", {})

        burst = args.burst_frames or cam_cfg.get("burst_frames", 5)

        # Camera
        self._camera = Camera(
            resolution=tuple(cam_cfg.get("resolution", [1280, 720])),
            framerate=cam_cfg.get("framerate", 10),
            stub_source=args.stub_camera,
        )
        self._burst_frames = burst

        # Detector
        from src.detection.detector import Detection
        fake = []
        if args.fake_deer:
            fake = [Detection(93, "deer", 0.92, (0.2, 0.1, 0.7, 0.9))]

        self._detector = Detector(
            model_path=det_cfg.get("model_path", "src/detection/models/yolov8n_int8.tflite"),
            input_size=det_cfg.get("input_size", 640),
            stub=(args.stub_detector or args.fake_deer),
            fake_detections=fake,
        )

        # Notifications
        notify.configure(
            ntfy_url=ntfy_cfg.get("ntfy_url", "https://ntfy.sh"),
            topic=ntfy_cfg.get("topic", "deerhunter-alerts"),
        )

        # Recording
        record.configure(
            camera=self._camera,
            clips_dir=stor_cfg.get("clips_dir", "storage/clips"),
            snapshots_dir=stor_cfg.get("snapshots_dir", "storage/snapshots"),
        )

        # Rules engine
        self._engine = RulesEngine(args.config)
        self._engine.register_action("audio", audio.play_audio)
        self._engine.register_action("notify", notify.send_notification)
        self._engine.register_action("record", record.record_clip)

        # PIR sensor
        self._pir = PIRSensor(pin=args.gpio_pin)
        self._pir.register_callback(self._on_motion)

        logger.info("DeerHunter initialized (dry_run=%s)", self._dry_run)

    def _on_motion(self) -> None:
        """PIR interrupt callback — runs in gpiozero's background thread."""
        if not self._processing.acquire(blocking=False):
            logger.debug("Motion ignored — already processing an event")
            return
        try:
            self._handle_motion_event()
        finally:
            self._processing.release()

    def _handle_motion_event(self) -> None:
        logger.info("Motion detected — capturing frames")

        # 1. Capture burst of frames
        frames = self._camera.capture_burst(
            n_frames=self._burst_frames, interval_s=0.15
        )
        if not frames:
            logger.warning("No frames captured")
            return

        best_frame = frames[0]

        # 2. Run deer detection
        det_cfg = self._config.get("detector", {})
        threshold = det_cfg.get("default_confidence", 0.60)
        detections = self._detector.detect_burst(frames, confidence_threshold=threshold)

        if detections:
            best = max(detections, key=lambda d: d.confidence)
            logger.info("Deer detected! confidence=%.2f bbox=%s",
                        best.confidence, best.bbox)

            # Use the frame where confidence was highest (heuristic: last frame)
            best_frame = frames[-1]
            self._engine.evaluate(
                "deer_detected",
                confidence=best.confidence,
                frame=best_frame,
                dry_run=self._dry_run,
            )
        else:
            logger.info("Motion detected, no deer — evaluating motion_detected rules")
            self._engine.evaluate(
                "motion_detected",
                confidence=1.0,
                frame=best_frame,
                dry_run=self._dry_run,
            )

    def start(self) -> None:
        self._running = True
        logger.info("DeerHunter running. Waiting for motion...")

        if self._args.simulate_motion:
            logger.info("Simulating one motion trigger...")
            time.sleep(0.5)
            self._pir.simulate_motion()
            time.sleep(3)   # Allow actions to complete
            self.stop()
            return

        try:
            while self._running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self.stop()

    def stop(self) -> None:
        self._running = False
        self._pir.close()
        self._camera.close()
        logger.info("DeerHunter stopped")


def main() -> None:
    args = parse_args()

    if args.dry_run:
        logger.info("=== DRY RUN MODE — actions will be logged but not executed ===")

    apply_power_savings()

    app = DeerHunter(args)

    def _sig_handler(sig, frame):
        logger.info("Signal %d received — shutting down", sig)
        app.stop()

    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT, _sig_handler)

    app.start()


if __name__ == "__main__":
    main()
