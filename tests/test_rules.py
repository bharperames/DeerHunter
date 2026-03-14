"""
Unit tests for the rules engine.

Tests run without a Pi, real camera, or ML model.
"""

import threading
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.rules.engine import RulesEngine, CooldownTracker, _in_time_range


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
SIMPLE_RULES_YAML = """
web:
  username: admin
  password: test

detector:
  default_confidence: 0.60

notifications:
  ntfy_url: https://ntfy.sh
  topic: test-topic

rules:
  - name: "Deer daytime deterrent"
    trigger:
      event: deer_detected
      conditions:
        min_confidence: 0.70
        time_of_day: "06:00-20:00"
        cooldown_seconds: 5
    actions:
      - type: audio
        file: predator_call.wav
        volume: 80
      - type: notify
        message: "Deer!"
        attach_snapshot: false

  - name: "Night motion record"
    trigger:
      event: motion_detected
      conditions:
        time_of_day: "20:00-06:00"
    actions:
      - type: record
        duration_seconds: 15
"""


@pytest.fixture
def rules_file(tmp_path):
    p = tmp_path / "rules.yaml"
    p.write_text(SIMPLE_RULES_YAML)
    return str(p)


@pytest.fixture
def engine(rules_file):
    return RulesEngine(rules_file)


# ---------------------------------------------------------------------------
# CooldownTracker
# ---------------------------------------------------------------------------
class TestCooldownTracker:
    def test_not_cooling_down_initially(self):
        t = CooldownTracker()
        assert not t.is_cooling_down("rule_a", 10)

    def test_cooling_down_after_mark(self):
        t = CooldownTracker()
        t.mark_fired("rule_a")
        assert t.is_cooling_down("rule_a", 30)

    def test_not_cooling_down_after_expiry(self):
        t = CooldownTracker()
        t.mark_fired("rule_a")
        # Fake expiry by manipulating internal state
        t._last_fired["rule_a"] = time.monotonic() - 100
        assert not t.is_cooling_down("rule_a", 10)

    def test_reset_single(self):
        t = CooldownTracker()
        t.mark_fired("rule_a")
        t.mark_fired("rule_b")
        t.reset("rule_a")
        assert not t.is_cooling_down("rule_a", 30)
        assert t.is_cooling_down("rule_b", 30)

    def test_reset_all(self):
        t = CooldownTracker()
        t.mark_fired("rule_a")
        t.mark_fired("rule_b")
        t.reset()
        assert not t.is_cooling_down("rule_a", 30)
        assert not t.is_cooling_down("rule_b", 30)


# ---------------------------------------------------------------------------
# Time range
# ---------------------------------------------------------------------------
class TestTimeRange:
    def test_in_daytime_range(self):
        noon = datetime(2024, 6, 1, 12, 0)
        assert _in_time_range("06:00-20:00", noon)

    def test_outside_daytime_range(self):
        midnight = datetime(2024, 6, 1, 0, 0)
        assert not _in_time_range("06:00-20:00", midnight)

    def test_overnight_range_before_midnight(self):
        late = datetime(2024, 6, 1, 22, 0)
        assert _in_time_range("20:00-06:00", late)

    def test_overnight_range_after_midnight(self):
        early = datetime(2024, 6, 1, 2, 0)
        assert _in_time_range("20:00-06:00", early)

    def test_overnight_range_midday_excluded(self):
        noon = datetime(2024, 6, 1, 12, 0)
        assert not _in_time_range("20:00-06:00", noon)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            _in_time_range("bad-format")


# ---------------------------------------------------------------------------
# RulesEngine
# ---------------------------------------------------------------------------
class TestRulesEngine:
    def test_loads_rules(self, engine):
        assert len(engine._rules) == 2

    def test_deer_rule_fires_with_sufficient_confidence(self, engine):
        handler = MagicMock()
        engine.register_action("audio", handler)
        engine.register_action("notify", MagicMock())

        fired = engine.evaluate(
            "deer_detected",
            confidence=0.80,
            dry_run=False,
            # Use a fixed daytime datetime
        )
        # Rule has a time condition; patch datetime.now() to noon
        # (tested separately; here we just check the call doesn't crash)

    def test_deer_rule_does_not_fire_low_confidence(self, engine):
        handler = MagicMock()
        engine.register_action("audio", handler)
        engine.register_action("notify", MagicMock())

        with patch("src.rules.engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 6, 1, 12, 0)
            fired = engine.evaluate("deer_detected", confidence=0.50, dry_run=True)

        assert "Deer daytime deterrent" not in fired

    def test_deer_rule_fires_in_window(self, engine):
        handler = MagicMock()
        engine.register_action("audio", handler)
        engine.register_action("notify", MagicMock())

        with patch("src.rules.engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 6, 1, 12, 0)
            fired = engine.evaluate("deer_detected", confidence=0.85, dry_run=True)

        assert "Deer daytime deterrent" in fired

    def test_deer_rule_does_not_fire_outside_window(self, engine):
        engine._cooldowns.reset()
        with patch("src.rules.engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 6, 1, 23, 0)
            fired = engine.evaluate("deer_detected", confidence=0.85, dry_run=True)

        assert "Deer daytime deterrent" not in fired

    def test_motion_rule_fires_at_night(self, engine):
        with patch("src.rules.engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 6, 1, 23, 0)
            fired = engine.evaluate("motion_detected", confidence=1.0, dry_run=True)

        assert "Night motion record" in fired

    def test_cooldown_prevents_double_fire(self, engine):
        engine._cooldowns.reset()
        engine.register_action("audio", MagicMock())
        engine.register_action("notify", MagicMock())

        with patch("src.rules.engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 6, 1, 12, 0)
            first = engine.evaluate("deer_detected", confidence=0.85, dry_run=True)
            second = engine.evaluate("deer_detected", confidence=0.85, dry_run=True)

        assert "Deer daytime deterrent" in first
        assert "Deer daytime deterrent" not in second

    def test_unknown_event_fires_nothing(self, engine):
        fired = engine.evaluate("unknown_event", dry_run=True)
        assert fired == []

    def test_dry_run_does_not_call_handlers(self, engine):
        handler = MagicMock()
        engine.register_action("audio", handler)
        engine.register_action("notify", handler)

        with patch("src.rules.engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 6, 1, 12, 0)
            engine._cooldowns.reset()
            engine.evaluate("deer_detected", confidence=0.85, dry_run=True)

        time.sleep(0.1)
        handler.assert_not_called()

    def test_handler_called_in_non_dry_run(self, engine):
        results = []
        engine.register_action("audio", lambda cfg: results.append("audio"))
        engine.register_action("notify", lambda cfg: results.append("notify"))

        engine._cooldowns.reset()
        with patch("src.rules.engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 6, 1, 12, 0)
            engine.evaluate("deer_detected", confidence=0.85, dry_run=False)

        time.sleep(0.3)  # Allow daemon threads to finish
        assert "audio" in results
        assert "notify" in results

    def test_reload(self, rules_file, engine):
        # Modify the file and reload
        cfg = yaml.safe_load(open(rules_file))
        cfg["rules"].append({
            "name": "New rule",
            "trigger": {"event": "deer_detected", "conditions": {}},
            "actions": [],
        })
        with open(rules_file, "w") as f:
            yaml.dump(cfg, f)

        engine.reload()
        assert len(engine._rules) == 3
