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
