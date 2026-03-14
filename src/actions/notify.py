"""
Push notification action via ntfy.sh (free, self-hostable).

Config keys:
  message          - notification body text
  attach_snapshot  - bool: attach current frame as image

Global ntfy config loaded from rules.yaml:
  notifications.ntfy_url   (default: https://ntfy.sh)
  notifications.topic      (required)
"""

import io
import logging
from typing import Optional

import numpy as np
import requests

logger = logging.getLogger(__name__)

_ntfy_url: str = "https://ntfy.sh"
_ntfy_topic: str = "deerhunter-alerts"


def configure(ntfy_url: str, topic: str) -> None:
    """Called once at startup with values from rules.yaml."""
    global _ntfy_url, _ntfy_topic
    _ntfy_url = ntfy_url.rstrip("/")
    _ntfy_topic = topic


def _frame_to_jpeg(frame: np.ndarray) -> bytes:
    """Convert RGB numpy array to JPEG bytes."""
    from PIL import Image
    img = Image.fromarray(frame)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def send_notification(config: dict) -> None:
    """Action handler: send ntfy push notification."""
    message = config.get("message", "DeerHunter alert")
    attach = config.get("attach_snapshot", False)
    frame: Optional[np.ndarray] = config.get("_frame")

    url = f"{_ntfy_url}/{_ntfy_topic}"
    headers = {
        "Title": "DeerHunter",
        "Priority": "high",
        "Tags": "deer,alert",
    }

    try:
        if attach and frame is not None:
            jpeg = _frame_to_jpeg(frame)
            headers["Filename"] = "snapshot.jpg"
            response = requests.post(
                url,
                data=jpeg,
                headers={**headers, "Message": message, "Content-Type": "image/jpeg"},
                timeout=10,
            )
        else:
            response = requests.post(
                url,
                data=message.encode("utf-8"),
                headers=headers,
                timeout=10,
            )

        if response.ok:
            logger.info("Notification sent to %s/%s", _ntfy_url, _ntfy_topic)
        else:
            logger.error("ntfy returned %d: %s", response.status_code, response.text)

    except requests.RequestException as e:
        logger.error("Failed to send notification: %s", e)
