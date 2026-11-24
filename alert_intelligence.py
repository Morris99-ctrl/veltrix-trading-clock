"""Alert lifecycle, deduplication and candidate generation for Veltrix v10.15."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo
from uuid import uuid4


STATUSES = ("ACTIVE", "UPCOMING", "TRIGGERED", "ACKNOWLEDGED")
IMPACTS = ("HIGH", "MEDIUM", "LOW", "INFO")


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Alert intelligence requires timezone-aware datetimes.")
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds") if value else ""


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _normalise_impact(value: Any, fallback: str = "INFO") -> str:
    impact = str(value or fallback).strip().upper()
    aliases = {"CRITICAL": "HIGH", "SEVERE": "HIGH", "MODERATE": "MEDIUM", "NONE": "INFO"}
    impact = aliases.get(impact, impact)
    return impact if impact in IMPACTS else fallback


class AlertCenterStore:
    """Small persistent alert journal with stable-ID deduplication.

    Triggered and acknowledged records are stored in application config. Active
    and upcoming rows are generated from current market/session data at runtime.
    """

    MAX_RECORDS = 250
    MAX_SEEN_IDS = 600
    RETENTION_DAYS = 30

    def __init__(self, state: dict[str, Any] | None = None) -> None:
        payload = state if isinstance(state, dict) else {}
        raw_records = payload.get("records", [])
        self.records: list[dict[str, Any]] = []
        self.seen_ids: list[str] = []
        if isinstance(raw_records, list):
            for raw in raw_records:
                if not isinstance(raw, dict):
                    continue
                record_id = str(raw.get("id", "")).strip()
                status = str(raw.get("status", "")).upper()
                if not record_id or status not in {"TRIGGERED", "ACKNOWLEDGED"}:
                    continue
                record = dict(raw)
                record["id"] = record_id
                record["status"] = status
                record["impact"] = _normalise_impact(record.get("impact"))
                self.records.append(record)
                self.seen_ids.append(record_id)
        raw_seen = payload.get("seen_ids", [])
        if isinstance(raw_seen, list):
            for value in raw_seen:
                value = str(value).strip()
                if value and value not in self.seen_ids:
                    self.seen_ids.append(value)
        self._trim(datetime.now(timezone.utc))

    def _trim(self, now_utc: datetime) -> None:
        cutoff = now_utc - timedelta(days=self.RETENTION_DAYS)
        retained = []
        for record in self.records:
            stamp = _parse_iso(record.get("created_at")) or _parse_iso(record.get("acknowledged_at"))
            if stamp is None or stamp >= cutoff:
                retained.append(record)
        self.records = retained[: self.MAX_RECORDS]
        valid_ids = {str(record["id"]) for record in self.records}
        # Keep a bounded dedupe tail, including IDs whose visible record was pruned.
        self.seen_ids = list(dict.fromkeys(self.seen_ids))[-self.MAX_SEEN_IDS :]
        for record_id in valid_ids:
            if record_id not in self.seen_ids:
                self.seen_ids.append(record_id)
        self.seen_ids = self.seen_ids[-self.MAX_SEEN_IDS :]

    def record_triggered(
        self,
        *,
        alert_id: str | None,
        title: str,
        message: str,
        category: str,
        source: str,
        market: str,
        impact: str,
        now: datetime,
    ) -> dict[str, Any] | None:
        now_utc = _aware_utc(now)
        record_id = str(alert_id or f"manual:{uuid4().hex}").strip()
        if not record_id or record_id in self.seen_ids:
            return None
        record = {
            "id": record_id,
            "status": "TRIGGERED",
            "created_at": _iso(now_utc),
            "scheduled_at": "",
            "title": str(title).strip()[:180],
            "message": str(message).strip()[:1200],
            "category": str(category or "info").strip().lower()[:32],
            "source": str(source or "Veltrix").strip()[:80],
            "market": str(market or "GLOBAL").strip().upper()[:24],
            "impact": _normalise_impact(impact),
        }
        self.records.insert(0, record)
        self.seen_ids.append(record_id)
        self._trim(now_utc)
        return dict(record)

    def acknowledge(
        self,
        alert_id: str,
        *,
        now: datetime,
        candidates: list[dict[str, Any]] | None = None,
    ) -> bool:
        now_utc = _aware_utc(now)
        record_id = str(alert_id)
        for record in self.records:
            if str(record.get("id")) == record_id:
                if record.get("status") == "ACKNOWLEDGED":
                    return False
                record["status"] = "ACKNOWLEDGED"
                record["acknowledged_at"] = _iso(now_utc)
                self._trim(now_utc)
                return True
        for candidate in candidates or []:
            if str(candidate.get("id")) != record_id:
                continue
            if str(candidate.get("status", "")).upper() not in {"ACTIVE", "UPCOMING"}:
                return False
            saved = dict(candidate)
            saved["status"] = "ACKNOWLEDGED"
            saved["created_at"] = _iso(now_utc)
            saved["acknowledged_at"] = _iso(now_utc)
            saved["category"] = str(saved.get("category", "schedule"))[:32]
            saved["source"] = str(saved.get("source", "Veltrix"))[:80]
            saved["market"] = str(saved.get("market", "GLOBAL")).upper()[:24]
            saved["impact"] = _normalise_impact(saved.get("impact"))
            self.records.insert(0, saved)
            if record_id not in self.seen_ids:
                self.seen_ids.append(record_id)
            self._trim(now_utc)
            return True
        return False

    def acknowledge_many(
        self, alert_ids: list[str], *, now: datetime, candidates: list[dict[str, Any]] | None = None
    ) -> int:
        changed = 0
        for alert_id in alert_ids:
            changed += int(self.acknowledge(alert_id, now=now, candidates=candidates))
        return changed

    def snapshot(
        self,
        candidates: list[dict[str, Any]],
        *,
        status: str = "ALL",
        market: str = "ALL",
        impact: str = "ALL",
        query: str = "",
    ) -> list[dict[str, Any]]:
        saved_by_id = {str(item["id"]): item for item in self.records}
        combined: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            record_id = str(candidate.get("id", ""))
            if not record_id:
                continue
            saved = saved_by_id.get(record_id)
            if saved and saved.get("status") == "ACKNOWLEDGED":
                combined[record_id] = dict(saved)
            else:
                combined[record_id] = dict(candidate)
        for record in self.records:
            combined[str(record["id"])] = dict(record)

        status_filter = str(status or "ALL").upper()
        market_filter = str(market or "ALL").upper()
        impact_filter = str(impact or "ALL").upper()
        terms = str(query or "").strip().casefold()
        rows = []
        for record in combined.values():
            if status_filter != "ALL" and record.get("status") != status_filter:
                continue
            if market_filter != "ALL" and str(record.get("market", "")).upper() != market_filter:
                continue
            if impact_filter != "ALL" and str(record.get("impact", "")).upper() != impact_filter:
                continue
            if terms:
                haystack = " ".join(
                    str(record.get(key, "")) for key in ("title", "message", "market", "source", "category")
                ).casefold()
                if terms not in haystack:
                    continue
            rows.append(record)

        priority = {"ACTIVE": 0, "TRIGGERED": 1, "UPCOMING": 2, "ACKNOWLEDGED": 3}
        def ordering(record: dict[str, Any]) -> tuple[int, float, str]:
            stamp = _parse_iso(record.get("scheduled_at")) or _parse_iso(record.get("created_at"))
            if stamp is None:
                stamp = datetime.max.replace(tzinfo=timezone.utc)
            return priority.get(str(record.get("status")), 9), stamp.timestamp(), str(record.get("id"))
        rows.sort(key=ordering)
        return rows

    def counts(self, candidates: list[dict[str, Any]]) -> dict[str, int]:
        rows = self.snapshot(candidates)
        return {status: sum(row.get("status") == status for row in rows) for status in STATUSES}

    def export_state(self) -> dict[str, Any]:
        self._trim(datetime.now(timezone.utc))
        return {
            "records": [dict(item) for item in self.records[: self.MAX_RECORDS]],
            "seen_ids": list(self.seen_ids[-self.MAX_SEEN_IDS :]),
        }


def build_alert_candidates(
    now: datetime,
    session_states: list[Any],
    calendar_events: list[dict[str, Any]],
    manual_events: list[dict[str, Any]],
    home_zone: ZoneInfo,
    *,
    horizon_hours: int = 24,
) -> list[dict[str, Any]]:
    """Build current ACTIVE and near-term UPCOMING rows without sending notifications."""
    now_utc = _aware_utc(now)
    horizon = now_utc + timedelta(hours=max(1, min(72, int(horizon_hours))))
    candidates: list[dict[str, Any]] = []

    def add(
        record_id: str, status: str, scheduled_at: datetime, title: str, message: str,
        market: str, impact: str, category: str, source: str,
    ) -> None:
        stamp = _aware_utc(scheduled_at)
        candidates.append({
            "id": record_id,
            "status": status,
            "created_at": "",
            "scheduled_at": _iso(stamp),
            "title": str(title)[:180],
            "message": str(message)[:1200],
            "market": str(market or "GLOBAL").upper()[:24],
            "impact": _normalise_impact(impact),
            "category": str(category)[:32],
            "source": str(source)[:80],
        })

    open_states = []
    for state in session_states or []:
        definition = getattr(state, "definition", None)
        if definition is None:
            continue
        market = str(getattr(definition, "name", definition.key)).upper()
        transition = getattr(state, "transition_at", None)
        seconds = int(getattr(state, "seconds_to_transition", 0) or 0)
        key = str(getattr(definition, "key", market)).lower()
        if bool(getattr(state, "is_open", False)):
            open_states.append(state)
            local_transition = transition.astimezone(definition.tz) if isinstance(transition, datetime) else None
            detail = (
                f"Configured {market} session is open. Next transition: "
                f"{local_transition.strftime('%H:%M %Z') if local_transition else 'time unavailable'}."
            )
            add(
                f"live:session:{key}", "ACTIVE", now_utc, f"{market} SESSION ACTIVE",
                detail, market, "LOW", "session", "Session monitor",
            )
        if isinstance(transition, datetime) and 0 < seconds <= horizon_hours * 3600:
            local_transition = transition.astimezone(definition.tz)
            action = "CLOSE" if bool(getattr(state, "is_open", False)) else "OPEN"
            add(
                f"schedule:{key}:{_iso(transition)}", "UPCOMING", transition,
                f"{market} SESSION {action}",
                f"Configured {market} hours transition at {local_transition.strftime('%H:%M %Z')}. "
                "This is a schedule estimate, not a broker execution-status feed.",
                market, "MEDIUM", "session", "Session schedule",
            )

    if len(open_states) >= 2:
        names = " + ".join(str(state.definition.name) for state in open_states)
        keys = "-".join(sorted(str(state.definition.key) for state in open_states))
        add(
            f"live:overlap:{keys}", "ACTIVE", now_utc, "GLOBAL SESSION OVERLAP ACTIVE",
            f"Currently configured open: {names}.", "GLOBAL", "LOW", "overlap", "Session monitor",
        )

    for event in calendar_events or []:
        if not isinstance(event, dict):
            continue
        if str(event.get("status", "scheduled")).lower() not in {"scheduled", "moved"}:
            continue
        try:
            event_time = datetime.fromtimestamp(int(event["timestamp_utc"]), tz=timezone.utc)
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        if not now_utc < event_time <= horizon:
            continue
        event_id = str(event.get("event_id") or event.get("id") or "").strip()
        if not event_id:
            continue
        currency = str(event.get("currency") or "GLOBAL").upper()
        impact = _normalise_impact(event.get("impact"), "INFO")
        confidence = str(event.get("confidence") or "").replace("_", " ").strip()
        note = f" Source confidence: {confidence}." if confidence else ""
        add(
            f"calendar:{event_id}:{int(event_time.timestamp())}", "UPCOMING", event_time,
            str(event.get("title") or "ECONOMIC RELEASE"),
            f"{currency} economic-calendar release.{note}",
            currency, impact, "economic", "Economic calendar",
        )

    for event in manual_events or []:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "").strip()
        try:
            event_time = datetime.fromisoformat(str(event["datetime"]))
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=home_zone)
        except (KeyError, TypeError, ValueError):
            continue
        event_time = event_time.astimezone(timezone.utc)
        if not event_id or not now_utc < event_time <= horizon:
            continue
        add(
            f"manual:{event_id}", "UPCOMING", event_time,
            str(event.get("name") or "MANUAL ECONOMIC EVENT"),
            "User-created event reminder.", "CUSTOM", "MEDIUM", "economic", "Manual reminder",
        )

    # Stable row identity: a provider item can appear in more than one source snapshot.
    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        unique[candidate["id"]] = candidate
    return list(unique.values())
