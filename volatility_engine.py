"""Transparent realised-volatility, ATR, expected-move and regime calculations."""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime, time, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from market_data import OHLCBar
from session_engine import SessionDefinition, get_session_state


def normalise_bars(raw_bars: Iterable[dict[str, Any] | OHLCBar]) -> list[OHLCBar]:
    bars: list[OHLCBar] = []
    for raw in raw_bars:
        try:
            bar = raw if isinstance(raw, OHLCBar) else OHLCBar.from_dict(raw)
            if bar.timestamp.tzinfo is None or min(bar.open, bar.high, bar.low, bar.close) <= 0:
                continue
            bars.append(bar)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    bars.sort(key=lambda item: item.timestamp)
    return bars


def realised_volatility(bars: Iterable[OHLCBar], *, max_gap_minutes: float = 12.5) -> dict[str, float | int | None]:
    """Close-to-close realised volatility: sqrt(sum(log-return^2)) in percent."""
    ordered = sorted(bars, key=lambda item: item.timestamp)
    squared_returns: list[float] = []
    for previous, current in zip(ordered, ordered[1:]):
        gap = (current.timestamp - previous.timestamp).total_seconds() / 60
        if gap <= 0 or gap > max_gap_minutes:
            continue  # Do not bridge overnight or missing-data gaps.
        value = math.log(current.close / previous.close)
        squared_returns.append(value * value)
    if not squared_returns:
        return {"realised_vol_pct": None, "returns": 0}
    return {
        "realised_vol_pct": math.sqrt(sum(squared_returns)) * 100,
        "returns": len(squared_returns),
    }


def session_bar_groups(bars: Iterable[OHLCBar], session: SessionDefinition) -> dict[str, list[OHLCBar]]:
    """Bucket bars into the configured local weekday session windows."""
    groups: dict[str, list[OHLCBar]] = defaultdict(list)
    zone = session.tz
    for bar in bars:
        local = bar.timestamp.astimezone(zone)
        local_clock = local.timetz().replace(tzinfo=None)
        if local.weekday() not in session.weekdays:
            continue
        if session.opens <= local_clock < session.closes:
            groups[local.date().isoformat()].append(bar)
    return dict(groups)


def _range_pct(bars: list[OHLCBar]) -> float | None:
    if not bars or bars[0].open <= 0:
        return None
    highest = max(item.high for item in bars)
    lowest = min(item.low for item in bars)
    return (highest - lowest) / bars[0].open * 100


def _same_elapsed_subset(bars: list[OHLCBar], session: SessionDefinition, elapsed_minutes: float) -> list[OHLCBar]:
    selected = []
    for bar in bars:
        local = bar.timestamp.astimezone(session.tz)
        elapsed = (local.hour * 60 + local.minute) - (session.opens.hour * 60 + session.opens.minute)
        if 0 <= elapsed <= elapsed_minutes:
            selected.append(bar)
    return selected


def session_volatility_report(
    bars: Iterable[dict[str, Any] | OHLCBar], sessions: list[SessionDefinition],
    *, now: datetime | None = None, baseline_sessions: int = 3,
    expansion_multiple: float = 1.5, contraction_multiple: float = 0.67,
) -> list[dict[str, Any]]:
    """Return most recent session observation and optional live regime comparison per session.

    Expansion/contraction compares the current session's realised volatility so far
    with the median of previous sessions over the same elapsed time window.
    """
    ordered = normalise_bars(bars)
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    reports: list[dict[str, Any]] = []
    for session in sessions:
        groups = session_bar_groups(ordered, session)
        local_now = now_utc.astimezone(session.tz)
        state = get_session_state(session, now_utc)
        current_date = local_now.date().isoformat()
        current_group = groups.get(current_date, [])
        is_current_live = state.is_open and bool(current_group)

        if is_current_live:
            chosen_date = current_date
            chosen_bars = current_group
            observation_state = "LIVE SESSION"
        elif groups:
            chosen_date = max(groups)
            chosen_bars = groups[chosen_date]
            observation_state = "LAST SESSION"
        else:
            reports.append({
                "session_key": session.key, "session_name": session.name, "date": "",
                "state": "NO DATA", "realised_vol_pct": None, "range_pct": None,
                "returns": 0, "bars": 0, "regime": "NO DATA", "ratio": None,
                "baseline_pct": None, "baseline_count": 0,
            })
            continue

        rv = realised_volatility(chosen_bars)
        regime = "BUILDING" if is_current_live else "HISTORICAL"
        ratio = None
        baseline_pct = None
        baseline_count = 0
        if is_current_live and rv["returns"] >= 4:
            regime = "WARMING UP"
            elapsed = (local_now.hour * 60 + local_now.minute) - (session.opens.hour * 60 + session.opens.minute)
            prior_values: list[float] = []
            for prior_date, prior_bars in groups.items():
                if prior_date >= current_date:
                    continue
                sample = _same_elapsed_subset(prior_bars, session, elapsed)
                sample_rv = realised_volatility(sample)
                if sample_rv["realised_vol_pct"] is not None and int(sample_rv["returns"] or 0) >= 3:
                    prior_values.append(float(sample_rv["realised_vol_pct"]))
            prior_values = prior_values[-max(3, int(baseline_sessions)):]
            baseline_count = len(prior_values)
            if baseline_count >= max(3, int(baseline_sessions)):
                baseline_pct = statistics.median(prior_values)
                current_pct = float(rv["realised_vol_pct"] or 0.0)
                if baseline_pct > 0.00001:
                    ratio = current_pct / baseline_pct
                    regime = "NORMAL"
                    if ratio >= max(1.05, float(expansion_multiple)):
                        regime = "EXPANSION"
                    elif ratio <= min(0.95, float(contraction_multiple)):
                        regime = "CONTRACTION"

        reports.append({
            "session_key": session.key, "session_name": session.name,
            "date": chosen_date, "state": observation_state,
            "realised_vol_pct": rv["realised_vol_pct"], "range_pct": _range_pct(chosen_bars),
            "returns": int(rv["returns"] or 0), "bars": len(chosen_bars),
            "regime": regime, "ratio": ratio, "baseline_pct": baseline_pct,
            "baseline_count": baseline_count,
        })
    return reports


