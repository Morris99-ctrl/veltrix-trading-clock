"""Provider-neutral market-data gateway and validation tools for Veltrix.

API credentials are read from the local .env file and process environment.
On Windows, the local file is protected with the current user's DPAPI key.
Process environment variables take precedence. Credentials are never written
to config.json, logs, URLs displayed in the UI, or research metadata.
"""
from __future__ import annotations

import json
import math
import os
import re
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from app_paths import APP_DATA_DIR
from market_data import OHLCBar
from secure_credentials import CredentialFileError, load_env_file

MAX_RESPONSE_BYTES = 20 * 1024 * 1024
USER_AGENT = "VeltrixTradingClock/9.4 (market-data-gateway)"
ENV_FILE_PATH = APP_DATA_DIR / ".env"


def load_local_env(env_path: str | Path | None = None) -> bool:
    """Load an optional local .env without overriding process environment vars.

    In source mode the data directory is beside main.py. In a frozen desktop
    build it is the per-user LocalAppData folder, so shortcuts and Start-menu
    launches find the same credentials regardless of the working directory.
    Existing Windows/process environment variables deliberately take priority.
    """
    path = Path(env_path).expanduser() if env_path is not None else ENV_FILE_PATH
    if not path.is_file():
        return False
    dotenv_text = load_env_file(path)
    if dotenv_text is None:
        return False
    load_dotenv(stream=StringIO(dotenv_text), override=False)
    return True


# Load credentials as soon as the gateway is imported, before the Data Center
# checks provider status. No secret values are copied into application config.
CREDENTIAL_LOAD_ERROR: str | None = None
try:
    DOTENV_FILE_LOADED = load_local_env()
except CredentialFileError as exc:
    DOTENV_FILE_LOADED = False
    CREDENTIAL_LOAD_ERROR = str(exc)

PROVIDER_CATALOG: dict[str, dict[str, Any]] = {
    "massive": {
        "name": "Massive",
        "env_var": "MASSIVE_API_KEY",
        "website": "https://massive.com/",
        "docs": "https://massive.com/docs",
        "coverage": "Forex, indices and exchange-traded US futures; plan and symbol dependent.",
        "best_for": "Index and futures aggregates; forex quotes where covered.",
        "adapter": True,
    },
    "twelve_data": {
        "name": "Twelve Data",
        "env_var": "TWELVE_DATA_API_KEY",
        "website": "https://twelvedata.com/",
        "docs": "https://twelvedata.com/docs",
        "coverage": "Forex, commodities, equities and other markets; symbol and plan dependent.",
        "best_for": "A direct XAU/USD spot-data candidate and broad symbol coverage.",
        "adapter": True,
    },
    "databento": {
        "name": "Databento",
        "env_var": "DATABENTO_API_KEY",
        "website": "https://databento.com/",
        "docs": "https://databento.com/docs",
        "coverage": "Exchange-published trades, quotes and order-book data; dataset/licence dependent.",
        "best_for": "Exchange-traded futures research, not OTC XAU/USD spot.",
        "adapter": False,
    },
}

INTERVALS: dict[str, tuple[int, str]] = {
    "1m": (1, "minute"),
    "5m": (5, "minute"),
    "15m": (15, "minute"),
    "30m": (30, "minute"),
    "1h": (1, "hour"),
    "1d": (1, "day"),
}
TWELVE_INTERVALS = {
    "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1h", "1d": "1day",
}


class DataGatewayError(RuntimeError):
    """A safe, user-facing provider or data-normalisation error."""


