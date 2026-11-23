from __future__ import annotations

import math
import unittest
from datetime import datetime

from session_clock import session_clock_hand_endpoints


class SessionClockGeometryTests(unittest.TestCase):
    def test_three_oclock_points_hour_hand_to_the_right_and_minute_to_twelve(self):
        hands = session_clock_hand_endpoints(
            datetime(2026, 11, 23, 3, 0, 0), center_x=100, center_y=100, radius=50
        )

        self.assertAlmostEqual(hands["hour"][0], 124.0, places=6)
        self.assertAlmostEqual(hands["hour"][1], 100.0, places=6)
        self.assertAlmostEqual(hands["minute"][0], 100.0, places=6)
        self.assertAlmostEqual(hands["minute"][1], 65.5, places=6)
        self.assertAlmostEqual(hands["second"][0], 100.0, places=6)
        self.assertAlmostEqual(hands["second"][1], 61.0, places=6)

    def test_six_oclock_points_hour_hand_downwards(self):
        hands = session_clock_hand_endpoints(
            datetime(2026, 11, 23, 6, 0, 0), center_x=0, center_y=0, radius=100
        )

        self.assertAlmostEqual(hands["hour"][0], 0.0, places=6)
        self.assertAlmostEqual(hands["hour"][1], 48.0, places=6)

    def test_second_hand_advances_with_seconds_and_fractional_microseconds(self):
        first = session_clock_hand_endpoints(
            datetime(2026, 11, 23, 0, 0, 0), center_x=0, center_y=0, radius=100
        )
        second = session_clock_hand_endpoints(
            datetime(2026, 11, 23, 0, 0, 1), center_x=0, center_y=0, radius=100
        )
        smooth = session_clock_hand_endpoints(
            datetime(2026, 11, 23, 0, 0, 1, 500_000), center_x=0, center_y=0, radius=100
        )

        self.assertNotEqual(first["second"], second["second"])
        self.assertNotEqual(second["second"], smooth["second"])

    def test_invalid_radius_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            session_clock_hand_endpoints(
                datetime(2026, 11, 23), center_x=0, center_y=0, radius=0
            )


if __name__ == "__main__":
    unittest.main()
