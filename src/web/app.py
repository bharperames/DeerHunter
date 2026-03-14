"""
DeerHunter web dashboard — FastAPI + HTMX.

Serves on port 8080. Routes:
  GET  /            → event log
  GET  /live        → live MJPEG stream with detection overlay
  GET  /stream      → raw MJPEG stream (src for <img> tags)
  GET  /snapshot    → single-frame snapshot page
  GET  /rules       → rules editor
  POST /rules       → save rules YAML
  GET  /status      → system status JSON
  GET  /events      → HTMX partial refresh
  GET  /api/events  → JSON event list

HTTP Basic Auth via credentials in rules.yaml.

Run standalone (no Pi needed):
  python3 src/web/app.py --video DeerTest.mov
  python3 src/web/app.py --video DeerTest.mov --yolo-world
"""

import argparse
import io
import logging
import os
import secrets
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import numpy as np
import yaml
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config" / "rules.yaml"
SNAPSHOTS_DIR = BASE_DIR / "storage" / "snapshots"
CLIPS_DIR = BASE_DIR / "storage" / "clips"
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


def _get_credentials():
    cfg = _load_config()
    web = cfg.get("web", {})
    return web.get("username", "admin"), web.get("password", "changeme")


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(application: FastAPI):
    if os.environ.get("DH_VIDEO"):
        _init_camera_and_detector()
    yield


app = FastAPI(title="DeerHunter Dashboard", lifespan=lifespan)
security = HTTPBasic()

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Shared state — injected by main.py or the standalone __main__ block
_camera = None
_detector = None
_stream_lock = threading.Lock()

# Detection event log (in-memory, newest first)
import collections
_detection_events: collections.deque = collections.deque(maxlen=50)
_last_detection_time: float = 0.0
_last_detection_count: int = 0
_DETECTION_COOLDOWN_S: float = 5.0
_detection_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Hardware / system state  (updated by the MJPEG generator on every frame)
# ---------------------------------------------------------------------------
_hw_state: dict = {
    "pir_active": False,
    "pir_level": 0.0,
    "pir_triggers": 0,
    "pir_last_triggered": "—",
    "pipeline": "IDLE",       # IDLE | MOTION | DETECTING | DETECTED
    "last_confidence": None,
}
_hw_lock = threading.Lock()
_PIPELINE_DETECTED_HOLD_S: float = 1.5   # keep DETECTED visible for this long
_pipeline_detected_at: float = 0.0

# ---------------------------------------------------------------------------
# Shared frame cache — one processor thread runs inference; all MJPEG clients
# read the cached JPEG so multiple open tabs don't each trigger detection.
# ---------------------------------------------------------------------------
_frame_cache: dict = {"jpeg": b"", "seq": 0}
_frame_cache_lock = threading.Lock()
_processor_thread: Optional[threading.Thread] = None


def _record_detection(detections: list) -> bool:
    """
    Append to the event log when:
      - a deer is detected AND cooldown has elapsed, OR
      - the deer count in this frame exceeds the previous event's count
        (new deer entered frame — override cooldown).
    Returns True if an event was recorded.
    """
    global _last_detection_time, _last_detection_count
    if not detections:
        return False
    best = max(detections, key=lambda d: d.confidence)
    count = len(detections)
    with _detection_lock:
        now = time.monotonic()
        cooldown_elapsed = (now - _last_detection_time) >= _DETECTION_COOLDOWN_S
        count_increased = count > _last_detection_count
        if not cooldown_elapsed and not count_increased:
            return False
        _last_detection_time = now
        _last_detection_count = count
        _detection_events.appendleft({
            "time": time.strftime("%H:%M:%S"),
            "confidence": round(best.confidence, 2),
            "count": count,
            "bbox": [round(v, 2) for v in best.bbox],
        })
    return True


def set_camera(cam) -> None:
    global _camera
    _camera = cam


