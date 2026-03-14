# DeerHunter — System Architecture

## 1. System Context

High-level view of the deployed device, the developer's machine, and external services.

```mermaid
flowchart LR
  DEV["💻 MacBook
Development & testing"]
  PI["🥧 Raspberry Pi Zero 2W
Trail camera device"]
  NTFY["☁️ ntfy.sh
Push notification relay"]
  PHONE["📱 Phone / Browser
Alerts + dashboard"]

  DEV -- "git push / deploy" --> PI
  PI -- "HTTP POST alert + snapshot" --> NTFY
  NTFY -- "push notification" --> PHONE
  PI -- "HTTP :8080 web dashboard" --> PHONE
```

---

## 2. Hardware

Physical components mounted in the weatherproof enclosure.

```mermaid
flowchart TB
  subgraph PWR["Power System"]
    SOLAR["☀️ 6V 2W Solar Panel
ETFE laminate"]
    LIPO["🔋 2× 18650 LiPo in parallel
~5000mAh · 3.7V nominal"]
    CHARGER["TP4056 USB-C Charger
+ over-discharge protection"]
    BOOST["5V Boost Converter
output to Pi USB-C"]
    SOLAR -- "charges via 5V USB" --> CHARGER
    CHARGER -- "maintains" --> LIPO
    LIPO --> BOOST
  end

  subgraph PI["Raspberry Pi Zero 2W"]
    CPU["ARM Cortex-A53 · 512MB RAM
2.4GHz WiFi · Bluetooth"]
  end

  subgraph PERIPH["Peripherals"]
    PIR["HC-SR501 PIR
Passive infrared motion sensor
~50µA standby · 3–7m range
GPIO 17 (BCM)"]
    CAM["Pi Camera Module v3 NoIR
No IR-cut filter — night vision
12MP · CSI ribbon cable"]
    SPK["Speaker
I2S MAX98357A amp
or USB audio adapter"]
  end

  BOOST -- "5V" --> CPU
  PIR -- "GPIO interrupt" --> CPU
  CAM -- "CSI" --> CPU
  CPU -- "audio out" --> SPK
```

### Power Budget

**Per-component current draw at 5V:**

| Component | State | Current | Power |
|---|---|---|---|
| Pi Zero 2W — CPU only | Idle, powersave governor | ~80mA | 0.40W |
| Pi Zero 2W — active inference | YOLOv8 TFLite running | ~250mA | 1.25W |
| Pi Camera v3 | Streaming / capturing | ~50mA | 0.25W |
| HC-SR501 PIR | Always on (standby) | ~0.05mA | negligible |
| MAX98357A amp + speaker | Playing audio (50% vol) | ~150mA | 0.75W |
| TP4056 charger circuit | Quiescent | ~3mA | negligible |
| **Idle total** (PIR awake, no inference) | — | **~85mA** | **0.43W** |
| **Active total** (inference + camera) | — | **~300mA** | **1.50W** |
| **Peak total** (inference + camera + audio) | — | **~450mA** | **2.25W** |

**Battery runtime estimates (5000mAh pack, 3.7V → 5V @ ~85% boost efficiency):**

| Scenario | Avg current | Runtime |
|---|---|---|
| Mostly idle, 2 detections/hr (15s active each) | ~95mA | **~47 hours (≈2 days)** |
| Moderate activity, 10 detections/hr | ~140mA | **~32 hours (≈1.3 days)** |
| Continuous inference (stress test) | ~300mA | **~15 hours** |

> Usable capacity ≈ 5000mAh × 3.7V / 5V × 85% efficiency ≈ **3145mAh** at 5V.

**Solar charging:**

| Condition | Panel output | Charge current (after regulation) | Net balance at idle |
|---|---|---|---|
| Full sun (4 peak hours/day) | 6V · 333mA = 2W | ~340mA average into TP4056 | +255mAh/day vs −2280mAh/day consumed → **not enough alone** |
| Full sun (6 peak hours/day, summer) | 6V · 333mA = 2W | ~340mA × 6h = 2040mAh/day | Nearly covers idle consumption |
| Partial overcast | ~80mA effective | ~80mA × 8h = 640mAh/day | Extends runtime by ~7 hours |

