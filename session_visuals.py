"""Pure visual calculations for the Global Sessions instrument clocks and UTC probe."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class SessionWindowProgress:
    """Progress through one configured local session window."""
    status: str
    fraction: float
    elapsed_seconds: int
    remaining_seconds: int
    until_open_seconds: int
    opens_at: datetime | None
    closes_at: datetime | None


def session_window_progress(session, local_now: datetime, *, close_at: datetime | None = None) -> SessionWindowProgress:
    """Return session progress using UTC elapsed time and the session's IANA zone."""
    if local_now.tzinfo is None:
        raise ValueError("Session progress requires a timezone-aware datetime.")
    local = local_now.astimezone(session.tz)
    if local.weekday() not in session.weekdays:
        return SessionWindowProgress("OFF DAY", 0.0, 0, 0, 0, None, None)
    opens_at = datetime.combine(local.date(), session.opens, tzinfo=session.tz)
    if close_at is None:
        closes_at = datetime.combine(local.date(), session.closes, tzinfo=session.tz)
    else:
        if close_at.tzinfo is None:
            raise ValueError("Session close override must be timezone-aware.")
        closes_at = close_at.astimezone(session.tz)
        if closes_at.date() != local.date():
            raise ValueError("Session close override must fall on the local session date.")
    open_utc = opens_at.astimezone(timezone.utc)
    close_utc = closes_at.astimezone(timezone.utc)
    now_utc = local.astimezone(timezone.utc)
    duration = int((close_utc-open_utc).total_seconds())
    if duration <= 0:
        raise ValueError("Session close must be later than its open time.")
    if now_utc < open_utc:
        return SessionWindowProgress("UPCOMING",0.0,0,0,int((open_utc-now_utc).total_seconds()),opens_at,closes_at)
    if now_utc >= close_utc:
        return SessionWindowProgress("COMPLETE",1.0,duration,0,0,opens_at,closes_at)
    elapsed = int((now_utc-open_utc).total_seconds())
    remaining = max(0,int((close_utc-now_utc).total_seconds()))
    return SessionWindowProgress("ACTIVE",elapsed/duration,elapsed,remaining,0,opens_at,closes_at)


def session_window_arc_angles(session, *, close_at: datetime | None = None) -> tuple[float,float]:
    """Return Tk Canvas start/extent angles for a 24-hour local-day ring."""
    open_minutes = session.opens.hour*60 + session.opens.minute
    if close_at is None:
        close_time = session.closes
    else:
        if close_at.tzinfo is None:
            raise ValueError("Session close override must be timezone-aware.")
        close_time = close_at.astimezone(session.tz).time()
    close_minutes = close_time.hour*60 + close_time.minute
    if close_minutes <= open_minutes:
        raise ValueError("Session close must be later than its open time.")
    return 90.0-open_minutes*0.25, -(close_minutes-open_minutes)*0.25


def utc_offset_label(local_now: datetime) -> str:
    """Format the actual UTC offset at this instant, including DST changes."""
    if local_now.tzinfo is None or local_now.utcoffset() is None:
        raise ValueError("UTC offset display requires a timezone-aware datetime.")
    seconds = int(local_now.utcoffset().total_seconds())
    sign = "+" if seconds >= 0 else "-"
    hours, remainder = divmod(abs(seconds),3600)
    return f"UTC{sign}{hours:02d}:{remainder//60:02d}"


def local_day_phase(local_now: datetime) -> str:
    """Return a wall-clock phase label, not an astronomical daylight estimate."""
    if local_now.tzinfo is None:
        raise ValueError("Day/night cycle requires a timezone-aware datetime.")
    return "DAY" if 6 <= local_now.hour < 18 else "NIGHT"


def timeline_probe_from_x(x: float,left: float,right: float,day_start_utc: datetime) -> datetime:
    """Map a timeline x-coordinate to the selected minute in its UTC calendar day."""
    if day_start_utc.tzinfo is None:
        raise ValueError("Timeline probe origin must be timezone-aware.")
    if right <= left:
        raise ValueError("Timeline probe bounds must have positive width.")
    fraction=max(0.0,min(1.0,(float(x)-left)/(right-left)))
    minute=min(1439,int(fraction*1440))
    start=day_start_utc.astimezone(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
    return start+timedelta(minutes=minute)
