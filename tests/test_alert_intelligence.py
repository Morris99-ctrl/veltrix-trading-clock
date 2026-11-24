from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from alert_intelligence import AlertCenterStore, build_alert_candidates  # noqa: E402
from session_engine import get_session_state, load_session_definitions  # noqa: E402


class AlertCenterStoreTests(unittest.TestCase):
    def setUp(self):
        with (PROJECT_ROOT / "config.json").open("r", encoding="utf-8") as file:
            self.sessions = load_session_definitions(json.load(file)["sessions"])
        self.by_key = {session.key: session for session in self.sessions}
        self.now = datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc)
        self.home_zone = ZoneInfo("Africa/Nairobi")

    def test_triggered_alert_is_deduplicated_by_stable_id(self):
        store = AlertCenterStore()
        values = {
            "alert_id": "session:london:2026-11-11:OPEN:NOW",
            "title": "LONDON SESSION OPENED",
            "message": "London is open.",
            "category": "transition",
            "source": "Session scheduler",
            "market": "LONDON",
            "impact": "MEDIUM",
            "now": self.now,
        }
        first = store.record_triggered(**values)
        second = store.record_triggered(**values)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(store.records), 1)

    def test_triggered_history_and_dedupe_survive_reload(self):
        store = AlertCenterStore()
        store.record_triggered(
            alert_id="calendar:CPI:1794384000",
            title="US CPI",
            message="Release approaching.",
            category="event",
            source="Economic calendar",
            market="USD",
            impact="HIGH",
            now=self.now,
        )
        restored = AlertCenterStore(store.export_state())
        self.assertEqual(restored.records[0]["status"], "TRIGGERED")
        duplicate = restored.record_triggered(
            alert_id="calendar:CPI:1794384000",
            title="US CPI",
            message="Duplicate.",
            category="event",
            source="Economic calendar",
            market="USD",
            impact="HIGH",
            now=self.now + timedelta(seconds=5),
        )
        self.assertIsNone(duplicate)

    def test_acknowledgement_is_persistent_and_idempotent(self):
        store = AlertCenterStore()
        store.record_triggered(
            alert_id="risk:london:2026-11-11:PRE_HOLIDAY_LIQUIDITY",
            title="LONDON RISK",
            message="Calendar caution.",
            category="warning",
            source="Session risk",
            market="LONDON",
            impact="MEDIUM",
            now=self.now,
        )
        self.assertTrue(store.acknowledge(
            "risk:london:2026-11-11:PRE_HOLIDAY_LIQUIDITY", now=self.now
        ))
        self.assertFalse(store.acknowledge(
            "risk:london:2026-11-11:PRE_HOLIDAY_LIQUIDITY", now=self.now
        ))
        restored = AlertCenterStore(store.export_state())
        self.assertEqual(restored.records[0]["status"], "ACKNOWLEDGED")

    def test_upcoming_candidate_can_be_acknowledged_and_remains_in_history(self):
        candidate = {
            "id": "schedule:london:2026-11-11T08:00:00+00:00",
            "status": "UPCOMING",
            "scheduled_at": "2026-11-11T08:00:00+00:00",
            "title": "LONDON SESSION OPEN",
            "message": "Configured opening.",
            "market": "LONDON",
            "impact": "MEDIUM",
            "category": "session",
            "source": "Session schedule",
        }
        store = AlertCenterStore()
        self.assertTrue(store.acknowledge(candidate["id"], now=self.now, candidates=[candidate]))
        restored = AlertCenterStore(store.export_state())
        rows = restored.snapshot([candidate])
        self.assertEqual(rows[0]["status"], "ACKNOWLEDGED")

    def test_filters_by_status_market_impact_and_search(self):
        store = AlertCenterStore()
        store.record_triggered(
            alert_id="cpi", title="US CPI RELEASE", message="Inflation report.",
            category="event", source="Calendar", market="USD", impact="HIGH", now=self.now,
        )
        store.record_triggered(
            alert_id="tokyo", title="TOKYO SESSION CLOSE", message="Tokyo closed.",
            category="session", source="Scheduler", market="TOKYO", impact="MEDIUM", now=self.now,
        )
        rows = store.snapshot(
            [], status="TRIGGERED", market="USD", impact="HIGH", query="inflation"
        )
        self.assertEqual([row["id"] for row in rows], ["cpi"])

    def test_naive_clock_is_rejected(self):
        store = AlertCenterStore()
        with self.assertRaises(ValueError):
            store.record_triggered(
                alert_id="bad", title="Bad", message="Bad", category="test",
                source="test", market="GLOBAL", impact="INFO",
                now=datetime(2026, 11, 11, 8, 0),
            )


