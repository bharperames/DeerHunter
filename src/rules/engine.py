"""
Rules engine: parses rules.yaml and evaluates trigger/action dispatch.

Supports events: deer_detected, motion_detected
Conditions: min_confidence, time_of_day, cooldown_seconds
Actions: audio, notify, record
"""

import logging
import re
import threading
import time
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

logger = logging.getLogger(__name__)


class CooldownTracker:
    """Thread-safe per-rule cooldown timer."""

    def __init__(self):
        self._last_fired: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_cooling_down(self, rule_name: str, cooldown_s: float) -> bool:
        with self._lock:
            if rule_name not in self._last_fired:
                return False
            return (time.monotonic() - self._last_fired[rule_name]) < cooldown_s

    def mark_fired(self, rule_name: str) -> None:
        with self._lock:
            self._last_fired[rule_name] = time.monotonic()

    def reset(self, rule_name: Optional[str] = None) -> None:
        with self._lock:
            if rule_name:
                self._last_fired.pop(rule_name, None)
            else:
                self._last_fired.clear()


def _parse_time_range(spec: str) -> tuple[dtime, dtime]:
    """
    Parse "HH:MM-HH:MM" into (start, end) time objects.
    Supports overnight ranges like "20:00-06:00".
    """
    m = re.fullmatch(r"(\d{2}:\d{2})-(\d{2}:\d{2})", spec.strip())
    if not m:
        raise ValueError(f"Invalid time_of_day format: {spec!r}. Expected HH:MM-HH:MM")
    start = dtime.fromisoformat(m.group(1))
    end = dtime.fromisoformat(m.group(2))
    return start, end


def _in_time_range(spec: str, now: Optional[datetime] = None) -> bool:
    """Return True if the current time falls within the given HH:MM-HH:MM range."""
    if now is None:
        now = datetime.now()
    current = now.time().replace(second=0, microsecond=0)
    start, end = _parse_time_range(spec)

    if start <= end:
        return start <= current <= end
    else:
        # Overnight: e.g. 20:00-06:00
        return current >= start or current <= end


class RulesEngine:
    """
    Loads rules from YAML, evaluates conditions on events, and calls action handlers.

    Action handlers are registered externally:
        engine.register_action("audio", audio_handler_fn)
        engine.register_action("notify", notify_handler_fn)
        engine.register_action("record", record_handler_fn)

    Usage:
        engine.evaluate("deer_detected", confidence=0.85, frame=np.array(...))
        engine.evaluate("motion_detected")
    """

    def __init__(self, config_path: str):
        self._config_path = config_path
        self._rules: list[dict] = []
        self._action_handlers: dict[str, Callable] = {}
        self._cooldowns = CooldownTracker()
        self.reload()

    def reload(self) -> None:
        """Reload rules from YAML without restarting."""
        path = Path(self._config_path)
        if not path.exists():
            logger.error("Config file not found: %s", self._config_path)
            return

        with open(path) as f:
            config = yaml.safe_load(f)

        self._rules = config.get("rules", [])
        self._full_config = config
        logger.info("Loaded %d rules from %s", len(self._rules), self._config_path)

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._full_config.get(key, default)

    def register_action(self, action_type: str, handler: Callable) -> None:
        """Register a handler function for a given action type."""
        self._action_handlers[action_type] = handler
        logger.debug("Registered handler for action type: %s", action_type)

    def evaluate(self, event: str, confidence: float = 1.0,
                 frame=None, dry_run: bool = False) -> list[str]:
        """
        Evaluate all rules against the event. Returns list of fired rule names.
        Dispatches matching actions in parallel threads.
        """
        fired = []
        now = datetime.now()

        for rule in self._rules:
            name = rule.get("name", "<unnamed>")
            trigger = rule.get("trigger", {})
            conditions = trigger.get("conditions", {})

            # Check event type
            if trigger.get("event") != event:
                continue

            # Check confidence
            min_conf = conditions.get("min_confidence", 0.0)
            if confidence < min_conf:
                logger.debug("Rule %r skipped: confidence %.2f < %.2f",
                             name, confidence, min_conf)
                continue

            # Check time of day
            tod = conditions.get("time_of_day")
            if tod and not _in_time_range(tod, now):
                logger.debug("Rule %r skipped: outside time window %s", name, tod)
                continue

            # Check cooldown
            cooldown_s = conditions.get("cooldown_seconds", 0)
            if cooldown_s and self._cooldowns.is_cooling_down(name, cooldown_s):
                logger.debug("Rule %r skipped: in cooldown (%ds)", name, cooldown_s)
                continue

            logger.info("Rule %r FIRED (event=%s, confidence=%.2f)", name, event, confidence)
            self._cooldowns.mark_fired(name)
            fired.append(name)

            # Dispatch actions
            actions = rule.get("actions", [])
            threads = []
            for action in actions:
                action_type = action.get("type")
                handler = self._action_handlers.get(action_type)

                if handler is None:
                    logger.warning("No handler for action type %r in rule %r",
                                   action_type, name)
                    continue

                if dry_run:
                    logger.info("[dry-run] Would execute action: %s %s",
                                action_type, action)
                    continue

                # Inject frame into action config if relevant
                action_config = dict(action)
                if frame is not None:
                    action_config["_frame"] = frame

                t = threading.Thread(
                    target=self._run_action,
                    args=(handler, action_config, name, action_type),
                    daemon=True,
                )
                t.start()
                threads.append(t)

        return fired

    def _run_action(self, handler: Callable, config: dict,
                    rule_name: str, action_type: str) -> None:
        try:
            handler(config)
        except Exception:
            logger.exception("Action %r failed in rule %r", action_type, rule_name)
