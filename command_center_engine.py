"""Pure data aggregation for the Veltrix Trading Command Center."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from risk_engine import assess_session_risk


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Command Center snapshots require a timezone-aware datetime.")
    return value.astimezone(timezone.utc)


def build_command_center_snapshot(
    session_states: list,
    economic_events: list[dict[str, Any]],
    market_instruments: list[dict[str, Any]],
    market_summaries: dict[str, dict[str, Any]],
    market_reports: dict[str, list[dict[str, Any]]],
    risk_settings: dict[str, Any],
    now: datetime,
    *,
    home_timezone: str = "UTC",
    exchange_calendar_enabled: bool = False,
    market_is_fresh: bool = False,
    market_fetched_at: str = "",
    calendar_is_fresh: bool = False,
    calendar_fetched_at: str = "",
    event_horizon_hours: int = 168,
) -> dict[str, Any]:
    """Build a read-only snapshot from data already owned by the main application."""
    now_utc = _aware_utc(now)
    home_zone = ZoneInfo(home_timezone)
    event_horizon = now_utc + timedelta(hours=max(1, min(24 * 30, int(event_horizon_hours))))

    sessions: list[dict[str, Any]] = []
    risks: list[dict[str, str]] = []
    for state in session_states:
        definition = state.definition
        sessions.append({
            "key": definition.key,
            "name": definition.name,
            "city": definition.city,
            "local_time": state.local_now,
            "is_open": bool(state.is_open),
            "transition_kind": state.transition_kind,
            "transition_at": state.transition_at,
            "seconds_to_transition": max(0, int(state.seconds_to_transition)),
            "calendar_status": str(state.calendar_status),
            "calendar_event": str(state.calendar_event or ""),
        })
        assessment = assess_session_risk(
            definition,
            state,
            now_utc,
            risk_settings,
            apply_exchange_calendar=exchange_calendar_enabled,
        )
        for flag in assessment.flags:
            if flag.severity not in {"HIGH", "CAUTION"}:
                continue
            risks.append({
                "severity": flag.severity,
                "source": definition.name,
                "label": flag.label,
                "detail": flag.detail,
            })

    sessions.sort(key=lambda item: item["name"])
    open_sessions = [item for item in sessions if item["is_open"]]
    transitions = sorted(sessions, key=lambda item: item["seconds_to_transition"])
    next_transition = transitions[0] if transitions else None

    events: list[dict[str, Any]] = []
    for event in economic_events:
        if not isinstance(event, dict):
            continue
        try:
            timestamp = int(event.get("timestamp_utc"))
            event_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        status = str(event.get("status", "scheduled") or "scheduled").strip().lower()
        if status == "cancelled" or event_time < now_utc or event_time > event_horizon:
            continue
        events.append({
            "event_id": str(event.get("event_id") or ""),
            "title": str(event.get("title") or "Economic event"),
            "currency": str(event.get("currency") or "").upper(),
            "impact": str(event.get("impact") or "unknown").lower(),
            "status": status,
            "event_time": event_time,
            "local_time": event_time.astimezone(home_zone),
            "seconds_until": max(0, int((event_time - now_utc).total_seconds())),
        })
    impact_order = {"high": 0, "medium": 1, "low": 2, "holiday": 3}
    events.sort(key=lambda item: (item["event_time"], impact_order.get(item["impact"], 4)))
    next_event = events[0] if events else None
    events_next_24h = sum(item["seconds_until"] <= 86_400 for item in events)

    markets: list[dict[str, Any]] = []
    for instrument in market_instruments:
        key = str(instrument.get("key") or "")
        markets.append({
            "key": key,
            "name": str(instrument.get("name") or key or "Instrument"),
            "symbol": str(instrument.get("symbol") or ""),
            "unit": str(instrument.get("unit") or ""),
            "summary": market_summaries.get(key, {}),
            "fresh": bool(market_is_fresh),
        })

    for asset_key, reports in market_reports.items():
        for report in reports:
            if (
                str(report.get("state", "")).upper() == "LIVE SESSION"
                and str(report.get("regime", "")).upper() == "EXPANSION"
            ):
                risks.append({
                    "severity": "CAUTION",
                    "source": str(report.get("asset_name") or asset_key),
                    "label": "LIVE SESSION VOLATILITY EXPANSION",
                    "detail": (
                        "Realised volatility is "
                        f"{float(report.get('ratio') or 0.0):.2f}x the same-time historical median. "
                        "Descriptive monitoring only, not a trade signal."
                    ),
                })

    severity_order = {"HIGH": 0, "CAUTION": 1}
    risks.sort(key=lambda item: (severity_order.get(item["severity"], 2), item["source"], item["label"]))

    return {
        "generated_at": now_utc,
        "home_timezone": home_timezone,
        "sessions": sessions,
        "open_sessions": open_sessions,
        "open_count": len(open_sessions),
        "session_count": len(sessions),
        "overlap_names": [item["name"] for item in open_sessions] if len(open_sessions) >= 2 else [],
        "next_transition": next_transition,
        "events": events[:8],
        "event_count_next_24h": events_next_24h,
        "next_event": next_event,
        "markets": markets,
        "risks": risks[:8],
        "market_is_fresh": bool(market_is_fresh),
        "market_fetched_at": str(market_fetched_at or ""),
        "calendar_is_fresh": bool(calendar_is_fresh),
        "calendar_fetched_at": str(calendar_fetched_at or ""),
        "exchange_calendar_enabled": bool(exchange_calendar_enabled),
    }
