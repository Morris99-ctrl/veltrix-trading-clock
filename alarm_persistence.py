"""Restart-safe persistence for scheduled desktop alarms."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEDULED_STATES = frozenset({"scheduled", "snoozed"})


@dataclass(frozen=True)
class AlarmRestore:
    state: str = "idle"
    alarm_datetime: datetime | None = None
    warning: str | None = None
    clear_saved_state: bool = False


def restore_alarm_state(
    payload: object,
    home_zone: ZoneInfo,
    *,
    now: datetime | None = None,
) -> AlarmRestore:
    if payload is None:
        return AlarmRestore()
    if not isinstance(payload, dict):
        return AlarmRestore(warning="Saved alarm data is invalid; it was not restored.")

    state = payload.get("state")
    if state == "idle":
        return AlarmRestore()
    if not isinstance(state, str) or state not in SCHEDULED_STATES:
        return AlarmRestore(warning="Saved alarm state is invalid; it was not restored.")
    try:
        deadline = datetime.fromisoformat(str(payload["alarm_datetime"]))
        if deadline.tzinfo is None:
            raise ValueError("Saved alarm time has no timezone.")
    except (KeyError, TypeError, ValueError) as exc:
        return AlarmRestore(warning=f"Saved alarm time is invalid; it was not restored: {exc}")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Alarm restoration requires a timezone-aware current time.")
    deadline = deadline.astimezone(home_zone)
    if deadline.astimezone(timezone.utc) <= current.astimezone(timezone.utc):
        return AlarmRestore(
            warning=f"Missed alarm for {deadline.strftime('%Y-%m-%d %I:%M %p %Z')} while Veltrix was closed.",
            clear_saved_state=True,
        )
    return AlarmRestore(state=state, alarm_datetime=deadline)


def load_alarm_state(
    path: str | Path,
    home_zone: ZoneInfo,
    *,
    now: datetime | None = None,
) -> AlarmRestore:
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except FileNotFoundError:
        return AlarmRestore()
    except json.JSONDecodeError as exc:
        return AlarmRestore(warning=f"Saved alarm file is invalid JSON and was left untouched: {exc}")
    except OSError as exc:
        return AlarmRestore(warning=f"Could not read saved alarm state: {exc}")
    return restore_alarm_state(payload, home_zone, now=now)


def save_alarm_state(path: str | Path, state: str, alarm_datetime: datetime | None) -> None:
    if state in SCHEDULED_STATES:
        if alarm_datetime is None or alarm_datetime.tzinfo is None:
            raise ValueError("A scheduled alarm requires a timezone-aware datetime.")
        payload = {"state": state, "alarm_datetime": alarm_datetime.isoformat()}
    elif state == "idle":
        payload = {"state": "idle"}
    else:
        raise ValueError(f"Unsupported persisted alarm state: {state}")

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = file.name
            json.dump(payload, file, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
