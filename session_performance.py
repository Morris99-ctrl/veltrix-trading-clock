"""Session-by-session performance analysis from imported, timestamped OHLC bars.

Timestamps are interpreted as bar-open times. Metrics are calculated only from
bars that fall inside each configured local session window. This is a historical
descriptive study, not a signal, forecast, liquidity estimate or broker feed.
"""
from __future__ import annotations

import csv
import math
from itertools import combinations
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable
from datetime import date, datetime, time, timezone

from market_data import OHLCBar
from session_engine import SessionDefinition


def _coerce_bars(raw_bars: Iterable[OHLCBar | dict[str, Any]]) -> list[OHLCBar]:
    by_timestamp: dict[datetime, OHLCBar] = {}
    for raw in raw_bars:
        try:
            bar = raw if isinstance(raw, OHLCBar) else OHLCBar.from_dict(raw)
            stamp = datetime.fromisoformat(bar.timestamp_utc.replace("Z", "+00:00"))
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("OHLC bar timestamps must include a timezone or UTC offset.")
            values = (float(bar.open), float(bar.high), float(bar.low), float(bar.close))
            if not all(math.isfinite(value) and value > 0 for value in values):
                continue
            if bar.high < max(bar.open, bar.close, bar.low) or bar.low > min(bar.open, bar.close):
                continue
            if bar.volume is not None and (
                not math.isfinite(float(bar.volume)) or float(bar.volume) < 0
            ):
                continue
            by_timestamp[stamp.astimezone(timezone.utc)] = OHLCBar(
                timestamp_utc=stamp.astimezone(timezone.utc).isoformat(),
                open=values[0], high=values[1], low=values[2], close=values[3],
                volume=bar.volume,
            )
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            continue
    return [by_timestamp[key] for key in sorted(by_timestamp)]


def _safe_stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None}
    return {"mean": mean(values), "median": median(values)}


def _session_window(session: SessionDefinition, local_date: date) -> tuple[datetime, datetime]:
    opens_at = datetime.combine(local_date, session.opens, tzinfo=session.tz)
    closes_at = datetime.combine(local_date, session.closes, tzinfo=session.tz)
    open_utc = opens_at.astimezone(timezone.utc)
    close_utc = closes_at.astimezone(timezone.utc)
    if close_utc <= open_utc:
        raise ValueError(f"{session.name} must have a close later than its open on the local session date.")
    return open_utc, close_utc


def _daily_metrics(bars: list[OHLCBar], expected_bars: int) -> dict[str, Any]:
    ordered = sorted(bars, key=lambda item: item.timestamp)
    first_open = float(ordered[0].open)
    final_close = float(ordered[-1].close)
    session_return = (final_close / first_open - 1.0) * 100.0
    session_range = (max(item.high for item in ordered) - min(item.low for item in ordered)) / first_open * 100.0

    log_returns = []
    previous_close = None
    for bar in ordered:
        reference = float(bar.open) if previous_close is None else previous_close
        if reference > 0:
            log_returns.append(math.log(float(bar.close) / reference))
        previous_close = float(bar.close)
    realised_volatility = math.sqrt(sum(value * value for value in log_returns)) * 100.0

    coverage = min(100.0, len(ordered) / expected_bars * 100.0) if expected_bars > 0 else 0.0
    return {
        "bars": len(ordered),
        "expected_bars": expected_bars,
        "coverage_pct": coverage,
        "return_pct": session_return,
        "range_pct": session_range,
        "realised_volatility_pct": realised_volatility,
        "direction": "UP" if session_return > 0 else "DOWN" if session_return < 0 else "FLAT",
        "first_bar_utc": ordered[0].timestamp.isoformat(),
        "last_bar_utc": ordered[-1].timestamp.isoformat(),
    }


