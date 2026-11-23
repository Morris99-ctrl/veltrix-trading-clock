"""Selectable, user-configurable market-session schedule profiles."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from session_engine import parse_hhmm

PROFILE_PRESETS: dict[str, dict[str, dict[str, Any]]] = {
    "Forex Standard": {
        "sydney": {"open": "07:00", "close": "16:00"},
        "tokyo": {"open": "09:00", "close": "18:00"},
        "london": {"open": "08:00", "close": "17:00"},
        "new_york": {"open": "08:00", "close": "17:00"},
    },
    "Equities Cash": {
        "sydney": {"open": "10:00", "close": "16:00"},
        "tokyo": {"open": "09:00", "close": "15:00"},
        "london": {"open": "08:00", "close": "16:30"},
        "new_york": {"open": "09:30", "close": "16:00"},
    },
    "Extended Monitoring": {
        "sydney": {"open": "06:00", "close": "17:00"},
        "tokyo": {"open": "08:00", "close": "19:00"},
        "london": {"open": "07:00", "close": "18:00"},
        "new_york": {"open": "07:00", "close": "18:00"},
    },
}
PROFILE_NAMES = (*PROFILE_PRESETS.keys(), "Custom")


def validate_session_schedule(schedule: dict[str, Any], *, name: str = "Session") -> dict[str, Any]:
    """Validate and normalise one local same-day session schedule."""
    if not isinstance(schedule, dict):
        raise ValueError(f"{name} schedule must be an object.")
    opens, closes = str(schedule.get("open", "")), str(schedule.get("close", ""))
    open_time, close_time = parse_hhmm(opens), parse_hhmm(closes)
    if close_time <= open_time:
        raise ValueError(f"{name} close time must be later than its open time; overnight sessions are not supported.")
    raw_weekdays = schedule.get("weekdays", [0, 1, 2, 3, 4])
    if not isinstance(raw_weekdays, (list, tuple)):
        raise ValueError(f"{name} weekdays must be a list.")
    try:
        weekdays = sorted({int(day) for day in raw_weekdays})
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} weekdays must use integers from 0 (Monday) to 6 (Sunday).") from exc
    if not weekdays or any(day < 0 or day > 6 for day in weekdays):
        raise ValueError(f"{name} must have at least one weekday selected (0=Monday, 6=Sunday).")
    return {"open": open_time.strftime("%H:%M"), "close": close_time.strftime("%H:%M"), "weekdays": weekdays}


def apply_session_profile(
    base_sessions: list[dict[str, Any]],
    profile_name: str,
    custom_schedules: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Apply a named profile to existing session metadata without changing timezones."""
    if profile_name not in PROFILE_NAMES:
        raise ValueError(f"Unknown market-session profile: {profile_name!r}.")
    profile = PROFILE_PRESETS.get(profile_name, {})
    custom_schedules = custom_schedules or {}
    result: list[dict[str, Any]] = []

    for raw in base_sessions:
        if not isinstance(raw, dict) or not raw.get("key"):
            raise ValueError("Base session definitions must contain a key.")
        item = deepcopy(raw)
        key = str(item["key"])
        if profile_name == "Custom":
            chosen = custom_schedules.get(key, item)
        else:
            chosen = {**item, **profile.get(key, {})}
        validated = validate_session_schedule(chosen, name=str(item.get("name") or key))
        item.update(validated)
        result.append(item)

    expected = {"sydney", "tokyo", "london", "new_york"}
    present = {str(item["key"]) for item in result}
    if expected.intersection(present) and not expected.issubset(present):
        missing = ", ".join(sorted(expected - present))
        raise ValueError(f"Profile cannot be applied because session definitions are missing: {missing}.")
    return result