@dataclass(frozen=True)
class ProviderStatus:
    provider_id: str
    name: str
    env_var: str
    credential_configured: bool
    adapter_available: bool
    website: str
    docs: str
    coverage: str
    best_for: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def provider_statuses() -> list[ProviderStatus]:
    statuses: list[ProviderStatus] = []
    for provider_id, spec in PROVIDER_CATALOG.items():
        statuses.append(ProviderStatus(
            provider_id=provider_id,
            name=str(spec["name"]),
            env_var=str(spec["env_var"]),
            credential_configured=bool(os.environ.get(str(spec["env_var"]), "").strip()),
            adapter_available=bool(spec["adapter"]),
            website=str(spec["website"]),
            docs=str(spec["docs"]),
            coverage=str(spec["coverage"]),
            best_for=str(spec["best_for"]),
        ))
    return statuses


def get_api_key(provider_id: str, explicit_key: str | None = None) -> str:
    if provider_id not in PROVIDER_CATALOG:
        raise DataGatewayError(f"Unknown provider: {provider_id}")
    key = (explicit_key or os.environ.get(PROVIDER_CATALOG[provider_id]["env_var"], "")).strip()
    if not key:
        raise DataGatewayError(
            f"{PROVIDER_CATALOG[provider_id]['name']} API key is not configured. "
            f"Add {PROVIDER_CATALOG[provider_id]['env_var']} to the local .env file in {APP_DATA_DIR} "
            f"or set it in your process environment, then restart Veltrix."
        )
    return key


def _safe_error_message(message: str, api_key: str) -> str:
    clean = str(message).replace(api_key, "[redacted]")
    clean = re.sub(r"(?i)(apikey|api_key|token)=([^&\s]+)", r"\1=[redacted]", clean)
    return clean[:500]


def _request_json(url: str, *, timeout: int, api_key: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise DataGatewayError("Provider response exceeded the 20 MB safety limit.")
        payload = json.loads(body.decode("utf-8"))
    except HTTPError as exc:
        try:
            details = exc.read(2048).decode("utf-8", errors="replace")
            details = _safe_error_message(details, api_key)
        except Exception:
            details = ""
        suffix = f" · {details}" if details else ""
        raise DataGatewayError(f"Provider HTTP {exc.code}{suffix}") from None
    except URLError as exc:
        reason = _safe_error_message(str(getattr(exc, "reason", "network error")), api_key)
        raise DataGatewayError(f"Provider connection failed: {reason}") from None
    except TimeoutError:
        raise DataGatewayError("Provider request timed out.") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataGatewayError(f"Provider response could not be read: {_safe_error_message(str(exc), api_key)}") from None
    if not isinstance(payload, dict):
        raise DataGatewayError("Provider returned an unexpected response format.")
    return payload


def _validate_dates(start_date: str, end_date: str) -> tuple[str, str]:
    try:
        start = date.fromisoformat(str(start_date))
        end = date.fromisoformat(str(end_date))
    except ValueError as exc:
        raise ValueError("Start and end dates must use YYYY-MM-DD format.") from exc
    if end < start:
        raise ValueError("End date cannot be earlier than start date.")
    if (end - start).days > 3650:
        raise ValueError("A single provider request is limited to a 10-year date range.")
    return start.isoformat(), end.isoformat()


def _timestamp_to_utc(value: Any, default_timezone=timezone.utc) -> datetime:
    if isinstance(value, (int, float)):
        number = float(value)
        absolute = abs(number)
        if absolute >= 1e17:       # nanoseconds
            number /= 1e9
        elif absolute >= 1e14:     # microseconds
            number /= 1e6
        elif absolute >= 1e11:     # milliseconds
            number /= 1e3
        return datetime.fromtimestamp(number, tz=timezone.utc)
    text = str(value).strip()
    if not text:
        raise ValueError("Missing bar timestamp")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y%m%d-%H%M%S"):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"Unrecognised provider timestamp: {text}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_timezone)
    return parsed.astimezone(timezone.utc)


def _valid_ohlc(open_price: Any, high: Any, low: Any, close: Any) -> tuple[float, float, float, float]:
    values = tuple(float(value) for value in (open_price, high, low, close))
    o, h, l, c = values
    if not all(math.isfinite(value) and value > 0 for value in values):
        raise ValueError("OHLC values must be finite positive prices")
    if h < l or h + 1e-10 < max(o, c) or l - 1e-10 > min(o, c):
        raise ValueError("OHLC high/low bounds are inconsistent")
    return values


