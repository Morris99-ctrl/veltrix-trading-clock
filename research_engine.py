"""Reproducible session-level historical market research and CSV import/export."""
from __future__ import annotations

import csv
import html
import json
import math
import re
import statistics
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from market_data import OHLCBar
from session_engine import SessionDefinition


CSV_MAX_BYTES = 100 * 1024 * 1024
CSV_MAX_ROWS = 2_000_000


def custom_research_asset_key(name: str) -> str:
    """Return a stable, collision-resistant namespace key for a broker CSV instrument."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")
    if not slug:
        raise ValueError("Instrument name must contain at least one letter or number.")
    return f"csv_{slug[:56]}"


def build_research_instrument_choices(
    market_instruments: Iterable[dict[str, Any]],
    research_assets: dict[str, dict[str, Any]],
) -> tuple[list[str], dict[str, str]]:
    """Build selector choices from built-in instruments plus imported CSV datasets."""
    labels: list[str] = []
    label_to_key: dict[str, str] = {}
    known_keys: set[str] = set()

    for instrument in market_instruments:
        key = str(instrument.get("key", "")).strip()
        if not key:
            continue
        name = str(instrument.get("name") or key).strip()
        symbol = str(instrument.get("symbol") or "").strip()
        label = f"{name} · {symbol}" if symbol else name
        if label in label_to_key:
            label = f"{label} · {key}"
        labels.append(label)
        label_to_key[label] = key
        known_keys.add(key)

    for key, dataset in research_assets.items():
        key = str(key)
        if key in known_keys or not isinstance(dataset, dict) or not dataset.get("bars"):
            continue
        name = str(dataset.get("name") or key).strip()
        symbol = str(dataset.get("symbol") or "").strip()
        source = str(dataset.get("source") or "").lower()
        marker = "BROKER CSV" if "broker csv" in source or key.startswith("csv_") else "CUSTOM DATA"
        label = f"{name} · {symbol} · {marker}" if symbol else f"{name} · {marker}"
        if label in label_to_key:
            label = f"{label} · {key}"
        labels.append(label)
        label_to_key[label] = key
        known_keys.add(key)

    return labels, label_to_key


def _normalise_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


HEADER_ALIASES = {
    "timestamp": {"timestamp", "datetime", "datetimeutc", "gmttime", "bartime", "opentime"},
    "date": {"date", "tradedate", "day"},
    "time": {"time", "tradetime", "hour"},
    "open": {"open", "o", "openprice"},
    "high": {"high", "h", "highprice"},
    "low": {"low", "l", "lowprice"},
    "close": {"close", "c", "closeprice", "last"},
    "volume": {"volume", "vol", "tickvol", "tickvolume", "realvolume"},
}


def _find_column(headers: list[str], kind: str) -> str | None:
    aliases = {_normalise_header(item) for item in HEADER_ALIASES[kind]}
    for header in headers:
        if _normalise_header(header) in aliases:
            return header
    return None


def _parse_timestamp(value: str, naive_zone: ZoneInfo) -> datetime:
    raw = str(value).strip().strip('"').strip("'")
    if not raw:
        raise ValueError("empty timestamp")
    # Unix seconds and milliseconds are common in exported data.
    if re.fullmatch(r"\d{10}(?:\.\d+)?", raw):
        return datetime.fromtimestamp(float(raw), timezone.utc)
    if re.fullmatch(r"\d{13}", raw):
        return datetime.fromtimestamp(int(raw) / 1000, timezone.utc)
    candidate = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        parsed = None
    if parsed is None:
        formats = (
            "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
            "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d.%m.%Y %H:%M:%S",
            "%d.%m.%Y %H:%M", "%Y-%m-%d", "%Y.%m.%d", "%m/%d/%Y",
        )
        for fmt in formats:
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError(f"unsupported timestamp {raw!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=naive_zone)
    return parsed.astimezone(timezone.utc)


def _number(value: Any, field: str, *, optional: bool = False) -> float | None:
    raw = "" if value is None else str(value).strip()
    if not raw and optional:
        return None
    try:
        parsed = float(raw.replace(",", ""))
        if not math.isfinite(parsed):
            raise ValueError("non-finite number")
        return parsed
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field} value {raw!r}") from exc


def import_ohlc_csv(path: str | Path, *, naive_timezone: str = "UTC") -> tuple[list[OHLCBar], dict[str, Any]]:
    """Import timestamp/open/high/low/close CSV; naive timestamps use the chosen IANA zone.

    Supports combined datetime columns or separate date/time columns, Unix epoch
    timestamps, and common broker/MT5-style angle-bracket headers.
    """
    source = Path(path)
    if source.stat().st_size > CSV_MAX_BYTES:
        raise ValueError(f"CSV exceeds the {CSV_MAX_BYTES // (1024 * 1024)} MB import limit.")
    try:
        zone = ZoneInfo(naive_timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown IANA timezone: {naive_timezone}") from exc

    with source.open("r", encoding="utf-8-sig", newline="") as file:
        sample = file.read(8192)
        file.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(file, dialect=dialect)
        if not reader.fieldnames:
            raise ValueError("CSV needs a header row with timestamp and OHLC columns.")
        headers = [str(item) for item in reader.fieldnames]
        timestamp_col = _find_column(headers, "timestamp")
        date_col, time_col = _find_column(headers, "date"), _find_column(headers, "time")
        # Some chart exports call the complete timestamp field simply "time";
        # when no separate Date column exists, interpret it as the timestamp.
        if timestamp_col is None and time_col and not date_col:
            timestamp_col = time_col
        # A Date column alone may itself contain a full datetime value.
        if timestamp_col is None and date_col and not time_col:
            timestamp_col = date_col
        columns = {name: _find_column(headers, name) for name in ("open", "high", "low", "close", "volume")}
        missing = [name.upper() for name in ("open", "high", "low", "close") if columns[name] is None]
        if timestamp_col is None and not (date_col and time_col):
            missing.insert(0, "TIMESTAMP (or separate DATE and TIME)")
        if missing:
            raise ValueError("Missing required CSV column(s): " + ", ".join(missing))

        parsed_by_timestamp: dict[str, OHLCBar] = {}
        invalid_rows = 0
        total_rows = 0
        for row in reader:
            total_rows += 1
            if total_rows > CSV_MAX_ROWS:
                raise ValueError(f"CSV exceeds the {CSV_MAX_ROWS:,}-row import limit.")
            try:
                stamp_raw = row.get(timestamp_col, "") if timestamp_col else f"{row.get(date_col, '')} {row.get(time_col, '')}"
                stamp = _parse_timestamp(stamp_raw, zone)
                o = _number(row.get(columns["open"]), "open")
                h = _number(row.get(columns["high"]), "high")
                low = _number(row.get(columns["low"]), "low")
                close = _number(row.get(columns["close"]), "close")
                volume = _number(row.get(columns["volume"]), "volume", optional=True) if columns["volume"] else None
                assert o is not None and h is not None and low is not None and close is not None
                if min(o, h, low, close) <= 0 or h < max(o, close, low) or low > min(o, close):
                    raise ValueError("OHLC values violate positive-price/high-low constraints")
                bar = OHLCBar(stamp.isoformat(), o, h, low, close, volume)
                # Last row wins for duplicate timestamps, matching most broker exports.
                parsed_by_timestamp[stamp.isoformat()] = bar
            except (ValueError, TypeError, AssertionError):
                invalid_rows += 1

    bars = sorted(parsed_by_timestamp.values(), key=lambda item: item.timestamp)
    if not bars:
        raise ValueError("No valid OHLC rows could be imported. Check the headers, timezone and price columns.")
    return bars, {
        "source": "CSV import", "file_name": source.name, "timezone_for_naive_timestamps": naive_timezone,
        "rows_read": total_rows, "valid_bars": len(bars), "invalid_rows": invalid_rows,
        "duplicate_timestamps": max(0, total_rows - invalid_rows - len(bars)),
        "start_utc": bars[0].timestamp.isoformat(), "end_utc": bars[-1].timestamp.isoformat(),
    }


def _ordered_bars(bars: Iterable[OHLCBar]) -> list[OHLCBar]:
    """Materialise bars and sort only when the input is not already chronological."""
    ordered = list(bars)
    if any(right.timestamp < left.timestamp for left, right in zip(ordered, ordered[1:])):
        ordered.sort(key=lambda item: item.timestamp)
    return ordered


def infer_bar_interval_minutes(bars: Iterable[OHLCBar], fallback: float = 60.0) -> float:
    ordered = _ordered_bars(bars)
    gaps = [
        (right.timestamp - left.timestamp).total_seconds() / 60
        for left, right in zip(ordered, ordered[1:])
        if 0 < (right.timestamp - left.timestamp).total_seconds() / 60 <= 360
    ]
    if not gaps:
        return float(fallback)
    return float(statistics.median(gaps))


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * min(100.0, max(0.0, percentile)) / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _percentile_rank(values: list[float], current: float) -> float | None:
    if not values:
        return None
    below = sum(value < current for value in values)
    equal = sum(math.isclose(value, current, rel_tol=1e-10, abs_tol=1e-12) for value in values)
    return 100.0 * (below + 0.5 * equal) / len(values)


def build_session_observations(
    bars: Iterable[OHLCBar], sessions: list[SessionDefinition], *,
    bar_interval_minutes: float | None = None, variable_interval: bool = False,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Build one dated RV/range/return observation per session and local trading date."""
    ordered = _ordered_bars(bars)
    if not ordered:
        return []
    interval = float(bar_interval_minutes or infer_bar_interval_minutes(ordered))
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    # Time bars use a gap guard to avoid bridging missing observations. Event-driven
    # bars have intentionally variable elapsed durations, so their adjacent returns
    # are retained inside each local session instead of being filtered by a median gap.
    max_gap = math.inf if variable_interval else max(interval * 1.6, interval + 2.0)
    observations: list[dict[str, Any]] = []
    for session in sessions:
        local_now = now_utc.astimezone(session.tz)
        current_clock = local_now.timetz().replace(tzinfo=None)
        current_session_open = (
            local_now.weekday() in session.weekdays and session.opens <= current_clock < session.closes
        )
        groups: dict[str, list[OHLCBar]] = defaultdict(list)
        for bar in ordered:
            local = bar.timestamp.astimezone(session.tz)
            local_time = local.timetz().replace(tzinfo=None)
            if local.weekday() in session.weekdays and session.opens <= local_time < session.closes:
                groups[local.date().isoformat()].append(bar)
        # Bars were traversed chronologically, so each per-date group is already sorted.
        for session_date, group in sorted(groups.items()):
            returns: list[float] = []
            # Include the first sampled bar's open-to-close return, then close-to-close
            # returns for adjacent bars. This captures the first observed intraday interval
            # without importing any overnight return from a previous session.
            if group[0].open > 0 and group[0].close > 0:
                returns.append(math.log(group[0].close / group[0].open))
            for previous, current in zip(group, group[1:]):
                gap = (current.timestamp - previous.timestamp).total_seconds() / 60
                if 0 < gap <= max_gap:
                    returns.append(math.log(current.close / previous.close))
            rv = math.sqrt(sum(value * value for value in returns)) * 100 if returns else None
            first_open, last_close = group[0].open, group[-1].close
            range_pct = (max(item.high for item in group) - min(item.low for item in group)) / first_open * 100 if first_open > 0 else None
            session_return = (last_close / first_open - 1) * 100 if first_open > 0 else None
            observations.append({
                "session_key": session.key, "session_name": session.name, "date": session_date,
                "realised_vol_pct": rv, "range_pct": range_pct, "session_return_pct": session_return,
                "bars": len(group), "returns": len(returns), "bar_interval_minutes": interval,
                "variable_interval_bars": bool(variable_interval),
                "start_utc": group[0].timestamp.isoformat(), "end_utc": group[-1].timestamp.isoformat(),
                "valid": rv is not None and len(returns) >= 2,
                "is_partial": session_date == local_now.date().isoformat() and current_session_open,
            })
    observations.sort(key=lambda row: (row["date"], row["session_key"]))
    return observations


