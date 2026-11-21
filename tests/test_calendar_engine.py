import json
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from calendar_engine import (  # noqa: E402
    CalendarEvent,
    calendar_is_due,
    calendar_retry_delay_seconds,
    load_calendar_cache,
    parse_calendar_payload,
    save_calendar_cache,
    due_calendar_reminders,
)


class CalendarEngineTests(unittest.TestCase):
    def sample_payload(self):
        return {
            "generated_at": "2026-11-11T12:00:00Z",
            "events": [
                {
                    "ts": 1794403800,
                    "time": "2026-11-11T13:30:00Z",
                    "currency": "USD",
                    "impact": "high",
                    "title": "US CPI",
                    "forecast": "0.3%",
                    "previous": "0.2%",
                    "actual": "",
                    "id": "usd-cpi.20261111T1330",
                    "status": "scheduled",
                    "moved_from": "",
                    "confidence": "official",
                },
                {
                    "ts": 1794403800,
                    "currency": "USD",
                    "impact": "high",
                    "title": "US CPI duplicate",
                    "id": "usd-cpi.20261111T1330",
                },
                {"ts": "invalid", "currency": "USD", "impact": "high", "title": "Bad", "id": "bad"},
            ],
            "attribution": {
                "text": "Economic calendar by ShowMyTrades",
                "url": "https://showmytrades.com/tools/economic-calendar",
                "required": False,
            },
        }

    def test_payload_normalisation_and_deduplication(self):
        events, attribution, generated = parse_calendar_payload(self.sample_payload())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].currency, "USD")
        self.assertEqual(events[0].impact, "high")
        self.assertEqual(events[0].forecast, "0.3%")
        self.assertEqual(attribution["text"], "Economic calendar by ShowMyTrades")
        self.assertEqual(generated, "2026-11-11T12:00:00Z")

    def test_status_and_confidence_are_normalised(self):
        payload = {"events": [{
            "id": "usd-fed.1", "title": "Fed decision", "currency": "usd",
            "impact": "HIGH", "ts": 1794403800, "status": "MOVED", "confidence": "OFFICIAL",
        }]}
        events, _, _ = parse_calendar_payload(payload)
        self.assertEqual(events[0].currency, "USD")
        self.assertEqual(events[0].impact, "high")
        self.assertEqual(events[0].status, "moved")
        self.assertEqual(events[0].confidence, "official")

    def test_malformed_top_level_payload_rejected(self):
        with self.assertRaises(ValueError):
            parse_calendar_payload({"events": None})

    def test_calendar_event_timestamp_is_utc(self):
        event = CalendarEvent("id", "CPI", "USD", "high", 1794403800)
        self.assertEqual(event.event_time.tzinfo, timezone.utc)

    def test_cache_round_trip(self):
        events, attribution, generated = parse_calendar_payload(self.sample_payload())
        payload = {
            "events": [event.to_dict() for event in events],
            "attribution": attribution,
            "generated_at": generated,
            "fetched_at": "2026-11-11T12:00:00+00:00",
            "provider": "ShowMyTrades",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calendar_cache.json"
            save_calendar_cache(path, payload)
            restored = load_calendar_cache(path)
        self.assertIsNotNone(restored)
        self.assertEqual(restored["events"][0]["title"], "US CPI")

    def test_missing_cache_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(load_calendar_cache(Path(directory) / "missing.json"))

    def test_refresh_first_time_is_due(self):
        self.assertTrue(calendar_is_due(None, now=1000))

    def test_refresh_is_not_due_before_15_minutes(self):
        self.assertFalse(calendar_is_due(1000, now=1899))

    def test_refresh_is_due_at_15_minutes(self):
        self.assertTrue(calendar_is_due(1000, now=1900))

    def test_high_impact_reminder_fires_once(self):
        events, _, _ = parse_calendar_payload(self.sample_payload())
        now = datetime(2026, 11, 11, 13, 20, tzinfo=timezone.utc)
        fired = set()
        first = due_calendar_reminders(events, now, lead_minutes=15, allowed_impacts={"high"}, fired_keys=fired)
        second = due_calendar_reminders(events, now, lead_minutes=15, allowed_impacts={"high"}, fired_keys=fired)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["title"], "US CPI")
        self.assertEqual(second, [])

    def test_low_impact_event_is_filtered_from_high_only_alerts(self):
        event = {
            "event_id": "eur-retail.1", "title": "Retail Sales", "currency": "EUR",
            "impact": "low", "timestamp_utc": 1794403800,
        }
        now = datetime(2026, 11, 11, 13, 20, tzinfo=timezone.utc)
        result = due_calendar_reminders([event], now, lead_minutes=15, allowed_impacts={"high"}, fired_keys=set())
        self.assertEqual(result, [])

    def test_no_reminder_after_release_time(self):
        event = {
            "event_id": "usd-cpi.1", "title": "CPI", "currency": "USD",
            "impact": "high", "timestamp_utc": 1794403800,
        }
        now = datetime(2026, 11, 11, 13, 31, tzinfo=timezone.utc)
        result = due_calendar_reminders([event], now, lead_minutes=15, allowed_impacts={"high"}, fired_keys=set())
        self.assertEqual(result, [])

    def test_zero_minute_reminder_fires_at_release_time(self):
        event = {
            "event_id": "usd-cpi.zero", "title": "CPI", "currency": "USD",
            "impact": "high", "timestamp_utc": 1794403800, "status": "scheduled",
        }
        now = datetime(2026, 11, 11, 13, 30, tzinfo=timezone.utc)
        result = due_calendar_reminders([event], now, lead_minutes=0,
                                        allowed_impacts={"high"}, fired_keys=set())
        self.assertEqual(len(result), 1)

    def test_tentative_high_impact_event_does_not_trigger_reminder(self):
        event = {
            "event_id": "usd-cpi.tentative", "title": "CPI", "currency": "USD",
            "impact": "high", "timestamp_utc": 1794403800, "status": "tentative",
        }
        now = datetime(2026, 11, 11, 13, 20, tzinfo=timezone.utc)
        result = due_calendar_reminders([event], now, lead_minutes=15,
                                        allowed_impacts={"high"}, fired_keys=set())
        self.assertEqual(result, [])

    def test_cancelled_event_does_not_trigger_reminder(self):
        event = {
            "event_id": "usd-cpi.cancelled", "title": "CPI", "currency": "USD",
            "impact": "high", "timestamp_utc": 1794403800, "status": "cancelled",
        }
        now = datetime(2026, 11, 11, 13, 20, tzinfo=timezone.utc)
        result = due_calendar_reminders([event], now, lead_minutes=15,
                                        allowed_impacts={"high"}, fired_keys=set())
        self.assertEqual(result, [])

    def test_moved_release_uses_revised_time_for_reminder(self):
        event = {
            "event_id": "usd-fed.moved", "title": "Fed decision", "currency": "USD",
            "impact": "high", "timestamp_utc": 1794403800, "status": "moved",
        }
        now = datetime(2026, 11, 11, 13, 20, tzinfo=timezone.utc)
        result = due_calendar_reminders([event], now, lead_minutes=15,
                                        allowed_impacts={"high"}, fired_keys=set())
        self.assertEqual(len(result), 1)

    def test_zero_lead_reminder_has_short_late_scheduler_grace(self):
        event = {
            "event_id": "usd-cpi.grace", "title": "CPI", "currency": "USD",
            "impact": "high", "timestamp_utc": 1794403800, "status": "scheduled",
        }
        now = datetime(2026, 11, 11, 13, 31, tzinfo=timezone.utc)
        result = due_calendar_reminders([event], now, lead_minutes=0,
                                        allowed_impacts={"high"}, fired_keys=set())
        self.assertEqual(len(result), 1)


    def test_moved_high_impact_event_can_still_trigger_reminder(self):
        event = {
            "event_id": "usd-cpi.moved", "title": "CPI", "currency": "USD",
            "impact": "high", "timestamp_utc": 1794403800, "status": "moved",
        }
        now = datetime(2026, 11, 11, 13, 20, tzinfo=timezone.utc)
        result = due_calendar_reminders([event], now, lead_minutes=15,
                                        allowed_impacts={"high"}, fired_keys=set())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "moved")

    def test_market_holiday_does_not_trigger_high_impact_release_reminder(self):
        event = {
            "event_id": "usd-holiday.1", "title": "Market Holiday", "currency": "USD",
            "impact": "holiday", "timestamp_utc": 1794403800, "status": "scheduled",
        }
        now = datetime(2026, 11, 11, 13, 20, tzinfo=timezone.utc)
        result = due_calendar_reminders([event], now, lead_minutes=15,
                                        allowed_impacts={"high", "holiday"}, fired_keys=set())
        self.assertEqual(result, [])


    def test_fetch_uses_public_endpoint_without_api_key(self):
        from urllib.parse import parse_qs, urlparse
        from unittest.mock import MagicMock
        from calendar_engine import fetch_calendar

        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(self.sample_payload()).encode("utf-8")
        with patch("calendar_engine.urlopen", return_value=response) as mocked_urlopen:
            payload = fetch_calendar(days=7)

        request = mocked_urlopen.call_args.args[0]
        parsed_url = urlparse(request.full_url)
        query = parse_qs(parsed_url.query)
        self.assertEqual(parsed_url.netloc, "showmytrades.com")
        self.assertEqual(parsed_url.path, "/api/public/calendar/v1")
        self.assertEqual(query["impact"], ["all"])
        self.assertEqual(query["days"], ["7"])
        self.assertNotIn("api_key", query)
        self.assertEqual(len(payload["events"]), 1)
        self.assertEqual(payload["provider"], "ShowMyTrades")


    def test_calendar_fetch_retries_once_after_timeout(self):
        from unittest.mock import MagicMock
        from urllib.error import URLError
        from calendar_engine import fetch_calendar

        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(self.sample_payload()).encode("utf-8")
        with patch("calendar_engine.urlopen", side_effect=[URLError(socket.timeout("timed out")), response]) as mocked_urlopen, \
             patch("calendar_engine.time_module.sleep") as mocked_sleep:
            payload = fetch_calendar(days=7, timeout=25, retries=1)

        self.assertEqual(mocked_urlopen.call_count, 2)
        self.assertEqual(mocked_urlopen.call_args_list[0].kwargs["timeout"], 25)
        mocked_sleep.assert_called_once_with(1.5)
        self.assertEqual(payload["provider"], "ShowMyTrades")

    def test_calendar_timeout_error_is_actionable_after_retry(self):
        from urllib.error import URLError
        from calendar_engine import fetch_calendar

        with patch("calendar_engine.urlopen", side_effect=URLError(socket.timeout("The operation timed out"))), \
             patch("calendar_engine.time_module.sleep") as mocked_sleep:
            with self.assertRaisesRegex(RuntimeError, "timed out after 25 seconds"):
                fetch_calendar(days=7, timeout=25, retries=1)
        self.assertEqual(mocked_sleep.call_count, 1)

    def test_calendar_retry_backoff_is_bounded(self):
        self.assertEqual(calendar_retry_delay_seconds(1), 30)
        self.assertEqual(calendar_retry_delay_seconds(2), 60)
        self.assertEqual(calendar_retry_delay_seconds(3), 120)
        self.assertEqual(calendar_retry_delay_seconds(4), 240)
        self.assertEqual(calendar_retry_delay_seconds(5), 480)
        self.assertEqual(calendar_retry_delay_seconds(6), 900)
        self.assertEqual(calendar_retry_delay_seconds(99), 900)

    def test_naive_reminder_time_is_rejected(self):
        with self.assertRaises(ValueError):
            due_calendar_reminders([], datetime(2026, 11, 11, 13, 20), lead_minutes=15,
                                   allowed_impacts={"high"}, fired_keys=set())


if __name__ == "__main__":
    unittest.main()