def parse_twelve_data_payload(payload: dict[str, Any]) -> tuple[list[OHLCBar], dict[str, Any]]:
    if str(payload.get("status", "")).lower() == "error" or payload.get("code"):
        message = payload.get("message") or payload.get("status") or "Twelve Data returned an error"
        raise DataGatewayError(str(message))
    values = payload.get("values")
    if not isinstance(values, list):
        raise DataGatewayError("Twelve Data response contains no time-series values.")
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    interval_name = str(meta.get("interval") or "").lower()
    exchange_timezone = str(meta.get("exchange_timezone") or "UTC")
    # Twelve Data ignores the timezone parameter for daily/weekly/monthly bars;
    # their naive timestamps use the exchange timezone in that case.
    default_tz = timezone.utc
    if any(token in interval_name for token in ("day", "week", "month")):
        try:
            default_tz = ZoneInfo(exchange_timezone)
        except ZoneInfoNotFoundError:
            default_tz = timezone.utc
    bars: list[OHLCBar] = []
    invalid_rows_skipped = 0
    for row in values:
        if not isinstance(row, dict):
            invalid_rows_skipped += 1
            continue
        try:
            timestamp = _timestamp_to_utc(row.get("datetime"), default_timezone=default_tz)
            o, h, l, c = _valid_ohlc(row.get("open"), row.get("high"), row.get("low"), row.get("close"))
            raw_volume = row.get("volume")
            volume = None if raw_volume in (None, "", "null") else float(raw_volume)
            if volume is not None and (not math.isfinite(volume) or volume < 0):
                volume = None
            bars.append(OHLCBar(timestamp.isoformat(), o, h, l, c, volume))
        except (TypeError, ValueError, OverflowError):
            invalid_rows_skipped += 1
            continue
    raw_valid_count = len(bars)
    bars = _deduplicate_and_sort(bars)
    duplicates_removed = raw_valid_count - len(bars)
    if not bars:
        raise DataGatewayError("Twelve Data returned no valid OHLC bars for this symbol and request.")
    metadata = {
        "invalid_rows_skipped": invalid_rows_skipped,
        "duplicate_timestamps_removed": duplicates_removed,
        "provider": "Twelve Data",
        "provider_symbol": str(meta.get("symbol") or ""),
        "exchange": str(meta.get("exchange") or ""),
        "exchange_timezone": str(meta.get("exchange_timezone") or "UTC"),
        "interval": str(meta.get("interval") or ""),
        "price_basis": (
            "Provider-supplied OTC spot/FX price series; not a consolidated exchange trade tape. "
            "Confirm construction and entitlement for the selected symbol and plan."
            if "/" in str(meta.get("symbol") or "") else
            "Provider-supplied OHLC series; instrument-specific price basis must be confirmed from provider metadata."
        ),
        "volume_semantics": "Provider field retained as supplied; verify whether it represents transactions, quote updates or is unavailable.",
        "request_date_basis": "UTC for intraday; exchange-local for daily, weekly and monthly intervals.",
        "timestamp_normalisation": "Intraday timestamps requested in UTC; daily and higher timestamps are exchange-local and converted to UTC.",
    }
    return bars, metadata