def set_detector(det) -> None:
    global _detector
    _detector = det


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def require_auth(credentials: HTTPBasicCredentials = Depends(security)):
    username, password = _get_credentials()
    if not (secrets.compare_digest(credentials.username, username) and
            secrets.compare_digest(credentials.password, password)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials


# ---------------------------------------------------------------------------
# MJPEG stream helpers
# ---------------------------------------------------------------------------
def _frame_to_jpeg(frame: np.ndarray,
                   detections: Optional[list] = None,
                   quality: int = 75) -> bytes:
    """Encode RGB frame to JPEG, optionally drawing detection boxes."""
    import cv2
    from PIL import Image

    out = frame.copy()
    h, w = out.shape[:2]

    if detections:
        for det in detections:
            x1, y1, x2, y2 = det.bbox
            pt1 = (int(x1 * w), int(y1 * h))
            pt2 = (int(x2 * w), int(y2 * h))
            cv2.rectangle(out, pt1, pt2, (220, 50, 50), 2, cv2.LINE_AA)
            label = f"{det.class_name} {det.confidence:.0%}"
            (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            cv2.rectangle(out, (pt1[0], pt1[1] - lh - 8),
                          (pt1[0] + lw + 4, pt1[1]), (220, 50, 50), -1)
            cv2.putText(out, label, (pt1[0] + 2, pt1[1] - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

    buf = io.BytesIO()
    Image.fromarray(out).save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _processor_loop(confidence: float = 0.40) -> None:
    """
    Single background thread: read camera, run detection, encode JPEG, cache.
    All MJPEG clients share this one cached frame — no per-client inference.
    """
    global _pipeline_detected_at
    while True:
        if _camera is None:
            time.sleep(0.2)
            continue

        try:
            frame = _camera.capture_frame()
        except Exception as e:
            logger.warning("Processor: capture error: %s", e)
            time.sleep(0.2)
            continue

        # Update PIR / motion state
        pir_active = False
        if hasattr(_camera, "motion_level"):
            pir_active = _camera.motion_active
            with _hw_lock:
                _hw_state["pir_level"] = _camera.motion_level
                _hw_state["pir_active"] = pir_active

        detections = []
        if _detector is not None:
            with _hw_lock:
                now = time.monotonic()
                if (_hw_state["pipeline"] != "DETECTED" or
                        (now - _pipeline_detected_at) >= _PIPELINE_DETECTED_HOLD_S):
                    _hw_state["pipeline"] = "MOTION" if pir_active else "DETECTING"
            try:
                detections = _detector.detect(frame, confidence_threshold=confidence)
                _record_detection(detections)
            except Exception as e:
                logger.warning("Processor: detection error: %s", e)
            with _hw_lock:
                now = time.monotonic()
                if detections:
                    _hw_state["pipeline"] = "DETECTED"
                    _pipeline_detected_at = now
                    _hw_state["last_confidence"] = round(
                        max(d.confidence for d in detections), 2)
                elif (_hw_state["pipeline"] == "DETECTED" and
                        (now - _pipeline_detected_at) < _PIPELINE_DETECTED_HOLD_S):
                    pass
                elif pir_active:
                    _hw_state["pipeline"] = "MOTION"
                else:
                    _hw_state["pipeline"] = "IDLE"
        else:
            with _hw_lock:
                _hw_state["pipeline"] = "MOTION" if pir_active else "IDLE"

        try:
            jpeg = _frame_to_jpeg(frame, detections)
        except Exception as e:
            logger.warning("Processor: encode error: %s", e)
            continue

        with _frame_cache_lock:
            _frame_cache["jpeg"] = jpeg
            _frame_cache["seq"] += 1


def _start_processor(confidence: float = 0.40) -> None:
    """Start the frame processor thread if it is not already running."""
    global _processor_thread
    if _processor_thread and _processor_thread.is_alive():
        return
    t = threading.Thread(
        target=_processor_loop, args=(confidence,),
        daemon=True, name="dh-frame-processor",
    )
    _processor_thread = t
    t.start()
    logger.info("Frame processor started")


def _mjpeg_generator(confidence: float = 0.40):
    """
    Broadcast MJPEG to clients by reading the shared frame cache.
    No per-client inference — all clients share one processed frame.
    """
    boundary = b"--deerhunter_frame\r\n"
    last_seq = -1
    while True:
        with _frame_cache_lock:
            seq = _frame_cache["seq"]
            jpeg = _frame_cache["jpeg"]
        if jpeg and seq != last_seq:
            last_seq = seq
            yield (
                boundary
                + b"Content-Type: image/jpeg\r\n"
                + f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                + jpeg
                + b"\r\n"
            )
        else:
            time.sleep(0.01)


# ---------------------------------------------------------------------------
# Event helpers
# ---------------------------------------------------------------------------
def _list_events(limit: int = 100) -> list[dict]:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(SNAPSHOTS_DIR.glob("snap_*.jpg"), reverse=True)
    events = []
    for f in files[:limit]:
        ts_str = f.stem.replace("snap_", "")
        try:
            ts = time.strptime(ts_str, "%Y%m%d_%H%M%S")
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", ts)
        except Exception:
            timestamp = ts_str
        events.append({
            "filename": f.name,
            "timestamp": timestamp,
            "url": f"/images/{f.name}",
        })
    return events


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, auth=Depends(require_auth)):
    events = _list_events(50)
    return templates.TemplateResponse("index.html", {
        "request": request, "events": events,
    })


@app.get("/live", response_class=HTMLResponse)
async def live_page(request: Request, auth=Depends(require_auth)):
    return templates.TemplateResponse("live.html", {"request": request})


@app.post("/live/restart")
async def live_restart(auth=Depends(require_auth)):
    """Rewind the video source to the beginning."""
    if _camera is not None and hasattr(_camera, "seek_to_start"):
        _camera.seek_to_start()
    with _detection_lock:
        _detection_events.clear()
        global _last_detection_time, _last_detection_count
        _last_detection_time = 0.0
        _last_detection_count = 0
    with _hw_lock:
        global _pipeline_detected_at
        _hw_state["pir_triggers"] = 0
        _hw_state["pir_last_triggered"] = "—"
        _hw_state["pipeline"] = "IDLE"
        _hw_state["last_confidence"] = None
        _pipeline_detected_at = 0.0
    return Response(status_code=204)


@app.get("/live/detections", response_class=HTMLResponse)
async def live_detections(request: Request, auth=Depends(require_auth)):
    """HTMX partial — detection trigger event list."""
    with _detection_lock:
        events = list(_detection_events)
    return templates.TemplateResponse("partials/detections.html", {
        "request": request,
        "events": events,
    })


@app.get("/stream")
async def mjpeg_stream(
    confidence: float = 0.40,
    auth=Depends(require_auth),
):
    """MJPEG stream with detection overlay. Open in <img src="/stream">."""
    return StreamingResponse(
        _mjpeg_generator(confidence=confidence),
        media_type="multipart/x-mixed-replace; boundary=deerhunter_frame",
    )


@app.get("/events", response_class=HTMLResponse)
async def events_partial(request: Request, auth=Depends(require_auth)):
    events = _list_events(50)
    return templates.TemplateResponse("partials/events.html", {
        "request": request, "events": events,
    })


@app.get("/api/events")
async def api_events(auth=Depends(require_auth)):
    return JSONResponse(_list_events(100))


@app.get("/images/{filename}")
async def serve_image(filename: str, auth=Depends(require_auth)):
    path = SNAPSHOTS_DIR / filename
    if not path.exists() or path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise HTTPException(404)
    return StreamingResponse(open(path, "rb"), media_type="image/jpeg")


@app.get("/snapshot/current")
async def snapshot_current(auth=Depends(require_auth)):
    """Return the latest processed frame JPEG from the shared cache — no extra inference."""
    with _frame_cache_lock:
        jpeg = _frame_cache.get("jpeg")
    if not jpeg:
        raise HTTPException(503, "No frame available yet")
    return Response(content=jpeg, media_type="image/jpeg")


@app.get("/snapshot", response_class=HTMLResponse)
async def snapshot_page(request: Request, auth=Depends(require_auth)):
    return templates.TemplateResponse("snapshot.html", {"request": request})


@app.get("/snapshot/image")
async def snapshot_image(auth=Depends(require_auth)):
    if _camera is None:
        raise HTTPException(503, "Camera not available")
    frame = _camera.capture_frame()
    detections = []
    if _detector is not None:
        cfg = _load_config()
        threshold = cfg.get("detector", {}).get("default_confidence", 0.40)
        detections = _detector.detect(frame, confidence_threshold=threshold)
    try:
        jpeg = _frame_to_jpeg(frame, detections)
        return Response(content=jpeg, media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/rules", response_class=HTMLResponse)
async def rules_page(request: Request, auth=Depends(require_auth)):
    with open(CONFIG_PATH) as f:
        raw = f.read()
    return templates.TemplateResponse("rules.html", {
        "request": request, "rules_yaml": raw, "saved": False, "error": None,
    })


@app.post("/rules", response_class=HTMLResponse)
async def save_rules(request: Request, rules_yaml: str = Form(...),
                     auth=Depends(require_auth)):
    error = None
    saved = False
    try:
        yaml.safe_load(rules_yaml)
        CONFIG_PATH.write_text(rules_yaml)
        saved = True
    except yaml.YAMLError as e:
        error = str(e)
    return templates.TemplateResponse("rules.html", {
        "request": request, "rules_yaml": rules_yaml,
        "saved": saved, "error": error,
    })


@app.get("/status")
async def system_status(auth=Depends(require_auth)):
    uptime_s = None
    try:
        with open("/proc/uptime") as f:
            uptime_s = int(float(f.read().split()[0]))
    except FileNotFoundError:
        pass
    snap_count = len(list(SNAPSHOTS_DIR.glob("snap_*.jpg"))) if SNAPSHOTS_DIR.exists() else 0
    clip_count = len(list(CLIPS_DIR.glob("clip_*.h264"))) if CLIPS_DIR.exists() else 0
    return {
        "uptime_seconds": uptime_s,
        "snapshot_count": snap_count,
        "clip_count": clip_count,
        "camera_available": _camera is not None,
        "detector_available": _detector is not None,
    }


# ---------------------------------------------------------------------------
# Hardware / system state dashboard
# ---------------------------------------------------------------------------
@app.get("/hardware", response_class=HTMLResponse)
async def hardware_page(request: Request, auth=Depends(require_auth)):
    return templates.TemplateResponse("hardware.html", {"request": request})


@app.get("/api/hw", response_class=HTMLResponse)
async def hw_state_partial(request: Request, auth=Depends(require_auth)):
    """HTMX partial — live hardware state panel, polled every 400 ms."""
    with _hw_lock:
        state = dict(_hw_state)

    # Build sparkline SVG points from camera motion history
    sparkline = ""
    history_len = 0
    threshold_pct = 0
    if _camera is not None and hasattr(_camera, "motion_history"):
        hist = _camera.motion_history
        history_len = len(hist)
        # Auto-scale: top of chart = max(recent_history, threshold*4, 0.02)
        # so the threshold line always sits in the lower quarter at minimum.
        threshold = getattr(_camera, "motion_threshold", 0.012)
        peak = max(hist) if hist else 0.0
        scale = max(peak * 1.2, threshold * 4.0, 0.02)
        W, H = 200, 48
        if history_len > 1:
            pts = [
                f"{i / (history_len - 1) * W:.1f},{H - min(1.0, v / scale) * H:.1f}"
                for i, v in enumerate(hist)
            ]
            sparkline = " ".join(pts)
        # Threshold marker position as percent from bottom (within the scale)
        threshold_pct = min(99, int(threshold / scale * 100))

    # Motion VU bar height (0-100%) — same auto-scale as sparkline
    motion_pct = 0
    if _camera is not None and hasattr(_camera, "motion_level"):
        threshold = getattr(_camera, "motion_threshold", 0.012)
        hist = _camera.motion_history
        peak = max(hist) if hist else 0.0
        scale = max(peak * 1.2, threshold * 4.0, 0.02)
        motion_pct = min(100, int(state["pir_level"] / scale * 100))

    return templates.TemplateResponse("partials/hw_state.html", {
        "request": request,
        **state,
        "sparkline": sparkline,
        "history_len": history_len,
        "threshold_pct": threshold_pct,
        "motion_pct": motion_pct,
        "ts": int(time.time()),
    })


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------
def _parse_server_args():
    p = argparse.ArgumentParser(description="DeerHunter web dashboard")
    p.add_argument("--video", default=None,
                   help="Video source for the stream (file path or webcam index)")
    p.add_argument("--yolo-world", action="store_true", default=True)
    p.add_argument("--no-yolo-world", dest="yolo_world", action="store_false")
    p.add_argument("--fake-deer", action="store_true")
    p.add_argument("--stub-detector", action="store_true")
    p.add_argument("--model", default=None)
    p.add_argument("--motion-threshold", type=float, default=None,
                   help="PIR motion threshold (0–1 mean frame diff). "
                        "Auto-detected from video if not set.")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--loop", action="store_true", default=True)
    p.add_argument("--reload", action="store_true",
                   help="Auto-restart server when source files change")
    return p.parse_args()


def _init_camera_and_detector() -> None:
    """
    Initialize camera and detector from environment variables.
    Called at startup (and after every reload) so the globals are always set.
    """
    video = os.environ.get("DH_VIDEO")
    if video:
        try:
            source = int(video)
        except ValueError:
            source = video
        from src.sensors.video_feed import VideoFeedCamera
        threshold_env = os.environ.get("DH_MOTION_THRESHOLD")
        motion_threshold = float(threshold_env) if threshold_env else 0.012
        cam = VideoFeedCamera(source=source, loop=True, realtime=True,
                              motion_threshold=motion_threshold)

        # Register motion callback so PIR trigger count / timestamps update
        def _motion_cb():
            with _hw_lock:
                _hw_state["pir_triggers"] += 1
                _hw_state["pir_last_triggered"] = time.strftime("%H:%M:%S")

        cam.register_motion_callback(_motion_cb)
        set_camera(cam)

    from src.detection.detector import Detector, Detection, DEER_CLASS_ID
    mode = os.environ.get("DH_DETECTOR", "yolo_world")
    if mode == "fake":
        fake = [Detection(DEER_CLASS_ID, "deer", 0.88, (0.2, 0.1, 0.7, 0.9))]
        det = Detector(stub=True, fake_detections=fake)
    elif mode == "stub":
        det = Detector(stub=True)
    else:
        model = os.environ.get("DH_MODEL", "")
        det = Detector(model_path=model, yolo_world=(mode == "yolo_world"))
    set_detector(det)
    _start_processor()


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    sys.path.insert(0, str(BASE_DIR))
    args = _parse_server_args()
    cfg = _load_config()
    web_cfg = cfg.get("web", {})

    # Store config in env vars so the startup event can re-apply them after reload
    if args.video:
        os.environ["DH_VIDEO"] = str(args.video)
    if args.fake_deer:
        os.environ["DH_DETECTOR"] = "fake"
    elif args.stub_detector:
        os.environ["DH_DETECTOR"] = "stub"
    else:
        os.environ["DH_DETECTOR"] = "yolo_world" if args.yolo_world else "standard"
    if args.model:
        os.environ["DH_MODEL"] = args.model
    if args.motion_threshold is not None:
        os.environ["DH_MOTION_THRESHOLD"] = str(args.motion_threshold)

    try:
        uvicorn.run(
            "src.web.app:app" if args.reload else app,
            host=args.host or web_cfg.get("host", "0.0.0.0"),
            port=args.port or web_cfg.get("port", 8080),
            reload=args.reload,
            reload_dirs=[str(BASE_DIR / "src")] if args.reload else None,
            log_level="warning",
        )
    except (KeyboardInterrupt, SystemExit):
        pass
    except BaseException as exc:
        # Silence asyncio cancellation noise produced during Ctrl-C shutdown
        if type(exc).__name__ in ("CancelledError", "TaskWasCancelled"):
            pass
        else:
            raise
