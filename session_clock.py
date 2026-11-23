"""Pure time-to-geometry helpers for the four Global Sessions analog clocks."""
from __future__ import annotations

import math
from datetime import datetime


def session_clock_hand_endpoints(
    local_now: datetime,
    *,
    center_x: float,
    center_y: float,
    radius: float,
) -> dict[str, tuple[float, float]]:
    """Return hour, minute and second hand endpoints for a local wall-clock time."""
    if radius <= 0:
        raise ValueError("Clock radius must be positive.")

    seconds = local_now.second + local_now.microsecond / 1_000_000
    minutes = local_now.minute + seconds / 60
    hours = (local_now.hour % 12) + minutes / 60
    angles = {
        "hour": hours * 30,
        "minute": minutes * 6,
        "second": seconds * 6,
    }
    lengths = {"hour": radius * 0.48, "minute": radius * 0.69, "second": radius * 0.78}

    endpoints: dict[str, tuple[float, float]] = {}
    for hand, degrees in angles.items():
        angle = math.radians(degrees - 90)
        length = lengths[hand]
        endpoints[hand] = (
            center_x + math.cos(angle) * length,
            center_y + math.sin(angle) * length,
        )
    return endpoints


def session_clock_hand_polygon_coordinates(
    center_x: float,
    center_y: float,
    end_x: float,
    end_y: float,
    *,
    half_width: float,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> tuple[float, ...]:
    """Return a seven-point tapered watch-hand polygon for a Canvas item.

    The pointer is wider through its shoulder, narrows to a precise tip and
    extends slightly behind its pivot. Optional offsets are useful for subtle
    drop shadows. Coordinates are returned in Tk Canvas's flat x/y format.
    """
    values = (center_x, center_y, end_x, end_y, half_width, offset_x, offset_y)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Clock hand geometry must contain finite values.")
    if half_width <= 0:
        raise ValueError("Clock hand half-width must be positive.")

    dx = end_x - center_x
    dy = end_y - center_y
    length = math.hypot(dx, dy)
    if length <= 0:
        raise ValueError("Clock hand endpoint must be away from its pivot.")

    ux, uy = dx / length, dy / length
    px, py = -uy, ux

    stations = (
        (-0.085, 0.48),
        (0.035, 0.64),
        (0.55, 1.00),
    )
    points: list[tuple[float, float]] = []
    for distance, width_ratio in stations:
        along = distance * length
        x = center_x + ux * along + offset_x
        y = center_y + uy * along + offset_y
        half = half_width * width_ratio
        points.append((x - px * half, y - py * half))

    points.append((end_x + offset_x, end_y + offset_y))

    for distance, width_ratio in reversed(stations):
        along = distance * length
        x = center_x + ux * along + offset_x
        y = center_y + uy * along + offset_y
        half = half_width * width_ratio
        points.append((x + px * half, y + py * half))

    return tuple(value for point in points for value in point)