def parse_massive_payload(payload: dict[str, Any], *, asset_class: str, symbol: str) -> tuple[list[OHLCBar], dict[str, Any]]:
    status = str(payload.get("status") or "").upper()
    if status in {"ERROR", "NOT_AUTHORIZED", "DELAYED"} and not payload.get("results"):
        message = payload.get("error") or payload.get("message") or payload.get("status") or "Massive returned an error"
        raise DataGatewayError(str(message))
    results = payload.get("results")
    if not isinstance(results, list):
        raise DataGatewayError("Massive response contains no aggregate results.")
    bars: list[OHLCBar] = []
    invalid_rows_skipped = 0
    for row in results:
        if not isinstance(row, dict):
            invalid_rows_skipped += 1
            continue
        raw_timestamp = row.get("t", row.get("window_start", row.get("timestamp")))
        try:
            timestamp = _timestamp_to_utc(raw_timestamp)
            o, h, l, c = _valid_ohlc(
                row.get("o", row.get("open")), row.get("h", row.get("high")),
                row.get("l", row.get("low")), row.get("c", row.get("close")),
            )
            raw_volume = row.get("v", row.get("volume"))
            volume = None if raw_volume is None else float(raw_volume)
            if volume is not None and (not math.isfinite(volume) or volume < 0):
                volume = None
            bars.append(OHLCBar(timestamp.isoformat(), o, h, l, c, volume))
        except (TypeError, ValueError, OverflowError):
            invalid_rows_skipped += 1
            continue
    raw_valid_count = len(bars)
    bars = _deduplicate_and_sort(bars)
    duplicates_removed = raw_valid_count - len(bars)
    if not bars:
        raise DataGatewayError("Massive returned no valid OHLC bars for this symbol and request.")
    metadata = {
        "invalid_rows_skipped": invalid_rows_skipped,
        "duplicate_timestamps_removed": duplicates_removed,
        "provider": "Massive",
        "provider_symbol": symbol,
        "asset_class": asset_class,
        "exchange_timezone": "UTC",
        "request_window_timezone": (
            "UTC date filters for futures; returned timestamps are UTC." if asset_class == "futures" else
            "Eastern Time (ET) date-window semantics; returned timestamps are UTC."
        ),
        "request_date_basis": (
            "UTC" if asset_class == "futures" else "America/New_York (Eastern Time)"
        ),
        "price_basis": (
            "Exchange trades for futures aggregate bars." if asset_class == "futures" else
            "Index values for index aggregates." if asset_class == "indices" else
            "Bid-price quote aggregates, not executed trades or midpoint prices."
        ),
        "volume_semantics": (
            "Provider-reported futures trade volume." if asset_class == "futures" else
            "Not applicable to index values; treat provider volume as unavailable." if asset_class == "indices" else
            "Quote count, not traded volume; forex has no consolidated trade tape."
        ),
    }
    return bars, metadata


def _deduplicate_and_sort(bars: list[OHLCBar]) -> list[OHLCBar]:
    by_timestamp: dict[str, OHLCBar] = {}
    for bar in bars:
        by_timestamp[bar.timestamp.astimezone(timezone.utc).isoformat()] = bar
    return sorted(by_timestamp.values(), key=lambda item: item.timestamp)


def fetch_twelve_data_bars(
    symbol: str, *, interval: str, start_date: str, end_date: str,
    api_key: str | None = None, timeout: int = 20,
) -> tuple[list[OHLCBar], dict[str, Any]]:
    key = get_api_key("twelve_data", api_key)
    if interval not in TWELVE_INTERVALS:
        raise ValueError(f"Unsupported Twelve Data interval: {interval}")
    start, end = _validate_dates(start_date, end_date)
    clean_symbol = str(symbol).strip()
    if not clean_symbol or len(clean_symbol) > 80:
        raise ValueError("Enter a valid provider-native Twelve Data symbol.")
    params = urlencode({
        "symbol": clean_symbol,
        "interval": TWELVE_INTERVALS[interval],
        "start_date": start,
        "end_date": end,
        "timezone": "UTC",
        "order": "ASC",
        "apikey": key,
    })
    payload = _request_json(f"https://api.twelvedata.com/time_series?{params}", timeout=timeout, api_key=key)
    bars, metadata = parse_twelve_data_payload(payload)
    metadata.update({
        "requested_interval": interval, "requested_start": start, "requested_end": end,
        "response_bars": len(bars),
        "potentially_truncated": len(bars) >= 5000,
        "response_limit": 5000,
    })
    return bars, metadata