class AlertCandidateTests(unittest.TestCase):
    def setUp(self):
        with (PROJECT_ROOT / "config.json").open("r", encoding="utf-8") as file:
            self.sessions = load_session_definitions(json.load(file)["sessions"])
        self.by_key = {session.key: session for session in self.sessions}
        self.home_zone = ZoneInfo("Africa/Nairobi")
        self.now = datetime(2026, 11, 11, 7, 30, tzinfo=timezone.utc)

    def test_session_transition_inside_horizon_is_upcoming(self):
        state = get_session_state(self.by_key["london"], self.now)
        rows = build_alert_candidates(self.now, [state], [], [], self.home_zone)
        london = [row for row in rows if row["id"].startswith("schedule:london:")]
        self.assertEqual(len(london), 1)
        self.assertEqual(london[0]["status"], "UPCOMING")
        self.assertEqual(london[0]["market"], "LONDON")

    def test_open_session_and_overlap_are_active(self):
        now = datetime(2026, 11, 11, 8, 30, tzinfo=timezone.utc)
        states = [
            get_session_state(self.by_key["london"], now),
            get_session_state(self.by_key["tokyo"], now),
        ]
        rows = build_alert_candidates(now, states, [], [], self.home_zone)
        active = [row for row in rows if row["status"] == "ACTIVE"]
        self.assertTrue(any(row["id"] == "live:overlap:london-tokyo" for row in active))
        self.assertEqual(sum(row["category"] == "session" for row in active), 2)

    def test_calendar_events_are_validated_and_future_bounded(self):
        event_time = self.now + timedelta(minutes=45)
        stamp = int(event_time.timestamp())
        events = [
            {
                "event_id": "usd-cpi", "timestamp_utc": stamp, "title": "US CPI",
                "currency": "USD", "impact": "high", "status": "scheduled",
            },
            {
                "event_id": "cancelled", "timestamp_utc": stamp, "title": "Cancelled",
                "currency": "EUR", "impact": "high", "status": "cancelled",
            },
            {
                "event_id": "bad-time", "timestamp_utc": "not-a-time", "title": "Invalid",
                "currency": "EUR", "impact": "high", "status": "scheduled",
            },
            {
                "event_id": "past", "timestamp_utc": int((self.now - timedelta(minutes=1)).timestamp()),
                "title": "Past", "currency": "GBP", "impact": "medium", "status": "scheduled",
            },
        ]
        rows = build_alert_candidates(self.now, [], events, [], self.home_zone)
        self.assertEqual([row["id"] for row in rows], [f"calendar:usd-cpi:{stamp}"])
        self.assertEqual(rows[0]["impact"], "HIGH")

    def test_manual_event_uses_home_timezone_when_timestamp_is_naive(self):
        local_time = self.now.astimezone(self.home_zone) + timedelta(hours=2)
        manual = [{
            "id": "manual-cpi",
            "name": "Manual CPI reminder",
            "datetime": local_time.replace(tzinfo=None).isoformat(timespec="minutes"),
        }]
        rows = build_alert_candidates(self.now, [], [], manual, self.home_zone)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["market"], "CUSTOM")
        self.assertEqual(rows[0]["source"], "Manual reminder")

    def test_events_beyond_horizon_are_not_added(self):
        far = self.now + timedelta(hours=30)
        events = [{
            "event_id": "far", "timestamp_utc": int(far.timestamp()),
            "title": "Far event", "currency": "USD", "impact": "high",
            "status": "scheduled",
        }]
        self.assertEqual(build_alert_candidates(self.now, [], events, [], self.home_zone), [])

    def test_naive_clock_is_rejected(self):
        with self.assertRaises(ValueError):
            build_alert_candidates(
                datetime(2026, 11, 11, 7, 30), [], [], [], self.home_zone
            )


if __name__ == "__main__":
    unittest.main()
