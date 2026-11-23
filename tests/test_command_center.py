from __future__ import annotations

import unittest
from datetime import datetime, time, timedelta, timezone

from command_center_engine import build_command_center_snapshot
from session_engine import SessionDefinition, get_session_state


def session(key: str, name: str, opens: str, closes: str, zone: str = "UTC") -> SessionDefinition:
    return SessionDefinition(
        key, name, name, "", zone,
        time.fromisoformat(opens), time.fromisoformat(closes),
    )


class CommandCenterEngineTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)
        self.london = session("london", "London", "08:00", "17:00")
        self.new_york = session("new_york", "New York", "13:30", "20:00")
        self.states = [
            get_session_state(self.london, self.now),
            get_session_state(self.new_york, self.now),
        ]

    def snapshot(self, **overrides):
        args = {
            "session_states": self.states,
            "economic_events": [],
            "market_instruments": [
                {"key": "gold", "name": "Spot Gold", "symbol": "XAUUSD=X", "unit": "USD/oz"},
            ],
            "market_summaries": {"gold": {"quote": 2650.0, "atr": 25.0,
                                           "expected_move": {"expected_move_abs": 35.0, "expected_move_pct": 1.32}}},
            "market_reports": {},
            "risk_settings": {"enabled": True, "opening_window_minutes": 15, "closing_window_minutes": 15},
            "now": self.now,
            "home_timezone": "Africa/Nairobi",
            "exchange_calendar_enabled": False,
        }
        args.update(overrides)
        return build_command_center_snapshot(**args)

    def test_snapshot_summarises_open_sessions_overlap_and_next_transition(self):
        result = self.snapshot()
        self.assertEqual(result["open_count"], 1)
        self.assertEqual([item["name"] for item in result["open_sessions"]], ["London"])
        self.assertEqual(result["overlap_names"], [])
        self.assertEqual(result["next_transition"]["name"], "New York")
        self.assertEqual(result["next_transition"]["transition_kind"], "OPEN")

    def test_events_are_sorted_in_home_timezone_and_cancelled_or_past_events_are_omitted(self):
        soon = int((self.now + timedelta(minutes=45)).timestamp())
        later = int((self.now + timedelta(hours=4)).timestamp())
        result = self.snapshot(economic_events=[
            {"event_id": "later", "title": "Retail Sales", "currency": "USD",
             "impact": "medium", "timestamp_utc": later, "status": "scheduled"},
            {"event_id": "soon", "title": "CPI", "currency": "USD",
             "impact": "high", "timestamp_utc": soon, "status": "moved"},
            {"event_id": "cancelled", "title": "Cancelled", "currency": "EUR",
             "impact": "high", "timestamp_utc": soon, "status": "cancelled"},
            {"event_id": "past", "title": "Past", "currency": "EUR",
             "impact": "high", "timestamp_utc": int((self.now - timedelta(minutes=1)).timestamp())},
            {"event_id": "invalid", "timestamp_utc": "bad"},
        ])
        self.assertEqual([item["event_id"] for item in result["events"]], ["soon", "later"])
        self.assertEqual(result["events"][0]["local_time"].hour, 13)
        self.assertEqual(result["events"][0]["local_time"].minute, 45)
        self.assertEqual(result["event_count_next_24h"], 2)

    def test_market_rows_keep_missing_data_as_missing_not_zero(self):
        result = self.snapshot(market_summaries={"gold": {}})
        self.assertIsNone(result["markets"][0]["summary"].get("quote"))
        self.assertFalse(result["markets"][0]["fresh"])

    def test_live_volatility_expansion_becomes_a_caution_item(self):
        result = self.snapshot(
            market_reports={
                "gold": [{
                    "state": "LIVE SESSION", "regime": "EXPANSION", "ratio": 1.8,
                    "asset_name": "Spot Gold",
                }]
            },
            market_is_fresh=True,
        )
        self.assertEqual(result["risks"][0]["severity"], "CAUTION")
        self.assertIn("1.80x", result["risks"][0]["detail"])

    def test_cached_market_snapshot_does_not_create_live_volatility_warning(self):
        result = self.snapshot(
            market_reports={
                "gold": [{
                    "state": "LIVE SESSION", "regime": "EXPANSION", "ratio": 1.8,
                    "asset_name": "Spot Gold",
                }]
            },
            market_is_fresh=False,
        )
        self.assertEqual(result["risks"], [])

    def test_schedule_risk_flags_are_not_created_when_disabled(self):
        states = [get_session_state(self.london, self.now.replace(hour=8, minute=5))]
        result = self.snapshot(
            session_states=states,
            risk_settings={"enabled": False},
        )
        self.assertEqual(result["risks"], [])

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            self.snapshot(now=datetime(2026, 11, 24, 10, 0))


if __name__ == "__main__":
    unittest.main()
