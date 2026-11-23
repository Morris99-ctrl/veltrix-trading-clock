from __future__ import annotations

import math
import unittest
from datetime import datetime

from session_clock import (
    session_clock_hand_endpoints,
    session_clock_hand_polygon_coordinates,
)


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

    def test_hour_and_minute_hands_progress_between_whole_seconds(self):
        first = session_clock_hand_endpoints(
            datetime(2026, 11, 23, 3, 15, 0), center_x=0, center_y=0, radius=100
        )
        later = session_clock_hand_endpoints(
            datetime(2026, 11, 23, 3, 15, 0, 500_000), center_x=0, center_y=0, radius=100
        )

        self.assertNotEqual(first["hour"], later["hour"])
        self.assertNotEqual(first["minute"], later["minute"])

    def test_tapered_hand_polygon_points_in_direction_of_endpoint(self):
        points = session_clock_hand_polygon_coordinates(
            10, 10, 60, 10, half_width=3.0,
        )

        self.assertEqual(len(points), 14)
        self.assertAlmostEqual(points[6], 60.0)
        self.assertAlmostEqual(points[7], 10.0)
        self.assertLess(points[3], points[11])
        self.assertAlmostEqual(points[2], points[8], places=6)
        self.assertAlmostEqual(points[3] + points[9], 20.0, places=6)

    def test_tapered_hand_shadow_offset_is_applied_to_every_point(self):
        normal = session_clock_hand_polygon_coordinates(
            0, 0, 0, -40, half_width=2.0,
        )
        shadow = session_clock_hand_polygon_coordinates(
            0, 0, 0, -40, half_width=2.0, offset_x=1.25, offset_y=1.5,
        )

        self.assertEqual(len(normal), len(shadow))
        for index in range(0, len(normal), 2):
            self.assertAlmostEqual(shadow[index] - normal[index], 1.25)
            self.assertAlmostEqual(shadow[index + 1] - normal[index + 1], 1.5)

    def test_invalid_hand_polygon_dimensions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "half-width"):
            session_clock_hand_polygon_coordinates(0, 0, 10, 0, half_width=0)
        with self.assertRaisesRegex(ValueError, "pivot"):
            session_clock_hand_polygon_coordinates(0, 0, 0, 0, half_width=2)

    def test_invalid_radius_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            session_clock_hand_endpoints(
                datetime(2026, 11, 23), center_x=0, center_y=0, radius=0
            )


if __name__ == "__main__":
    unittest.main()
