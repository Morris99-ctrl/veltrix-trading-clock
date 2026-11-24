from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from market_watch import (
    FX_REFERENCE_PAIRS,
    fx_reference_week_label,
    fx_reference_week_state,
)


class FXReferenceWeekTests(unittest.TestCase):
    def test_watchlist_contains_28_unique_pairs(self):
        self.assertEqual(len(FX_REFERENCE_PAIRS), 28)
        self.assertEqual(len(set(FX_REFERENCE_PAIRS)), 28)
        self.assertIn("EURUSD", FX_REFERENCE_PAIRS)
        self.assertIn("USDJPY", FX_REFERENCE_PAIRS)
        self.assertIn("EURGBP", FX_REFERENCE_PAIRS)

    def test_monday_is_open_until_friday_17_new_york(self):
        now = datetime(2026, 11, 23, 9, 0, tzinfo=ZoneInfo("America/New_York"))
        state = fx_reference_week_state(now)
        self.assertTrue(state.is_open)
        self.assertEqual(state.next_transition_at, datetime(2026, 11, 27, 17, 0, tzinfo=ZoneInfo("America/New_York")))
        self.assertEqual(state.transition_kind, "CLOSE")

    def test_friday_before_close_is_open(self):
        now = datetime(2026, 11, 27, 16, 30, tzinfo=ZoneInfo("America/New_York"))
        state = fx_reference_week_state(now)
        self.assertTrue(state.is_open)
        self.assertEqual(state.seconds_to_transition, 1800)

    def test_friday_at_close_is_closed_until_sunday(self):
        now = datetime(2026, 11, 27, 17, 0, tzinfo=ZoneInfo("America/New_York"))
        state = fx_reference_week_state(now)
        self.assertFalse(state.is_open)
        self.assertEqual(state.next_transition_at, datetime(2026, 11, 29, 17, 0, tzinfo=ZoneInfo("America/New_York")))
        self.assertEqual(state.transition_kind, "OPEN")

    def test_saturday_is_closed_and_counts_down_to_sunday_open(self):
        now = datetime(2026, 11, 28, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        state = fx_reference_week_state(now)
        self.assertFalse(state.is_open)
        self.assertEqual(state.seconds_to_transition, 29 * 3600)

    def test_sunday_before_open_is_closed(self):
        now = datetime(2026, 11, 29, 16, 59, tzinfo=ZoneInfo("America/New_York"))
        state = fx_reference_week_state(now)
        self.assertFalse(state.is_open)
        self.assertEqual(state.seconds_to_transition, 60)

    def test_sunday_at_open_is_open(self):
        now = datetime(2026, 11, 29, 17, 0, tzinfo=ZoneInfo("America/New_York"))
        state = fx_reference_week_state(now)
        self.assertTrue(state.is_open)
        self.assertEqual(state.transition_kind, "CLOSE")

    def test_dst_boundary_is_calculated_in_new_york_zone(self):
        winter = fx_reference_week_state(datetime(2026, 11, 23, 15, 0, tzinfo=ZoneInfo("UTC")))
        summer = fx_reference_week_state(datetime(2026, 7, 6, 13, 0, tzinfo=ZoneInfo("UTC")))
        self.assertEqual(winter.next_transition_at.utcoffset().total_seconds(), -5 * 3600)
        self.assertEqual(summer.next_transition_at.utcoffset().total_seconds(), -4 * 3600)

    def test_spring_dst_transition_uses_real_elapsed_seconds(self):
        now = datetime(2026, 3, 7, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        state = fx_reference_week_state(now)
        self.assertEqual(state.next_transition_at, datetime(2026, 3, 8, 17, 0, tzinfo=ZoneInfo("America/New_York")))
        self.assertEqual(state.seconds_to_transition, 28 * 3600)

    def test_autumn_dst_transition_uses_real_elapsed_seconds(self):
        now = datetime(2026, 10, 31, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        state = fx_reference_week_state(now)
        self.assertEqual(state.seconds_to_transition, 30 * 3600)

    def test_naive_datetime_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            fx_reference_week_state(datetime(2026, 11, 23, 10))

    def test_next_transition_label_identifies_reference_zone(self):
        state = fx_reference_week_state(datetime(2026, 11, 28, 12, tzinfo=ZoneInfo("America/New_York")))
        self.assertEqual(fx_reference_week_label(state), "OPENS Sun 17:00 NY")


if __name__ == "__main__":
    unittest.main()
