"""Causal market-regime classification and conditional outcome research.

Phase 12 for Veltrix Trading Clock. Regime labels use only the current and
preceding completed OHLC bars. Forward returns are computed separately as
historical outcome diagnostics and never feed back into the labels.

This module is descriptive research, not a trading signal generator.
"""
from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median, mean
from typing import Any, Iterable

from market_data import OHLCBar

REGIMES = ("RANGE", "TREND_UP", "TREND_DOWN", "VOLATILITY_SHOCK", "TRANSITION")


@dataclass(frozen=True, slots=True)
class RegimeConfig:
    lookback: int = 20
    atr_fast_period: int = 14
    atr_slow_period: int = 50
    range_er_max: float = 0.25
    trend_er_min: float = 0.35
    trend_slope_atr_min: float = 0.20
    shock_atr_ratio: float = 1.80
    shock_true_range_multiple: float = 2.50
    forward_horizon: int = 10

    def validate(self) -> "RegimeConfig":
        if not 5 <= int(self.lookback) <= 500:
            raise ValueError("Lookback must be between 5 and 500 bars.")
        if not 2 <= int(self.atr_fast_period) <= 500:
            raise ValueError("Fast ATR period must be between 2 and 500 bars.")
        if not 3 <= int(self.atr_slow_period) <= 2000:
            raise ValueError("Slow ATR period must be between 3 and 2,000 bars.")
        if self.atr_fast_period >= self.atr_slow_period:
            raise ValueError("Fast ATR period must be smaller than slow ATR period.")
        if not (0.0 <= self.range_er_max < self.trend_er_min <= 1.0):
            raise ValueError("ER thresholds must satisfy 0 ≤ range threshold < trend threshold ≤ 1.")
        if not math.isfinite(self.trend_slope_atr_min) or self.trend_slope_atr_min <= 0:
            raise ValueError("Normalized trend-slope threshold must be positive and finite.")
        if not math.isfinite(self.shock_atr_ratio) or self.shock_atr_ratio <= 1:
            raise ValueError("Shock ATR ratio must be greater than 1.")
        if not math.isfinite(self.shock_true_range_multiple) or self.shock_true_range_multiple <= 1:
            raise ValueError("Shock true-range multiple must be greater than 1.")
        if not 1 <= int(self.forward_horizon) <= 1000:
            raise ValueError("Forward-return horizon must be between 1 and 1,000 bars.")
        return self


def _normalise_bars(bars: Iterable[OHLCBar | dict[str, Any]]) -> list[OHLCBar]:
    """Validate, de-duplicate by timestamp and return ascending OHLC bars."""
    by_time: dict[str, OHLCBar] = {}
    for raw in bars:
        try:
            bar = raw if isinstance(raw, OHLCBar) else OHLCBar.from_dict(raw)
            stamp = bar.timestamp
            values = (bar.open, bar.high, bar.low, bar.close)
            if not all(math.isfinite(float(value)) and float(value) > 0 for value in values):
                continue
            if bar.high < bar.low or bar.high + 1e-10 < max(bar.open, bar.close):
                continue
            if bar.low - 1e-10 > min(bar.open, bar.close):
                continue
            if bar.volume is not None and (not math.isfinite(float(bar.volume)) or bar.volume < 0):
                continue
            by_time[stamp.isoformat()] = bar
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return sorted(by_time.values(), key=lambda item: item.timestamp)


def _true_ranges(bars: list[OHLCBar]) -> list[float]:
    result: list[float] = []
    previous_close: float | None = None
    for bar in bars:
        if previous_close is None:
            value = bar.high - bar.low
        else:
            value = max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        result.append(max(0.0, float(value)))
        previous_close = bar.close
    return result


def _wilder_atr(values: list[float], period: int) -> list[float | None]:
    """Wilder ATR; first value is the simple mean of the first period TRs."""
    output: list[float | None] = [None] * len(values)
    if len(values) < period:
        return output
    current = sum(values[:period]) / period
    output[period - 1] = current
    for index in range(period, len(values)):
        current = ((current * (period - 1)) + values[index]) / period
        output[index] = current
    return output


def _efficiency_ratio(closes: list[float], end: int, lookback: int) -> float | None:
    start = end - lookback
    if start < 0:
        return None
    path = sum(abs(closes[i] - closes[i - 1]) for i in range(start + 1, end + 1))
    if path <= 1e-15:
        return 0.0
    return min(1.0, abs(closes[end] - closes[start]) / path)


def _normalised_regression_slope(closes: list[float], end: int, lookback: int,
                                  atr_reference: float | None) -> tuple[float | None, float]:
    """Return signed slope drift in ATR units and raw slope per bar."""
    start = end - lookback
    if start < 0:
        return None, 0.0
    sample = closes[start:end + 1]
    n = len(sample)
    x_mean = (n - 1) / 2.0
    y_mean = sum(sample) / n
    denominator = sum((x - x_mean) ** 2 for x in range(n))
    if denominator <= 0:
        return 0.0, 0.0
    slope = sum((x - x_mean) * (sample[x] - y_mean) for x in range(n)) / denominator
    if atr_reference is None or atr_reference <= 1e-15:
        if abs(slope) <= 1e-15:
            return 0.0, slope
        return None, slope
    return (slope * lookback) / atr_reference, slope


