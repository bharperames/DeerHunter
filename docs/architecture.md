# DeerHunter — System Architecture

## 1. System Context

High-level view of the deployed device, the developer's machine, and external services.

```mermaid
flowchart LR
  DEV["💻 MacBook\nDevelopment &\ntesting"]
  PI["🥧 Raspberry Pi Zero 2W\nTrail camera device"]
  NTFY["☁️ ntfy.sh\nPush notification relay"]
  PHONE["📱 Phone / Browser\nAlerts + dashboard"]

  DEV -- "git push\ndeploy" --> PI
  PI -- "HTTP POST\nalert + snapshot" --> NTFY
  NTFY -- "push notification" --> PHONE
  PI -- "HTTP :8080\nweb dashboard" --> PHONE
```

---

## 2. Hardware

Physical components mounted in the weatherproof enclosure.

```mermaid
flowchart TB
  subgraph PWR["Power System"]
    SOLAR["☀️ 6V Solar Panel"]
    LIPO["🔋 5000mAh 18650 LiPo"]
    CHARGER["TP4056 Charger\n+ protection circuit"]
    BOOST["5V Boost Converter\nto Pi USB-C"]
    SOLAR -- "charges" --> CHARGER
    CHARGER -- "maintains" --> LIPO
    LIPO --> BOOST
  end

  subgraph PI["Raspberry Pi Zero 2W"]
    CPU["ARM Cortex-A53 · 512MB RAM\n2.4GHz WiFi · Bluetooth"]
  end

  subgraph PERIPH["Peripherals"]
    PIR["HC-SR501 PIR\nPassive infrared motion sensor\n~50µA standby · 3–7m range\nConnects: GPIO 17 (BCM)"]
    CAM["Pi Camera Module v3 NoIR\nNo IR-cut filter → night vision\n12MP · CSI ribbon cable"]
    SPK["Speaker\nUSB audio adapter or\nI2S MAX98357A amp"]
  end

  BOOST -- "5V" --> CPU
  PIR -- "GPIO interrupt" --> CPU
  CAM -- "CSI" --> CPU
  CPU -- "audio out" --> SPK
```

**Power budget:**
| State | Current | Notes |
|---|---|---|
| Active (inference) | ~300mA @ 5V | Camera + CPU at full speed |
| Idle (PIR polling) | ~15mA | HDMI off, CPU powersave governor |
| Target runtime | ≥3 days | 5000mAh pack without sun |

---

## 3. Core Detection Pipeline

The event flow from hardware interrupt to action dispatch on every motion trigger.

```mermaid
sequenceDiagram
  actor PIR as HC-SR501 PIR
  participant PY_PIR as pir.py
  participant MAIN as main.py
  participant CAM as camera.py
  participant DET as detector.py
  participant ENGINE as engine.py
  participant ACTIONS as actions/

  PIR->>PY_PIR: GPIO rising edge interrupt
  PY_PIR->>MAIN: on_motion() callback
  MAIN->>CAM: capture_burst(n=5, interval=150ms)
  CAM-->>MAIN: [frame₀ … frame₄]  numpy RGB arrays

  loop Each frame
    MAIN->>DET: detect(frame, confidence≥0.70)
    DET-->>MAIN: [Detection(class=deer, conf, bbox)]
  end

  MAIN->>ENGINE: evaluate("deer_detected", best_confidence)
  ENGINE->>ENGINE: Check time_of_day window
  ENGINE->>ENGINE: Check per-rule cooldown timer
  ENGINE->>ENGINE: Check min_confidence threshold

  par Parallel action threads
    ENGINE->>ACTIONS: audio.play_audio(predator_call.wav)
    ENGINE->>ACTIONS: notify.send_notification(+ snapshot)
    ENGINE->>ACTIONS: record.record_clip(30s H264)
  end

  MAIN->>MAIN: re-enter sleep state
```

---

## 4. Rules Engine

Rules are defined in `config/rules.yaml` using an IFTTT-style trigger/action model. The engine re-reads the config on each evaluation, so edits via the web dashboard take effect immediately.

```mermaid
flowchart TD
  YAML["config/rules.yaml\nSource of truth for all behaviour"]

  subgraph TRIGGER["Trigger Conditions (all must pass)"]
    EV["event:\ndeer_detected | motion_detected"]
    TOD["time_of_day:\nHH:MM–HH:MM range\nsupports overnight e.g. 20:00–06:00"]
    CONF["min_confidence:\n0.0–1.0  (YOLOv8 score)"]
    CD["cooldown_seconds:\nper-rule timer\nresets after each fire"]
    COUNT["count override:\nskip cooldown if deer count\nexceeds previous trigger"]
  end

  subgraph ACTIONS["Actions (dispatched in parallel threads)"]
    A_AUDIO["audio\nPlay .wav via pygame or aplay\nConfigurable volume"]
    A_NOTIFY["notify\nPOST to ntfy.sh topic\nOptional JPEG attachment"]
    A_RECORD["record\nSave snapshot + H264 clip\nConfigurable duration"]
  end

  YAML --> TRIGGER
  TRIGGER --> ACTIONS
```

