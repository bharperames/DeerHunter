#!/bin/bash
# DeerHunter install script — runs on a fresh Raspberry Pi OS Lite (64-bit)
# Usage: sudo bash install.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_URL="https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8n_saved_model.tar.gz"
MODEL_DIR="$REPO_DIR/src/detection/models"

echo "=== DeerHunter Setup ==="
echo "Working directory: $REPO_DIR"

# ---------------------------------------------------------------------------
# System packages
# ---------------------------------------------------------------------------
echo "[1/6] Installing system packages..."
apt-get update -q
apt-get install -y -q \
  python3-pip python3-venv python3-numpy \
  python3-picamera2 \
  python3-gpiozero \
  libcamera-apps \
  alsa-utils \
  ffmpeg \
  cpufrequtils \
  git

# ---------------------------------------------------------------------------
# Python virtual environment
# ---------------------------------------------------------------------------
echo "[2/6] Creating Python virtual environment..."
python3 -m venv --system-site-packages "$REPO_DIR/.venv"
source "$REPO_DIR/.venv/bin/activate"

pip install --upgrade pip -q
pip install -r "$REPO_DIR/requirements.txt" -q

# ---------------------------------------------------------------------------
# Download TFLite model
# ---------------------------------------------------------------------------
echo "[3/6] Downloading YOLOv8n INT8 TFLite model..."
mkdir -p "$MODEL_DIR"

# Export YOLOv8n to TFLite INT8 using ultralytics CLI
# This requires ~500MB download on first run
python3 - <<'EOF'
from pathlib import Path
import sys

model_path = Path("src/detection/models/yolov8n_int8.tflite")
if model_path.exists():
    print(f"Model already exists: {model_path}")
    sys.exit(0)

try:
    from ultralytics import YOLO
    print("Exporting YOLOv8n to TFLite INT8...")
    model = YOLO("yolov8n.pt")
    model.export(format="tflite", int8=True, imgsz=640)
    # Ultralytics exports to yolov8n_saved_model/yolov8n_int8.tflite
    import shutil, glob
    tflite_files = glob.glob("yolov8n_saved_model/*.tflite")
    if tflite_files:
        shutil.copy(tflite_files[-1], str(model_path))
        print(f"Model saved to {model_path}")
    else:
        print("Warning: could not find exported .tflite file")
except ImportError:
    print("ultralytics not installed — skipping model export")
    print("Manually place yolov8n_int8.tflite in src/detection/models/")
EOF

# ---------------------------------------------------------------------------
# Storage directories
# ---------------------------------------------------------------------------
echo "[4/6] Creating storage directories..."
mkdir -p "$REPO_DIR/storage/clips"
mkdir -p "$REPO_DIR/storage/snapshots"
mkdir -p "$REPO_DIR/sounds"

# ---------------------------------------------------------------------------
# systemd services
# ---------------------------------------------------------------------------
echo "[5/6] Installing systemd services..."

# Main detection service
cat > /etc/systemd/system/deerhunter.service <<UNIT
[Unit]
Description=DeerHunter deer detection service
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=$REPO_DIR
ExecStart=$REPO_DIR/.venv/bin/python src/main.py --config config/rules.yaml
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

# Web dashboard service
cat > /etc/systemd/system/deerhunter-web.service <<UNIT
[Unit]
Description=DeerHunter web dashboard
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=$REPO_DIR
ExecStart=$REPO_DIR/.venv/bin/python src/web/app.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable deerhunter.service
systemctl enable deerhunter-web.service

echo "Services installed. Start with:"
echo "  sudo systemctl start deerhunter deerhunter-web"

# ---------------------------------------------------------------------------
# Camera interface
# ---------------------------------------------------------------------------
echo "[6/6] Enabling camera interface..."
if command -v raspi-config &>/dev/null; then
    raspi-config nonint do_camera 0
    echo "Camera interface enabled."
else
    echo "raspi-config not found — enable camera manually in raspi-config."
fi

echo ""
echo "=== Installation complete ==="
echo "Edit config/rules.yaml to set your ntfy.sh topic and dashboard password."
echo "Then run: sudo systemctl start deerhunter deerhunter-web"
echo "Dashboard: http://$(hostname -I | awk '{print $1}'):8080"