def _classify(er: float, slope_atr: float | None, atr_ratio: float | None,
              tr_multiple: float | None, config: RegimeConfig) -> str:
    if ((atr_ratio is not None and atr_ratio >= config.shock_atr_ratio) or
            (tr_multiple is not None and tr_multiple >= config.shock_true_range_multiple)):
        return "VOLATILITY_SHOCK"
    if slope_atr is None:
        return "TRANSITION"
    if er >= config.trend_er_min and abs(slope_atr) >= config.trend_slope_atr_min:
        return "TREND_UP" if slope_atr > 0 else "TREND_DOWN"
    if er <= config.range_er_max and abs(slope_atr) < config.trend_slope_atr_min:
        return "RANGE"
    return "TRANSITION"


def analyse_market_regimes(
    bars: Iterable[OHLCBar | dict[str, Any]],
    config: RegimeConfig | None = None,
) -> dict[str, Any]:
    """Classify bars causally and measure subsequent fixed-horizon outcomes.

    All indicators for record i are computed using bars <= i. The optional
    forward_return_pct is a post-classification research outcome using close
    i+horizon; it is intentionally not used by the classifier.
    """
    cfg = (config or RegimeConfig()).validate()
    raw_bars = list(bars)
    ordered = _normalise_bars(raw_bars)
    if not ordered:
        raise ValueError("No valid OHLC bars are available for regime analysis.")

    closes = [bar.close for bar in ordered]
    tr_values = _true_ranges(ordered)
    atr_fast = _wilder_atr(tr_values, cfg.atr_fast_period)
    atr_slow = _wilder_atr(tr_values, cfg.atr_slow_period)

    records: list[dict[str, Any]] = []
    for index, bar in enumerate(ordered):
        er = _efficiency_ratio(closes, index, cfg.lookback)
        slope_atr, raw_slope = _normalised_regression_slope(
            closes, index, cfg.lookback, atr_slow[index]
        )
        fast = atr_fast[index]
        slow = atr_slow[index]
        atr_ratio = (fast / slow) if fast is not None and slow is not None and slow > 1e-15 else None
        previous_slow = atr_slow[index - 1] if index > 0 else None
        tr_multiple = tr_values[index] / previous_slow if previous_slow is not None and previous_slow > 1e-15 else None

        ready = er is not None and slow is not None and slope_atr is not None
        regime = _classify(er, slope_atr, atr_ratio, tr_multiple, cfg) if ready else "WARMUP"
        records.append({
            "timestamp_utc": bar.timestamp_utc,
            "close": float(bar.close),
            "regime": regime,
            "efficiency_ratio": er,
            "normalised_slope_atr": slope_atr,
            "regression_slope_per_bar": raw_slope,
            "atr_fast": fast,
            "atr_slow": slow,
            "volatility_ratio": atr_ratio,
            "true_range": tr_values[index],
            "true_range_vs_prior_atr": tr_multiple,
            "forward_return_pct": None,
        })

    horizon = cfg.forward_horizon
    for index, record in enumerate(records):
        future_index = index + horizon
        if future_index < len(ordered) and record["regime"] != "WARMUP":
            record["forward_return_pct"] = (closes[future_index] / closes[index] - 1.0) * 100.0

    classified = [item for item in records if item["regime"] != "WARMUP"]
    total_classified = len(classified)
    distribution: dict[str, dict[str, float | int]] = {}
    for regime in REGIMES:
        count = sum(1 for item in classified if item["regime"] == regime)
        distribution[regime] = {
            "count": count,
            "frequency_pct": (count / total_classified * 100.0) if total_classified else 0.0,
        }

    outcomes: dict[str, dict[str, float | int | None]] = {}
    for regime in REGIMES:
        values = [float(item["forward_return_pct"]) for item in records
                  if item["regime"] == regime and item["forward_return_pct"] is not None]
        outcomes[regime] = {
            "samples": len(values),
            "mean_return_pct": mean(values) if values else None,
            "median_return_pct": median(values) if values else None,
            "positive_rate_pct": (sum(value > 0 for value in values) / len(values) * 100.0) if values else None,
            "mean_absolute_return_pct": mean(abs(value) for value in values) if values else None,
        }

    transitions: dict[str, dict[str, int]] = {regime: {target: 0 for target in REGIMES} for regime in REGIMES}
    for previous, current in zip(records, records[1:]):
        source = previous["regime"]
        target = current["regime"]
        if source in transitions and target in transitions[source]:
            transitions[source][target] += 1

    latest = next((item for item in reversed(records) if item["regime"] != "WARMUP"), records[-1])
    return {
        "config": asdict(cfg),
        "metadata": {
            "input_bars": len(raw_bars),
            "valid_bars": len(ordered),
            "classified_bars": total_classified,
            "warmup_bars": len(ordered) - total_classified,
            "first_timestamp_utc": ordered[0].timestamp_utc,
            "last_timestamp_utc": ordered[-1].timestamp_utc,
            "forward_horizon_bars": horizon,
            "classification_method": "Causal efficiency ratio + ATR-normalised regression slope + ATR shock tests",
            "classification_uses_future_data": False,
            "forward_returns_are_outcomes_only": True,
        },
        "latest": dict(latest),
        "distribution": distribution,
        "outcomes": outcomes,
        "transitions": transitions,
        "records": records,
    }


def export_regime_analysis_csv(path: str | Path, analysis: dict[str, Any]) -> None:
    """Export per-bar regime labels and diagnostics to CSV."""
    fields = (
        "timestamp_utc", "close", "regime", "efficiency_ratio",
        "normalised_slope_atr", "regression_slope_per_bar", "atr_fast", "atr_slow",
        "volatility_ratio", "true_range", "true_range_vs_prior_atr", "forward_return_pct",
    )
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(analysis.get("records", []))
