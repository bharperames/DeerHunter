"""
DeerHunter Testing Harness — macOS / non-Pi video feed simulator.

Plays back a video file (or webcam), runs the full detection + rules pipeline,
and logs results without requiring Pi hardware.

Usage examples:

  # Real YOLOWorld inference on a video file (recommended for macOS):
  python3 src/harness.py --video DeerTest.mov

  # Play back with fake deer detections (no model download needed):
  python3 src/harness.py --video DeerTest.mov --fake-deer --dry-run

  # Directory of JPEG images:
  python3 src/harness.py --video test_footage/ --fps 2

  # Live webcam:
  python3 src/harness.py --video 0
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.detection.detector import Detector, Detection, DEER_CLASS_ID
from src.rules.engine import RulesEngine
from src.actions import audio, notify, record

DEFAULT_CONFIG = "config/rules.yaml"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="DeerHunter macOS testing harness — video feed simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--video", required=True, metavar="PATH_OR_INDEX",
                   help="Video file, image directory, or webcam index")
    p.add_argument("--config", default=DEFAULT_CONFIG)
    p.add_argument("--model", default=None,
                   help="Path to .pt or .tflite model (default: auto-download yolov8s-worldv2.pt)")
    p.add_argument("--yolo-world", action="store_true", default=True,
                   help="Use YOLOWorld open-vocabulary model (default: on)")
    p.add_argument("--no-yolo-world", dest="yolo_world", action="store_false",
                   help="Use standard YOLOv8n instead of YOLOWorld")
    p.add_argument("--stub-detector", action="store_true",
                   help="Skip ML inference entirely (no detections)")
    p.add_argument("--fake-deer", action="store_true",
                   help="Inject a fake deer detection on every trigger (no model needed)")
    p.add_argument("--fake-confidence", type=float, default=0.88)
    p.add_argument("--confidence", type=float, default=None,
                   help="Detection confidence threshold (default: from rules.yaml)")
    p.add_argument("--dry-run", action="store_true",
                   help="Log actions that would fire without executing them")
    p.add_argument("--loop", action="store_true",
                   help="Loop the video indefinitely")
    p.add_argument("--realtime", action="store_true",
                   help="Play at native video FPS (default: as fast as possible)")
    p.add_argument("--fps", type=float, default=None,
                   help="Override playback FPS (image directory default: 2)")
    p.add_argument("--burst", type=int, default=1,
                   help="Frames to capture per simulated PIR trigger (default: 1)")
    p.add_argument("--trigger-every", type=int, default=1,
                   help="Simulate a PIR trigger every N frames (default: 1 = every frame)")
    p.add_argument("--verbose", action="store_true",
                   help="Show per-frame log lines (default: detections only)")
    return p.parse_args()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Always show our harness-level messages regardless of verbose
    logging.getLogger("deerhunter.harness").setLevel(logging.INFO)


def _make_camera(args):
    source = args.video

    if os.path.isdir(source):
        from src.sensors.camera import StubCamera

        class _PacedDirCamera:
            def __init__(self, cam, fps):
                self._cam = cam
                self._interval = 1.0 / fps
                self._last = 0.0

            def capture_frame(self):
                elapsed = time.monotonic() - self._last
                wait = self._interval - elapsed
                if wait > 0:
                    time.sleep(wait)
                self._last = time.monotonic()
                return self._cam.capture_frame()

            def capture_burst(self, n=1, interval_s=0):
                return [self.capture_frame() for _ in range(n)]

            def close(self):
                self._cam.close()

        cam = StubCamera(resolution=(1280, 720), source_path=source)
        return _PacedDirCamera(cam, args.fps or 2.0)

    try:
        source = int(source)
    except (ValueError, TypeError):
        pass

    from src.sensors.video_feed import VideoFeedCamera
    return VideoFeedCamera(source=source, loop=args.loop, realtime=args.realtime)


def _make_detector(args) -> Detector:
    if args.fake_deer:
        fake = [Detection(DEER_CLASS_ID, "deer", args.fake_confidence,
                          (0.2, 0.1, 0.7, 0.9))]
        return Detector(stub=True, fake_detections=fake)

    if args.stub_detector:
        return Detector(stub=True)

    return Detector(
        model_path=args.model or "",
        yolo_world=args.yolo_world,
    )


def _annotate_jpeg(frame: np.ndarray, detections: list) -> bytes:
    """Draw bounding boxes and return JPEG bytes."""
    import cv2, io
    from PIL import Image

    out = frame.copy()
    h, w = out.shape[:2]
    for det in detections:
        x1, y1, x2, y2 = det.bbox
        pt1 = (int(x1 * w), int(y1 * h))
        pt2 = (int(x2 * w), int(y2 * h))
        cv2.rectangle(out, pt1, pt2, (220, 50, 50), 2, cv2.LINE_AA)
        label = f"{det.class_name} {det.confidence:.0%}"
        (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
        cv2.rectangle(out, (pt1[0], pt1[1] - lh - 8), (pt1[0] + lw + 4, pt1[1]), (220, 50, 50), -1)
        cv2.putText(out, label, (pt1[0] + 2, pt1[1] - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)

    buf = io.BytesIO()
    Image.fromarray(out).save(buf, format="JPEG", quality=82)
    return buf.getvalue()


def run_harness(args: argparse.Namespace) -> None:
    import yaml

    logger = logging.getLogger("deerhunter.harness")

    print(f"DeerHunter Harness  |  source: {args.video}  |  dry-run: {args.dry_run}")
    if args.fake_deer:
        print("Mode: fake deer detections (no model)")
    elif args.stub_detector:
        print("Mode: stub detector (no detections)")
    elif args.yolo_world:
        print("Mode: YOLOWorld open-vocabulary  (model downloads on first run ~87MB)")
    else:
        print(f"Mode: standard YOLOv8  model={args.model or 'yolov8n.pt'}")
    print()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    threshold = args.confidence or cfg.get("detector", {}).get("default_confidence", 0.40)
    ntfy_cfg = cfg.get("notifications", {})
    stor_cfg = cfg.get("storage", {})

    camera = _make_camera(args)
    detector = _make_detector(args)

    notify.configure(
        ntfy_url=ntfy_cfg.get("ntfy_url", "https://ntfy.sh"),
        topic=ntfy_cfg.get("topic", "deerhunter-harness"),
    )
    record.configure(
        camera=camera,
        clips_dir=stor_cfg.get("clips_dir", "storage/clips"),
        snapshots_dir=stor_cfg.get("snapshots_dir", "storage/snapshots"),
    )

    engine = RulesEngine(args.config)
    engine.register_action("audio", audio.play_audio)
    engine.register_action("notify", notify.send_notification)
    engine.register_action("record", record.record_clip)

    stats = {"frames": 0, "triggers": 0, "deer": 0, "rules": 0}

    try:
        frame_num = 0
        while True:
            frame = camera.capture_frame()
            if frame is None:
                break

            frame_num += 1
            stats["frames"] += 1

            if frame_num % args.trigger_every != 0:
                continue

            stats["triggers"] += 1
            burst = [frame] + [camera.capture_frame()
                                for _ in range(args.burst - 1)]
            stats["frames"] += args.burst - 1

            detections = detector.detect_burst(burst, confidence_threshold=threshold)

            if detections:
                best = max(detections, key=lambda d: d.confidence)
                stats["deer"] += 1
                ts = time.strftime("%H:%M:%S")
                print(f"[{ts}] DEER  conf={best.confidence:.2f}  "
                      f"box=({best.bbox[0]:.2f},{best.bbox[1]:.2f},"
                      f"{best.bbox[2]:.2f},{best.bbox[3]:.2f})  "
                      f"frame={frame_num}")
                fired = engine.evaluate("deer_detected", confidence=best.confidence,
                                        frame=frame, dry_run=args.dry_run)
                if fired:
                    print(f"         rules fired: {fired}")
                stats["rules"] += len(fired)
            else:
                engine.evaluate("motion_detected", confidence=1.0,
                                frame=frame, dry_run=args.dry_run)

    except KeyboardInterrupt:
        print("\nStopped by user")
    finally:
        camera.close()

    print(f"\n{'─'*50}")
    print(f"  Frames     : {stats['frames']}")
    print(f"  Triggers   : {stats['triggers']}")
    print(f"  Deer hits  : {stats['deer']}")
    print(f"  Rules fired: {stats['rules']}")
    print(f"{'─'*50}")


if __name__ == "__main__":
    args = parse_args()
    _setup_logging(args.verbose)
    run_harness(args)
