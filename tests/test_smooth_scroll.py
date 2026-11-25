from __future__ import annotations

import unittest

from smooth_scroll import (
    find_scrollable_canvas,
    scroll_canvas_by_pixels,
    wheel_delta_pixels,
)


class FakeCanvas:
    def __init__(self, *, content_height=1000, viewport_height=200, top=0.25):
        self.content_height = content_height
        self.viewport_height = viewport_height
        self.top = top
        self.moves = []

    def bbox(self, _tag):
        return (0, 0, 500, self.content_height)

    def winfo_height(self):
        return self.viewport_height

    def yview(self):
        return (self.top, min(1.0, self.top + self.viewport_height / self.content_height))

    def yview_moveto(self, fraction):
        self.top = fraction
        self.moves.append(fraction)


class FakeWidget:
    def __init__(self, name, widget_class="Frame", master=None):
        self.name = name
        self.widget_class = widget_class
        self.master = master

    def __str__(self):
        return self.name

    def winfo_class(self):
        return self.widget_class


class SmoothScrollTests(unittest.TestCase):
    def test_windows_wheel_detents_and_fractional_trackpad_delta(self):
        self.assertEqual(wheel_delta_pixels(120, platform_name="win32"), -48.0)
        self.assertEqual(wheel_delta_pixels(-120, platform_name="win32"), 48.0)
        self.assertEqual(wheel_delta_pixels(30, platform_name="win32"), -12.0)

    def test_macos_small_wheel_deltas_are_not_discarded(self):
        self.assertEqual(wheel_delta_pixels(2, platform_name="darwin"), -24.0)
        self.assertEqual(wheel_delta_pixels(-1, platform_name="darwin"), 12.0)

    def test_linux_button_wheel_events_are_normalised(self):
        self.assertEqual(wheel_delta_pixels(0, platform_name="linux", button=4), -48.0)
        self.assertEqual(wheel_delta_pixels(0, platform_name="linux", button=5), 48.0)

    def test_canvas_moves_by_fractional_pixel_distance(self):
        canvas = FakeCanvas(top=0.25)

        handled = scroll_canvas_by_pixels(canvas, -50.0)

        self.assertTrue(handled)
        self.assertAlmostEqual(canvas.top, 0.20)
        self.assertEqual(len(canvas.moves), 1)

    def test_canvas_scroll_is_clamped_to_content_bounds(self):
        canvas = FakeCanvas(top=0.0)

        self.assertTrue(scroll_canvas_by_pixels(canvas, -100.0))
        self.assertEqual(canvas.moves, [])
        self.assertTrue(scroll_canvas_by_pixels(canvas, 5000.0))
        self.assertAlmostEqual(canvas.top, 0.8)

    def test_canvas_without_overflow_does_not_claim_scroll(self):
        canvas = FakeCanvas(content_height=200, viewport_height=200)

        self.assertFalse(scroll_canvas_by_pixels(canvas, 48.0))
        self.assertEqual(canvas.moves, [])

    def test_wheel_routes_from_nested_content_to_registered_page_canvas(self):
        canvas = FakeCanvas()
        canvas_widget = FakeWidget(".page.canvas", "Canvas")
        content = FakeWidget(".page.canvas.content", "Frame", canvas_widget)
        label = FakeWidget(".page.canvas.content.label", "Label", content)

        result = find_scrollable_canvas(label, {str(canvas_widget): canvas})

        self.assertIs(result, canvas)

    def test_inner_treeviews_keep_their_own_mousewheel(self):
        canvas_widget = FakeWidget(".page.canvas", "Canvas")
        content = FakeWidget(".page.canvas.content", "Frame", canvas_widget)
        tree = FakeWidget(".page.canvas.content.tree", "Treeview", content)

        result = find_scrollable_canvas(tree, {str(canvas_widget): object()})

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
