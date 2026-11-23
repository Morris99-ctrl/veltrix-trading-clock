from __future__ import annotations

import json
import sys
import unittest
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from alert_engine import due_session_alerts  # noqa: E402
from exchange_calendar import (  # noqa: E402
    calendar_coverage_status,
    get_exchange_aware_session_state,
    get_exchange_event,
)
from session_engine import load_session_definitions  # noqa: E402
from session_timeline import build_session_timeline  # noqa: E402


class ExchangeCalendarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (PROJECT_ROOT / "config.json").open("r", encoding="utf-8") as file:
            config = json.load(file)
        cls.config_sessions = config["sessions"]
        cls.sessions = load_session_definitions(cls.config_sessions)
        cls.by_key = {session.key: session for session in cls.sessions}

    def local_time(self, key: str, day: str, clock: str) -> datetime:
        session = self.by_key[key]
        hour, minute = map(int, clock.split(":"))
        return datetime.fromisoformat(day).replace(
            hour=hour, minute=minute, tzinfo=session.tz
        )

    def test_official_sources_have_venue_mapped_events_and_coverage(self):
        event = get_exchange_event("nyse", date(2026, 11, 26))
        self.assertIsNotNone(event)
        self.assertEqual(event.title, "Thanksgiving Day")
        self.assertEqual(event.status, "CLOSED")
        self.assertEqual(calendar_coverage_status("lse", date(2026, 8, 30)), "OUT_OF_RANGE")
        self.assertEqual(calendar_coverage_status("lse", date(2026, 8, 31)), "PUBLISHED")

    def test_asx_christmas_closure_skips_boxing_day_substitute_and_weekend(self):
        session = self.by_key["sydney"]
        now = self.local_time("sydney", "2026-12-25", "10:00")
        state = get_exchange_aware_session_state(session, now, enabled=True)

        self.assertFalse(state.is_open)
        self.assertEqual(state.calendar_status, "EXCHANGE_HOLIDAY")
        self.assertEqual(state.calendar_event, "Christmas Day")
        self.assertEqual(state.transition_at.date().isoformat(), "2026-12-29")
        self.assertEqual(state.transition_at.strftime("%H:%M"), "07:00")

    def test_tokyo_exchange_holiday_overrides_weekday_schedule(self):
        session = self.by_key["tokyo"]
        now = self.local_time("tokyo", "2026-11-23", "10:00")
        state = get_exchange_aware_session_state(session, now, enabled=True)

        self.assertFalse(state.is_open)
        self.assertEqual(state.calendar_status, "EXCHANGE_HOLIDAY")
        self.assertEqual(state.calendar_event, "Labor Thanksgiving Day")

    def test_nyse_early_close_shortens_state_at_1300_eastern(self):
        session = self.by_key["new_york"]
        before = self.local_time("new_york", "2026-11-27", "12:45")
        state = get_exchange_aware_session_state(session, before, enabled=True)

        self.assertTrue(state.is_open)
        self.assertEqual(state.calendar_status, "EARLY_CLOSE")
        self.assertEqual(state.transition_kind, "CLOSE")
        self.assertEqual(state.transition_at.strftime("%H:%M"), "13:00")

        after = self.local_time("new_york", "2026-11-27", "13:05")
        closed = get_exchange_aware_session_state(session, after, enabled=True)
        self.assertFalse(closed.is_open)
        self.assertEqual(closed.calendar_status, "EARLY_CLOSE_PASSED")
        self.assertEqual(closed.transition_at.date().isoformat(), "2026-11-30")

    def test_lse_1230_marker_is_closing_process_not_a_forced_market_close(self):
        session = self.by_key["london"]
        before = self.local_time("london", "2026-12-24", "11:30")
        process = get_exchange_aware_session_state(session, before, enabled=True)

        self.assertTrue(process.is_open)
        self.assertEqual(process.calendar_status, "CLOSING_PROCESS")
        self.assertEqual(process.transition_kind, "CLOSE_PROCESS")
        self.assertEqual(process.transition_at.strftime("%H:%M"), "12:30")

        after = self.local_time("london", "2026-12-24", "13:00")
        still_open = get_exchange_aware_session_state(session, after, enabled=True)
        self.assertTrue(still_open.is_open)
        self.assertEqual(still_open.calendar_status, "CLOSING_PROCESS_PASSED")
        self.assertEqual(still_open.transition_at.strftime("%H:%M"), "17:00")

    def test_calendar_disabled_preserves_generic_weekday_schedule(self):
        session = self.by_key["tokyo"]
        now = self.local_time("tokyo", "2026-11-23", "10:00")
        state = get_exchange_aware_session_state(session, now, enabled=False)

        self.assertTrue(state.is_open)
        self.assertEqual(state.calendar_status, "SCHEDULED")
        self.assertIsNone(state.calendar_event)

    def test_out_of_range_is_not_silently_marked_as_verified_normal(self):
        session = self.by_key["london"]
        now = self.local_time("london", "2028-01-03", "10:00")
        state = get_exchange_aware_session_state(session, now, enabled=True)

        self.assertTrue(state.is_open)
        self.assertEqual(state.calendar_status, "OUT_OF_RANGE")

    def test_timeline_omits_exchange_holidays_and_clips_actual_early_closes(self):
        start = datetime(2026, 11, 27, 0, 0, tzinfo=ZoneInfo("UTC"))
        snapshot = build_session_timeline(
            self.sessions, start, hours=24, apply_exchange_calendar=True
        )
        nyse = next(item for item in snapshot.windows if item.session_key == "new_york")

        self.assertEqual(nyse.ends_at.astimezone(self.by_key["new_york"].tz).strftime("%H:%M"), "13:00")

        tokyo_day = datetime(2026, 11, 23, 0, 0, tzinfo=ZoneInfo("UTC"))
        holiday_snapshot = build_session_timeline(
            self.sessions, tokyo_day, hours=24, apply_exchange_calendar=True
        )
        self.assertFalse(any(item.session_key == "tokyo" for item in holiday_snapshot.windows))

    def test_lse_closing_process_marker_does_not_shorten_timeline_window(self):
        start = datetime(2026, 12, 24, 0, 0, tzinfo=ZoneInfo("UTC"))
        snapshot = build_session_timeline(
            self.sessions, start, hours=24, apply_exchange_calendar=True
        )
        london = next(item for item in snapshot.windows if item.session_key == "london")
        self.assertEqual(london.ends_at.astimezone(self.by_key["london"].tz).strftime("%H:%M"), "17:00")

    def test_full_holiday_suppresses_open_close_alerts(self):
        session = self.by_key["nyse"]
        now = self.local_time("new_york", "2026-11-26", "09:00")
        alerts = due_session_alerts(
            [session], now,
            {"notify_open": True, "notify_close": True,
             "notify_pre_open": True, "notify_pre_close": True,
             "pre_open_minutes": 15, "pre_close_minutes": 10},
            set(), days_ahead=0, apply_exchange_calendar=True,
        )
        self.assertEqual(alerts, [])

    def test_early_close_generates_pre_close_alert_at_exchange_time(self):
        session = self.by_key["new_york"]
        now = self.local_time("new_york", "2026-11-27", "12:55")
        alerts = due_session_alerts(
            [session], now,
            {"notify_open": True, "notify_close": True,
             "notify_pre_open": True, "notify_pre_close": True,
             "pre_open_minutes": 15, "pre_close_minutes": 10},
            set(), days_ahead=0, apply_exchange_calendar=True,
        )

        self.assertEqual(len(alerts), 1)
        self.assertIn("EARLY CLOSE IN 10 MIN", alerts[0].title)


if __name__ == "__main__":
    unittest.main()
