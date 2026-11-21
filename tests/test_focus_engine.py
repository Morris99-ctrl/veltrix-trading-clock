import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from focus_engine import FocusError, FocusStore, format_duration


class FakeClock:
    def __init__(self, instant: datetime):
        self.timestamp = instant.timestamp()

    def __call__(self):
        return self.timestamp

    def advance(self, seconds: float):
        self.timestamp += seconds


class FocusEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.clock = FakeClock(datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc))
        self.db_path = Path(self.temp_dir.name) / "focus.sqlite3"
        self.store = FocusStore(self.db_path, timezone_name="Africa/Nairobi", now_fn=self.clock)

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_format_duration_handles_hours_and_negative_values(self):
        self.assertEqual(format_duration(3661), "01:01:01")
        self.assertEqual(format_duration(-5), "00:00:00")

    def test_create_goal_and_validate_dates(self):
        goal_id = self.store.create_goal(
            "Launch Veltrix Capital", description="Build the research and risk platform",
            category="Business", start_date="2026-11-13", deadline_date="2027-11-13",
        )
        goal = self.store.get_goal(goal_id)
        self.assertEqual(goal["title"], "Launch Veltrix Capital")
        self.assertEqual(goal["category"], "Business")
        self.assertEqual(self.store.list_goals()[0]["days_remaining"], 366)
        with self.assertRaises(FocusError):
            self.store.create_goal("Invalid", start_date="2027-01-02", deadline_date="2027-01-01")

    def test_milestones_drive_goal_progress_and_cascade_on_delete(self):
        goal_id = self.store.create_goal("Complete curriculum", start_date="2026-11-12", deadline_date="2027-01-01")
        first = self.store.add_milestone(goal_id, "Finish probability theory")
        self.store.add_milestone(goal_id, "Complete time-series module")
        self.assertEqual(self.store.list_goals()[0]["progress"], 0)
        self.store.toggle_milestone(first)
        goals = self.store.list_goals()
        self.assertEqual(goals[0]["progress"], 50)
        self.assertEqual(self.store.list_milestones(goal_id)[0]["completed"], 1)
        self.store.delete_goal(goal_id)
        self.assertEqual(self.store.list_milestones(goal_id), [])

    def test_manual_progress_is_used_until_milestones_exist(self):
        goal_id = self.store.create_goal("Study", start_date="2026-11-12", deadline_date="2026-12-12", progress=35)
        self.assertEqual(self.store.list_goals()[0]["progress"], 35)
        self.store.add_milestone(goal_id, "Module 1")
        self.assertEqual(self.store.list_goals()[0]["progress"], 0)

    def test_stopwatch_pause_resume_and_stop_records_active_segments(self):
        session_id = self.store.start_timer("stopwatch", label="Quant research")
        self.clock.advance(65)
        running = self.store.get_active_timer()
        self.assertEqual(running["id"], session_id)
        self.assertEqual(running["elapsed_seconds"], 65)
        paused = self.store.pause_timer()
        self.assertEqual(paused["status"], "paused")
        self.clock.advance(120)
        self.assertEqual(self.store.get_active_timer()["elapsed_seconds"], 65)
        self.store.resume_timer()
        self.clock.advance(10)
        stopped = self.store.stop_timer()
        self.assertEqual(stopped["status"], "stopped")
        self.assertEqual(stopped["elapsed_seconds"], 75)
        self.assertEqual(self.store.get_recent_sessions(1)[0]["duration_seconds"], 75)

    def test_cannot_start_a_second_timer_while_one_is_running_or_paused(self):
        self.store.start_timer("stopwatch")
        with self.assertRaises(FocusError):
            self.store.start_timer("countdown", duration_seconds=60)
        self.store.pause_timer()
        with self.assertRaises(FocusError):
            self.store.start_timer("stopwatch")

    def test_countdown_pause_resume_and_completion(self):
        self.store.start_timer("countdown", label="Deep work", duration_seconds=60)
        self.clock.advance(20)
        paused = self.store.pause_timer()
        self.assertEqual(paused["remaining_seconds"], 40)
        self.clock.advance(300)
        self.store.resume_timer()
        self.clock.advance(39)
        running = self.store.get_active_timer()
        self.assertEqual(running["status"], "running")
        self.assertEqual(running["remaining_seconds"], 1)
        self.clock.advance(1)
        completed = self.store.get_active_timer()
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["remaining_seconds"], 0)
        self.assertEqual(completed["elapsed_seconds"], 60)

    def test_stopping_running_countdown_preserves_remaining_time(self):
        self.store.start_timer("countdown", duration_seconds=120)
        self.clock.advance(35)
        stopped = self.store.stop_timer()
        self.assertEqual(stopped["status"], "stopped")
        self.assertEqual(stopped["remaining_seconds"], 85)
        self.assertEqual(stopped["display_seconds"], 85)
        self.assertEqual(stopped["elapsed_seconds"], 35)

    def test_countdown_recovers_as_completed_after_application_was_closed(self):
        self.store.start_timer("countdown", duration_seconds=30)
        self.clock.advance(35)
        restarted_store = FocusStore(self.db_path, timezone_name="Africa/Nairobi", now_fn=self.clock)
        snapshot = restarted_store.get_active_timer()
        self.assertEqual(snapshot["status"], "completed")
        self.assertEqual(snapshot["elapsed_seconds"], 30)
        restarted_store.close()

    def test_running_stopwatch_continues_across_store_recreation(self):
        self.store.start_timer("stopwatch")
        self.clock.advance(90)
        restarted_store = FocusStore(self.db_path, timezone_name="Africa/Nairobi", now_fn=self.clock)
        snapshot = restarted_store.get_active_timer()
        self.assertEqual(snapshot["status"], "running")
        self.assertEqual(snapshot["elapsed_seconds"], 90)
        restarted_store.close()

    def test_daily_focus_is_allocated_across_local_midnight(self):
        # 18:00 UTC is 21:00 in Nairobi on Nov 12; the session crosses local midnight.
        self.clock.timestamp = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc).timestamp()
        self.store.start_timer("stopwatch")
        self.clock.advance(4 * 3600)
        nov12 = self.store.get_daily_focus_seconds(date(2026, 11, 12))
        nov13 = self.store.get_daily_focus_seconds(date(2026, 11, 13))
        self.assertEqual(nov12, 3 * 3600)
        self.assertEqual(nov13, 1 * 3600)

    def test_status_and_progress_updates_are_validated(self):
        goal_id = self.store.create_goal("Goal", start_date="2026-11-12", deadline_date="2026-12-12")
        self.store.update_goal(goal_id, status="in_progress", progress=55)
        self.assertEqual(self.store.get_goal(goal_id)["status"], "in_progress")
        with self.assertRaises(FocusError):
            self.store.update_goal(goal_id, progress=101)
        with self.assertRaises(FocusError):
            self.store.update_goal(goal_id, status="maybe")


if __name__ == "__main__":
    unittest.main()