def analyse_session_history(
    bars_by_asset: dict[str, list[OHLCBar]], assets: dict[str, dict[str, Any]],
    sessions: list[SessionDefinition], *, windows: tuple[int, ...] = (30, 60, 90),
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Calculate 30/60/90-calendar-day distribution and latest-observation rankings."""
    summary_rows: list[dict[str, Any]] = []
    observation_map: dict[str, list[dict[str, Any]]] = {}
    for asset_key, bars in bars_by_asset.items():
        metadata = assets.get(asset_key, {})
        observations = build_session_observations(
            bars, sessions,
            bar_interval_minutes=metadata.get("bar_interval_minutes"),
            variable_interval=bool(metadata.get("variable_interval_bars", False)),
            now=now,
        )
        observation_map[asset_key] = observations
        # The currently open local session is displayed as PARTIAL but excluded
        # from historical distributions, percentile ranks and win-rate statistics.
        valid_dates = [date.fromisoformat(row["date"]) for row in observations
                       if row["valid"] and not row.get("is_partial", False)]
        if not valid_dates:
            for session in sessions:
                for window in windows:
                    summary_rows.append(_empty_summary(asset_key, metadata, session, window))
            continue
        anchor = max(valid_dates)
        for session in sessions:
            session_rows = [row for row in observations if row["session_key"] == session.key
                            and row["valid"] and not row.get("is_partial", False)]
            for window in windows:
                cutoff = anchor - timedelta(days=max(1, int(window)) - 1)
                sample = [row for row in session_rows if cutoff <= date.fromisoformat(row["date"]) <= anchor]
                rvs = [float(row["realised_vol_pct"]) for row in sample]
                ranges = [float(row["range_pct"]) for row in sample if row.get("range_pct") is not None]
                returns = [float(row["session_return_pct"]) for row in sample if row.get("session_return_pct") is not None]
                latest = max(sample, key=lambda row: row["date"]) if sample else None
                latest_rv = float(latest["realised_vol_pct"]) if latest else None
                summary_rows.append({
                    "asset_key": asset_key, "asset_name": str(metadata.get("name") or asset_key),
                    "symbol": str(metadata.get("symbol") or ""), "unit": str(metadata.get("unit") or ""),
                    "source": str(metadata.get("source") or "Unknown source"),
                    "session_key": session.key, "session_name": session.name, "window_days": int(window),
                    "sample_count": len(rvs), "mean_rv_pct": statistics.fmean(rvs) if rvs else None,
                    "median_rv_pct": statistics.median(rvs) if rvs else None,
                    "p75_rv_pct": _percentile(rvs, 75), "p90_rv_pct": _percentile(rvs, 90),
                    "stdev_rv_pct": statistics.stdev(rvs) if len(rvs) >= 2 else None,
                    "min_rv_pct": min(rvs) if rvs else None, "max_rv_pct": max(rvs) if rvs else None,
                    "latest_rv_pct": latest_rv,
                    "latest_percentile": _percentile_rank(rvs, latest_rv) if latest_rv is not None else None,
                    "median_range_pct": statistics.median(ranges) if ranges else None,
                    "mean_return_pct": statistics.fmean(returns) if returns else None,
                    "median_return_pct": statistics.median(returns) if returns else None,
                    "win_rate_pct": (sum(value > 0 for value in returns) / len(returns) * 100) if returns else None,
                    "latest_date": latest["date"] if latest else "",
                    "coverage_start": min((row["date"] for row in sample), default=""),
                    "coverage_end": max((row["date"] for row in sample), default=""),
                    "calendar_days_covered": (
                        (date.fromisoformat(max(row["date"] for row in sample)) -
                         date.fromisoformat(min(row["date"] for row in sample))).days + 1
                    ) if sample else 0,
                    "bar_interval_minutes": float(metadata.get("bar_interval_minutes") or 0.0),
                })
    return summary_rows, observation_map


def analyse_research_assets(
    asset_data: dict[str, dict[str, Any]], sessions: list[SessionDefinition], *,
    windows: tuple[int, ...] = (30, 60, 90), now: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    """Parse cached JSON OHLC records and calculate all research outputs.

    This pure function is designed to run in a worker thread. It never accesses Tk
    widgets and returns compact metadata rather than retaining raw bar dictionaries.
    """
    bars_by_asset: dict[str, list[OHLCBar]] = {}
    metadata: dict[str, dict[str, Any]] = {}
    for asset_key, item in asset_data.items():
        bars: list[OHLCBar] = []
        for raw in item.get("bars", []):
            try:
                bars.append(OHLCBar.from_dict(raw))
            except (KeyError, TypeError, ValueError):
                continue
        if not bars:
            continue
        asset_meta = {key: value for key, value in item.items() if key != "bars"}
        interval = asset_meta.get("bar_interval_minutes")
        if not interval:
            interval = infer_bar_interval_minutes(bars)
        nested_metadata = item.get("metadata", {})
        if not isinstance(nested_metadata, dict):
            nested_metadata = {}
        variable_interval = item.get(
            "variable_interval_bars", nested_metadata.get("variable_interval_bars", False)
        )
        asset_meta.update({
            "name": asset_meta.get("name", asset_key),
            "symbol": asset_meta.get("symbol", ""),
            "unit": asset_meta.get("unit", ""),
            "source": asset_meta.get("source", "Unknown source"),
            "bar_interval_minutes": float(interval),
            "bar_count": len(bars),
            "variable_interval_bars": bool(variable_interval),
        })
        bars_by_asset[asset_key] = bars
        metadata[asset_key] = asset_meta
    rows, observations = analyse_session_history(
        bars_by_asset, metadata, sessions, windows=windows, now=now
    )
    return rows, observations, metadata


def _empty_summary(asset_key: str, metadata: dict[str, Any], session: SessionDefinition, window: int) -> dict[str, Any]:
    return {
        "asset_key": asset_key, "asset_name": str(metadata.get("name") or asset_key),
        "symbol": str(metadata.get("symbol") or ""), "unit": str(metadata.get("unit") or ""),
        "source": str(metadata.get("source") or "Unknown source"),
        "session_key": session.key, "session_name": session.name, "window_days": int(window),
        "sample_count": 0, "mean_rv_pct": None, "median_rv_pct": None, "p75_rv_pct": None,
        "p90_rv_pct": None, "stdev_rv_pct": None, "min_rv_pct": None, "max_rv_pct": None,
        "latest_rv_pct": None, "latest_percentile": None, "median_range_pct": None,
        "mean_return_pct": None, "median_return_pct": None, "win_rate_pct": None,
        "latest_date": "", "coverage_start": "", "coverage_end": "", "calendar_days_covered": 0,
        "bar_interval_minutes": float(metadata.get("bar_interval_minutes") or 0.0),
    }


def _spreadsheet_safe(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_summary_csv(path: str | Path, rows: list[dict[str, Any]], *, generated_at: datetime | None = None) -> Path:
    destination = Path(path)
    fields = [
        "asset_name", "symbol", "unit", "source", "session_name", "window_days", "sample_count",
        "mean_rv_pct", "median_rv_pct", "p75_rv_pct", "p90_rv_pct", "stdev_rv_pct",
        "latest_rv_pct", "latest_percentile", "median_range_pct", "mean_return_pct",
        "median_return_pct", "win_rate_pct", "latest_date", "coverage_start", "coverage_end",
        "bar_interval_minutes",
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["generated_at_utc", *fields], extrasaction="ignore")
        writer.writeheader()
        timestamp = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        for row in rows:
            writer.writerow({
                key: _spreadsheet_safe(value)
                for key, value in {"generated_at_utc": timestamp, **row}.items()
            })
    return destination


def export_daily_observations_csv(path: str | Path, observations: dict[str, list[dict[str, Any]]]) -> Path:
    destination = Path(path)
    fields = ["asset_key", "session_key", "session_name", "date", "realised_vol_pct", "range_pct",
              "session_return_pct", "bars", "returns", "bar_interval_minutes", "valid", "is_partial",
              "start_utc", "end_utc"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for asset_key, rows in observations.items():
            for row in rows:
                writer.writerow({
                    key: _spreadsheet_safe(value)
                    for key, value in {"asset_key": asset_key, **row}.items()
                })
    return destination


def export_html_report(
    path: str | Path, rows: list[dict[str, Any]], observations: dict[str, list[dict[str, Any]]],
    *, generated_at: datetime | None = None,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    generated = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    columns = [
        ("Instrument", "asset_name"), ("Symbol", "symbol"), ("Unit", "unit"), ("Source", "source"),
        ("Bar interval (min)", "bar_interval_minutes"), ("Session", "session_name"),
        ("Window (days)", "window_days"), ("Samples", "sample_count"), ("Mean RV %", "mean_rv_pct"),
        ("Median RV %", "median_rv_pct"), ("P75 RV %", "p75_rv_pct"), ("P90 RV %", "p90_rv_pct"),
        ("Latest RV %", "latest_rv_pct"), ("Latest percentile", "latest_percentile"),
        ("Median range %", "median_range_pct"), ("Win rate %", "win_rate_pct"),
    ]
    def cell(value: Any) -> str:
        if value is None:
            return "N/A"
        if isinstance(value, float):
            return f"{value:.4f}"
        return str(value)
    header = "".join(f"<th>{html.escape(label)}</th>" for label, _ in columns)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(cell(row.get(key)))}</td>" for _, key in columns)
        body_rows.append(f"<tr>{cells}</tr>")
    daily_rows = []
    for asset_key, items in observations.items():
        for item in items:
            daily_rows.append(
                "<tr>" + "".join(f"<td>{html.escape(cell(value))}</td>" for value in (
                    asset_key, item.get("session_name"), item.get("date"),
                    "PARTIAL · EXCLUDED FROM DISTRIBUTIONS" if item.get("is_partial") else "COMPLETE / HISTORICAL",
                    item.get("realised_vol_pct"), item.get("range_pct"), item.get("session_return_pct"),
                    item.get("bars"), item.get("returns"),
                )) + "</tr>"
            )
    daily_head = "".join(f"<th>{name}</th>" for name in ("Asset", "Session", "Date", "Observation status", "RV %", "Range %", "Return %", "Bars", "Returns"))
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Veltrix Historical Session Research</title>
<style>
body{{font:14px Segoe UI,Arial,sans-serif;background:#08131c;color:#d8e8ef;margin:32px}}
h1,h2{{color:#48d9e6}}p{{color:#a7bdc8}}.wrap{{overflow-x:auto;margin:18px 0}}
table{{border-collapse:collapse;width:100%;background:#0d202b}}th,td{{border:1px solid #24424f;padding:8px;text-align:left;white-space:nowrap}}
th{{background:#12303d;color:#72edf0}}tr:nth-child(even){{background:#102630}}.note{{border-left:3px solid #48d9e6;padding:10px 14px;background:#10232c}}
</style></head><body>
<h1>VELTRIX CAPITAL · HISTORICAL SESSION RESEARCH</h1>
<p>Generated: {html.escape(generated)} · UTC</p>
<div class="note"><strong>Interpretation:</strong> Descriptive historical statistics, not a trading signal or forecast. Missing observations are not treated as zero. Results depend on the selected source, bar interval, session definitions and timezone handling.</div>
<h2>Rolling session distribution summary</h2><div class="wrap"><table><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>
<h2>Daily session observations</h2><div class="wrap"><table><thead><tr>{daily_head}</tr></thead><tbody>{''.join(daily_rows)}</tbody></table></div>
<h2>Methodology</h2><p>Session realised volatility is sqrt(sum of squared log returns) × 100, including the first bar's open-to-close return and subsequent adjacent close-to-close returns. For time-based bars, close-to-close returns are only calculated across adjacent bars whose gap does not exceed 1.6 times the inferred bar interval (with a 2-minute tolerance). For event-driven fixed-tick and Tick Imbalance Bar datasets, elapsed time varies by design, so adjacent within-session returns are retained; median elapsed minutes is descriptive only. Session range is (highest high − lowest low) / first open × 100. Session return is (last close / first open − 1) × 100. Rolling windows use calendar days ending at the latest valid completed observation date. Percentile rank uses mid-ranks for tied values. An in-progress current session is shown as PARTIAL in daily observations and excluded from historical distributions, percentile ranks and win-rate statistics.</p>
<p>Review data-source permissions and validate broker exports before relying on results. This report contains no executable orders or investment advice.</p>
</body></html>"""
    destination.write_text(document, encoding="utf-8")
    return destination


def save_research_cache(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(destination)


def load_research_cache(path: str | Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("assets"), dict):
            return None
        for asset in payload["assets"].values():
            if not isinstance(asset, dict) or not isinstance(asset.get("bars"), list):
                return None
        return payload
    except (OSError, ValueError, TypeError):
        return None