def calculate_atr(daily_bars: Iterable[dict[str, Any] | OHLCBar], period: int = 14) -> float | None:
    """Wilder ATR calculated from daily high/low/previous-close True Range."""
    bars = normalise_bars(daily_bars)
    period = max(2, int(period))
    if len(bars) < period + 1:
        return None
    true_ranges = []
    for previous, current in zip(bars, bars[1:]):
        true_ranges.append(max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        ))
    if len(true_ranges) < period:
        return None
    atr = sum(true_ranges[:period]) / period
    for value in true_ranges[period:]:
        atr = ((atr * (period - 1)) + value) / period
    return atr


def calculate_daily_expected_move(
    daily_bars: Iterable[dict[str, Any] | OHLCBar], *, lookback: int = 20,
) -> dict[str, float | int | None]:
    """One-day 1-sigma close-to-close move from rolling log-return standard deviation."""
    bars = normalise_bars(daily_bars)
    lookback = max(5, int(lookback))
    closes = [bar.close for bar in bars if bar.close > 0]
    returns = [math.log(curr / prev) for prev, curr in zip(closes, closes[1:])]
    recent = returns[-lookback:]
    if len(recent) < 5 or not closes:
        return {"expected_move_pct": None, "expected_move_abs": None, "lower_1sigma": None,
                "upper_1sigma": None, "samples": len(recent), "reference_close": closes[-1] if closes else None}
    sigma = statistics.stdev(recent)
    reference = closes[-1]
    move = reference * sigma
    return {
        "expected_move_pct": sigma * 100,
        "expected_move_abs": move,
        "lower_1sigma": reference * math.exp(-sigma),
        "upper_1sigma": reference * math.exp(sigma),
        "samples": len(recent),
        "reference_close": reference,
    }


def instrument_summary(asset: dict[str, Any], *, atr_period: int = 14,
                       expected_move_lookback: int = 20) -> dict[str, Any]:
    intraday = normalise_bars(asset.get("intraday_bars", []))
    daily = normalise_bars(asset.get("daily_bars", []))
    latest_intraday = intraday[-1] if intraday else None
    latest_daily = daily[-1] if daily else None
    latest = latest_intraday or latest_daily
    atr = calculate_atr(daily, atr_period)
    expected = calculate_daily_expected_move(daily, lookback=expected_move_lookback)
    latest_time = latest.timestamp.isoformat() if latest else ""
    return {
        "key": asset.get("key", ""), "name": asset.get("name", ""),
        "symbol": asset.get("symbol", ""), "unit": asset.get("unit", ""),
        "quote": latest.close if latest else None, "quote_time": latest_time,
        "currency": (asset.get("intraday_meta") or asset.get("daily_meta") or {}).get("currency", ""),
        "atr": atr, "atr_period": atr_period, "expected_move": expected,
        "intraday_bar_count": len(intraday), "daily_bar_count": len(daily),
        "error": str(asset.get("error") or ""),
    }


def evaluate_volatility_regimes(reports_by_asset: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Flatten expansion/contraction observations into user-facing alert records."""
    alerts = []
    for asset_key, reports in reports_by_asset.items():
        for report in reports:
            if report.get("regime") in {"EXPANSION", "CONTRACTION"}:
                alerts.append({
                    "asset_key": asset_key,
                    "asset_name": report.get("asset_name", asset_key),
                    "session_name": report.get("session_name", ""),
                    "regime": report["regime"], "ratio": report.get("ratio"),
                    "current_rv_pct": report.get("realised_vol_pct"),
                    "baseline_rv_pct": report.get("baseline_pct"),
                    "date": report.get("date", ""),
                })
    return alerts