def _append_massive_api_key(url: str, api_key: str) -> str:
    absolute = urljoin("https://api.massive.com/", str(url))
    parts = urlsplit(absolute)
    if parts.scheme != "https" or parts.netloc.lower() != "api.massive.com":
        raise DataGatewayError("Massive pagination returned an unexpected destination host.")
    query_items = parse_qsl(parts.query, keep_blank_values=True)
    if not any(key.casefold() == "apikey" for key, _value in query_items):
        query_items.append(("apiKey", api_key))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query_items), parts.fragment))


def _fetch_massive_pages(url: str, *, api_key: str, timeout: int, max_pages: int = 5) -> tuple[dict[str, Any], int, bool]:
    """Fetch at most five 50k pages; report a cap rather than hiding truncation."""
    first = _request_json(url, timeout=timeout, api_key=api_key)
    combined = dict(first)
    combined_results = list(first.get("results", [])) if isinstance(first.get("results"), list) else []
    page_count = 1
    next_url = first.get("next_url")
    while next_url and page_count < max_pages:
        page_url = _append_massive_api_key(str(next_url), api_key)
        page = _request_json(page_url, timeout=timeout, api_key=api_key)
        page_results = page.get("results", [])
        if isinstance(page_results, list):
            combined_results.extend(page_results)
        page_count += 1
        next_url = page.get("next_url")
    combined["results"] = combined_results
    combined.pop("next_url", None)
    return combined, page_count, not bool(next_url)


def fetch_massive_bars(
    symbol: str, *, asset_class: str, interval: str, start_date: str, end_date: str,
    api_key: str | None = None, timeout: int = 20,
) -> tuple[list[OHLCBar], dict[str, Any]]:
    key = get_api_key("massive", api_key)
    if interval not in INTERVALS:
        raise ValueError(f"Unsupported Massive interval: {interval}")
    asset = str(asset_class).strip().lower()
    if asset not in {"forex", "indices", "futures"}:
        raise ValueError("Massive supports forex, indices or futures in this gateway.")
    start, end = _validate_dates(start_date, end_date)
    clean_symbol = str(symbol).strip()
    if not clean_symbol or len(clean_symbol) > 80:
        raise ValueError("Enter a valid provider-native Massive ticker.")
    multiplier, timespan = INTERVALS[interval]
    encoded_symbol = quote(clean_symbol, safe=":")
    if asset == "futures":
        resolution_unit = {"minute": "min", "hour": "hour", "day": "day"}[timespan]
        resolution = f"{multiplier}{resolution_unit}"
        query = urlencode({
            "resolution": resolution,
            "window_start.gte": start,
            "window_start.lte": end,
            "sort": "window_start.asc",
            "limit": 50000,
            "apiKey": key,
        })
        url = f"https://api.massive.com/futures/v1/aggs/{encoded_symbol}?{query}"
    else:
        query = urlencode({"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": key})
        url = (
            f"https://api.massive.com/v2/aggs/ticker/{encoded_symbol}/range/"
            f"{multiplier}/{timespan}/{start}/{end}?{query}"
        )
    payload, page_count, pagination_complete = _fetch_massive_pages(url, timeout=timeout, api_key=key)
    bars, metadata = parse_massive_payload(payload, asset_class=asset, symbol=clean_symbol)
    metadata.update({
        "requested_interval": interval, "requested_start": start, "requested_end": end,
        "pagination_pages": page_count, "pagination_complete": pagination_complete,
    })
    return bars, metadata