def analyse_session_performance(
    raw_bars: Iterable[OHLCBar | dict[str, Any]],
    sessions: Iterable[SessionDefinition],
    *,
    bar_interval_minutes: float,
    minimum_bars_per_session: int = 3,
    minimum_coverage_pct: float = 50.0,
) -> dict[str, Any]:
    """Calculate local-session return/range/realised-volatility and overlap stats.

    Only imported, fixed-interval OHLC bars are supported. A bar belongs to a
    session when its UTC-normalised bar-open timestamp falls in that session's
    local [open, close) window. A date is included in session-level averages only
    when both the minimum bar count and estimated coverage threshold are met.
    Coverage is a count-based estimate from the median imported bar interval.
    """
    try:
        interval = float(bar_interval_minutes)
        min_bars = int(minimum_bars_per_session)
        min_coverage = float(minimum_coverage_pct)
    except (TypeError, ValueError) as exc:
        raise ValueError("Session performance parameters must be numeric.") from exc
    if not math.isfinite(interval) or interval <= 0 or interval > 1_440:
        raise ValueError("Bar interval must be between 0 and 1,440 minutes.")
    if min_bars < 1 or min_bars > 10_000:
        raise ValueError("Minimum bars per session must be between 1 and 10,000.")
    if not math.isfinite(min_coverage) or not 0 <= min_coverage <= 100:
        raise ValueError("Minimum session coverage must be between 0 and 100 percent.")

    definitions = list(sessions)
    if not definitions:
        raise ValueError("At least one configured market session is required.")
    bars = _coerce_bars(raw_bars)
    if not bars:
        raise ValueError("No valid timezone-aware OHLC bars were supplied.")

    min_window_minutes = min(
        (_session_window(session, datetime.now(session.tz).date())[1]
         - _session_window(session, datetime.now(session.tz).date())[0]).total_seconds() / 60.0
        for session in definitions
    )
    if interval >= min_window_minutes:
        raise ValueError(
            "The imported bar interval is too coarse for the configured session windows. "
            "Use intraday OHLC bars shorter than the shortest session."
        )

    session_groups: dict[str, dict[date, list[OHLCBar]]] = {item.key: {} for item in definitions}
    overlap_groups: dict[tuple[str, str], dict[date, list[OHLCBar]]] = {}
    session_membership: dict[datetime, list[str]] = {}

    for bar in bars:
        stamp = bar.timestamp
        members: list[str] = []
        for session in definitions:
            local = stamp.astimezone(session.tz)
            if local.weekday() not in session.weekdays:
                continue
            open_utc, close_utc = _session_window(session, local.date())
            if open_utc <= stamp < close_utc:
                session_groups[session.key].setdefault(local.date(), []).append(bar)
                members.append(session.key)
        session_membership[stamp] = members
        for left, right in combinations(sorted(members), 2):
            left_session = next(item for item in definitions if item.key == left)
            right_session = next(item for item in definitions if item.key == right)
            # UTC date is used for a consistent overlap-day bucket across zones.
            overlap_groups.setdefault((left, right), {}).setdefault(stamp.date(), []).append(bar)

    session_summaries: list[dict[str, Any]] = []
    session_daily: list[dict[str, Any]] = []
    for session in definitions:
        candidate_days = session_groups[session.key]
        accepted: list[dict[str, Any]] = []
        excluded_low_bars = 0
        excluded_low_coverage = 0
        for local_date, day_bars in sorted(candidate_days.items()):
            open_utc, close_utc = _session_window(session, local_date)
            expected = max(1, int(math.ceil((close_utc - open_utc).total_seconds() / 60.0 / interval)))
            metrics = _daily_metrics(day_bars, expected)
            base = {
                "row_type": "SESSION",
                "date": local_date.isoformat(),
                "session": session.name,
                "session_key": session.key,
                **metrics,
            }
            if metrics["bars"] < min_bars:
                excluded_low_bars += 1
                base["included"] = False
                base["exclusion_reason"] = "MINIMUM_BARS"
            elif metrics["coverage_pct"] < min_coverage:
                excluded_low_coverage += 1
                base["included"] = False
                base["exclusion_reason"] = "MINIMUM_COVERAGE"
            else:
                accepted.append(base)
                base["included"] = True
                base["exclusion_reason"] = ""
            session_daily.append(base)

        returns = [item["return_pct"] for item in accepted]
        ranges = [item["range_pct"] for item in accepted]
        volatilities = [item["realised_volatility_pct"] for item in accepted]
        coverages = [item["coverage_pct"] for item in accepted]
        count = len(accepted)
        return_stats = _safe_stats(returns)
        range_stats = _safe_stats(ranges)
        vol_stats = _safe_stats(volatilities)
        session_summaries.append({
            "session": session.name,
            "session_key": session.key,
            "observed_dates": len(candidate_days),
            "sample_sessions": count,
            "excluded_low_bars": excluded_low_bars,
            "excluded_low_coverage": excluded_low_coverage,
            "bars_used": sum(int(item["bars"]) for item in accepted),
            "mean_return_pct": return_stats["mean"],
            "median_return_pct": return_stats["median"],
            "positive_rate_pct": (
                sum(value > 0 for value in returns) / count * 100.0 if count else None
            ),
            "mean_range_pct": range_stats["mean"],
            "median_range_pct": range_stats["median"],
            "mean_realised_volatility_pct": vol_stats["mean"],
            "mean_coverage_pct": mean(coverages) if coverages else None,
        })

    overlap_summaries: list[dict[str, Any]] = []
    overlap_daily: list[dict[str, Any]] = []
    session_names = {item.key: item.name for item in definitions}
    for pair, days in sorted(overlap_groups.items()):
        accepted: list[dict[str, Any]] = []
        for utc_date, overlap_bars in sorted(days.items()):
            ordered = sorted(overlap_bars, key=lambda item: item.timestamp)
            metrics = _daily_metrics(ordered, max(1, int(math.ceil(60 / interval))))
            first_open = ordered[0].open
            # Per-bar OHLC returns describe the bars whose open timestamps fell
            # inside the pairwise overlap. They are not stitched across unobserved gaps.
            per_bar_returns = [
                math.log(float(item.close) / float(item.open))
                for item in ordered
                if item.open > 0 and item.close > 0
            ]
            overlap_return = (math.exp(sum(per_bar_returns)) - 1.0) * 100.0
            row = {
                "row_type": "OVERLAP",
                "date": utc_date.isoformat(),
                "session": f"{session_names[pair[0]]} + {session_names[pair[1]]}",
                "session_key": "+".join(pair),
                **metrics,
                "return_pct": overlap_return,
                "direction": "UP" if overlap_return > 0 else "DOWN" if overlap_return < 0 else "FLAT",
                "included": True,
                "exclusion_reason": "",
            }
            accepted.append(row)
            overlap_daily.append(row)
        returns = [float(item["return_pct"]) for item in accepted]
        ranges = [float(item["range_pct"]) for item in accepted]
        volatilities = [float(item["realised_volatility_pct"]) for item in accepted]
        count = len(accepted)
        return_stats = _safe_stats(returns)
        range_stats = _safe_stats(ranges)
        vol_stats = _safe_stats(volatilities)
        overlap_summaries.append({
            "pair": f"{session_names[pair[0]]} + {session_names[pair[1]]}",
            "pair_key": "+".join(pair),
            "sample_days": count,
            "bars_used": sum(int(item["bars"]) for item in accepted),
            "mean_return_pct": return_stats["mean"],
            "median_return_pct": return_stats["median"],
            "positive_rate_pct": (
                sum(value > 0 for value in returns) / count * 100.0 if count else None
            ),
            "mean_range_pct": range_stats["mean"],
            "mean_realised_volatility_pct": vol_stats["mean"],
        })

    return {
        "metadata": {
            "input_bars": len(list(raw_bars)) if not isinstance(raw_bars, (list, tuple)) else len(raw_bars),
            "valid_bars": len(bars),
            "bar_interval_minutes": interval,
            "first_timestamp_utc": bars[0].timestamp.isoformat(),
            "last_timestamp_utc": bars[-1].timestamp.isoformat(),
            "minimum_bars_per_session": min_bars,
            "minimum_coverage_pct": min_coverage,
            "timestamp_convention": "CSV timestamps are interpreted as bar-open times.",
            "session_assignment": "Local IANA timezone; bar-open timestamp in [open, close); configured weekdays.",
            "coverage_method": "Observed bars divided by expected bars estimated from median interval; capped at 100%.",
            "overlap_return_method": "Compounded OHLC bar open-to-close returns for bars timestamped inside both session windows; unobserved gaps are not stitched.",
            "classification_uses_future_data": False,
        },
        "sessions": session_summaries,
        "overlaps": overlap_summaries,
        "session_daily": session_daily,
        "overlap_daily": overlap_daily,
    }


def export_session_performance_csv(path: str | Path, analysis: dict[str, Any]) -> None:
    """Export daily session and pair-overlap metrics for independent inspection."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "row_type", "date", "session", "session_key", "bars", "expected_bars",
        "coverage_pct", "return_pct", "range_pct", "realised_volatility_pct",
        "direction", "included", "exclusion_reason", "first_bar_utc", "last_bar_utc",
    )
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(analysis.get("session_daily", []))
        writer.writerows(analysis.get("overlap_daily", []))
