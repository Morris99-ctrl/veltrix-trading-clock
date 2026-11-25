"""Market Intelligence Engine: causal regimes, volatility and cross-asset context.

All displayed metrics are descriptive research outputs. Regime labels use
completed OHLC bars up to the observation; forward outcomes are never used to
produce the current label. Provider data is treated as indicative monitoring
data, not execution-grade pricing.
"""
from __future__ import annotations

import math
from dataclasses import asdict, fields
from datetime import datetime, timezone
from itertools import combinations
from statistics import stdev
from typing import Any, Iterable, Mapping

from market_data import OHLCBar
from regime_engine import RegimeConfig, analyse_market_regimes
from volatility_engine import (
    calculate_atr,
    calculate_daily_expected_move,
    normalise_bars,
)

TRADING_DAYS_PER_YEAR = 252
CORRELATION_WINDOWS = (20, 60)


def _daily_bars(raw_bars: Iterable[dict[str, Any] | OHLCBar]) -> list[OHLCBar]:
    """Return one valid bar per UTC calendar date, retaining the latest bar."""
    by_date: dict[str, OHLCBar] = {}
    for bar in normalise_bars(raw_bars):
        day = bar.timestamp.astimezone(timezone.utc).date().isoformat()
        by_date[day] = bar
    return [by_date[key] for key in sorted(by_date)]


def _returns_by_date(bars: list[OHLCBar]) -> dict[str, float]:
    result: dict[str, float] = {}
    for previous, current in zip(bars, bars[1:]):
        if previous.close <= 0 or current.close <= 0:
            continue
        value = math.log(current.close / previous.close)
        if math.isfinite(value):
            result[current.timestamp.astimezone(timezone.utc).date().isoformat()] = value
    return result


def _annualised_volatility(returns: list[float], minimum: int) -> float | None:
    if len(returns) < minimum:
        return None
    value = stdev(returns) * math.sqrt(TRADING_DAYS_PER_YEAR) * 100.0
    return value if math.isfinite(value) else None


def _percentile_rank(history: list[float], current: float) -> float | None:
    valid = [value for value in history if math.isfinite(value)]
    if not valid or not math.isfinite(current):
        return None
    return sum(value <= current for value in valid) / len(valid) * 100.0


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 3:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    left_delta = [value - left_mean for value in left]
    right_delta = [value - right_mean for value in right]
    left_ss = sum(value * value for value in left_delta)
    right_ss = sum(value * value for value in right_delta)
    if left_ss <= 1e-24 or right_ss <= 1e-24:
        return None
    covariance = sum(a * b for a, b in zip(left_delta, right_delta))
    value = covariance / math.sqrt(left_ss * right_ss)
    return max(-1.0, min(1.0, value)) if math.isfinite(value) else None


def _coerce_regime_config(value: RegimeConfig | Mapping[str, Any] | None) -> RegimeConfig:
    if isinstance(value, RegimeConfig):
        return value.validate()
    allowed = {item.name for item in fields(RegimeConfig)}
    supplied = {key: raw for key, raw in dict(value or {}).items() if key in allowed}
    return RegimeConfig(**supplied).validate()


def _regime_summary(
    bars: list[OHLCBar], config: RegimeConfig,
) -> dict[str, Any]:
    if not bars:
        return {
            "state": "INSUFFICIENT DATA",
            "label": "N/A",
            "evidence": {},
            "distribution": {},
            "classified_bars": 0,
            "warmup_bars": 0,
            "as_of_utc": None,
            "method": "Causal ER + ATR-normalised slope + ATR shock tests",
        }
    try:
        analysis = analyse_market_regimes(bars, config)
    except (ValueError, TypeError, OverflowError) as exc:
        return {
            "state": "ANALYSIS UNAVAILABLE",
            "label": "N/A",
            "evidence": {},
            "distribution": {},
            "classified_bars": 0,
            "warmup_bars": len(bars),
            "as_of_utc": bars[-1].timestamp_utc,
            "error": str(exc),
            "method": "Causal ER + ATR-normalised slope + ATR shock tests",
        }
    latest = analysis.get("latest", {})
    evidence = {
        "efficiency_ratio": latest.get("efficiency_ratio"),
        "normalised_slope_atr": latest.get("normalised_slope_atr"),
        "fast_slow_atr_ratio": latest.get("volatility_ratio"),
        "true_range_vs_prior_atr": latest.get("true_range_vs_prior_atr"),
        "close": latest.get("close"),
    }
    return {
        "state": "CLASSIFIED" if latest.get("regime") != "WARMUP" else "WARMUP",
        "label": str(latest.get("regime") or "N/A"),
        "evidence": evidence,
        "distribution": analysis.get("distribution", {}),
        "classified_bars": int(analysis.get("metadata", {}).get("classified_bars", 0)),
        "warmup_bars": int(analysis.get("metadata", {}).get("warmup_bars", 0)),
        "as_of_utc": latest.get("timestamp_utc"),
        "method": str(analysis.get("metadata", {}).get("classification_method") or
                      "Causal ER + ATR-normalised slope + ATR shock tests"),
        "uses_future_data_for_label": False,
    }


