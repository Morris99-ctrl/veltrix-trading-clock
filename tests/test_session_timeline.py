from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from session_engine import load_session_definitions  # noqa: E402
from session_timeline import build_session_timeline  # noqa: E402


class SessionTimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (PROJECT_ROOT / "config.json").open("r", encoding="utf-8") as file:
            cls.sessions = load_session_definitions(json.load(file)["sessions"])

    def test_timeline_is_exactly_24_hours_and_utc_aligned(self):
        start = datetime(2026, 11, 23, 0, 0, tzinfo=timezone.utc)
        result = build_session_timeline(self.sessions, start)

        self.assertEqual(result.starts_at, start)
        self.assertEqual((result.ends_at - result.starts_at).total_seconds(), 86_400)
        self.assertTrue(all(item.starts_at.tzinfo == timezone.utc for item in result.windows))

    def test_default_weekday_schedule_has_tokyo_sydney_and_london_new_york_overlaps(self):
        start = datetime(2026, 11, 23, 0, 0, tzinfo=timezone.utc)
        result = build_session_timeline(self.sessions, start)

        overlaps = {(item.session_keys, item.starts_at.hour, item.ends_at.hour) for item in result.overlaps}
        self.assertIn((("sydney", "tokyo"), 0, 5), overlaps)
        self.assertIn((("london", "new_york"), 13, 17), overlaps)

    def test_weekend_has_no_weekday_session_windows(self):
        start = datetime(2026, 11, 21, 0, 0, tzinfo=timezone.utc)
        result = build_session_timeline(self.sessions, start)

        self.assertEqual(result.windows, ())
        self.assertEqual(result.overlaps, ())

    def test_london_window_shifts_by_one_utc_hour_across_bst_and_gmt(self):
        london = [item for item in self.sessions if item.key == "london"]
        summer = build_session_timeline(
            london, datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
        )
        winter = build_session_timeline(
            london, datetime(2026, 11, 11, 0, 0, tzinfo=timezone.utc)
        )

        self.assertEqual(
            next(item for item in summer.windows if item.session_key == "london").starts_at.hour, 7
        )
        self.assertEqual(
            next(item for item in winter.windows if item.session_key == "london").starts_at.hour, 8
        )

    def test_naive_start_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            build_session_timeline(self.sessions, datetime(2026, 11, 23))

    def test_unsupported_overnight_schedule_is_rejected(self):
        from session_engine import SessionDefinition
        from datetime import time

        overnight = SessionDefinition(
            "test", "TEST", "Test City", "XX", "UTC",
            time(22), time(6), (0, 1, 2, 3, 4),
        )
        with self.assertRaisesRegex(ValueError, "overnight"):
            build_session_timeline([overnight], datetime(2026, 11, 23, tzinfo=timezone.utc))

    def test_timeline_range_is_validated(self):
        start = datetime(2026, 11, 23, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "between 1 and 168"):
            build_session_timeline(self.sessions, start, hours=0)


if __name__ == "__main__":
    unittest.main()
