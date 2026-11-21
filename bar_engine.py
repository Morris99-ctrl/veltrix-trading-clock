"""Raw-tick import and information-driven bar construction for Veltrix Phase 8.

Time bars already exist in the application. This module adds fixed-tick and
Tick Imbalance Bar (TIB) sampling while keeping the downstream OHLCBar schema.
TIBs are calculated causally: the threshold for a bar is fixed at its start and
is updated only after that bar has closed.
"""
from __future__ import annotations

import csv
import math
import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from market_data import OHLCBar

TICK_CSV_MAX_BYTES = 250 * 1024 * 1024
TICK_CSV_MAX_ROWS = 5_000_000
MAX_GENERATED_BARS = 250_000


@dataclass(frozen=True, slots=True)
class MarketTick:
    timestamp_utc: str
    price: float
    bid: float | None = None
    ask: float | None = None
    volume: float | None = None

    @property
    def timestamp(self) -> datetime:
        return datetime.fromisoformat(self.timestamp_utc.replace("Z", "+00:00")).astimezone(timezone.utc)

    @property
    def spread(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid


TIMESTAMP_ALIASES = {
    "timestamp", "datetime", "datetimeutc", "gmttime", "time", "timemsc",
    "timestampms", "epochtime", "epochms", "bartime", "dateandtime",
}
DATE_ALIASES = {"date", "tradedate", "day"}
TIME_ALIASES = {"time", "tradetime", "hour"}
BID_ALIASES = {"bid", "bidprice", "bestbid"}
ASK_ALIASES = {"ask", "askprice", "bestask", "offer"}
LAST_ALIASES = {"last", "lastprice", "tradeprice", "price", "close"}
VOLUME_ALIASES = {"volume", "vol", "size", "qty", "quantity", "realvolume", "tickvol", "tickvolume"}


def _normalise_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def _find_column(headers: list[str], aliases: set[str]) -> str | None:
    for header in headers:
        if _normalise_header(header) in aliases:
            return header
    return None


def _parse_tick_timestamp(value: str, zone: ZoneInfo) -> datetime:
    raw = str(value).strip().strip('"').strip("'")
    if not raw:
        raise ValueError("empty timestamp")
    # MT5 time_msc and common Unix exports use milliseconds; 10-digit values are seconds.
    if re.fullmatch(r"\d{13}", raw):
        return datetime.fromtimestamp(int(raw) / 1000.0, timezone.utc)
    if re.fullmatch(r"\d{10}(?:\.\d+)?", raw):
        return datetime.fromtimestamp(float(raw), timezone.utc)
    candidate = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in (
            "%Y.%m.%d %H:%M:%S.%f", "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M",
            "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
            "%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
            "%m/%d/%Y %H:%M:%S.%f", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
        ):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError(f"unsupported timestamp {raw!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(timezone.utc)


def _finite_number(value: Any, field: str, *, optional: bool = True) -> float | None:
    raw = "" if value is None else str(value).strip()
    if not raw and optional:
        return None
    try:
        number = float(raw.replace(",", ""))
    except (TypeError, ValueError) as exc:
        if optional and not raw:
            return None
        raise ValueError(f"invalid {field} value {raw!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"non-finite {field} value")
    return number


def _tick_reader(file):
    sample = file.read(8192)
    file.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(file, dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("Tick CSV needs a header row containing a timestamp and Last or Bid/Ask prices.")
    headers = [str(item) for item in reader.fieldnames]
    timestamp_col = _find_column(headers, TIMESTAMP_ALIASES)
    date_col = _find_column(headers, DATE_ALIASES)
    time_col = _find_column(headers, TIME_ALIASES)
    # If Date and Time are separate columns, do not mistake Time for a full timestamp.
    if date_col and time_col and _normalise_header(timestamp_col or "") in TIME_ALIASES:
        timestamp_col = None
    elif timestamp_col is None and time_col and not date_col:
        timestamp_col = time_col
    columns = {
        "timestamp": timestamp_col, "date": date_col, "time": time_col,
        "bid": _find_column(headers, BID_ALIASES),
        "ask": _find_column(headers, ASK_ALIASES),
        "last": _find_column(headers, LAST_ALIASES),
        "volume": _find_column(headers, VOLUME_ALIASES),
    }
    if timestamp_col is None and not (date_col and time_col):
        raise ValueError("Tick CSV needs a timestamp column or separate Date and Time columns.")
    if columns["last"] is None and not (columns["bid"] and columns["ask"]):
        raise ValueError("Tick CSV needs a Last/Price column or both Bid and Ask columns.")
    return reader, columns


def _parse_tick_row(row: dict[str, Any], columns: dict[str, str | None], zone: ZoneInfo):
    timestamp_col = columns["timestamp"]
    stamp_raw = (
        row.get(timestamp_col, "") if timestamp_col
        else f"{row.get(columns['date'], '')} {row.get(columns['time'], '')}"
    )
    stamp = _parse_tick_timestamp(stamp_raw, zone)
    def optional_number(column: str | None, field: str) -> float | None:
        if not column:
            return None
        try:
            return _finite_number(row.get(column), field)
        except ValueError:
            # Optional quote, Last and volume fields are validated independently.
            # A malformed unused volume or quote must not discard a valid Last tick.
            return None

    bid = optional_number(columns["bid"], "bid")
    ask = optional_number(columns["ask"], "ask")
    last = optional_number(columns["last"], "last")
    volume = optional_number(columns["volume"], "volume")
    if volume is not None and volume < 0:
        volume = None
    if bid is not None and bid <= 0:
        bid = None
    if ask is not None and ask <= 0:
        ask = None
    if bid is not None and ask is not None and ask < bid:
        bid = ask = None
    if last is not None and last <= 0:
        last = None
    if bid is not None and ask is not None:
        quote_valid = True
    else:
        quote_valid = False
    if last is None and not quote_valid:
        raise ValueError("row has no usable Last or Bid/Ask price")
    selected_price = last if last is not None else (bid + ask) / 2.0
    return MarketTick(stamp.isoformat(), selected_price, bid, ask, volume), last, quote_valid


def import_tick_csv(path: str | Path, *, naive_timezone: str = "UTC") -> tuple[list[MarketTick], dict[str, Any]]:
    """Read broker tick CSV and select either Last prices or a Bid/Ask midpoint.

    The file is scanned once for source-quality counts and a second time to build
    only the selected tick stream. This avoids retaining a full preliminary copy
    of large broker exports in memory. Last is preferred when at least half of
    all source rows contain a usable Last value; otherwise valid Bid/Ask midpoints
    are selected and explicitly labelled as quote-flow proxies.
    """
    source = Path(path)
    if source.stat().st_size > TICK_CSV_MAX_BYTES:
        raise ValueError(f"Tick CSV exceeds the {TICK_CSV_MAX_BYTES // (1024 * 1024)} MB import limit.")
    try:
        zone = ZoneInfo(naive_timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown IANA timezone: {naive_timezone}") from exc

    invalid_rows = 0
    total_rows = 0
    last_valid = 0
    quote_valid = 0
    unsorted = False
    previous_stamp: datetime | None = None

    # Pass 1: validate and count, without materialising every tick object.
    with source.open("r", encoding="utf-8-sig", newline="") as file:
        reader, columns = _tick_reader(file)
        for row in reader:
            total_rows += 1
            if total_rows > TICK_CSV_MAX_ROWS:
                raise ValueError(f"Tick CSV exceeds the {TICK_CSV_MAX_ROWS:,}-row import limit.")
            try:
                tick, last, has_quote = _parse_tick_row(row, columns, zone)
                stamp = tick.timestamp
                if previous_stamp is not None and stamp < previous_stamp:
                    unsorted = True
                previous_stamp = stamp
                if last is not None:
                    last_valid += 1
                if has_quote:
                    quote_valid += 1
            except (ValueError, TypeError, OverflowError):
                invalid_rows += 1

    if total_rows == 0:
        raise ValueError("No tick rows were found below the CSV header.")
    use_last = last_valid >= max(1, math.ceil(total_rows * 0.5))
    price_source = "last_price_tick_rule" if use_last else "bid_ask_midquote_proxy"

    # Pass 2: construct only the chosen price stream. Python's sort is stable, so
    # duplicate timestamps retain their original source order.
    ticks: list[MarketTick] = []
    missing_selected_price = 0
    with source.open("r", encoding="utf-8-sig", newline="") as file:
        reader, columns = _tick_reader(file)
        for row in reader:
            try:
                tick, last, has_quote = _parse_tick_row(row, columns, zone)
                if use_last:
                    if last is None:
                        missing_selected_price += 1
                        continue
                    tick = MarketTick(tick.timestamp_utc, last, tick.bid, tick.ask, tick.volume)
                else:
                    if not has_quote:
                        missing_selected_price += 1
                        continue
                    tick = MarketTick(
                        tick.timestamp_utc, (tick.bid + tick.ask) / 2.0,
                        tick.bid, tick.ask, tick.volume,
                    )
                ticks.append(tick)
            except (ValueError, TypeError, OverflowError):
                continue

    if not ticks:
        raise ValueError("No valid tick rows were found. Check timestamp, Last and Bid/Ask columns.")
    if unsorted:
        ticks.sort(key=lambda item: item.timestamp)  # stable: duplicates keep source order
    if len(ticks) < 3:
        raise ValueError("At least three usable ticks are required to construct bars.")
    return ticks, {
        "source_file": source.name,
        "timezone_for_naive_timestamps": naive_timezone,
        "rows_read": total_rows,
        "valid_ticks": len(ticks),
        "invalid_rows": invalid_rows,
        "last_price_rows": last_valid,
        "bid_ask_quote_rows": quote_valid,
        "missing_selected_price_rows": missing_selected_price,
        "input_was_out_of_order": unsorted,
        "price_source": price_source,
        "price_source_description": (
            "Last/price values classified with the tick rule; aggressor side is still inferred, not exchange-stamped."
            if use_last else
            "Midpoint of broker Bid/Ask quote updates classified with the tick rule; this is a quote-flow proxy, not traded order flow."
        ),
        "volume_column_present": columns["volume"] is not None,
        "volume_semantics": "Broker-supplied volume field; semantics are unverified and it is not used by TIB.",
        "start_utc": ticks[0].timestamp_utc,
        "end_utc": ticks[-1].timestamp_utc,
        "timestamp_convention": "tick event timestamp",
    }

def _make_ohlc_bar(ticks: list[MarketTick]) -> OHLCBar:
    if not ticks:
        raise ValueError("Cannot construct an OHLC bar from an empty tick sequence.")
    prices = [tick.price for tick in ticks]
    volumes = [tick.volume for tick in ticks if tick.volume is not None]
    return OHLCBar(
        timestamp_utc=ticks[-1].timestamp_utc,
        open=prices[0], high=max(prices), low=min(prices), close=prices[-1],
        volume=sum(volumes) if volumes else None,
    )


def _median_duration_minutes(stats: list[dict[str, Any]], fallback: float = 0.0) -> float:
    durations = [float(item["duration_seconds"]) / 60.0 for item in stats if float(item["duration_seconds"]) > 0]
    return float(statistics.median(durations)) if durations else float(fallback)


def build_fixed_tick_bars(
    ticks: Iterable[MarketTick], *, ticks_per_bar: int = 500, include_partial: bool = False,
) -> tuple[list[OHLCBar], dict[str, Any]]:
    """Construct equal-tick-count bars. A trailing incomplete bar is omitted by default."""
    ordered = list(ticks)
    if ticks_per_bar < 2:
        raise ValueError("Ticks per bar must be at least 2.")
    if len(ordered) < ticks_per_bar:
        raise ValueError(f"Need at least {ticks_per_bar:,} ticks; received {len(ordered):,}.")
    estimated_bars = len(ordered) // ticks_per_bar + (1 if include_partial and len(ordered) % ticks_per_bar else 0)
    if estimated_bars > MAX_GENERATED_BARS:
        raise ValueError(
            f"This setting would create {estimated_bars:,} bars, above the {MAX_GENERATED_BARS:,}-bar safety limit. "
            "Increase ticks per bar or use a smaller raw tick sample."
        )
    bars: list[OHLCBar] = []
    stats: list[dict[str, Any]] = []
    for start in range(0, len(ordered), ticks_per_bar):
        chunk = ordered[start:start + ticks_per_bar]
        if len(chunk) < ticks_per_bar and not include_partial:
            break
        bar = _make_ohlc_bar(chunk)
        bars.append(bar)
        spread_values = [tick.spread for tick in chunk if tick.spread is not None and tick.spread >= 0]
        stats.append({
            "bar_number": len(bars), "tick_count": len(chunk), "duration_seconds": max(
                0.0, (chunk[-1].timestamp - chunk[0].timestamp).total_seconds()
            ),
            "mean_spread": statistics.fmean(spread_values) if spread_values else None,
            "signed_imbalance": None, "expected_threshold": None,
            "is_calibration_bar": False, "is_partial": len(chunk) < ticks_per_bar,
        })
    used = sum(item["tick_count"] for item in stats)
    if not bars:
        raise ValueError("No complete fixed-tick bars were produced.")
    return bars, {
        "bar_construction": "fixed_tick",
        "bar_construction_label": f"Fixed Tick Bars ({ticks_per_bar:,} ticks)",
        "ticks_per_bar": int(ticks_per_bar),
        "bar_count": len(bars),
        "source_ticks_used": used,
        "trailing_ticks_discarded": len(ordered) - used,
        "variable_interval_bars": True,
        "timestamp_convention": "bar end / final tick timestamp",
        "bar_stats": stats,
        "median_bar_duration_minutes": _median_duration_minutes(stats),
        "volume_used_for_signals": False,
    }


def _tick_signs(ticks: list[MarketTick]) -> list[int]:
    """Tick rule. First direction is unknown (0); unchanged prices inherit last sign."""
    signs: list[int] = []
    previous_price: float | None = None
    previous_sign = 0
    for tick in ticks:
        if previous_price is None:
            sign = 0
        elif tick.price > previous_price:
            sign = 1
        elif tick.price < previous_price:
            sign = -1
        else:
            sign = previous_sign
        if sign != 0:
            previous_sign = sign
        signs.append(sign)
        previous_price = tick.price
    return signs


def build_tick_imbalance_bars(
    ticks: Iterable[MarketTick], *, seed_ticks: int = 250, ewma_span: int = 20,
    imbalance_ewma_span: int = 20,
    min_expected_imbalance_fraction: float = 0.05,
) -> tuple[list[OHLCBar], dict[str, Any]]:
    """Construct causal Tick Imbalance Bars using an adaptive expected threshold.

    The first `seed_ticks` observations form a clearly-labelled calibration bar.
    Thereafter each bar's threshold is fixed at its start using an EWMA of
    completed-bar lengths and a separate tick-by-tick EWMA of signed tick-rule
    observations. A configurable imbalance floor stabilises near-zero estimates.
    """
    ordered = list(ticks)
    if not 20 <= seed_ticks < len(ordered):
        raise ValueError(
            f"TIB requires at least 21 ticks and a seed window smaller than the sample; "
            f"received {len(ordered):,} ticks with seed {seed_ticks:,}."
        )
    if not 2 <= ewma_span <= 500:
        raise ValueError("Expected bar-length EWMA span must be between 2 and 500 bars.")
    if not 2 <= imbalance_ewma_span <= 500:
        raise ValueError("Expected tick-imbalance EWMA span must be between 2 and 500 ticks.")
    if not 0.001 <= min_expected_imbalance_fraction <= 0.50:
        raise ValueError("Minimum expected imbalance fraction must be between 0.001 and 0.50.")

    signs = _tick_signs(ordered)
    bars: list[OHLCBar] = []
    stats: list[dict[str, Any]] = []
    seed = ordered[:seed_ticks]
    seed_signs = signs[:seed_ticks]
    bars.append(_make_ohlc_bar(seed))
    seed_spreads = [tick.spread for tick in seed if tick.spread is not None and tick.spread >= 0]
    seed_rate = sum(seed_signs) / len(seed_signs)
    stats.append({
        "bar_number": 1,
        "tick_count": len(seed),
        "duration_seconds": max(0.0, (seed[-1].timestamp - seed[0].timestamp).total_seconds()),
        "mean_spread": statistics.fmean(seed_spreads) if seed_spreads else None,
        "signed_imbalance": int(sum(seed_signs)),
        "expected_threshold": None,
        "is_calibration_bar": True,
        "is_partial": False,
    })

    alpha_bar = 2.0 / (ewma_span + 1.0)
    alpha_tick = 2.0 / (imbalance_ewma_span + 1.0)
    expected_ticks = float(seed_ticks)
    expected_imbalance = float(seed_rate)
    current: list[MarketTick] = []
    current_signs: list[int] = []
    current_threshold: float | None = None
    current_theta = 0

    for tick, sign in zip(ordered[seed_ticks:], signs[seed_ticks:]):
        if not current:
            # Freeze expectations at bar open. Later ticks cannot change this threshold.
            current_expected_ticks = expected_ticks
            current_expected_imbalance = expected_imbalance
            current_threshold = max(
                1.0,
                current_expected_ticks * max(abs(current_expected_imbalance), min_expected_imbalance_fraction),
            )
        current.append(tick)
        current_signs.append(sign)
        current_theta += sign
        if abs(current_theta) >= float(current_threshold):
            if len(bars) >= MAX_GENERATED_BARS:
                raise ValueError(
                    f"TIB construction exceeded the {MAX_GENERATED_BARS:,}-bar safety limit. "
                    "Use a shorter tick sample or adjust the seed and imbalance settings."
                )
            bar = _make_ohlc_bar(current)
            bars.append(bar)
            spreads = [item.spread for item in current if item.spread is not None and item.spread >= 0]
            stats.append({
                "bar_number": len(bars), "tick_count": len(current),
                "duration_seconds": max(0.0, (current[-1].timestamp - current[0].timestamp).total_seconds()),
                "mean_spread": statistics.fmean(spreads) if spreads else None,
                "signed_imbalance": int(current_theta),
                "expected_ticks_at_open": float(current_expected_ticks),
                "expected_imbalance_fraction_at_open": float(current_expected_imbalance),
                "expected_threshold": float(current_threshold),
                "is_calibration_bar": False,
                "is_partial": False,
            })
            # Update expectations only after the bar has closed, so no future tick
            # can alter the current bar's threshold.
            observed_ticks = float(len(current))
            expected_ticks = (1.0 - alpha_bar) * expected_ticks + alpha_bar * observed_ticks
            # The signed-imbalance expectation is an EWMA of individual tick-rule
            # signs, not an EWMA of each completed bar's average sign. Updating it
            # only after the bar closes keeps the threshold causal for the next bar.
            for observed_sign in current_signs:
                expected_imbalance = (
                    (1.0 - alpha_tick) * expected_imbalance + alpha_tick * float(observed_sign)
                )
            current = []
            current_signs = []
            current_threshold = None
            current_theta = 0

    trailing = len(current)
    if not bars:
        raise ValueError("No TIB bars could be produced from the supplied ticks.")
    if len(bars) < 3:
        raise ValueError(
            f"Only {len(bars)} TIB/calibration bars were produced. Import a longer tick sample or adjust the seed/floor settings."
        )
    return bars, {
        "bar_construction": "tick_imbalance",
        "bar_construction_label": "Tick Imbalance Bars (TIB)",
        "seed_ticks": int(seed_ticks),
        "ewma_span": int(ewma_span),
        "expected_bar_length_ewma_span_bars": int(ewma_span),
        "expected_tick_imbalance_ewma_span_ticks": int(imbalance_ewma_span),
        "min_expected_imbalance_fraction": float(min_expected_imbalance_fraction),
        "initial_expected_ticks": float(seed_ticks),
        "initial_expected_imbalance_fraction": float(seed_rate),
        "bar_count": len(bars),
        "calibration_bars": 1,
        "source_ticks_used": len(ordered) - trailing,
        "trailing_ticks_discarded": trailing,
        "variable_interval_bars": True,
        "timestamp_convention": "bar end / final tick timestamp",
        "threshold_method": "At each bar start: max(1 tick, EWMA(expected bar tick count) × max(abs(EWMA of individual tick-rule signs), configured floor)); expectations update only after a bar closes.",
        "expected_tick_count_ewma": "completed_bar_tick_count",
        "expected_imbalance_ewma": "individual_tick_rule_signs",
        "bar_stats": stats,
        "median_bar_duration_minutes": _median_duration_minutes(stats),
        "volume_used_for_signals": False,
    }


def build_bars_from_tick_csv(
    path: str | Path, *, method: str, naive_timezone: str = "UTC",
    ticks_per_bar: int = 500, seed_ticks: int = 250, ewma_span: int = 20,
    imbalance_ewma_span: int = 20,
    min_expected_imbalance_fraction: float = 0.05,
) -> tuple[list[OHLCBar], dict[str, Any]]:
    ticks, import_meta = import_tick_csv(path, naive_timezone=naive_timezone)
    if method == "fixed_tick":
        bars, build_meta = build_fixed_tick_bars(ticks, ticks_per_bar=ticks_per_bar)
    elif method == "tick_imbalance":
        bars, build_meta = build_tick_imbalance_bars(
            ticks, seed_ticks=seed_ticks, ewma_span=ewma_span,
            imbalance_ewma_span=imbalance_ewma_span,
            min_expected_imbalance_fraction=min_expected_imbalance_fraction,
        )
    else:
        raise ValueError("Unknown bar method. Choose fixed_tick or tick_imbalance.")
    return bars, {**import_meta, **build_meta}
