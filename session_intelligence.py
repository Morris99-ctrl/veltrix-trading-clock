"""Weekly scheduled-hours and historical scheduled-overlap analytics."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import combinations
from typing import Iterable

from session_engine import SessionDefinition
from session_timeline import build_session_timeline


@dataclass(frozen=True)
class WeeklySessionHours:
    session_key: str
    session_name: str
    scheduled_hours: float
    active_days: int


@dataclass(frozen=True)
class HistoricalOverlapReport:
    start_utc: datetime
    end_utc: datetime
    days: int
    total_overlap_hours: float
    average_daily_overlap_hours: float
    busiest_utc_date: str | None
    busiest_day_hours: float
    pair_overlap_hours: tuple[tuple[str, str, float], ...]
    daily_overlap_hours: tuple[tuple[str, float], ...]


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Analytics timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


def weekly_session_hours(
    sessions: Iterable[SessionDefinition],
    reference_utc: datetime,
) -> tuple[WeeklySessionHours, ...]:
    """Calculate Monday-Sunday scheduled hours in each session's own local timezone."""
    session_list = list(sessions)
    reference = _aware_utc(reference_utc)
    output: list[WeeklySessionHours] = []

    for session in session_list:
        local_reference = reference.astimezone(session.tz)
        local_monday = local_reference.date() - timedelta(days=local_reference.weekday())
        total_seconds = 0.0
        active_days = 0
        for offset in range(7):
            local_date = local_monday + timedelta(days=offset)
            if local_date.weekday() not in session.weekdays:
                continue
            local_open = datetime.combine(local_date, session.opens, tzinfo=session.tz)
            local_close = datetime.combine(local_date, session.closes, tzinfo=session.tz)
            open_utc = local_open.astimezone(timezone.utc)
            close_utc = local_close.astimezone(timezone.utc)
            if close_utc > open_utc:
                total_seconds += (close_utc - open_utc).total_seconds()
                active_days += 1

        output.append(WeeklySessionHours(
            session_key=session.key,
            session_name=session.name,
            scheduled_hours=total_seconds / 3600.0,
            active_days=active_days,
        ))
    return tuple(output)


def historical_overlap_report(
    sessions: Iterable[SessionDefinition],
    end_utc: datetime,
    *,
    days: int = 30,
) -> HistoricalOverlapReport:
    """Reconstruct scheduled overlap over the prior 7/30/90 UTC calendar days.

    This is a schedule-based estimate from configured weekdays and local hours.
    It is not proof that an exchange was open on a holiday or emergency closure.
    """
    if days not in (7, 30, 90):
        raise ValueError("Historical overlap period must be 7, 30 or 90 days.")
    end = _aware_utc(end_utc)
    start = end - timedelta(days=days)
    session_list = list(sessions)
    timeline = build_session_timeline(session_list, start, hours=days * 24)
    daily: dict[str, float] = {}
    pairs: dict[tuple[str, str], float] = {}
    names = {session.key: session.name for session in session_list}
    union_seconds = 0.0

    for overlap in timeline.overlaps:
        cursor = overlap.starts_at
        while cursor < overlap.ends_at:
            next_midnight = (cursor + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            segment_end = min(overlap.ends_at, next_midnight)
            seconds = (segment_end - cursor).total_seconds()
            day_key = cursor.date().isoformat()
            daily[day_key] = daily.get(day_key, 0.0) + seconds / 3600.0
            union_seconds += seconds
            for left, right in combinations(overlap.session_keys, 2):
                pair = (left, right)
                pairs[pair] = pairs.get(pair, 0.0) + seconds / 3600.0
            cursor = segment_end

    daily_rows = tuple(sorted(daily.items()))
    busiest = max(daily_rows, key=lambda item: item[1]) if daily_rows else (None, 0.0)
    pair_rows = tuple(sorted(
        ((names.get(left, left), names.get(right, right), hours) for (left, right), hours in pairs.items()),
        key=lambda item: item[2], reverse=True,
    ))
    total_hours = union_seconds / 3600.0
    return HistoricalOverlapReport(
        start_utc=start,
        end_utc=end,
        days=days,
        total_overlap_hours=total_hours,
        average_daily_overlap_hours=total_hours / days,
        busiest_utc_date=busiest[0],
        busiest_day_hours=busiest[1],
        pair_overlap_hours=pair_rows,
        daily_overlap_hours=daily_rows,
    )
