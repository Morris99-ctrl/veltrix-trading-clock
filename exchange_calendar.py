"""Official exchange cash-market holiday and early-close overlays.

The bundled schedule is deliberately finite and source-attributed. It covers
published ASX, TSE/JPX, London Stock Exchange and NYSE dates from late 2026
through 2027. It is not a broker-hours feed and must be refreshed when an
exchange publishes amendments or the next year's calendar.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable

from session_engine import SessionDefinition, SessionState, get_session_state, parse_hhmm

DATA_CHECKED_DATE = date(2026, 11, 23)

EXCHANGE_BY_SESSION = {
    "sydney": "asx",
    "tokyo": "jpx_tse",
    "london": "lse",
    "new_york": "nyse",
}


@dataclass(frozen=True)
class ExchangeCalendarInfo:
    key: str
    name: str
    timezone_name: str
    coverage_from: date
    coverage_to: date
    source_name: str
    source_url: str


@dataclass(frozen=True)
class ExchangeDayEvent:
    exchange_key: str
    event_date: date
    title: str
    status: str  # CLOSED or EARLY_CLOSE
    close_time: time | None = None
    note: str = ""


EXCHANGE_CALENDARS: dict[str, ExchangeCalendarInfo] = {
    "asx": ExchangeCalendarInfo(
        "asx", "ASX Cash Market", "Australia/Sydney",
        date(2026, 1, 1), date(2027, 12, 31),
        "ASX Trade cash-market trading calendar",
        "https://www.asx.com.au/markets/market-resources/trading-hours-calendar/cash-market-trading-hours/trading-calendar",
    ),
    "jpx_tse": ExchangeCalendarInfo(
        "jpx_tse", "Tokyo Stock Exchange (JPX)", "Asia/Tokyo",
        date(2026, 1, 1), date(2027, 12, 31),
        "Japan Exchange Group market holidays",
        "https://www.jpx.co.jp/english/corporate/about-jpx/calendar/index.html",
    ),
    "lse": ExchangeCalendarInfo(
        "lse", "London Stock Exchange", "Europe/London",
        date(2026, 8, 31), date(2027, 12, 31),
        "London Stock Exchange business days",
        "https://www.londonstockexchange.com/en/resources/markets-products/business-days",
    ),
    "nyse": ExchangeCalendarInfo(
        "nyse", "New York Stock Exchange", "America/New_York",
        date(2026, 1, 1), date(2027, 12, 31),
        "NYSE holidays and trading hours",
        "https://www.nyse.com/trade/hours-calendars",
    ),
}


def _day(
    exchange: str, value: str, title: str, *, close: str | None = None,
    note: str = "", status: str | None = None,
) -> ExchangeDayEvent:
    if status is None:
        status = "EARLY_CLOSE" if close else "CLOSED"
    return ExchangeDayEvent(
        exchange_key=exchange,
        event_date=date.fromisoformat(value),
        title=title,
        status=status,
        close_time=parse_hhmm(close) if close else None,
        note=note,
    )


_EVENTS: tuple[ExchangeDayEvent, ...] = (
    # ASX Trade cash market, calendar years 2026-2027.
    _day("asx", "2026-01-01", "New Year's Day"),
    _day("asx", "2026-01-26", "Australia Day"),
    _day("asx", "2026-04-03", "Good Friday"),
    _day("asx", "2026-04-06", "Easter Monday"),
    _day("asx", "2026-04-25", "ANZAC Day"),
    _day("asx", "2026-06-08", "King's Birthday"),
    _day("asx", "2026-12-24", "Christmas Eve early close", close="14:10", note="Normal trading ceases at 14:10 Sydney time."),
    _day("asx", "2026-12-25", "Christmas Day"),
    _day("asx", "2026-12-28", "Boxing Day substitute"),
    _day("asx", "2026-12-31", "Year-end early close", close="14:10", note="Normal trading ceases at 14:10 Sydney time."),
    _day("asx", "2027-01-01", "New Year's Day"),
    _day("asx", "2027-01-26", "Australia Day"),
    _day("asx", "2027-03-26", "Good Friday"),
    _day("asx", "2027-03-29", "Easter Monday"),
    _day("asx", "2027-06-14", "King's Birthday"),
    _day("asx", "2027-12-24", "Christmas Eve early close", close="14:10", note="Normal trading ceases at 14:10 Sydney time."),
    _day("asx", "2027-12-27", "Christmas Day substitute"),
    _day("asx", "2027-12-28", "Boxing Day substitute"),
    _day("asx", "2027-12-31", "Year-end early close", close="14:10", note="Normal trading ceases at 14:10 Sydney time."),

    # Tokyo Stock Exchange / JPX cash market holidays. JPX's separate
    # derivatives holiday-trading programme is intentionally not included.
    *(
        _day("jpx_tse", d, title) for d, title in (
            ("2026-01-01", "New Year's Day"), ("2026-01-02", "Market holiday"),
            ("2026-01-03", "Market holiday"), ("2026-01-12", "Coming of Age Day"),
            ("2026-02-11", "National Foundation Day"), ("2026-02-23", "Emperor's Birthday"),
            ("2026-03-20", "Vernal Equinox"), ("2026-04-29", "Showa Day"),
            ("2026-05-03", "Constitution Memorial Day"), ("2026-05-04", "Greenery Day"),
            ("2026-05-05", "Children's Day"), ("2026-05-06", "Constitution Memorial Day observed"),
            ("2026-07-20", "Marine Day"), ("2026-08-11", "Mountain Day"),
            ("2026-09-21", "Respect for the Aged Day"), ("2026-09-22", "National holiday"),
            ("2026-09-23", "Autumnal Equinox"), ("2026-10-12", "Sports Day"),
            ("2026-11-03", "Culture Day"), ("2026-11-23", "Labor Thanksgiving Day"),
            ("2026-12-31", "Year-end market holiday"),
            ("2027-01-01", "New Year's Day"), ("2027-01-02", "Market holiday"),
            ("2027-01-03", "Market holiday"), ("2027-01-11", "Coming of Age Day"),
            ("2027-02-11", "National Foundation Day"), ("2027-02-23", "Emperor's Birthday"),
            ("2027-03-21", "Vernal Equinox"), ("2027-03-22", "Vernal Equinox observed"),
            ("2027-04-29", "Showa Day"), ("2027-05-03", "Constitution Memorial Day"),
            ("2027-05-04", "Greenery Day"), ("2027-05-05", "Children's Day"),
            ("2027-07-19", "Marine Day"), ("2027-08-11", "Mountain Day"),
            ("2027-09-20", "Respect for the Aged Day"), ("2027-09-23", "Autumnal Equinox"),
            ("2027-10-11", "Sports Day"), ("2027-11-03", "Culture Day"),
            ("2027-11-23", "Labor Thanksgiving Day"), ("2027-12-31", "Year-end market holiday"),
        )
    ),

    # London Stock Exchange dates currently listed in its published business-day table.
    _day("lse", "2026-08-31", "Summer Bank Holiday"),
    _day("lse", "2026-12-24", "Christmas Eve early closing process", close="12:30", status="CLOSE_PROCESS",
         note="LSE says the markets closing process commences from 12:30 London time; this is a process-start marker, not a separately published continuous-trading cutoff."),
    _day("lse", "2026-12-25", "Christmas Day"),
    _day("lse", "2026-12-28", "Boxing Day substitute"),
    _day("lse", "2026-12-31", "New Year's Eve early closing process", close="12:30", status="CLOSE_PROCESS",
         note="LSE says the markets closing process commences from 12:30 London time; this is a process-start marker, not a separately published continuous-trading cutoff."),
    _day("lse", "2027-01-01", "New Year's Day"),
    _day("lse", "2027-03-26", "Good Friday"),
    _day("lse", "2027-03-29", "Easter Monday"),
    _day("lse", "2027-05-03", "Early May Bank Holiday"),
    _day("lse", "2027-05-31", "Spring Bank Holiday"),
    _day("lse", "2027-08-30", "Summer Bank Holiday"),
    _day("lse", "2027-12-24", "Christmas Eve early closing process", close="12:30", status="CLOSE_PROCESS",
         note="LSE says the markets closing process commences from 12:30 London time; this is a process-start marker, not a separately published continuous-trading cutoff."),
    _day("lse", "2027-12-27", "Christmas Day substitute"),
    _day("lse", "2027-12-28", "Boxing Day substitute"),
    _day("lse", "2027-12-31", "New Year's Eve early closing process", close="12:30", status="CLOSE_PROCESS",
         note="LSE says the markets closing process commences from 12:30 London time; this is a process-start marker, not a separately published continuous-trading cutoff."),

    # NYSE core cash-market holidays / early closes.
    *(
        _day("nyse", d, title) for d, title in (
            ("2026-01-01", "New Year's Day"), ("2026-01-19", "Martin Luther King Jr. Day"),
            ("2026-02-16", "Washington's Birthday"), ("2026-04-03", "Good Friday"),
            ("2026-05-25", "Memorial Day"), ("2026-06-19", "Juneteenth"),
            ("2026-07-03", "Independence Day observed"), ("2026-09-07", "Labor Day"),
            ("2026-11-26", "Thanksgiving Day"), ("2026-12-25", "Christmas Day"),
            ("2027-01-01", "New Year's Day"), ("2027-01-18", "Martin Luther King Jr. Day"),
            ("2027-02-15", "Washington's Birthday"), ("2027-03-26", "Good Friday"),
            ("2027-05-31", "Memorial Day"), ("2027-06-18", "Juneteenth observed"),
            ("2027-07-05", "Independence Day observed"), ("2027-09-06", "Labor Day"),
            ("2027-11-25", "Thanksgiving Day"), ("2027-12-24", "Christmas Day observed"),
        )
    ),
    _day("nyse", "2026-11-27", "Day after Thanksgiving early close", close="13:00",
         note="NYSE states 1:00 p.m. Eastern early close."),
    _day("nyse", "2026-12-24", "Christmas Eve early close", close="13:00",
         note="NYSE states 1:00 p.m. Eastern early close."),
    _day("nyse", "2027-11-26", "Day after Thanksgiving early close", close="13:00",
         note="NYSE states 1:00 p.m. Eastern early close."),
)

EVENTS_BY_EXCHANGE_DATE = {
    (event.exchange_key, event.event_date): event for event in _EVENTS
}


def get_exchange_calendar_info(exchange_key: str) -> ExchangeCalendarInfo:
    try:
        return EXCHANGE_CALENDARS[exchange_key]
    except KeyError as exc:
        raise ValueError(f"Unknown exchange calendar: {exchange_key!r}.") from exc


def get_exchange_event(exchange_key: str, event_date: date) -> ExchangeDayEvent | None:
    """Return the published exception for an exchange-local date, if any."""
    return EVENTS_BY_EXCHANGE_DATE.get((exchange_key, event_date))


def calendar_coverage_status(exchange_key: str, event_date: date) -> str:
    info = get_exchange_calendar_info(exchange_key)
    return "PUBLISHED" if info.coverage_from <= event_date <= info.coverage_to else "OUT_OF_RANGE"


def upcoming_exchange_events(
    now_utc: datetime,
    *,
    days_ahead: int = 45,
) -> tuple[ExchangeDayEvent, ...]:
    if now_utc.tzinfo is None:
        raise ValueError("Upcoming exchange events require a timezone-aware datetime.")
    end_date = now_utc.astimezone(timezone.utc).date() + timedelta(days=days_ahead)
    today = now_utc.astimezone(timezone.utc).date()
    return tuple(sorted(
        (
            event for event in _EVENTS
            if today <= event.event_date <= end_date
        ),
        key=lambda event: (event.event_date, event.exchange_key),
    ))


def _next_valid_open(session: SessionDefinition, exchange_key: str, after_date: date) -> datetime:
    for offset in range(1, 370):
        candidate_date = after_date + timedelta(days=offset)
        if candidate_date.weekday() not in session.weekdays:
            continue
        event = get_exchange_event(exchange_key, candidate_date)
        if event and event.status == "CLOSED":
            continue
        return datetime.combine(candidate_date, session.opens, tzinfo=session.tz)
    raise RuntimeError(f"Could not find the next exchange opening for {session.name}.")


def get_exchange_aware_session_state(
    session: SessionDefinition,
    now: datetime,
    *,
    enabled: bool,
) -> SessionState:
    """Overlay official cash-market full-day and early-close exceptions on a session state.

    When the calendar is enabled, events are applied only for the venue associated
    with the session key. Dates beyond the published dataset are marked OUT_OF_RANGE
    rather than silently treated as verified normal exchange days.
    """
    state = get_session_state(session, now)
    if not enabled:
        return state

    exchange_key = EXCHANGE_BY_SESSION.get(session.key)
    if exchange_key is None:
        return replace(state, calendar_status="NO_VENUE_MAPPING")

    local_date = state.local_now.date()
    coverage = calendar_coverage_status(exchange_key, local_date)
    event = get_exchange_event(exchange_key, local_date)

    if event and event.status == "CLOSED":
        next_open = _next_valid_open(session, exchange_key, local_date)
        return SessionState(
            definition=session,
            local_now=state.local_now,
            is_open=False,
            transition_at=next_open,
            transition_kind="OPEN",
            seconds_to_transition=max(
                0, int((next_open.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds())
            ),
            calendar_status="EXCHANGE_HOLIDAY",
            calendar_event=event.title,
            calendar_close_time=None,
        )

    if event and event.status == "CLOSE_PROCESS" and event.close_time is not None:
        process_at = datetime.combine(local_date, event.close_time, tzinfo=session.tz)
        if now.astimezone(timezone.utc) < process_at.astimezone(timezone.utc):
            if state.is_open:
                return SessionState(
                    definition=session,
                    local_now=state.local_now,
                    is_open=True,
                    transition_at=process_at,
                    transition_kind="CLOSE_PROCESS",
                    seconds_to_transition=max(
                        0, int((process_at.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds())
                    ),
                    calendar_status="CLOSING_PROCESS",
                    calendar_event=event.title,
                    calendar_close_time=event.close_time,
                )
            return replace(
                state,
                calendar_status="CLOSING_PROCESS",
                calendar_event=event.title,
                calendar_close_time=event.close_time,
            )
        return replace(
            state,
            calendar_status="CLOSING_PROCESS_PASSED",
            calendar_event=event.title,
            calendar_close_time=event.close_time,
        )

    if event and event.status == "EARLY_CLOSE" and event.close_time is not None:
        close_at = datetime.combine(local_date, event.close_time, tzinfo=session.tz)
        if now.astimezone(timezone.utc) < close_at.astimezone(timezone.utc) and state.is_open:
            return SessionState(
                definition=session,
                local_now=state.local_now,
                is_open=True,
                transition_at=close_at,
                transition_kind="CLOSE",
                seconds_to_transition=max(
                    0, int((close_at.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds())
                ),
                calendar_status="EARLY_CLOSE",
                calendar_event=event.title,
                calendar_close_time=event.close_time,
            )
        if now.astimezone(timezone.utc) >= close_at.astimezone(timezone.utc):
            next_open = _next_valid_open(session, exchange_key, local_date)
            return SessionState(
                definition=session,
                local_now=state.local_now,
                is_open=False,
                transition_at=next_open,
                transition_kind="OPEN",
                seconds_to_transition=max(
                    0, int((next_open.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds())
                ),
                calendar_status="EARLY_CLOSE_PASSED",
                calendar_event=event.title,
                calendar_close_time=event.close_time,
            )

        return replace(
            state,
            calendar_status="EARLY_CLOSE",
            calendar_event=event.title,
            calendar_close_time=event.close_time,
        )

    status = "SCHEDULED" if coverage == "PUBLISHED" else "OUT_OF_RANGE"
    return replace(state, calendar_status=status, calendar_event=None, calendar_close_time=None)
