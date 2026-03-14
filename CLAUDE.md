# CLAUDE.md

## Project Overview
DeerHunter — a solar/battery-powered Raspberry Pi Zero 2W trail camera that detects deer via on-device YOLOv8n TFLite ML, then deters them with audio + push notifications. Rules are configured in `config/rules.yaml` (IFTTT-style trigger/action model). A FastAPI + HTMX web dashboard lets users review events and edit rules over WiFi.

## Repository Layout
```
DeerHunter/
├── config/rules.yaml       # Source of truth for all rules + config
├── src/
│   ├── main.py             # Orchestrator — run this on the Pi
│   ├── harness.py          # macOS testing harness (video file simulator)
│   ├── sensors/
│   │   ├── pir.py          # PIR GPIO interrupt handler
│   │   ├── camera.py       # picamera2 wrapper + StubCamera
│   │   └── video_feed.py   # VideoFeedCamera: OpenCV video file → Camera API
│   ├── detection/detector.py    # YOLOv8n TFLite inference
│   ├── rules/engine.py          # YAML rules parser + action dispatcher
│   ├── actions/{audio,notify,record}.py
│   ├── power/manager.py         # Pi power savings (HDMI off, CPU governor)
│   └── web/app.py               # FastAPI dashboard (port 8080)
├── sounds/                 # .wav deterrent audio files (add your own)
├── storage/                # Event clips + snapshots (gitignored)
└── tests/                  # pytest unit tests
```

## Development Commands

### Run tests (macOS / any machine):
```bash
python -m pytest tests/ -v
```

### Run on Pi (production):
```bash
python src/main.py --config config/rules.yaml
```

### Dry-run with simulated motion (Pi or macOS):
```bash
python src/main.py --stub-camera --stub-detector --fake-deer --dry-run --simulate-motion
```

### macOS testing harness (video file feed):
```bash
# Install OpenCV first:
pip install opencv-python-headless

# Run with fake deer detections on a video file:
python src/harness.py --video test_footage/backyard.mp4 --fake-deer --dry-run

# Real inference (model required):
python src/harness.py --video test_footage/backyard.mp4 --model src/detection/models/yolov8n_int8.tflite

# Live webcam preview:
python src/harness.py --video 0 --fake-deer --preview

# Directory of JPEG images:
python src/harness.py --video test_footage/ --fake-deer --fps 2
```

### Web dashboard (run separately):
```bash
python src/web/app.py
# Open http://localhost:8080  (credentials in config/rules.yaml)
```

### Pi setup:
```bash
sudo bash install.sh
```

## Key Design Decisions
- `StubCamera` / `VideoFeedCamera` / `StubDetector` are drop-in replacements for Pi hardware — same public API, enabling all development + testing on macOS.
- `RulesEngine.evaluate()` accepts `dry_run=True` to log actions without executing them.
- Actions are dispatched in parallel daemon threads to avoid blocking the PIR callback.
- Per-rule cooldowns are tracked in-memory (reset on restart).
- The web server runs as a separate systemd service; `set_camera()` in `web/app.py` connects it to the live camera if running in the same process.

## Hardware (Raspberry Pi Zero 2W)
- PIR sensor on GPIO 17 (BCM). Change with `--gpio-pin`.
- Camera: Pi Camera Module v3 NoIR via CSI.
- Audio: USB audio adapter or I2S MAX98357A → `sounds/*.wav`.
- Power target: 5000mAh LiPo, ~3 days without sun, PIR wake from sleep.
