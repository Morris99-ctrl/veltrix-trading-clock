"""Best-effort Yahoo Finance chart-data adapter for Veltrix Trading Clock.

This adapter uses Yahoo Finance's public chart endpoint. It is unofficial,
unauthenticated and not covered by an SLA. Treat values as indicative; confirm
critical prices with a broker or licensed market-data provider.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

API_HOSTS = ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com")
USER_AGENT = "Mozilla/5.0 (compatible; VeltrixTradingClock/6.0; market-monitor)"
MAX_RESPONSE_BYTES = 12 * 1024 * 1024


@dataclass(frozen=True)
class OHLCBar:
    timestamp_utc: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None

    @property
    def timestamp(self) -> datetime:
        return datetime.fromisoformat(self.timestamp_utc.replace("Z", "+00:00")).astimezone(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> "OHLCBar":
        return cls(
            timestamp_utc=str(item["timestamp_utc"]),
            open=float(item["open"]), high=float(item["high"]),
            low=float(item["low"]), close=float(item["close"]),
            volume=None if item.get("volume") is None else float(item["volume"]),
        )


def parse_chart_payload(payload: dict[str, Any]) -> tuple[list[OHLCBar], dict[str, Any]]:
    """Convert the Yahoo chart response to validated, ascending OHLC bars."""
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        raise ValueError("Market-data response is missing its chart object.")
    if chart.get("error"):
        error = chart["error"]
        if isinstance(error, dict):
            raise RuntimeError(str(error.get("description") or error.get("code") or "Yahoo chart error"))
        raise RuntimeError("Yahoo chart returned an error.")
    results = chart.get("result")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise ValueError("No chart result was returned for this instrument.")
    result = results[0]
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote_rows = indicators.get("quote") or []
    if not isinstance(quote_rows, list) or not quote_rows or not isinstance(quote_rows[0], dict):
        raise ValueError("Market-data response contains no OHLC quote arrays.")
    quote_row = quote_rows[0]
    arrays = {key: quote_row.get(key) or [] for key in ("open", "high", "low", "close", "volume")}

    bars: list[OHLCBar] = []
    seen: set[int] = set()
    for index, raw_timestamp in enumerate(timestamps):
        try:
            timestamp = int(raw_timestamp)
            if timestamp in seen:
                continue
            seen.add(timestamp)
            values = [arrays[key][index] if index < len(arrays[key]) else None
                      for key in ("open", "high", "low", "close")]
            if any(value is None for value in values):
                continue
            open_price, high, low, close = (float(value) for value in values)
            if min(open_price, high, low, close) <= 0 or high < low:
                continue
            if high + 1e-9 < max(open_price, close) or low - 1e-9 > min(open_price, close):
                continue
            volume_raw = arrays["volume"][index] if index < len(arrays["volume"]) else None
            volume = None if volume_raw is None else float(volume_raw)
            bars.append(OHLCBar(
                timestamp_utc=datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
                open=open_price, high=high, low=low, close=close, volume=volume,
            ))
        except (TypeError, ValueError, OverflowError, OSError):
            continue
    bars.sort(key=lambda bar: bar.timestamp)
    if not bars:
        raise ValueError("No valid OHLC bars were present in the provider response.")

    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    metadata = {
        "symbol": str(meta.get("symbol") or ""),
        "currency": str(meta.get("currency") or ""),
        "exchange_timezone": str(meta.get("exchangeTimezoneName") or "UTC"),
        "exchange": str(meta.get("fullExchangeName") or meta.get("exchangeName") or ""),
        "instrument_name": str(meta.get("longName") or meta.get("shortName") or ""),
        "regular_market_price": _safe_float(meta.get("regularMarketPrice")),
        "regular_market_time": _safe_int(meta.get("regularMarketTime")),
        "data_granularity": str(meta.get("dataGranularity") or ""),
    }
    return bars, metadata


def _safe_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def fetch_chart(symbol: str, *, interval: str, range_: str, timeout: int = 15) -> tuple[list[OHLCBar], dict[str, Any]]:
    """Fetch a single Yahoo chart series, trying its two public chart hosts."""
    if interval not in {"5m", "15m", "30m", "1h", "1d"}:
        raise ValueError(f"Unsupported chart interval: {interval}")
    if range_ not in {"1d", "5d", "1mo", "3mo", "6mo", "1y"}:
        raise ValueError(f"Unsupported chart range: {range_}")
    path_symbol = quote(str(symbol), safe="")
    query = urlencode({"range": range_, "interval": interval, "includePrePost": "false"})
    errors: list[str] = []
    for host in API_HOSTS:
        request = Request(
            f"{host}/v8/finance/chart/{path_symbol}?{query}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError("Market-data response exceeded the 12 MB safety limit.")
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Market-data provider returned an unexpected response format.")
            return parse_chart_payload(payload)
        except HTTPError as exc:
            errors.append(f"{host.split('//', 1)[-1]} HTTP {exc.code}")
        except (URLError, TimeoutError, OSError) as exc:
            errors.append(f"{host.split('//', 1)[-1]}: {exc}")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
            errors.append(f"{host.split('//', 1)[-1]}: {exc}")
        time.sleep(0.15)
    raise RuntimeError(f"Could not retrieve {symbol} ({interval}): {'; '.join(errors)}")


def fetch_market_snapshot(instruments: list[dict[str, Any]], *, intraday_range: str = "5d",
                          daily_range: str = "3mo", interval: str = "5m") -> dict[str, Any]:
    """Fetch intraday and daily bars per configured instrument; partial success is retained."""
    snapshot: dict[str, Any] = {
        "provider": "Yahoo Finance public chart endpoint",
        "provider_url": "https://finance.yahoo.com/",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "intraday_interval": interval,
        "intraday_range": intraday_range,
        "daily_range": daily_range,
        "assets": {},
    }
    successful = 0
    for instrument in instruments:
        key = str(instrument["key"])
        symbol = str(instrument["symbol"])
        asset: dict[str, Any] = {**instrument, "intraday_bars": [], "daily_bars": [], "intraday_meta": {},
                                 "daily_meta": {}, "error": ""}
        errors: list[str] = []
        try:
            bars, metadata = fetch_chart(symbol, interval=interval, range_=intraday_range)
            asset["intraday_bars"] = [bar.to_dict() for bar in bars]
            asset["intraday_meta"] = metadata
        except Exception as exc:
            errors.append(f"Intraday: {exc}")
        time.sleep(0.25)
        try:
            bars, metadata = fetch_chart(symbol, interval="1d", range_=daily_range)
            asset["daily_bars"] = [bar.to_dict() for bar in bars]
            asset["daily_meta"] = metadata
        except Exception as exc:
            errors.append(f"Daily: {exc}")
        asset["error"] = " | ".join(errors)
        if asset["intraday_bars"] or asset["daily_bars"]:
            successful += 1
        snapshot["assets"][key] = asset
        time.sleep(0.25)
    if successful == 0:
        errors = [f"{item.get('name', key)}: {snapshot['assets'][key]['error']}"
                  for key, item in ((str(x["key"]), x) for x in instruments)]
        raise RuntimeError("No market instruments could be updated. " + " || ".join(errors))
    return snapshot


def load_market_cache(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, dict) or not isinstance(payload.get("assets"), dict):
            return None
        # Validate the structure enough to prevent a damaged cache breaking the UI.
        for asset in payload["assets"].values():
            if not isinstance(asset, dict):
                return None
            for collection in ("intraday_bars", "daily_bars"):
                if not isinstance(asset.get(collection, []), list):
                    return None
        return payload
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def save_market_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
    temporary.replace(path)