def test_provider_connection(provider_id: str, *, timeout: int = 12) -> dict[str, Any]:
    """Perform a small real API request; never expose the credential or request URL."""
    key = get_api_key(provider_id)
    started = time.monotonic()
    if provider_id == "massive":
        params = urlencode({"market": "indices", "active": "true", "limit": 1, "apiKey": key})
        payload = _request_json(f"https://api.massive.com/v3/reference/tickers?{params}", timeout=timeout, api_key=key)
        if str(payload.get("status", "")).upper() in {"ERROR", "NOT_AUTHORIZED"}:
            raise DataGatewayError(str(payload.get("error") or payload.get("status")))
        if "results" not in payload:
            raise DataGatewayError("Massive responded, but the reference-data payload was unexpected.")
        detail = "Authenticated reference-data request succeeded. Instrument entitlement still needs separate testing."
    elif provider_id == "twelve_data":
        # /api_usage verifies the credential without assuming the account has
        # entitlement to a particular market or symbol. The endpoint consumes
        # one API credit, which is disclosed in the UI/README.
        params = urlencode({"apikey": key})
        payload = _request_json(f"https://api.twelvedata.com/api_usage?{params}", timeout=timeout, api_key=key)
        if str(payload.get("status", "")).lower() == "error" or payload.get("code"):
            raise DataGatewayError(str(payload.get("message") or "Twelve Data authentication check failed."))
        if not isinstance(payload, dict):
            raise DataGatewayError("Twelve Data responded, but the API-usage payload was unexpected.")
        detail = "Authenticated API-usage endpoint succeeded. This check consumes one API credit; instrument and plan entitlements must be tested separately."
    elif provider_id == "databento":
        raise DataGatewayError("Databento is registered as a research candidate, but its SDK adapter is not enabled in this release.")
    else:
        raise DataGatewayError(f"No connection test is available for {provider_id}.")
    return {
        "provider_id": provider_id,
        "connected": True,
        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "detail": detail,
    }


def audit_ohlc_bars(bars: list[dict[str, Any]] | list[OHLCBar]) -> dict[str, Any]:
    """Measure OHLC structural quality without pretending market closures are data gaps."""
    valid: list[tuple[datetime, float, float, float, float, float | None]] = []
    invalid = 0
    duplicates = 0
    out_of_order = 0
    missing_volume = 0
    seen: set[datetime] = set()
    prior_timestamp: datetime | None = None
    for item in bars:
        try:
            record = item.to_dict() if isinstance(item, OHLCBar) else item
            timestamp = _timestamp_to_utc(record.get("timestamp_utc", record.get("timestamp")))
            if prior_timestamp is not None and timestamp < prior_timestamp:
                out_of_order += 1
            prior_timestamp = timestamp
            if timestamp in seen:
                duplicates += 1
                continue
            seen.add(timestamp)
            o, h, l, c = _valid_ohlc(record.get("open"), record.get("high"), record.get("low"), record.get("close"))
            raw_volume = record.get("volume")
            volume = None if raw_volume in (None, "", "null") else float(raw_volume)
            if volume is None:
                missing_volume += 1
            elif not math.isfinite(volume) or volume < 0:
                volume = None
                missing_volume += 1
            valid.append((timestamp, o, h, l, c, volume))
        except (AttributeError, TypeError, ValueError, OverflowError):
            invalid += 1
    valid.sort(key=lambda row: row[0])
    gaps = [(valid[i][0] - valid[i - 1][0]).total_seconds() / 60.0 for i in range(1, len(valid))]
    positive_gaps = [gap for gap in gaps if gap > 0]
    median_gap = statistics.median(positive_gaps) if positive_gaps else None
    p95_gap = _percentile(positive_gaps, 0.95) if positive_gaps else None
    large_gap_count = sum(gap > 3 * median_gap for gap in positive_gaps) if median_gap else 0
    returns = [abs(math.log(valid[i][4] / valid[i - 1][4])) * 100 for i in range(1, len(valid))]
    return {
        "input_bars": len(bars),
        "valid_bars": len(valid),
        "invalid_bars": invalid,
        "duplicate_timestamps": duplicates,
        "out_of_order_timestamps": out_of_order,
        "missing_volume_bars": missing_volume,
        "first_timestamp_utc": valid[0][0].isoformat() if valid else None,
        "last_timestamp_utc": valid[-1][0].isoformat() if valid else None,
        "median_gap_minutes": round(median_gap, 3) if median_gap is not None else None,
        "p95_gap_minutes": round(p95_gap, 3) if p95_gap is not None else None,
        "max_gap_minutes": round(max(positive_gaps), 3) if positive_gaps else None,
        "gaps_over_3x_median": large_gap_count,
        "max_abs_close_return_pct": round(max(returns), 5) if returns else None,
        "gap_note": "Large gaps are candidates for review, not automatically missing bars; sessions, weekends and holidays must be considered.",
    }


