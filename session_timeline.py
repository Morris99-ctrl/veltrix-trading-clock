"""UTC-aligned trading-session windows and overlap intervals."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable

from session_engine import SessionDefinition
from exchange_calendar import EXCHANGE_BY_SESSION, get_exchange_event


@dataclass(frozen=True)
class SessionWindow:
    """One configured local trading session represented as a UTC interval."""

    session_key: str
    session_name: str
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class OverlapWindow:
    """A continuous UTC interval shared by two or more market sessions."""

    starts_at: datetime
    ends_at: datetime
    session_keys: tuple[str, ...]
    session_names: tuple[str, ...]


@dataclass(frozen=True)
class SessionTimeline:
    """A fixed UTC time range with its session windows and overlap intervals."""

    starts_at: datetime
    ends_at: datetime
    windows: tuple[SessionWindow, ...]
    overlaps: tuple[OverlapWindow, ...]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Timeline timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


def build_session_timeline(
    sessions: Iterable[SessionDefinition],
    starts_at: datetime,
    *,
    hours: int = 24,
    apply_exchange_calendar: bool = False,
) -> SessionTimeline:
    """Build local-weekday sessions clipped to a UTC timeline range.

    The local opening/closing wall times and weekday rules come directly from
    SessionDefinition. Daylight-saving offsets are resolved by each session's
    IANA timezone before intervals are converted to UTC. Overnight schedules
    are rejected because the existing session engine models same-day sessions.
    """
    if not isinstance(hours, int) or hours <= 0 or hours > 168:
        raise ValueError("Timeline hours must be an integer between 1 and 168.")
    start_utc = _utc(starts_at)
    end_utc = start_utc + timedelta(hours=hours)
    windows: list[SessionWindow] = []

    for session in sessions:
        if session.closes <= session.opens:
            raise ValueError(
                f"{session.name} must close after it opens; overnight sessions are not supported."
            )
        local_start_date = start_utc.astimezone(session.tz).date() - timedelta(days=1)
        local_end_date = end_utc.astimezone(session.tz).date() + timedelta(days=1)
        day_count = (local_end_date - local_start_date).days

        for day_offset in range(day_count + 1):
            local_date: date = local_start_date + timedelta(days=day_offset)
            if local_date.weekday() not in session.weekdays:
                continue

            event = (
                get_exchange_event(EXCHANGE_BY_SESSION[session.key], local_date)
                if apply_exchange_calendar and session.key in EXCHANGE_BY_SESSION else None
            )
            if event and event.status == "CLOSED":
                continue

            local_open = datetime.combine(local_date, session.opens, tzinfo=session.tz)
            close_time = event.close_time if event and event.status == "EARLY_CLOSE" else session.closes
            local_close = datetime.combine(local_date, close_time, tzinfo=session.tz)
            open_utc, close_utc = local_open.astimezone(timezone.utc), local_close.astimezone(timezone.utc)
            clipped_start = max(start_utc, open_utc)
            clipped_end = min(end_utc, close_utc)
            if clipped_start < clipped_end:
                windows.append(SessionWindow(
                    session_key=session.key,
                    session_name=session.name,
                    starts_at=clipped_start,
                    ends_at=clipped_end,
                ))

    windows.sort(key=lambda item: (item.starts_at, item.session_key))
    boundaries = sorted({point for item in windows for point in (item.starts_at, item.ends_at)})
    overlaps: list[OverlapWindow] = []

    for left, right in zip(boundaries, boundaries[1:]):
        if left >= right:
            continue
        midpoint = left + (right - left) / 2
        active = sorted(
            (item for item in windows if item.starts_at <= midpoint < item.ends_at),
            key=lambda item: item.session_key,
        )
        if len(active) < 2:
            continue
        keys = tuple(item.session_key for item in active)
        names = tuple(item.session_name for item in active)
        if overlaps and overlaps[-1].ends_at == left and overlaps[-1].session_keys == keys:
            previous = overlaps[-1]
            overlaps[-1] = OverlapWindow(previous.starts_at, right, keys, names)
        else:
            overlaps.append(OverlapWindow(left, right, keys, names))

    return SessionTimeline(start_utc, end_utc, tuple(windows), tuple(overlaps))