**Example rule:**
```yaml
- name: "Deer daytime deterrent"
  trigger:
    event: deer_detected
    conditions:
      min_confidence: 0.70
      time_of_day: "06:00-20:00"
      cooldown_seconds: 120
  actions:
    - type: audio
      file: predator_call.wav
      volume: 90
    - type: notify
      message: "Deer detected!"
      attach_snapshot: true
    - type: record
      duration_seconds: 30
```

---

## 5. ML Detection

```mermaid
flowchart LR
  subgraph INPUT["Input"]
    FRAME["RGB frame\nnumpy array H×W×3"]
  end

  subgraph BACKENDS["Detector backends (auto-selected)"]
    direction TB
    TF["TFLite INT8\nyolov8n_int8.tflite\n~3MB · ~1–2 FPS on Pi Zero 2W\nTarget: Raspberry Pi"]
    CORAL["Edge TPU delegate\nGoogle Coral USB\nauto-detected if attached\n~10× faster inference"]
    ULTRA["UltralyticsDetector\nyolov8s-worldv2.pt · ~25MB\nYOLOWorld open-vocabulary\nTarget: macOS dev"]
    STUB["StubDetector\nConfigurable fake output\nTarget: unit tests"]
  end

  subgraph OUTPUT["Output"]
    DET["Detection list\nclass_name · confidence\nbbox (x1,y1,x2,y2) normalised"]
  end

  FRAME --> TF & CORAL & ULTRA & STUB
  TF & CORAL & ULTRA & STUB --> DET
```

> **Why YOLOWorld on macOS?**  Standard YOLOv8n is trained on COCO-80 classes which does not include deer. YOLOWorld uses a CLIP text encoder to match the prompt `"deer"` against visual features, enabling zero-shot detection without a custom model. On the Pi the TFLite model can be fine-tuned on a deer dataset if needed.

---

## 6. Web Dashboard

Served by FastAPI + uvicorn on port 8080. All pages use HTTP Basic Auth. The live stream and trigger panel update without full-page reloads.

```mermaid
flowchart LR
  subgraph SERVER["FastAPI  app.py"]
    direction TB
    AUTH["HTTP Basic Auth\ncredentials from rules.yaml"]
    MJPEG_GEN["MJPEG generator\nRuns detector on every frame\nDraws red bounding boxes\nStreams multipart/x-mixed-replace"]
    SNAPSHOT["GET /snapshot/image\nSingle annotated JPEG"]
    DET_API["GET /live/detections\nHTMX partial — trigger event list\n5s cooldown · count-increase override"]
    RESTART["POST /live/restart\nRewind VideoCapture cursor\nClear event log"]
    RULES_API["GET+POST /rules\nRead/write rules.yaml\nYAML validated before save"]
    EVENTS_API["GET /events\nHTMX partial — snapshot log"]
  end

  subgraph PAGES["Browser pages"]
    LIVE_PAGE["/live\nMJPEG stream + trigger panel\nRestart button"]
    EVENTS_PAGE["/ Events\nSnapshot thumbnails + timestamps\nAuto-refreshes every 15s"]
    RULES_PAGE["/rules\nYAML textarea editor\nSave validates before writing"]
    STATUS_PAGE["/status\nSystem JSON — uptime, counts,\ncamera + detector availability"]
  end

  subgraph CAMERA_SRC["Video source"]
    VIDFEED["VideoFeedCamera\nOpenCV VideoCapture\nseek_to_start() on restart"]
    PICAM["picamera2\nLive CSI camera on Pi"]
  end

  AUTH --> MJPEG_GEN & SNAPSHOT & DET_API & RESTART & RULES_API & EVENTS_API
  MJPEG_GEN --> LIVE_PAGE
  DET_API --> LIVE_PAGE
  RESTART --> LIVE_PAGE
  EVENTS_API --> EVENTS_PAGE
  RULES_API --> RULES_PAGE
  SNAPSHOT --> LIVE_PAGE
  VIDFEED --> MJPEG_GEN
  PICAM --> MJPEG_GEN
```

---

## 7. macOS Development & Testing

The entire pipeline runs on a MacBook without any Pi hardware. Hardware classes are replaced by drop-in stubs with identical interfaces.

