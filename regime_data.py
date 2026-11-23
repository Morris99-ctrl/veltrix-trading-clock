"""Local OHLC CSV import and persistence for the standalone Regime Lab."""
from __future__ import annotations

import csv
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from market_data import OHLCBar

CSV_MAX_BYTES = 100 * 1024 * 1024
CSV_MAX_ROWS = 2_000_000

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


def _normalise_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def _find_column(headers: list[str], kind: str) -> str | None:
    aliases = {_normalise_header(item) for item in HEADER_ALIASES[kind]}
    return next((header for header in headers if _normalise_header(header) in aliases), None)


def _parse_timestamp(value: str, naive_zone: ZoneInfo) -> datetime:
    raw = str(value).strip().strip('"').strip("'")
    if not raw:
        raise ValueError("empty timestamp")
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
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field} value {raw!r}") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"invalid {field} value {raw!r}")
    return parsed


def import_ohlc_csv(path: str | Path, *, naive_timezone: str = "UTC") -> tuple[list[OHLCBar], dict[str, Any]]:
    """Import common broker OHLC CSV formats into sorted, de-duplicated UTC bars."""
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
        if timestamp_col is None and time_col and not date_col:
            timestamp_col = time_col
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
                if volume is not None and volume < 0:
                    raise ValueError("volume cannot be negative")
                parsed_by_timestamp[stamp.isoformat()] = OHLCBar(stamp.isoformat(), o, h, low, close, volume)
            except (ValueError, TypeError, AssertionError, OverflowError):
                invalid_rows += 1

    bars = sorted(parsed_by_timestamp.values(), key=lambda item: item.timestamp)
    if not bars:
        raise ValueError("No valid OHLC rows could be imported. Check the headers, timezone and price columns.")
    return bars, {
        "source": "CSV import",
        "file_name": source.name,
        "timezone_for_naive_timestamps": naive_timezone,
        "rows_read": total_rows,
        "valid_bars": len(bars),
        "invalid_rows": invalid_rows,
        "duplicate_timestamps": max(0, total_rows - invalid_rows - len(bars)),
        "start_utc": bars[0].timestamp.isoformat(),
        "end_utc": bars[-1].timestamp.isoformat(),
    }


def infer_bar_interval_minutes(bars: list[OHLCBar], fallback: float = 60.0) -> float:
    gaps = [
        (current.timestamp - previous.timestamp).total_seconds() / 60.0
        for previous, current in zip(bars, bars[1:])
        if current.timestamp > previous.timestamp
    ]
    return float(median(gaps)) if gaps else float(fallback)


def _normalise_dataset_record(record: Any) -> dict[str, Any] | None:
    if not isinstance(record, dict) or not isinstance(record.get("bars"), list):
        return None
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    # The core clock deliberately does not expose information-driven/tick-bar research.
    if record.get("variable_interval_bars") or metadata.get("variable_interval_bars") or metadata.get("bar_construction"):
        return None

    bars: list[OHLCBar] = []
    for raw in record["bars"]:
        try:
            bar = raw if isinstance(raw, OHLCBar) else OHLCBar.from_dict(raw)
            values = (bar.open, bar.high, bar.low, bar.close)
            if not all(math.isfinite(float(value)) and float(value) > 0 for value in values):
                continue
            if bar.high < max(bar.open, bar.close, bar.low) or bar.low > min(bar.open, bar.close):
                continue
            bars.append(bar)
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            continue
    if not bars:
        return None
    bars.sort(key=lambda item: item.timestamp)
    result = dict(record)
    result["bars"] = [bar.to_dict() for bar in bars]
    result["metadata"] = dict(metadata)
    result.setdefault("name", "Imported OHLC dataset")
    result.setdefault("source", "Local OHLC dataset")
    result["bar_interval_minutes"] = float(
        result.get("bar_interval_minutes") or infer_bar_interval_minutes(bars)
    )
    return result


def load_regime_datasets(path: str | Path, legacy_path: str | Path | None = None) -> dict[str, Any]:
    """Load standalone datasets, migrating regular OHLC assets from the old research cache once."""
    source = Path(path)
    if source.is_file():
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
        raw = payload.get("datasets", {}) if isinstance(payload, dict) else {}
        datasets = {
            str(key): cleaned
            for key, value in raw.items()
            if (cleaned := _normalise_dataset_record(value)) is not None
        } if isinstance(raw, dict) else {}
        return {"datasets": datasets, "migrated_from_legacy": False, "skipped_tick_datasets": 0}

    legacy = Path(legacy_path) if legacy_path is not None else None
    if legacy is None or not legacy.is_file():
        return {"datasets": {}, "migrated_from_legacy": False, "skipped_tick_datasets": 0}
    try:
        payload = json.loads(legacy.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"datasets": {}, "migrated_from_legacy": False, "skipped_tick_datasets": 0}

    datasets: dict[str, dict[str, Any]] = {}
    skipped_tick = 0
    if isinstance(payload, dict):
        for section in ("assets", "provider_assets"):
            records = payload.get(section, {})
            if not isinstance(records, dict):
                continue
            for key, value in records.items():
                if isinstance(value, dict):
                    metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
                    if value.get("variable_interval_bars") or metadata.get("variable_interval_bars") or metadata.get("bar_construction"):
                        skipped_tick += 1
                        continue
                    cleaned = _normalise_dataset_record(value)
                    if cleaned is not None:
                        datasets[str(key)] = cleaned
    return {
        "datasets": datasets,
        "migrated_from_legacy": bool(datasets),
        "skipped_tick_datasets": skipped_tick,
    }


def save_regime_datasets(path: str | Path, datasets: dict[str, dict[str, Any]]) -> None:
    """Atomically persist the local OHLC dataset library."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "datasets": datasets,
    }
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(destination)
