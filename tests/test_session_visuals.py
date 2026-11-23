from __future__ import annotations
import json
import unittest
from datetime import datetime,time,timezone
from types import SimpleNamespace
from pathlib import Path
from zoneinfo import ZoneInfo
from session_engine import load_session_definitions
from session_visuals import local_day_phase,session_calendar_close_override,session_window_arc_angles,session_window_progress,timeline_probe_from_x,utc_offset_label

ROOT=Path(__file__).resolve().parents[1]


class SessionVisualsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (ROOT/"config.json").open("r",encoding="utf-8") as f:
            cls.sessions={s.key:s for s in load_session_definitions(json.load(f)["sessions"])}

    def test_sydney_offsets_follow_dst(self):
        self.assertEqual(utc_offset_label(datetime(2026,1,15,12,tzinfo=ZoneInfo("Australia/Sydney"))),"UTC+11:00")
        self.assertEqual(utc_offset_label(datetime(2026,7,15,12,tzinfo=ZoneInfo("Australia/Sydney"))),"UTC+10:00")

    def test_new_york_standard_offset(self):
        self.assertEqual(utc_offset_label(datetime(2026,11,23,12,tzinfo=ZoneInfo("America/New_York"))),"UTC-05:00")

    def test_day_night_wall_clock_boundaries(self):
        zone=ZoneInfo("Europe/London")
        self.assertEqual(local_day_phase(datetime(2026,11,23,5,59,tzinfo=zone)),"NIGHT")
        self.assertEqual(local_day_phase(datetime(2026,11,23,6,0,tzinfo=zone)),"DAY")
        self.assertEqual(local_day_phase(datetime(2026,11,23,17,59,tzinfo=zone)),"DAY")
        self.assertEqual(local_day_phase(datetime(2026,11,23,18,0,tzinfo=zone)),"NIGHT")

    def test_active_progress_uses_utc_elapsed_seconds(self):
        p=session_window_progress(self.sessions["new_york"],datetime(2026,11,23,15,0,tzinfo=timezone.utc))
        self.assertEqual(p.status,"ACTIVE")
        self.assertAlmostEqual(p.fraction,2/9)
        self.assertEqual(p.elapsed_seconds,7200)
        self.assertEqual(p.remaining_seconds,25200)

    def test_upcoming_open_countdown(self):
        p=session_window_progress(self.sessions["new_york"],datetime(2026,11,23,12,0,tzinfo=timezone.utc))
        self.assertEqual(p.status,"UPCOMING")
        self.assertEqual(p.until_open_seconds,3600)

    def test_completed_session(self):
        p=session_window_progress(self.sessions["new_york"],datetime(2026,11,23,23,0,tzinfo=timezone.utc))
        self.assertEqual(p.status,"COMPLETE")
        self.assertEqual(p.fraction,1.0)

    def test_off_day(self):
        p=session_window_progress(self.sessions["new_york"],datetime(2026,11,21,15,0,tzinfo=timezone.utc))
        self.assertEqual(p.status,"OFF DAY")

    def test_early_close_controls_progress(self):
        zone=ZoneInfo("America/New_York")
        p=session_window_progress(self.sessions["new_york"],datetime(2026,11,27,12,0,tzinfo=zone),close_at=datetime(2026,11,27,13,0,tzinfo=zone))
        self.assertEqual(p.status,"ACTIVE")
        self.assertAlmostEqual(p.fraction,4/5)
        self.assertEqual(p.remaining_seconds,3600)

    def test_arc_angles_represent_new_york_eight_to_five(self):
        start,extent=session_window_arc_angles(self.sessions["new_york"])
        self.assertAlmostEqual(start,-30.0)
        self.assertAlmostEqual(extent,-135.0)

    def test_published_actual_early_close_shortens_session_ring(self):
        session=self.sessions["new_york"]
        local_now=datetime(2026,11,27,12,0,tzinfo=ZoneInfo("America/New_York"))
        state=SimpleNamespace(calendar_status="EARLY_CLOSE",calendar_close_time=time(13,0))
        close=session_calendar_close_override(session,local_now,state)
        self.assertEqual(close,datetime(2026,11,27,13,0,tzinfo=ZoneInfo("America/New_York")))

    def test_lse_closing_process_marker_does_not_shortcut_continuous_session_ring(self):
        session=self.sessions["london"]
        local_now=datetime(2026,12,24,12,0,tzinfo=ZoneInfo("Europe/London"))
        state=SimpleNamespace(calendar_status="CLOSING_PROCESS",calendar_close_time=time(12,30))
        self.assertIsNone(session_calendar_close_override(session,local_now,state))

    def test_timeline_probe_maps_left_middle_and_right(self):
        start=datetime(2026,11,23,tzinfo=timezone.utc)
        self.assertEqual(timeline_probe_from_x(100,100,900,start),start)
        self.assertEqual(timeline_probe_from_x(500,100,900,start).strftime("%H:%M"),"12:00")
        self.assertEqual(timeline_probe_from_x(900,100,900,start).strftime("%H:%M"),"23:59")

    def test_invalid_naive_timestamps_and_bounds_are_rejected(self):
        with self.assertRaisesRegex(ValueError,"timezone-aware"):
            session_window_progress(self.sessions["new_york"],datetime(2026,11,23,10))
        with self.assertRaisesRegex(ValueError,"timezone-aware"):
            utc_offset_label(datetime(2026,11,23,10))
        with self.assertRaisesRegex(ValueError,"positive width"):
            timeline_probe_from_x(1,4,4,datetime(2026,11,23,tzinfo=timezone.utc))


if __name__=="__main__":
    unittest.main()
