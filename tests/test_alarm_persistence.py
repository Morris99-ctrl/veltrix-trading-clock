import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from alarm_persistence import load_alarm_state, restore_alarm_state, save_alarm_state


class AlarmPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.zone = ZoneInfo("Africa/Nairobi")
        self.now = datetime(2026, 11, 21, 10, 0, tzinfo=self.zone)

    def test_future_alarm_is_restored_with_its_state(self):
        deadline = self.now + timedelta(hours=2)
        result = restore_alarm_state(
            {"state": "snoozed", "alarm_datetime": deadline.isoformat()},
            self.zone,
            now=self.now,
        )
        self.assertEqual(result.state, "snoozed")
        self.assertEqual(result.alarm_datetime, deadline)
        self.assertIsNone(result.warning)

    def test_past_alarm_is_reported_and_not_replayed(self):
        result = restore_alarm_state(
            {"state": "scheduled", "alarm_datetime": (self.now - timedelta(minutes=1)).isoformat()},
            self.zone,
            now=self.now,
        )
        self.assertEqual(result.state, "idle")
        self.assertIsNone(result.alarm_datetime)
        self.assertTrue(result.clear_saved_state)
        self.assertIn("Missed alarm", result.warning)

    def test_alarm_state_round_trip_and_clear(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "alarm_state.json"
            deadline = self.now + timedelta(hours=1)

            save_alarm_state(path, "scheduled", deadline)
            restored = load_alarm_state(path, self.zone, now=self.now)
            self.assertEqual(restored.state, "scheduled")
            self.assertEqual(restored.alarm_datetime, deadline)

            save_alarm_state(path, "idle", None)
            self.assertEqual(load_alarm_state(path, self.zone, now=self.now).state, "idle")

    def test_malformed_alarm_is_reported_without_overwriting_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "alarm_state.json"
            path.write_text("{", encoding="utf-8")

            result = load_alarm_state(path, self.zone)

            self.assertIn("invalid JSON", result.warning)
            self.assertEqual(path.read_text(encoding="utf-8"), "{")

    def test_non_string_alarm_state_is_reported(self):
        result = restore_alarm_state({"state": []}, self.zone, now=self.now)

        self.assertIn("state is invalid", result.warning)


if __name__ == "__main__":
    unittest.main()