def compare_ohlc_datasets(
    left_bars: list[dict[str, Any]], right_bars: list[dict[str, Any]], *,
    left_group: str, right_group: str, left_interval: float | None, right_interval: float | None,
) -> dict[str, Any]:
    """Compare two provider series only after requiring a common instrument and interval label."""
    if not left_group.strip() or left_group.strip().casefold() != right_group.strip().casefold():
        raise ValueError("Datasets must share the same canonical instrument label before comparison.")
    if left_interval is None or right_interval is None or abs(float(left_interval) - float(right_interval)) > 1e-9:
        raise ValueError("Datasets must use the same bar interval before comparison.")
    left = _close_map(left_bars)
    right = _close_map(right_bars)
    common = sorted(set(left).intersection(right))
    if len(common) < 3:
        raise ValueError("At least three common timestamps are required for a meaningful comparison.")
    differences_bps = [((left[t] - right[t]) / ((left[t] + right[t]) / 2.0)) * 10000.0 for t in common]
    abs_differences = [abs(value) for value in differences_bps]
    paired_left_returns: list[float] = []
    paired_right_returns: list[float] = []
    for previous, current in zip(common, common[1:]):
        if left[previous] > 0 and right[previous] > 0:
            paired_left_returns.append(math.log(left[current] / left[previous]))
            paired_right_returns.append(math.log(right[current] / right[previous]))
    correlation = _pearson(paired_left_returns, paired_right_returns)
    return {
        "canonical_instrument": left_group.strip(),
        "matched_timestamps": len(common),
        "left_total_bars": len(left),
        "right_total_bars": len(right),
        "left_overlap_pct": round(100 * len(common) / max(1, len(left)), 2),
        "right_overlap_pct": round(100 * len(common) / max(1, len(right)), 2),
        "mean_signed_close_difference_bps": round(statistics.mean(differences_bps), 4),
        "mean_absolute_close_difference_bps": round(statistics.mean(abs_differences), 4),
        "median_absolute_close_difference_bps": round(statistics.median(abs_differences), 4),
        "p95_absolute_close_difference_bps": round(_percentile(abs_differences, 0.95), 4),
        "max_absolute_close_difference_bps": round(max(abs_differences), 4),
        "matched_return_correlation": round(correlation, 6) if correlation is not None else None,
        "return_pairs": len(paired_left_returns),
        "method_note": "Exact UTC timestamp intersection. Price differences are descriptive; feeds may represent different quote composites or market conventions.",
    }


def _close_map(bars: list[dict[str, Any]]) -> dict[datetime, float]:
    values: dict[datetime, float] = {}
    for item in bars:
        timestamp = _timestamp_to_utc(item.get("timestamp_utc", item.get("timestamp")))
        close = float(item.get("close"))
        if math.isfinite(close) and close > 0:
            values[timestamp] = close
    return values


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    mean_left = statistics.mean(left)
    mean_right = statistics.mean(right)
    covariance = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    variance_left = sum((a - mean_left) ** 2 for a in left)
    variance_right = sum((b - mean_right) ** 2 for b in right)
    denominator = math.sqrt(variance_left * variance_right)
    return covariance / denominator if denominator > 0 else None