def _volatility_summary(bars: list[OHLCBar]) -> dict[str, Any]:
    returns = [
        math.log(current.close / previous.close)
        for previous, current in zip(bars, bars[1:])
        if previous.close > 0 and current.close > 0
    ]
    rv10 = _annualised_volatility(returns[-10:], 10)
    rv20 = _annualised_volatility(returns[-20:], 20)
    rv60 = _annualised_volatility(returns[-60:], 60)

    # The percentile uses only the latest 60 rolling windows. Avoid
    # calculating older windows that cannot affect the displayed result.
    rolling_20: list[float] = []
    first_end = max(20, len(returns) - 59)
    for end in range(first_end, len(returns) + 1):
        value = _annualised_volatility(returns[end - 20:end], 20)
        if value is not None:
            rolling_20.append(value)
    percentile = _percentile_rank(rolling_20, rv20) if rv20 is not None and len(rolling_20) >= 5 else None

    latest_close = bars[-1].close if bars else None
    atr = calculate_atr(bars, 14) if bars else None
    atr_pct = (atr / latest_close * 100.0) if atr is not None and latest_close else None
    expected = calculate_daily_expected_move(bars, lookback=20) if bars else {
        "expected_move_pct": None, "expected_move_abs": None,
        "lower_1sigma": None, "upper_1sigma": None, "samples": 0,
        "reference_close": latest_close,
    }

    state = "INSUFFICIENT DATA"
    expansion_ratio = (rv10 / rv60) if rv10 is not None and rv60 is not None and rv60 > 1e-12 else None
    if expansion_ratio is not None and expansion_ratio >= 1.25:
        state = "EXPANDING"
    elif expansion_ratio is not None and expansion_ratio <= 0.80:
        state = "CONTRACTING"
    elif percentile is not None and percentile >= 80:
        state = "ELEVATED"
    elif percentile is not None and percentile <= 20:
        state = "QUIET"
    elif rv20 is not None:
        state = "BALANCED"

    return {
        "state": state,
        "realised_vol_10d_ann_pct": rv10,
        "realised_vol_20d_ann_pct": rv20,
        "realised_vol_60d_ann_pct": rv60,
        "rv20_percentile_lookback": percentile,
        "rv20_percentile_samples": len(rolling_20),
        "expansion_ratio_10d_to_60d": expansion_ratio,
        "atr14": atr,
        "atr14_pct": atr_pct,
        "expected_move_1d_pct": expected.get("expected_move_pct"),
        "expected_move_1d_abs": expected.get("expected_move_abs"),
        "expected_move_samples": expected.get("samples", 0),
        "reference_close": latest_close,
        "annualisation": "Sample standard deviation of daily log returns × sqrt(252)",
    }


