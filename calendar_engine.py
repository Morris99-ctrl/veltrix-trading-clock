"""Economic-calendar client and event normalisation for Veltrix Trading Clock.

Provider: ShowMyTrades public economic calendar API.
The endpoint is polled on a 15-minute cadence to match its documented cache window.
"""

from __future__ import annotations

import json
import socket
import ssl
import time as time_module
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_URL = "https://showmytrades.com/api/public/calendar/v1"
DOCS_URL = "https://showmytrades.com/docs/api/economic-calendar"
DEFAULT_ATTRIBUTION_URL = "https://showmytrades.com/tools/economic-calendar"
USER_AGENT = "VeltrixTradingClock/4.0 (desktop economic calendar)"


@dataclass(frozen=True)
class CalendarEvent:
    event_id: str
    title: str
    currency: str
    impact: str
    timestamp_utc: int
    forecast: str = ""
    previous: str = ""
    actual: str = ""
    status: str = "scheduled"
    moved_from: str = ""
    period: str = ""
    confidence: str = ""

    @property
    def event_time(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp_utc, tz=timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> "CalendarEvent":
        return cls(
            event_id=str(item["event_id"]),
            title=str(item["title"]),
            currency=str(item.get("currency", "")).upper(),
            impact=str(item.get("impact", "unknown")).lower(),
            timestamp_utc=int(item["timestamp_utc"]),
            forecast=str(item.get("forecast", "") or ""),
            previous=str(item.get("previous", "") or ""),
            actual=str(item.get("actual", "") or ""),
            status=str(item.get("status", "scheduled") or "scheduled").strip().lower(),
            moved_from=str(item.get("moved_from", "") or ""),
            period=str(item.get("period", "") or ""),
            confidence=str(item.get("confidence", "") or "").strip().lower(),
        )


def parse_calendar_payload(payload: dict[str, Any]) -> tuple[list[CalendarEvent], dict[str, Any], str]:
    """Validate and normalise a provider payload without trusting optional fields."""
    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        raise ValueError("Calendar response did not contain an 'events' list.")

    events: list[CalendarEvent] = []
    seen: set[tuple[str, int]] = set()
    for raw in raw_events:
        if not isinstance(raw, dict):
            continue
        try:
            event_id = str(raw.get("id") or "").strip()
            title = str(raw.get("title") or "").strip()
            currency = str(raw.get("currency") or "").strip().upper()
            impact = str(raw.get("impact") or "unknown").strip().lower()
            timestamp = int(raw.get("ts"))
            if not event_id or not title or not currency:
                continue
            # Validate the timestamp range before constructing a datetime.
            datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            continue

        identity = (event_id, timestamp)
        if identity in seen:
            continue
        seen.add(identity)
        events.append(
            CalendarEvent(
                event_id=event_id,
                title=title,
                currency=currency,
                impact=impact,
                timestamp_utc=timestamp,
                forecast=str(raw.get("forecast") or ""),
                previous=str(raw.get("previous") or ""),
                actual=str(raw.get("actual") or ""),
                status=str(raw.get("status") or "scheduled").strip().lower(),
                moved_from=str(raw.get("moved_from") or ""),
                period=str(raw.get("period") or ""),
                confidence=str(raw.get("confidence") or "").strip().lower(),
            )
        )

    events.sort(key=lambda event: event.timestamp_utc)
    attribution = payload.get("attribution") if isinstance(payload.get("attribution"), dict) else {}
    attribution_info = {
        "text": str(attribution.get("text") or "Economic calendar by ShowMyTrades"),
        "url": str(attribution.get("url") or DEFAULT_ATTRIBUTION_URL),
        "required": bool(attribution.get("required", False)),
    }
    generated_at = str(payload.get("generated_at") or payload.get("server_time_iso") or "")
    return events, attribution_info, generated_at


def _connection_error_message(exc: BaseException, timeout: int) -> str:
    """Return a practical, platform-neutral description of a connection failure."""
    reason = getattr(exc, "reason", exc)
    detail = str(reason or exc).strip() or exc.__class__.__name__
    lowered = detail.lower()

    if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in lowered or "timeout" in lowered or "winerror 10060" in lowered:
        return (
            f"Calendar request timed out after {timeout} seconds. "
            "Check your internet connection, DNS, VPN/proxy or firewall; the provider may also be temporarily slow."
        )
    if isinstance(reason, socket.gaierror) or "name or service not known" in lowered or "getaddrinfo failed" in lowered:
        return (
            "DNS could not resolve showmytrades.com. Check your internet connection or DNS settings, "
            "then try again."
        )
    if isinstance(reason, ssl.SSLError) or "ssl" in lowered or "certificate" in lowered:
        return (
            "A secure connection to the calendar provider failed. Check your system date/time, "
            "VPN/proxy and antivirus HTTPS inspection settings."
        )
    return f"Could not reach the calendar provider: {detail}"


def fetch_calendar(days: int = 7, timeout: int = 25, retries: int = 1) -> dict[str, Any]:
    """Fetch all impact tiers, with one bounded retry for transient network failures.

    The request remains HTTPS-only. We intentionally do not fall back to the
    provider's documented plain-HTTP alternate port, because calendar data
    should not be accepted over an unauthenticated transport.
    """
    safe_days = max(1, min(30, int(days)))
    safe_timeout = max(5, min(60, int(timeout)))
    safe_retries = max(0, min(2, int(retries)))
    query = urlencode({"impact": "all", "days": safe_days, "format": "json"})
    request = Request(
        f"{API_URL}?{query}",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        method="GET",
    )

    raw_body: bytes | None = None
    last_error: BaseException | None = None
    for attempt in range(safe_retries + 1):
        try:
            with urlopen(request, timeout=safe_timeout) as response:
                raw_body = response.read(4 * 1024 * 1024 + 1)
                if len(raw_body) > 4 * 1024 * 1024:
                    raise ValueError("Calendar response exceeded the 4 MB safety limit.")
            break
        except HTTPError as exc:
            # A malformed request (4xx) will not be fixed by repeating it.
            # Retry only rate limiting and temporary provider/server failures.
            last_error = exc
            if attempt < safe_retries and exc.code in {429, 500, 502, 503, 504}:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    wait_seconds = min(5.0, max(1.0, float(retry_after))) if retry_after else 2.0
                except ValueError:
                    wait_seconds = 2.0
                time_module.sleep(wait_seconds)
                continue
            if exc.code == 429:
                raise RuntimeError("Calendar provider rate-limited this connection (HTTP 429). Wait before retrying.") from exc
            raise RuntimeError(f"Calendar provider returned HTTP {exc.code}.") from exc
        except (URLError, TimeoutError, socket.timeout, ssl.SSLError, OSError) as exc:
            last_error = exc
            if attempt < safe_retries:
                time_module.sleep(1.5)
                continue
            break

    if raw_body is None:
        assert last_error is not None
        raise RuntimeError(_connection_error_message(last_error, safe_timeout)) from last_error

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Calendar provider returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Calendar provider returned an unexpected response format.")

    events, attribution, generated_at = parse_calendar_payload(payload)
    return {
        "events": [event.to_dict() for event in events],
        "attribution": attribution,
        "generated_at": generated_at,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "provider": "ShowMyTrades",
    }

def load_calendar_cache(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            return None
        events = [CalendarEvent.from_dict(item).to_dict() for item in payload["events"] if isinstance(item, dict)]
        return {
            "events": events,
            "attribution": payload.get("attribution") or {
                "text": "Economic calendar by ShowMyTrades",
                "url": DEFAULT_ATTRIBUTION_URL,
                "required": False,
            },
            "generated_at": str(payload.get("generated_at") or ""),
            "fetched_at": str(payload.get("fetched_at") or ""),
            "provider": "ShowMyTrades",
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def save_calendar_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
    temporary.replace(path)


def calendar_is_due(last_success_monotonic: float | None, *, refresh_minutes: int = 15, now: float | None = None) -> bool:
    """Return true when a new request is allowed after the last successful fetch."""
    if last_success_monotonic is None:
        return True
    current = time_module.monotonic() if now is None else float(now)
    return current - last_success_monotonic >= max(15, int(refresh_minutes)) * 60


def calendar_retry_delay_seconds(failed_attempt_count: int) -> int:
    """Bounded exponential backoff for failed fetches: 30s up to 15 minutes."""
    count = max(1, min(6, int(failed_attempt_count)))
    return min(15 * 60, 30 * (2 ** (count - 1)))


def due_calendar_reminders(
    events: list[dict[str, Any]],
    now: datetime,
    *,
    lead_minutes: int,
    allowed_impacts: set[str],
    fired_keys: set[str],
) -> list[dict[str, Any]]:
    """Return live calendar events entering their reminder window, once per scheduled time."""
    if now.tzinfo is None:
        raise ValueError("Calendar reminder calculations require a timezone-aware datetime.")
    now_utc = now.astimezone(timezone.utc)
    lead = max(0, min(1440, int(lead_minutes)))
    due: list[dict[str, Any]] = []
    for raw in events:
        try:
            event = raw if isinstance(raw, CalendarEvent) else CalendarEvent.from_dict(raw)
        except (KeyError, TypeError, ValueError):
            continue
        if allowed_impacts and event.impact not in allowed_impacts:
            continue
        # Tentative releases are displayed but are not precise enough for a timed alert.
        # Market holidays describe a closure, not a macroeconomic release.
        if event.status not in {"scheduled", "moved"} or event.impact == "holiday":
            continue
        event_time = event.event_time
        seconds_until = (event_time - now_utc).total_seconds()
        key = f"{event.event_id}:{event.timestamp_utc}"
        if lead == 0:
            # Fire once at the release instant, allowing a short scheduler grace window.
            is_due = -90 <= seconds_until <= 0
        else:
            # Allow a late application start within the configured reminder window.
            is_due = 0 < seconds_until <= lead * 60
        if is_due and key not in fired_keys:
            fired_keys.add(key)
            due.append({**event.to_dict(), "reminder_key": key, "minutes_before": lead})
    return due
