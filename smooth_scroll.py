"""Pixel-based mouse-wheel scrolling helpers for Tk canvases."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Widgets with their own scrolling behaviour should keep receiving wheel input.
_INNER_SCROLL_WIDGETS = {
    "Entry", "Listbox", "Spinbox", "Text", "Treeview",
    "TEntry", "TCombobox", "TSpinbox",
}


def wheel_delta_pixels(
    delta: int | float,
    *,
    platform_name: str,
    button: int | None = None,
) -> float:
    """Convert Tk mouse-wheel events into signed pixel distances.

    Windows reports wheel detents in multiples of 120, macOS commonly reports
    smaller deltas, and X11 uses Button-4 / Button-5 events.
    """
    if button == 4:
        return -48.0
    if button == 5:
        return 48.0
    try:
        amount = float(delta)
    except (TypeError, ValueError):
        return 0.0
    if platform_name == "darwin":
        return -amount * 12.0
    return -(amount / 120.0) * 48.0


def find_scrollable_canvas(
    widget: Any,
    canvases: Mapping[str, Any],
) -> Any | None:
    """Find the nearest registered page canvas above the pointer widget."""
    current = widget
    while current is not None:
        try:
            widget_class = str(current.winfo_class())
        except Exception:
            widget_class = ""
        if widget_class in _INNER_SCROLL_WIDGETS:
            return None
        canvas = canvases.get(str(current))
        if canvas is not None:
            return canvas
        current = getattr(current, "master", None)
    return None


def scroll_canvas_by_pixels(canvas: Any, delta_pixels: float) -> bool:
    """Move a canvas by a fractional, pixel-based distance without timers."""
    if not delta_pixels:
        return False
    try:
        bounds = canvas.bbox("all")
        if not bounds:
            return False
        content_height = max(1, int(bounds[3] - bounds[1]))
        viewport_height = max(1, int(canvas.winfo_height()))
        max_offset = max(0, content_height - viewport_height)
        if max_offset <= 0:
            return False
        current_fraction = float(canvas.yview()[0])
        current_offset = current_fraction * content_height
        target_offset = min(max_offset, max(0.0, current_offset + delta_pixels))
        if abs(target_offset - current_offset) < 0.5:
            return True
        canvas.yview_moveto(target_offset / content_height)
        return True
    except (AttributeError, TypeError, ValueError, IndexError):
        return False
