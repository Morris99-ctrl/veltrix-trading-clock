from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import alerts_dashboard  # noqa: E402
from session_engine import load_session_definitions  # noqa: E402
from session_timeline import build_session_timeline  # noqa: E402


class FakeVariable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class FakeCanvas:
    def __init__(self, width=820):
        self.width = width
        self.calls = []

    def winfo_width(self):
        return self.width

    def delete(self, *args, **kwargs):
        self.calls.append(("delete", args, kwargs))

    def configure(self, *args, **kwargs):
        self.calls.append(("configure", args, kwargs))

    def create_text(self, *args, **kwargs):
        self.calls.append(("create_text", args, kwargs))

    def create_line(self, *args, **kwargs):
        self.calls.append(("create_line", args, kwargs))

    def create_rectangle(self, *args, **kwargs):
        self.calls.append(("create_rectangle", args, kwargs))


class AlertsDashboardTimelineCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (PROJECT_ROOT / "config.json").open("r", encoding="utf-8") as handle:
            config = json.load(handle)
        cls.sessions = load_session_definitions(config["sessions"])

    def make_app(self):
        return SimpleNamespace(
            alerts_session_canvas=FakeCanvas(),
            theme_name="CYAN",
            sessions=list(self.sessions),
            exchange_calendar_enabled_var=FakeVariable(False),
            alerts_session_timeline_signature=None,
            alerts_session_timeline_cache_key=None,
            alerts_session_timeline_cache=None,
        )

    def test_schedule_snapshot_is_reused_and_invalidated_only_by_schedule_inputs(self):
        app = self.make_app()
        start = datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc)

        with patch.object(
            alerts_dashboard,
            "build_session_timeline",
            wraps=build_session_timeline,
        ) as build:
            alerts_dashboard.draw_alerts_session_timeline(app, start, [])
            first_snapshot = app.alerts_session_timeline_cache

            # Normal one-second UI refreshes do not rebuild the 24-hour schedule.
            alerts_dashboard.draw_alerts_session_timeline(app, start + timedelta(seconds=1), [])
            self.assertEqual(build.call_count, 1)
            self.assertIs(app.alerts_session_timeline_cache, first_snapshot)

            # Theme and canvas-size changes redraw the presentation, not the schedule model.
            app.theme_name = "AMBER"
            app.alerts_session_canvas.width += 40
            alerts_dashboard.draw_alerts_session_timeline(app, start + timedelta(seconds=2), [])
            self.assertEqual(build.call_count, 1)

            # Exchange-calendar mode changes which session windows are in the snapshot.
            app.exchange_calendar_enabled_var.value = True
            alerts_dashboard.draw_alerts_session_timeline(app, start + timedelta(seconds=3), [])
            self.assertEqual(build.call_count, 2)

            # A new UTC calendar day requires a new 24-hour schedule.
            alerts_dashboard.draw_alerts_session_timeline(app, start + timedelta(days=1), [])
            self.assertEqual(build.call_count, 3)

            # A changed configured session set also requires a fresh schedule.
            app.sessions = app.sessions[:-1]
            alerts_dashboard.draw_alerts_session_timeline(app, start + timedelta(days=1, seconds=1), [])
            self.assertEqual(build.call_count, 4)


if __name__ == "__main__":
    unittest.main()
