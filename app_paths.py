"""Runtime paths for source and frozen Veltrix desktop installations.

Personal settings and caches stay separate from bundled program resources.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Mapping

APP_NAME = "Veltrix Trading Clock"
PROJECT_DIR = Path(__file__).resolve().parent
IS_FROZEN = bool(getattr(sys, "frozen", False))
APP_INSTALL_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else PROJECT_DIR


def get_app_data_dir(
    *,
    frozen: bool | None = None,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    home: str | Path | None = None,
    project_dir: str | Path | None = None,
) -> Path:
    """Return the writable data directory for the current installation."""
    frozen = IS_FROZEN if frozen is None else bool(frozen)
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    home_path = Path(home).expanduser() if home is not None else Path.home()
    if not frozen:
        return Path(project_dir).resolve() if project_dir is not None else PROJECT_DIR

    if platform == "win32":
        base = Path(env.get("LOCALAPPDATA") or (home_path / "AppData" / "Local"))
    elif platform == "darwin":
        base = home_path / "Library" / "Application Support"
    else:
        base = Path(env.get("XDG_DATA_HOME") or (home_path / ".local" / "share"))
    return base / APP_NAME


APP_DATA_DIR = get_app_data_dir()


def resource_path(relative_path: str | Path) -> Path:
    """Resolve a read-only resource bundled by PyInstaller or in source."""
    bundle_dir = Path(getattr(sys, "_MEIPASS", PROJECT_DIR))
    return (bundle_dir / relative_path).resolve()


def initialize_app_data(app_data_dir: str | Path | None = None) -> Path:
    """Create the writable application directory and seed first-run config.

    Existing user files are never overwritten. The Core Edition does not load
    provider API credentials or create a raw tick-data workspace.
    """
    data_dir = Path(app_data_dir).expanduser() if app_data_dir is not None else APP_DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)

    source = resource_path("config.json")
    destination = data_dir / "config.json"
    if source.is_file() and not destination.exists():
        shutil.copy2(source, destination)

    return data_dir