```mermaid
flowchart TB
  subgraph REAL["Pi hardware classes"]
    R_PIR["pir.py\ngpiozero MotionSensor"]
    R_CAM["camera.py\npicamera2"]
    R_DET["TFLite INT8\ntflite-runtime"]
  end

  subgraph STUB["macOS replacements — same public API"]
    S_PIR["StubMotionSensor\nsimulate_motion() fires callback"]
    S_CAM["StubCamera\nImages from file / directory\nor synthetic grey frames"]
    S_VID["VideoFeedCamera\nOpenCV reads .mov/.mp4\nloops · realtime pacing\nseek_to_start()"]
    S_DET["UltralyticsDetector\nYOLOWorld + CLIP\nzero-shot deer detection"]
    S_STUB["StubDetector\nfake_detections=[ ] list\nfor unit tests"]
  end

  subgraph HARNESS["src/harness.py — CLI test runner"]
    H["Reads video file frame by frame\nSimulates PIR trigger every N frames\nRuns full pipeline: detect → rules → actions\n--dry-run suppresses real actions\nPrints clean detection log + summary"]
  end

  subgraph TESTS["tests/  (pytest · 37 tests)"]
    T_RULES["test_rules.py\nCooldown · time windows\nrule dispatch · dry-run"]
    T_DET["test_detector.py\nStub detections · burst · filtering"]
    T_SENS["test_sensors.py\nPIR callbacks · StubCamera\nframe shapes · directory loading"]
    T_HARNESS["test_harness.py\nSynthetic .mp4 via OpenCV\nfull harness dry-run"]
  end

  R_PIR -.->|"replaced by"| S_PIR
  R_CAM -.->|"replaced by"| S_CAM & S_VID
  R_DET -.->|"replaced by"| S_DET & S_STUB

  S_VID --> HARNESS
  S_DET --> HARNESS
  S_PIR --> TESTS
  S_CAM --> TESTS
  S_STUB --> TESTS
```

---

## 8. Storage Layout

```
storage/             # gitignored — lives only on device
├── snapshots/       # snap_YYYYMMDD_HHMMSS.jpg  (trigger frame JPEGs)
└── clips/           # clip_YYYYMMDD_HHMMSS.h264  (raw H264 video)
```

The web dashboard event log is built by scanning `storage/snapshots/` — no database required. Events rotate when the snapshot count exceeds the limit configured in `rules.yaml`.

---

## Component Reference

### Hardware

| Component | Part | Role |
|---|---|---|
| SBC | Raspberry Pi Zero 2W | Main compute — runs all software, WiFi |
| Camera | Pi Camera v3 NoIR | IR-capable image capture via CSI |
| Motion sensor | HC-SR501 PIR | Hardware interrupt wake from sleep, ~50µA standby |
| Speaker | USB audio adapter + speaker | Plays deterrent audio (.wav files) |
| Battery | 5000mAh 18650 LiPo + TP4056 | Powers device; TP4056 handles charging + protection |
| Solar | 6V panel + boost converter | Trickle-charges battery for multi-day runtime |
| Enclosure | 3D printed PETG | Weatherproof housing for outdoor deployment |

### Software — Core

| Module | Path | Role |
|---|---|---|
| Orchestrator | `src/main.py` | Event loop, wires all components together, handles signals |
| PIR handler | `src/sensors/pir.py` | Wraps gpiozero MotionSensor; thread-safe callback registration |
| Camera | `src/sensors/camera.py` | picamera2 burst capture + H264 recording; StubCamera fallback |
| Detector | `src/detection/detector.py` | TFLite / YOLOWorld / Stub backends behind a unified API |
| Rules engine | `src/rules/engine.py` | Parses rules.yaml; evaluates time/confidence/cooldown; dispatches actions |
| Audio action | `src/actions/audio.py` | pygame primary, aplay fallback |
| Notify action | `src/actions/notify.py` | ntfy.sh HTTP POST with optional JPEG attachment |
| Record action | `src/actions/record.py` | Saves snapshot JPEG + starts H264 clip recording |
| Power manager | `src/power/manager.py` | Disables HDMI, sets CPU powersave governor on startup |

### Software — Web Dashboard

| Module | Path | Role |
|---|---|---|
| FastAPI app | `src/web/app.py` | All routes, MJPEG generator, detection event store |
| Templates | `src/web/templates/` | Jinja2 HTML; HTMX for partial updates without page reloads |
| Stylesheet | `src/web/static/style.css` | Dark theme, responsive two-column live layout |

### Software — macOS Dev

| Module | Path | Role |
|---|---|---|
| Video feed camera | `src/sensors/video_feed.py` | OpenCV VideoCapture; same API as Camera; loops, rewind |
| Harness | `src/harness.py` | CLI pipeline simulator with clean detection output |
| Tests | `tests/` | pytest suite; all 37 tests run without Pi hardware |
