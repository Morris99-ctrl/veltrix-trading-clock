import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from alert_engine import due_session_alerts  # noqa: E402
from session_engine import load_session_definitions  # noqa: E402


class SessionAlertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (PROJECT_ROOT / "config.json").open("r", encoding="utf-8") as file:
            cls.sessions = load_session_definitions(json.load(file)["sessions"])
        cls.by_key = {session.key: session for session in cls.sessions}

    def settings(self, **changes):
        result = {
            "pre_open_minutes": 15,
            "pre_close_minutes": 10,
            "notify_pre_open": True,
            "notify_open": True,
            "notify_pre_close": True,
            "notify_close": True,
        }
        result.update(changes)
        return result

    def test_london_pre_open_warning_uses_gmt_in_november(self):
        now = datetime(2026, 11, 11, 7, 50, tzinfo=timezone.utc)
        fired = set()
        alerts = due_session_alerts([self.by_key["london"]], now, self.settings(), fired)
        self.assertEqual(len(alerts), 1)
        self.assertIn("LONDON OPEN IN 15 MIN", alerts[0].title)
        self.assertIn("08:00 GMT", alerts[0].message)

    def test_london_exact_open_alert_fires_once(self):
        now = datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc)
        fired = set()
        first = due_session_alerts([self.by_key["london"]], now, self.settings(), fired)
        second = due_session_alerts([self.by_key["london"]], now, self.settings(), fired)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].title, "LONDON SESSION OPENED")
        self.assertEqual(second, [])

    def test_pre_close_warning_uses_session_local_time(self):
        # Tokyo is 17:50 JST here; its 18:00 close is ten minutes away.
        now = datetime(2026, 11, 11, 8, 50, tzinfo=timezone.utc)
        alerts = due_session_alerts(
            [self.by_key["tokyo"]], now, self.settings(), set(),
        )
        self.assertEqual(len(alerts), 1)
        self.assertIn("TOKYO CLOSE IN 10 MIN", alerts[0].title)

    def test_no_preopen_when_disabled(self):
        now = datetime(2026, 11, 11, 7, 50, tzinfo=timezone.utc)
        alerts = due_session_alerts(
            [self.by_key["london"]], now,
            self.settings(notify_pre_open=False), set(),
        )
        self.assertEqual(alerts, [])

    def test_weekend_skips_to_next_valid_session_day(self):
        # Sunday 07:50 UTC should not generate a London pre-open alert.
        now = datetime(2026, 11, 15, 7, 50, tzinfo=timezone.utc)
        alerts = due_session_alerts([self.by_key["london"]], now, self.settings(), set())
        self.assertEqual(alerts, [])


    def test_london_preopen_uses_bst_in_july(self):
        now = datetime(2026, 7, 1, 6, 45, tzinfo=timezone.utc)
        alerts = due_session_alerts([self.by_key["london"]], now, self.settings(), set())
        self.assertEqual(len(alerts), 1)
        self.assertIn("08:00 BST", alerts[0].message)

    def test_sydney_preopen_uses_daylight_time_in_november(self):
        # Sydney opens at 07:00 AEDT, which is 20:00 UTC on the prior date.
        now = datetime(2026, 11, 10, 19, 45, tzinfo=timezone.utc)
        alerts = due_session_alerts([self.by_key["sydney"]], now, self.settings(), set())
        self.assertEqual(len(alerts), 1)
        self.assertIn("07:00 AEDT", alerts[0].message)

    def test_exact_open_can_be_disabled(self):
        now = datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc)
        alerts = due_session_alerts(
            [self.by_key["london"]], now,
            self.settings(notify_open=False), set(),
        )
        self.assertEqual(alerts, [])

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            due_session_alerts([self.by_key["london"]], datetime(2026, 11, 11, 7, 50), self.settings(), set())


if __name__ == "__main__":
    unittest.main()
