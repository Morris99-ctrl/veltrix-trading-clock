from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from session_engine import load_session_definitions  # noqa: E402
from session_intelligence import historical_overlap_report, weekly_session_hours  # noqa: E402
from session_profiles import PROFILE_NAMES, apply_session_profile, validate_session_schedule  # noqa: E402


class SessionIntelligenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (PROJECT_ROOT / "config.json").open("r", encoding="utf-8") as file:
            cls.base_config = json.load(file)["sessions"]
        cls.sessions = load_session_definitions(cls.base_config)

    def test_weekly_hours_match_five_day_default_profile(self):
        result = weekly_session_hours(
            self.sessions, datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
        )
        hours = {item.session_key: item.scheduled_hours for item in result}
        active_days = {item.session_key: item.active_days for item in result}

        self.assertEqual(hours, {
            "sydney": 45.0, "tokyo": 45.0, "london": 45.0, "new_york": 45.0,
        })
        self.assertEqual(set(active_days.values()), {5})

    def test_weekly_hours_change_when_equities_profile_is_applied(self):
        config = apply_session_profile(self.base_config, "Equities Cash")
        sessions = load_session_definitions(config)
        result = weekly_session_hours(
            sessions, datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
        )
        hours = {item.session_key: item.scheduled_hours for item in result}

        self.assertEqual(hours["sydney"], 30.0)
        self.assertEqual(hours["tokyo"], 30.0)
        self.assertEqual(hours["london"], 42.5)
        self.assertEqual(hours["new_york"], 32.5)

    def test_historical_overlap_report_reconstructs_pair_hours(self):
        report = historical_overlap_report(
            self.sessions, datetime(2026, 11, 30, 0, 0, tzinfo=timezone.utc), days=7
        )
        pair_hours = {(left, right): hours for left, right, hours in report.pair_overlap_hours}

        self.assertAlmostEqual(report.total_overlap_hours, 45.0)
        self.assertAlmostEqual(report.average_daily_overlap_hours, 45.0 / 7)
        self.assertAlmostEqual(pair_hours[("SYDNEY", "TOKYO")], 25.0)
        self.assertAlmostEqual(pair_hours[("LONDON", "NEW YORK")], 20.0)
        self.assertEqual(report.busiest_day_hours, 9.0)

    def test_historical_overlap_supports_30_and_90_day_periods(self):
        end = datetime(2026, 11, 30, tzinfo=timezone.utc)
        for days in (30, 90):
            result = historical_overlap_report(self.sessions, end, days=days)
            self.assertEqual(result.days, days)
            self.assertGreater(result.total_overlap_hours, 0)

    def test_historical_overlap_rejects_unsupported_periods_and_naive_time(self):
        end = datetime(2026, 11, 30, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "7, 30 or 90"):
            historical_overlap_report(self.sessions, end, days=14)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            historical_overlap_report(self.sessions, datetime(2026, 11, 30), days=7)

    def test_profile_preserves_session_metadata_and_timezone(self):
        result = apply_session_profile(self.base_config, "Equities Cash")
        by_key = {item["key"]: item for item in result}
        original = {item["key"]: item for item in self.base_config}

        self.assertEqual(by_key["new_york"]["open"], "09:30")
        self.assertEqual(by_key["new_york"]["close"], "16:00")
        self.assertEqual(by_key["new_york"]["timezone"], original["new_york"]["timezone"])
        self.assertEqual(by_key["new_york"]["city"], original["new_york"]["city"])
        self.assertEqual(by_key["new_york"]["weekdays"], [0, 1, 2, 3, 4])

    def test_custom_profile_applies_times_and_weekdays(self):
        custom = {
            "new_york": {"open": "09:30", "close": "13:00", "weekdays": [0, 1, 2, 3]},
        }
        result = apply_session_profile(self.base_config, "Custom", custom)
        by_key = {item["key"]: item for item in result}

        self.assertEqual(by_key["new_york"]["open"], "09:30")
        self.assertEqual(by_key["new_york"]["close"], "13:00")
        self.assertEqual(by_key["new_york"]["weekdays"], [0, 1, 2, 3])
        self.assertEqual(by_key["london"]["weekdays"], [0, 1, 2, 3, 4])

    def test_custom_profile_rejects_empty_weekdays_and_overnight_hours(self):
        with self.assertRaisesRegex(ValueError, "at least one weekday"):
            validate_session_schedule({"open": "08:00", "close": "17:00", "weekdays": []})
        with self.assertRaisesRegex(ValueError, "overnight"):
            validate_session_schedule({"open": "22:00", "close": "06:00", "weekdays": [0]})

    def test_unknown_profile_is_rejected(self):
        self.assertIn("Forex Standard", PROFILE_NAMES)
        with self.assertRaisesRegex(ValueError, "Unknown market-session profile"):
            apply_session_profile(self.base_config, "Crypto Always Open")


if __name__ == "__main__":
    unittest.main()
