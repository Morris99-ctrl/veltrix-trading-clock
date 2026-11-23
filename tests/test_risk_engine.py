from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from exchange_calendar import get_exchange_aware_session_state  # noqa: E402
from risk_engine import assess_session_risk, due_session_risk_alerts  # noqa: E402
from session_engine import load_session_definitions  # noqa: E402


class SessionRiskEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (PROJECT_ROOT / "config.json").open("r", encoding="utf-8") as file:
            cls.sessions = load_session_definitions(json.load(file)["sessions"])
        cls.by_key = {session.key: session for session in cls.sessions}

    def local_time(self, key: str, value: str) -> datetime:
        return datetime.fromisoformat(value).replace(tzinfo=self.by_key[key].tz)

    def settings(self, **changes):
        result = {
            "enabled": True,
            "notifications_enabled": True,
            "holiday_liquidity_flags": True,
            "opening_window_minutes": 15,
            "closing_window_minutes": 15,
            "pre_open_window_minutes": 15,
        }
        result.update(changes)
        return result

    def state(self, key: str, local_value: str, *, calendar: bool = True):
        session = self.by_key[key]
        now = self.local_time(key, local_value)
        return now, get_exchange_aware_session_state(session, now, enabled=calendar)

    def test_nyse_thanksgiving_is_a_high_severity_exchange_holiday(self):
        now, state = self.state("new_york", "2026-11-26T09:00")
        assessment = assess_session_risk(
            self.by_key["new_york"], state, now, self.settings(),
            apply_exchange_calendar=True,
        )
        codes = {flag.code for flag in assessment.flags}

        self.assertEqual(assessment.level, "HIGH")
        self.assertIn("EXCHANGE_HOLIDAY", codes)
        self.assertIn("PRE_HOLIDAY_LIQUIDITY", codes)

    def test_pre_holiday_caution_flags_the_last_configured_session_before_close(self):
        now, state = self.state("new_york", "2026-11-25T10:00")
        assessment = assess_session_risk(
            self.by_key["new_york"], state, now, self.settings(),
            apply_exchange_calendar=True,
        )
        codes = {flag.code for flag in assessment.flags}
        self.assertIn("PRE_HOLIDAY_LIQUIDITY", codes)
        self.assertEqual(assessment.level, "CAUTION")

    def test_post_holiday_caution_flags_first_session_after_thanksgiving(self):
        now, state = self.state("new_york", "2026-11-27T10:00")
        assessment = assess_session_risk(
            self.by_key["new_york"], state, now, self.settings(),
            apply_exchange_calendar=True,
        )
        codes = {flag.code for flag in assessment.flags}
        self.assertIn("POST_HOLIDAY_LIQUIDITY", codes)
        self.assertIn("EARLY_CLOSE", codes)

    def test_opening_and_closing_windows_are_separate_configurable_flags(self):
        london = self.by_key["london"]
        open_now, open_state = self.state("london", "2026-11-11T08:05", calendar=False)
        opening = assess_session_risk(
            london, open_state, open_now,
            self.settings(opening_window_minutes=10, closing_window_minutes=0),
        )
        self.assertIn("OPENING_WINDOW", {flag.code for flag in opening.flags})

        close_now, close_state = self.state("london", "2026-11-11T16:50", calendar=False)
        closing = assess_session_risk(
            london, close_state, close_now,
            self.settings(opening_window_minutes=0, closing_window_minutes=15),
        )
        self.assertIn("CLOSING_WINDOW", {flag.code for flag in closing.flags})

    def test_pre_open_flag_uses_its_own_lead_window(self):
        london = self.by_key["london"]
        now, state = self.state("london", "2026-11-11T07:50", calendar=False)
        assessment = assess_session_risk(
            london, state, now, self.settings(pre_open_window_minutes=15)
        )
        self.assertIn("PRE_OPEN_WINDOW", {flag.code for flag in assessment.flags})

    def test_risk_flags_can_be_disabled_without_changing_session_state(self):
        london = self.by_key["london"]
        now, state = self.state("london", "2026-11-11T08:05", calendar=False)
        assessment = assess_session_risk(
            london, state, now, self.settings(enabled=False)
        )
        self.assertEqual(assessment.level, "NORMAL")
        self.assertEqual(assessment.flags, ())

    def test_liquidity_notifications_fire_once_per_session_date_and_flag(self):
        nyse = self.by_key["new_york"]
        now, state = self.state("new_york", "2026-11-26T09:00")
        fired = set()
        first = due_session_risk_alerts(
            [nyse], [state], now, self.settings(), fired,
            apply_exchange_calendar=True,
        )
        second = due_session_risk_alerts(
            [nyse], [state], now, self.settings(), fired,
            apply_exchange_calendar=True,
        )
        self.assertGreaterEqual(len(first), 1)
        self.assertEqual(second, [])

    def test_risk_notifications_can_be_disabled_independently_of_card_flags(self):
        nyse = self.by_key["new_york"]
        now, state = self.state("new_york", "2026-11-26T09:00")
        alerts = due_session_risk_alerts(
            [nyse], [state], now, self.settings(notifications_enabled=False), set(),
            apply_exchange_calendar=True,
        )
        self.assertEqual(alerts, [])

    def test_holiday_liquidity_flags_can_be_disabled(self):
        now, state = self.state("new_york", "2026-11-25T10:00")
        assessment = assess_session_risk(
            self.by_key["new_york"], state, now,
            self.settings(holiday_liquidity_flags=False),
            apply_exchange_calendar=True,
        )
        self.assertNotIn("PRE_HOLIDAY_LIQUIDITY", {flag.code for flag in assessment.flags})


if __name__ == "__main__":
    unittest.main()
