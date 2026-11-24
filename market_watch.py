"""Reference FX week schedule and symbol universe for the Market Watch panel.

This is a schedule reference only. It does not assert that a broker offers a
symbol, provide a quote, account for broker holidays, or describe execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


FX_REFERENCE_TIMEZONE = "America/New_York"
FX_REFERENCE_CLOSE_TIME = time(17, 0)
FX_REFERENCE_OPEN_TIME = time(17, 0)

# Seven USD majors plus all 21 crosses among EUR, GBP, AUD, NZD, CAD, CHF and JPY.
# This is a conventional reference watchlist, not a claim about broker availability.
FX_REFERENCE_PAIRS: tuple[str, ...] = (
    "AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY",
    "AUDCAD", "AUDCHF", "AUDJPY", "AUDNZD",
    "CADCHF", "CADJPY", "CHFJPY",
    "EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "EURNZD",
    "GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", "GBPNZD",
    "NZDCAD", "NZDCHF", "NZDJPY",
)


@dataclass(frozen=True)
class FXReferenceWeekState:
    """Reference Sunday 17:00–Friday 17:00 New York FX trading-week state."""

    is_open: bool
    now_new_york: datetime
    next_transition_at: datetime
    transition_kind: str

    @property
    def seconds_to_transition(self) -> int:
        return max(0, int((self.next_transition_at.astimezone(timezone.utc) - self.now_new_york.astimezone(timezone.utc)).total_seconds()))


def fx_reference_week_state(now: datetime) -> FXReferenceWeekState:
    """Return the generic FX week reference state for an aware instant.

    New York's IANA timezone is used so the reference boundary follows DST.
    Broker-specific weekend hours, holidays, symbol restrictions and daily
    maintenance/rollover breaks are intentionally not inferred.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("FX reference-week calculations require a timezone-aware datetime.")

    zone = ZoneInfo(FX_REFERENCE_TIMEZONE)
    local = now.astimezone(zone)
    weekday = local.weekday()
    after_sunday_open = weekday == 6 and local.timetz().replace(tzinfo=None) >= FX_REFERENCE_OPEN_TIME
    before_friday_close = weekday == 4 and local.timetz().replace(tzinfo=None) < FX_REFERENCE_CLOSE_TIME
    is_open = weekday in (0, 1, 2, 3) or before_friday_close or after_sunday_open

    if is_open:
        days_to_friday = (4 - weekday) % 7
        close_date = local.date() + timedelta(days=days_to_friday)
        close_at = datetime.combine(close_date, FX_REFERENCE_CLOSE_TIME, tzinfo=zone)
        if close_at <= local:
            close_at += timedelta(days=7)
        return FXReferenceWeekState(True, local, close_at, "CLOSE")

    days_to_sunday = (6 - weekday) % 7
    open_date = local.date() + timedelta(days=days_to_sunday)
    open_at = datetime.combine(open_date, FX_REFERENCE_OPEN_TIME, tzinfo=zone)
    if open_at <= local:
        open_at += timedelta(days=7)
    return FXReferenceWeekState(False, local, open_at, "OPEN")


def fx_reference_week_label(state: FXReferenceWeekState) -> str:
    """Human-readable reference boundary for the next weekly transition."""
    day = state.next_transition_at.strftime("%a")
    time_text = state.next_transition_at.strftime("%H:%M")
    action = "CLOSES" if state.transition_kind == "CLOSE" else "OPENS"
    return f"{action} {day} {time_text} NY"
