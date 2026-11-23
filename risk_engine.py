"""Transparent session-risk flags derived from schedules and exchange calendars.

These flags are context indicators, not live measurements of liquidity, volatility,
spread, order-book depth, or trading risk. Market-data confirmation is outside this
module's remit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from exchange_calendar import EXCHANGE_BY_SESSION, ExchangeDayEvent, get_exchange_event
from session_engine import SessionDefinition, SessionState


@dataclass(frozen=True)
class SessionRiskFlag:
    code: str
    severity: str  # INFO, CAUTION, HIGH
    label: str
    detail: str


@dataclass(frozen=True)
class SessionRiskAssessment:
    session_key: str
    level: str  # NORMAL, CAUTION, HIGH
    flags: tuple[SessionRiskFlag, ...]
    summary: str


@dataclass(frozen=True)
class SessionRiskAlert:
    key: str
    title: str
    message: str
    severity: str


def _holiday_neighbours(
    session: SessionDefinition,
    local_date,
) -> tuple[ExchangeDayEvent | None, ExchangeDayEvent | None]:
    exchange_key = EXCHANGE_BY_SESSION.get(session.key)
    if exchange_key is None:
        return None, None

    upcoming = None
    recent = None
    for offset in range(1, 4):
        candidate = local_date + timedelta(days=offset)
        event = get_exchange_event(exchange_key, candidate)
        if event and event.status == "CLOSED":
            upcoming = event
            break
    for offset in range(1, 4):
        candidate = local_date - timedelta(days=offset)
        event = get_exchange_event(exchange_key, candidate)
        if not event or event.status != "CLOSED":
            continue
        # Only flag the first configured weekday session after the closure.
        intervening_trade_day = False
        for between_offset in range(1, offset):
            between = local_date - timedelta(days=between_offset)
            if between.weekday() not in session.weekdays:
                continue
            between_event = get_exchange_event(exchange_key, between)
            if not between_event or between_event.status != "CLOSED":
                intervening_trade_day = True
                break
        if not intervening_trade_day:
            recent = event
            break
    return upcoming, recent


def assess_session_risk(
    session: SessionDefinition,
    state: SessionState,
    now: datetime,
    settings: dict[str, Any] | None = None,
    *,
    apply_exchange_calendar: bool = False,
) -> SessionRiskAssessment:
    """Assess schedule-based session warnings without claiming observed liquidity."""
    if now.tzinfo is None:
        raise ValueError("Session risk assessments require a timezone-aware datetime.")
    config = settings or {}
    if not bool(config.get("enabled", True)):
        return SessionRiskAssessment(session.key, "NORMAL", (), "SESSION RISK FLAGS DISABLED")

    opening_window = max(0, min(180, int(config.get("opening_window_minutes", 15))))
    closing_window = max(0, min(180, int(config.get("closing_window_minutes", 15))))
    pre_open_window = max(0, min(180, int(config.get("pre_open_window_minutes", 15))))
    holiday_flags = bool(config.get("holiday_liquidity_flags", True))
    now_utc = now.astimezone(timezone.utc)
    local_date = state.local_now.date()
    flags: list[SessionRiskFlag] = []

    if state.calendar_status == "EXCHANGE_HOLIDAY":
        flags.append(SessionRiskFlag(
            "EXCHANGE_HOLIDAY", "HIGH", "EXCHANGE HOLIDAY",
            state.calendar_event or "Published full-day exchange closure.",
        ))
    elif state.calendar_status in {"EARLY_CLOSE", "EARLY_CLOSE_PASSED"}:
        flags.append(SessionRiskFlag(
            "EARLY_CLOSE", "CAUTION", "EARLY-CLOSE SESSION",
            f"{state.calendar_event or 'Published early close'}; normal session duration is shortened.",
        ))
    elif state.calendar_status in {"CLOSING_PROCESS", "CLOSING_PROCESS_PASSED"}:
        flags.append(SessionRiskFlag(
            "CLOSING_PROCESS", "CAUTION", "CLOSING PROCESS",
            f"{state.calendar_event or 'Published exchange closing-process marker'}; marker is not a confirmed continuous-trading cutoff.",
        ))
    elif state.calendar_status in {"OUT_OF_RANGE", "NO_VENUE_MAPPING"}:
        flags.append(SessionRiskFlag(
            "SCHEDULE_ONLY", "CAUTION", "SCHEDULE ONLY",
            "This date is outside the venue's published calendar coverage; exchange status is unverified.",
        ))

    if apply_exchange_calendar and holiday_flags:
        upcoming, recent = _holiday_neighbours(session, local_date)
        if upcoming:
            days = (upcoming.event_date - local_date).days
            flags.append(SessionRiskFlag(
                "PRE_HOLIDAY_LIQUIDITY", "CAUTION", "HOLIDAY-AHEAD LIQUIDITY CAUTION",
                f"{upcoming.title} is in {days} calendar day(s). Participation may be thinner; this is a calendar heuristic, not a live liquidity measurement.",
            ))
        if recent:
            days = (local_date - recent.event_date).days
            flags.append(SessionRiskFlag(
                "POST_HOLIDAY_LIQUIDITY", "CAUTION", "POST-HOLIDAY LIQUIDITY CAUTION",
                f"First configured session after {recent.title} ({days} day(s) ago). Participation may be uneven; this is a calendar heuristic, not a live liquidity measurement.",
            ))

    if state.is_open and opening_window > 0 and local_date.weekday() in session.weekdays:
        local_open = datetime.combine(local_date, session.opens, tzinfo=session.tz)
        elapsed = (now_utc - local_open.astimezone(timezone.utc)).total_seconds()
        if 0 <= elapsed <= opening_window * 60:
            flags.append(SessionRiskFlag(
                "OPENING_WINDOW", "CAUTION", "OPENING WINDOW",
                f"Within the first {opening_window} minutes of the configured session; opening conditions can be less orderly.",
            ))

    if state.is_open and closing_window > 0 and state.transition_kind == "CLOSE":
        if 0 <= state.seconds_to_transition <= closing_window * 60:
            flags.append(SessionRiskFlag(
                "CLOSING_WINDOW", "CAUTION", "NEAR SESSION CLOSE",
                f"Within {closing_window} minutes of the session's configured or published close.",
            ))

    if (
        not state.is_open
        and state.transition_kind == "OPEN"
        and pre_open_window > 0
        and 0 <= state.seconds_to_transition <= pre_open_window * 60
    ):
        flags.append(SessionRiskFlag(
            "PRE_OPEN_WINDOW", "INFO", "PRE-OPEN",
            f"Configured session opening is within {pre_open_window} minutes.",
        ))

    severity_order = {"INFO": 1, "CAUTION": 2, "HIGH": 3}
    highest = max((severity_order[item.severity] for item in flags), default=0)
    level = "HIGH" if highest == 3 else "CAUTION" if highest == 2 else "NORMAL"
    if not flags:
        summary = "NO SCHEDULE-BASED RISK FLAGS"
    else:
        summary = " · ".join(item.label for item in flags[:2])
        if len(flags) > 2:
            summary += f" · +{len(flags) - 2} MORE"

    return SessionRiskAssessment(session.key, level, tuple(flags), summary)



def due_session_risk_alerts(
    sessions: list[SessionDefinition],
    states: list[SessionState],
    now: datetime,
    settings: dict[str, Any] | None,
    fired_keys: set[str],
    *,
    apply_exchange_calendar: bool = False,
) -> list[SessionRiskAlert]:
    """Emit one alert per session/date for material calendar/liquidity caution flags."""
    config = settings or {}
    if not bool(config.get("notifications_enabled", True)):
        return []
    alerts: list[SessionRiskAlert] = []
    sessions_by_key = {session.key: session for session in sessions}
    for state in states:
        session = sessions_by_key.get(state.definition.key)
        if session is None:
            continue
        assessment = assess_session_risk(
            session, state, now, config, apply_exchange_calendar=apply_exchange_calendar
        )
        local_date = state.local_now.date().isoformat()
        for flag in assessment.flags:
            if flag.code not in {
                "EXCHANGE_HOLIDAY", "EARLY_CLOSE", "CLOSING_PROCESS",
                "PRE_HOLIDAY_LIQUIDITY", "POST_HOLIDAY_LIQUIDITY",
            }:
                continue
            key = f"risk:{session.key}:{local_date}:{flag.code}"
            if key in fired_keys:
                continue
            fired_keys.add(key)
            alerts.append(SessionRiskAlert(
                key=key,
                title=f"{session.name} · {flag.label}",
                message=flag.detail,
                severity=flag.severity,
            ))
    return alerts
