"""Deterministic, timezone-aware market-session alert scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable

from session_engine import SessionDefinition
from exchange_calendar import EXCHANGE_BY_SESSION, get_exchange_event


@dataclass(frozen=True)
class MarketAlert:
    key: str
    title: str
    message: str
    category: str


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Alert calculations require timezone-aware datetimes.")
    return value.astimezone(timezone.utc)


def due_session_alerts(
    sessions: Iterable[SessionDefinition],
    now: datetime,
    settings: dict,
    fired_keys: set[str],
    *,
    days_ahead: int = 9,
    transition_grace_seconds: int = 90,
    apply_exchange_calendar: bool = False,
) -> list[MarketAlert]:
    """Return session alerts due now, marking each event key as fired once.

    Pre-open and pre-close warnings fire once during their lead window. Exact
    opening/closing alerts fire only inside a short grace period, preventing an
    old alert from appearing when the application is launched much later.
    """
    now_utc = _utc(now)
    alerts: list[MarketAlert] = []

    pre_open_minutes = max(0, int(settings.get("pre_open_minutes", 15)))
    pre_close_minutes = max(0, int(settings.get("pre_close_minutes", 10)))

    for session in sessions:
        local_today = now_utc.astimezone(session.tz).date()
        for offset in range(days_ahead + 1):
            session_date: date = local_today + timedelta(days=offset)
            if session_date.weekday() not in session.weekdays:
                continue

            exchange_event = (
                get_exchange_event(EXCHANGE_BY_SESSION[session.key], session_date)
                if apply_exchange_calendar and session.key in EXCHANGE_BY_SESSION else None
            )
            if exchange_event and exchange_event.status == "CLOSED":
                continue

            close_time = (
                exchange_event.close_time
                if exchange_event and exchange_event.status == "EARLY_CLOSE"
                else session.closes
            )
            close_name = "EARLY_CLOSE" if exchange_event and exchange_event.status == "EARLY_CLOSE" else "CLOSE"
            events = (
                ("OPEN", session.opens, "session_open", "notify_open", pre_open_minutes, "notify_pre_open"),
                (close_name, close_time, "session_close", "notify_close", pre_close_minutes, "notify_pre_close"),
            )
            for event_name, event_time, exact_category, exact_setting, lead_minutes, lead_setting in events:
                event_local = datetime.combine(session_date, event_time, tzinfo=session.tz)
                event_utc = event_local.astimezone(timezone.utc)
                if event_utc < now_utc - timedelta(seconds=transition_grace_seconds):
                    continue

                if bool(settings.get(lead_setting, True)) and lead_minutes > 0:
                    lead_at = event_utc - timedelta(minutes=lead_minutes)
                    lead_key = f"{session.key}:{session_date.isoformat()}:{event_name}:PRE"
                    if lead_at <= now_utc < event_utc and lead_key not in fired_keys:
                        fired_keys.add(lead_key)
                        alerts.append(
                            MarketAlert(
                                key=lead_key,
                                title=(
                                    f"{session.name} EARLY CLOSE PROCESS IN {lead_minutes} MIN"
                                    if event_name == "EARLY_CLOSE"
                                    else f"{session.name} {event_name} IN {lead_minutes} MIN"
                                ),
                                message=(
                                    f"{session.city} has an exchange early-close event at "
                                    f"{event_local.strftime('%H:%M %Z')}."
                                    if event_name == "EARLY_CLOSE"
                                    else f"{session.city} is scheduled to {event_name.lower()} at "
                                         f"{event_local.strftime('%H:%M %Z')}."
                                ),
                                category="warning",
                            )
                        )

                exact_key = f"{session.key}:{session_date.isoformat()}:{event_name}:NOW"
                elapsed = (now_utc - event_utc).total_seconds()
                if (bool(settings.get(exact_setting, True)) and 0 <= elapsed <= transition_grace_seconds
                        and exact_key not in fired_keys):
                    fired_keys.add(exact_key)
                    alerts.append(
                        MarketAlert(
                            key=exact_key,
                            title=(
                                f"{session.name} EXCHANGE EARLY-CLOSE PROCESS STARTED"
                                if event_name == "EARLY_CLOSE"
                                else f"{session.name} SESSION {event_name}ED"
                            ),
                            message=(
                                f"{session.city} has reached the published early-close process time."
                                if event_name == "EARLY_CLOSE"
                                else f"{session.city} scheduled hours have reached {event_name.lower()}."
                            ),
                            category="transition",
                        )
                    )

    return alerts