> The 6V 2W panel (333mA peak) feeds into the TP4056's 5V USB input via a small buck converter (or used directly if panel Voc ≤ 5.5V). In a typical backyard summer deployment with 5–6 peak sun hours, the panel can sustain near-indefinite operation at idle activity levels. In winter or heavy overcast, the 5000mAh pack provides 2–3 days of buffer.

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
  YAML["config/rules.yaml
Source of truth for all behaviour"]

  subgraph TRIGGER["Trigger Conditions (all must pass)"]
    EV["event:
deer_detected | motion_detected"]
    TOD["time_of_day:
HH:MM–HH:MM range
supports overnight e.g. 20:00–06:00"]
    CONF["min_confidence:
0.0–1.0  (YOLOv8 score)"]
    CD["cooldown_seconds:
per-rule timer
resets after each fire"]
    COUNT["count override:
skip cooldown if deer count
exceeds previous trigger"]
  end

  subgraph ACTIONS["Actions (dispatched in parallel threads)"]
    A_AUDIO["audio
Play .wav via pygame or aplay
Configurable volume"]
    A_NOTIFY["notify
POST to ntfy.sh topic
Optional JPEG attachment"]
    A_RECORD["record
Save snapshot + H264 clip
Configurable duration"]
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
    FRAME["RGB frame
numpy array H×W×3"]
  end

  subgraph BACKENDS["Detector backends (auto-selected)"]
    direction TB
    TF["TFLite INT8
yolov8n_int8.tflite
~3MB · ~1–2 FPS on Pi Zero 2W
Target: Raspberry Pi"]
    CORAL["Edge TPU delegate
Google Coral USB
auto-detected if attached
~10× faster inference"]
    ULTRA["UltralyticsDetector
yolov8s-worldv2.pt · ~25MB
YOLOWorld open-vocabulary
Target: macOS dev"]
    STUB["StubDetector
Configurable fake output
Target: unit tests"]
  end

  subgraph OUTPUT["Output"]
    DET["Detection list
class_name · confidence
bbox (x1,y1,x2,y2) normalised"]
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
    AUTH["HTTP Basic Auth
credentials from rules.yaml"]
    MJPEG_GEN["MJPEG generator
Runs detector on every frame
Draws red bounding boxes
Streams multipart/x-mixed-replace"]
    SNAPSHOT["GET /snapshot/image
Single annotated JPEG"]
    DET_API["GET /live/detections
HTMX partial — trigger event list
5s cooldown · count-increase override"]
    RESTART["POST /live/restart
Rewind VideoCapture cursor
Clear event log"]
    RULES_API["GET+POST /rules
Read/write rules.yaml
YAML validated before save"]
    EVENTS_API["GET /events
HTMX partial — snapshot log"]
  end

  subgraph PAGES["Browser pages"]
    LIVE_PAGE["/live
MJPEG stream + trigger panel
Restart button"]
    EVENTS_PAGE["/ Events
Snapshot thumbnails + timestamps
Auto-refreshes every 15s"]
    RULES_PAGE["/rules
YAML textarea editor
Save validates before writing"]
    STATUS_PAGE["/status
System JSON — uptime, counts,
camera + detector availability"]
  end

  subgraph CAMERA_SRC["Video source"]
    VIDFEED["VideoFeedCamera
OpenCV VideoCapture
seek_to_start() on restart"]
    PICAM["picamera2
Live CSI camera on Pi"]
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
    R_PIR["pir.py
gpiozero MotionSensor"]
    R_CAM["camera.py
picamera2"]
    R_DET["TFLite INT8
tflite-runtime"]
  end

  subgraph STUB["macOS replacements — same public API"]
    S_PIR["StubMotionSensor
simulate_motion() fires callback"]
    S_CAM["StubCamera
Images from file / directory
or synthetic grey frames"]
    S_VID["VideoFeedCamera
OpenCV reads .mov/.mp4
loops · realtime pacing
seek_to_start()"]
    S_DET["UltralyticsDetector
YOLOWorld + CLIP
zero-shot deer detection"]
    S_STUB["StubDetector
fake_detections=[ ] list
for unit tests"]
  end

  subgraph HARNESS["src/harness.py — CLI test runner"]
    H["Reads video file frame by frame
Simulates PIR trigger every N frames
Runs full pipeline: detect → rules → actions
--dry-run suppresses real actions
Prints clean detection log + summary"]
  end

  subgraph TESTS["tests/  (pytest · 37 tests)"]
    T_RULES["test_rules.py
Cooldown · time windows
rule dispatch · dry-run"]
    T_DET["test_detector.py
Stub detections · burst · filtering"]
    T_SENS["test_sensors.py
PIR callbacks · StubCamera
frame shapes · directory loading"]
    T_HARNESS["test_harness.py
Synthetic .mp4 via OpenCV
full harness dry-run"]
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

## Bill of Materials

Estimated prices as of early 2026. Links are representative — parts are available from multiple vendors.

| # | Component | Part / SKU | Vendor | Unit Price |
|---|---|---|---|---|
| 1 | SBC | Raspberry Pi Zero 2W | PiShop.us | $17.25 |
| 2 | Camera | Pi Camera Module v3 NoIR — Adafruit #5660 | Adafruit | $25.00 |
| 3 | Motion sensor | HC-SR501 PIR sensor | PiShop.us | $3.95 |
| 4 | Amplifier | MAX98357A I2S Class D Amp breakout — Adafruit #3006 | Adafruit | $5.95 |
| 5 | Speaker | 3W 8Ω mini speaker, 40mm — CQRobot | Amazon | $3.99 |
| 6 | Cells | 2× Samsung 35E 18650 3500mAh (series = 7000mAh @ 3.7V) | IMR Batteries | $10.00 |
| 7 | Battery holder | 2S 18650 holder with leads | Amazon | $2.00 |
| 8 | Charger / protection | TP4056 USB-C 1A LiPo charger + DW01 protection | Addicore | $1.80 |
| 9 | Boost converter | 5V 2A MT3608 boost module | Amazon | $1.50 |
| 10 | Solar panel | 6V 2W ETFE solar panel — Adafruit #5366 | Adafruit | $20.95 |
| 11 | CSI cable | 15-pin 30cm FFC ribbon for Pi Zero | Arducam / Amazon | $4.00 |
| 12 | USB-C cable | Short right-angle USB-C (Pi power) | Amazon | $3.50 |
| 13 | Power switch | Rocker switch SPST — SparkFun COM-11138 | SparkFun | $0.75 |
| 14 | Enclosure | 3D printed PETG (≈200g) — Hatchbox 1kg spool | Amazon | $5.20 |
| 15 | Misc | Jumper wires, heat-shrink, M2.5 screws | — | ~$3.00 |
| | | | **Total** | **~$109** |

> **Notes:**
> - The Pi Camera v3 NoIR has no IR-cut filter, enabling night vision with a cheap IR illuminator. The standard v3 (with IR cut) is ~$5 less but loses night capability.
> - Two 18650 cells in parallel (not series) gives ~7000mAh at 3.7V, boosted to 5V. This exceeds the 3-day runtime target without sun.
> - The solar panel's 6V Voc feeds the TP4056's USB-C input directly when panel voltage stays ≤ 5.5V (typical with a Schottky diode drop) or via a small LDO/buck.
> - Optional upgrade: Google Coral USB Accelerator (~$25, Coral store) brings inference from ~1–2 FPS to ~15–20 FPS on the Pi Zero 2W.

---

## Component Reference

### Hardware

| Component | Part | Role |
|---|---|---|
| SBC | Raspberry Pi Zero 2W | Main compute — runs all software, WiFi |
| Camera | Pi Camera v3 NoIR | IR-capable image capture via CSI |
| Motion sensor | HC-SR501 PIR | Hardware interrupt wake from sleep, ~50µA standby |
| Amplifier + speaker | MAX98357A + 3W speaker | Plays deterrent audio (.wav files) |
| Battery | 2× 18650 LiPo + TP4056 | Powers device; TP4056 handles charging + protection |
| Solar | 6V 2W ETFE panel + boost | Trickle-charges battery for extended runtime |
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
