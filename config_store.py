"""Validated and crash-safe persistence for the desktop application config."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from session_engine import load_session_definitions

CONFIG_SCHEMA_VERSION = 1
_MAPPING_SECTIONS = (
    "alerts", "calendar", "market_data", "research", "regime_lab", "backtest", "focus",
    "session_profiles", "exchange_calendar", "session_risk", "command_center",
)


def load_config(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8") as file:
            config = json.load(file)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Configuration file not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{source.name} contains invalid JSON: {exc}") from exc
    except OSError as exc:
        raise RuntimeError(f"Could not read configuration file {source}: {exc}") from exc

    if not isinstance(config, dict):
        raise RuntimeError(f"{source.name} must contain a JSON object.")

    version = config.get("schema_version", CONFIG_SCHEMA_VERSION)
    if isinstance(version, bool) or not isinstance(version, int) or version > CONFIG_SCHEMA_VERSION:
        raise RuntimeError(f"{source.name} uses an unsupported configuration version: {version!r}.")

    sessions = config.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise RuntimeError(f"{source.name} must contain a non-empty 'sessions' list.")
    try:
        load_session_definitions(sessions)
        for session in sessions:
            ZoneInfo(str(session["timezone"]))
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise RuntimeError(f"{source.name} contains an invalid trading session: {exc}") from exc

    for section in _MAPPING_SECTIONS:
        if section in config and not isinstance(config[section], dict):
            raise RuntimeError(f"{source.name} field '{section}' must be a JSON object.")
    for section in ("market_instruments", "economic_events"):
        if section in config and not isinstance(config[section], list):
            raise RuntimeError(f"{source.name} field '{section}' must be a JSON array.")

    try:
        ZoneInfo(str(config.get("home_timezone", "Africa/Nairobi")))
        refresh_ms = int(config.get("refresh_milliseconds", 1000))
    except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise RuntimeError(f"{source.name} has an invalid timezone or refresh interval: {exc}") from exc
    if not 250 <= refresh_ms <= 60_000:
        raise RuntimeError(f"{source.name} refresh_milliseconds must be between 250 and 60000.")
    return config


def save_config(path: str | Path, config: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    serialized = dict(config)
    serialized["schema_version"] = CONFIG_SCHEMA_VERSION
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
            json.dump(serialized, file, indent=2, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