def _correlations(
    instruments: list[dict[str, Any]],
    returns_by_key: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for left, right in combinations(instruments, 2):
        left_key = str(left.get("key", ""))
        right_key = str(right.get("key", ""))
        left_returns = returns_by_key.get(left_key, {})
        right_returns = returns_by_key.get(right_key, {})
        aligned_days = sorted(set(left_returns).intersection(right_returns))
        row: dict[str, Any] = {
            "left_key": left_key,
            "right_key": right_key,
            "left_name": str(left.get("name") or left_key),
            "right_name": str(right.get("name") or right_key),
            "samples_available": len(aligned_days),
        }
        for window in CORRELATION_WINDOWS:
            paired = aligned_days[-window:]
            minimum = 10 if window == 20 else 20
            row[f"correlation_{window}d"] = (
                _pearson([left_returns[day] for day in paired],
                         [right_returns[day] for day in paired])
                if len(paired) >= minimum else None
            )
            row[f"samples_{window}d"] = len(paired)
        results.append(row)
    return results


def _market_breadth(
    breadth_universe: Mapping[str, Iterable[dict[str, Any] | OHLCBar]] | None,
) -> dict[str, Any]:
    """Calculate simple member advances only when constituent OHLC is supplied."""
    if not isinstance(breadth_universe, Mapping) or len(breadth_universe) < 2:
        return {
            "state": "UNAVAILABLE",
            "reason": "No constituent-level breadth universe is configured.",
            "constituents": 0,
            "advancers": None,
            "decliners": None,
            "unchanged": None,
            "advance_share_pct": None,
            "as_of_utc": None,
        }

    series = {
        str(symbol): _daily_bars(raw)
        for symbol, raw in breadth_universe.items()
    }
    date_sets = [set(item.timestamp.astimezone(timezone.utc).date().isoformat() for item in bars)
                 for bars in series.values() if len(bars) >= 2]
    if len(date_sets) != len(series) or not date_sets:
        return {
            "state": "UNAVAILABLE",
            "reason": "Each constituent needs at least two daily bars.",
            "constituents": len(series),
            "advancers": None, "decliners": None, "unchanged": None,
            "advance_share_pct": None, "as_of_utc": None,
        }
    common_dates = sorted(set.intersection(*date_sets))
    if not common_dates:
        return {
            "state": "UNAVAILABLE",
            "reason": "Constituent histories have no common completed trading date.",
            "constituents": len(series),
            "advancers": None, "decliners": None, "unchanged": None,
            "advance_share_pct": None, "as_of_utc": None,
        }
    day = common_dates[-1]
    # common_dates is the intersection of every constituent's dates, so its
    # penultimate entry is the latest valid prior date for every series.
    previous_day = common_dates[-2] if len(common_dates) >= 2 else None
    counts = {"advancers": 0, "decliners": 0, "unchanged": 0}
    for bars in series.values():
        indexed = {item.timestamp.astimezone(timezone.utc).date().isoformat(): item.close for item in bars}
        if previous_day is None or previous_day not in indexed:
            return {
                "state": "UNAVAILABLE",
                "reason": "A shared prior trading date is missing for one or more constituents.",
                "constituents": len(series),
                "advancers": None, "decliners": None, "unchanged": None,
                "advance_share_pct": None, "as_of_utc": None,
            }
        previous = indexed[previous_day]
        current = indexed[day]
        counts["advancers" if current > previous else
               "decliners" if current < previous else "unchanged"] += 1
    active = counts["advancers"] + counts["decliners"]
    return {
        "state": "AVAILABLE",
        "reason": "Equal-weight constituent advances based on the latest common completed date.",
        "constituents": len(series),
        **counts,
        "advance_share_pct": (counts["advancers"] / active * 100.0) if active else None,
        "as_of_utc": day,
    }


def build_market_intelligence_snapshot(
    market_snapshot: Mapping[str, Any] | None,
    instruments: Iterable[Mapping[str, Any]],
    *,
    market_is_fresh: bool,
    now_utc: datetime | None = None,
    regime_config: RegimeConfig | Mapping[str, Any] | None = None,
    breadth_universe: Mapping[str, Iterable[dict[str, Any] | OHLCBar]] | None = None,
) -> dict[str, Any]:
    """Build a compact, auditable intelligence snapshot from existing OHLC data."""
    snapshot = market_snapshot if isinstance(market_snapshot, Mapping) else {}
    raw_assets = snapshot.get("assets", {})
    raw_assets = raw_assets if isinstance(raw_assets, Mapping) else {}
    configured = [dict(item) for item in instruments if isinstance(item, Mapping)]
    config = _coerce_regime_config(regime_config)
    generated = now_utc or datetime.now(timezone.utc)
    if generated.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware.")
    generated = generated.astimezone(timezone.utc)

    asset_results: dict[str, dict[str, Any]] = {}
    returns_by_key: dict[str, dict[str, float]] = {}
    for instrument in configured:
        key = str(instrument.get("key") or "")
        raw_asset = raw_assets.get(key, {})
        raw_asset = raw_asset if isinstance(raw_asset, Mapping) else {}
        daily = _daily_bars(raw_asset.get("daily_bars", []))
        intraday = normalise_bars(raw_asset.get("intraday_bars", []))
        quote_bar = intraday[-1] if intraday else (daily[-1] if daily else None)
        error = str(raw_asset.get("error") or "")
        if not daily and not intraday:
            freshness = "NO DATA"
        elif not market_is_fresh:
            freshness = "CACHED"
        elif error or not daily:
            freshness = "PARTIAL"
        else:
            freshness = "UPDATED"

        regime = _regime_summary(daily, config)
        volatility = _volatility_summary(daily)
        asset_results[key] = {
            "key": key,
            "name": str(instrument.get("name") or key),
            "symbol": str(instrument.get("symbol") or ""),
            "unit": str(instrument.get("unit") or ""),
            "quote": quote_bar.close if quote_bar else None,
            "quote_time_utc": quote_bar.timestamp_utc if quote_bar else None,
            "daily_bars": len(daily),
            "intraday_bars": len(intraday),
            "freshness": freshness,
            "provider_error": error,
            "regime": regime,
            "volatility": volatility,
        }
        returns_by_key[key] = _returns_by_date(daily)

    observed_assets = [
        item for item in asset_results.values()
        if int(item.get("daily_bars", 0)) + int(item.get("intraday_bars", 0)) > 0
    ]
    freshness_values = [str(item.get("freshness") or "NO DATA") for item in asset_results.values()]
    if not observed_assets:
        feed_state = "NO DATA"
    elif market_is_fresh and all(value == "UPDATED" for value in freshness_values):
        feed_state = "UPDATED"
    elif market_is_fresh:
        feed_state = "PARTIAL"
    else:
        feed_state = "CACHED"

    return {
        "generated_at_utc": generated.isoformat(),
        "fetched_at": str(snapshot.get("fetched_at") or ""),
        "provider": "Yahoo Finance public chart · indicative monitoring data",
        "feed_state": feed_state,
        "assets": asset_results,
        "correlations": _correlations(configured, returns_by_key),
        "breadth": _market_breadth(breadth_universe),
        "methodology": {
            "regime_labels_use_future_data": False,
            "forward_returns_used_for_current_label": False,
            "volatility_annualisation": "sqrt(252) trading-day convention",
            "correlation": "Pearson correlation of aligned daily log returns",
            "market_breadth": "Equal-weight constituent advances; unavailable without a configured universe",
        },
    }
