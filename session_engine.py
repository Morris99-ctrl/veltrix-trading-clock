"""Timezone-aware trading-session calculations for Veltrix Trading Clock."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Iterable


@dataclass(frozen=True)
class SessionDefinition:
    key: str
    name: str
    city: str
    flag: str
    timezone_name: str
    opens: time
    closes: time
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)  # Monday-Friday

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise RuntimeError(
                f"Timezone '{self.timezone_name}' is unavailable. Install tzdata: pip install tzdata"
            ) from exc


@dataclass(frozen=True)
class SessionState:
    definition: SessionDefinition
    local_now: datetime
    is_open: bool
    transition_at: datetime
    transition_kind: str  # "CLOSE" when open, "OPEN" when closed
    seconds_to_transition: int

    @property
    def timezone_label(self) -> str:
        return self.local_now.tzname() or self.definition.timezone_name


def parse_hhmm(value: str) -> time:
    try:
        hour_text, minute_text = value.split(":", 1)
        return time(hour=int(hour_text), minute=int(minute_text))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid time '{value}'. Expected HH:MM, for example 08:00.") from exc


def load_session_definitions(config_sessions: Iterable[dict]) -> list[SessionDefinition]:
    sessions: list[SessionDefinition] = []
    for item in config_sessions:
        sessions.append(
            SessionDefinition(
                key=str(item["key"]),
                name=str(item["name"]),
                city=str(item["city"]),
                flag=str(item.get("flag", "")),
                timezone_name=str(item["timezone"]),
                opens=parse_hhmm(str(item["open"])),
                closes=parse_hhmm(str(item["close"])),
                weekdays=tuple(int(day) for day in item.get("weekdays", [0, 1, 2, 3, 4])),
            )
        )
    return sessions


def _seconds_between(start: datetime, end: datetime) -> int:
    """Compare instants in UTC, avoiding local DST arithmetic surprises."""
    return max(0, int((end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds()))


def _next_opening(session: SessionDefinition, local_now: datetime) -> datetime:
    """Find the next scheduled opening, scanning far enough to cross a weekend."""
    for offset in range(0, 9):
        candidate_date: date = local_now.date() + timedelta(days=offset)
        if candidate_date.weekday() not in session.weekdays:
            continue
        candidate = datetime.combine(candidate_date, session.opens, tzinfo=session.tz)
        if candidate.astimezone(timezone.utc) > local_now.astimezone(timezone.utc):
            return candidate
    # With a normal weekday schedule this should never be reached.
    raise RuntimeError(f"Could not find the next opening for {session.name}.")


def get_session_state(session: SessionDefinition, now: datetime) -> SessionState:
    """Return the session's state at an aware instant supplied by the caller."""
    if now.tzinfo is None:
        raise ValueError("'now' must be timezone-aware.")

    local_now = now.astimezone(session.tz)
    current_time = local_now.timetz().replace(tzinfo=None)
    scheduled_today = local_now.weekday() in session.weekdays
    currently_open = scheduled_today and session.opens <= current_time < session.closes

    if currently_open:
        transition = datetime.combine(local_now.date(), session.closes, tzinfo=session.tz)
        kind = "CLOSE"
    else:
        transition = _next_opening(session, local_now)
        kind = "OPEN"

    return SessionState(
        definition=session,
        local_now=local_now,
        is_open=currently_open,
        transition_at=transition,
        transition_kind=kind,
        seconds_to_transition=_seconds_between(local_now, transition),
    )


def format_countdown(total_seconds: int) -> str:
    seconds = max(0, int(total_seconds))
    days, remainder = divmod(seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"{days}d {hours:02d}h"
    if hours:
        return f"{hours:02d}h {minutes:02d}m"
    return f"{minutes:02d}m"
