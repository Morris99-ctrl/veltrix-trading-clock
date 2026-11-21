import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from session_engine import get_session_state, load_session_definitions  # noqa: E402


class SessionEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (PROJECT_ROOT / "config.json").open("r", encoding="utf-8") as file:
            cls.sessions = {item.key: item for item in load_session_definitions(json.load(file)["sessions"])}

    def test_tokyo_is_open_at_0930_local_on_weekday(self):
        now = datetime(2026, 11, 11, 0, 30, tzinfo=timezone.utc)
        self.assertTrue(get_session_state(self.sessions["tokyo"], now).is_open)

    def test_london_uses_gmt_in_november(self):
        now = datetime(2026, 11, 11, 8, 30, tzinfo=timezone.utc)
        state = get_session_state(self.sessions["london"], now)
        self.assertEqual(state.local_now.tzname(), "GMT")
        self.assertTrue(state.is_open)

    def test_london_uses_bst_in_july(self):
        now = datetime(2026, 7, 1, 7, 30, tzinfo=timezone.utc)
        state = get_session_state(self.sessions["london"], now)
        self.assertEqual(state.local_now.tzname(), "BST")
        self.assertTrue(state.is_open)

    def test_weekend_is_closed_and_next_open_is_monday(self):
        now = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
        state = get_session_state(self.sessions["london"], now)
        self.assertFalse(state.is_open)
        self.assertEqual(state.transition_at.strftime("%A %H:%M"), "Monday 08:00")

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            get_session_state(self.sessions["tokyo"], datetime(2026, 11, 11, 9, 30))


if __name__ == "__main__":
    unittest.main()
