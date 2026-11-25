"""Verified local backup and next-launch recovery for Veltrix user data."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

BACKUP_FORMAT = "VELTRIX_LOCAL_BACKUP"
BACKUP_FORMAT_VERSION = 1
BACKUP_DIRECTORY = "backups"
BACKUP_PREFIX = "veltrix-backup-"
MANIFEST_NAME = "manifest.json"
PENDING_RESTORE_NAME = "pending_restore.json"
DEFAULT_RETENTION = 14
MAX_TOTAL_UNCOMPRESSED_BYTES = 3 * 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
HASH_CHUNK_BYTES = 1024 * 1024

# Only known user-owned files are included. Program files, API credentials,
# Python environments, temporary files and the backup directory are excluded.
MANAGED_FILES = (
    "config.json",
    "alarm_state.json",
    "calendar_cache.json",
    "market_cache.json",
    "regime_data.json",
    "research_cache.json",
    "focus_goals.sqlite3",
    "alarm.mp3",
)
_BACKUP_NAME_RE = re.compile(
    r"^veltrix-backup-\d{8}T\d{6}Z-[0-9a-f]{8}\.zip$"
)
_RESTORE_ORDER = (
    "calendar_cache.json",
    "market_cache.json",
    "research_cache.json",
    "regime_data.json",
    "alarm_state.json",
    "alarm.mp3",
    "focus_goals.sqlite3",
    "config.json",
)


class BackupError(RuntimeError):
    """Raised when a local backup or recovery action cannot be completed safely."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _backup_dir(data_dir: str | Path) -> Path:
    return Path(data_dir).expanduser() / BACKUP_DIRECTORY


def _pending_restore_path(data_dir: str | Path) -> Path:
    return Path(data_dir).expanduser() / PENDING_RESTORE_NAME


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(HASH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _write_file_to_zip(
    archive: zipfile.ZipFile,
    name: str,
    source_path: Path,
) -> tuple[int, str]:
    """Stream one source into the archive while hashing the exact archived bytes."""
    digest = hashlib.sha256()
    size = 0
    with source_path.open("rb") as source, archive.open(name, "w", force_zip64=True) as target:
        while True:
            chunk = source.read(HASH_CHUNK_BYTES)
            if not chunk:
                break
            target.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _sha256_zip_member(archive: zipfile.ZipFile, name: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with archive.open(name, "r") as stream:
        while True:
            chunk = stream.read(HASH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = stream.name
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def _sqlite_online_snapshot(source_path: Path, target_path: Path) -> None:
    """Create a transactionally consistent SQLite snapshot, including WAL data."""
    source_uri = source_path.resolve().as_uri() + "?mode=ro"
    source: sqlite3.Connection | None = None
    destination: sqlite3.Connection | None = None
    try:
        source = sqlite3.connect(source_uri, uri=True, timeout=15)
        destination = sqlite3.connect(target_path, timeout=15)
        source.backup(destination, pages=256, sleep=0.05)
        destination.commit()
        check = destination.execute("PRAGMA integrity_check").fetchone()
        if not check or str(check[0]).lower() != "ok":
            raise BackupError(f"SQLite integrity check failed for {source_path.name}.")
    except sqlite3.Error as exc:
        raise BackupError(f"Could not snapshot {source_path.name}: {exc}") from exc
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()


def _file_entries_for_backup(
    data_dir: Path,
    staging_dir: Path,
) -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []
    for name in MANAGED_FILES:
        source = data_dir / name
        if not source.exists():
            continue
        if source.is_symlink() or not source.is_file():
            raise BackupError(f"Refusing to back up non-regular user-data file: {name}.")
        if name == "focus_goals.sqlite3":
            target = staging_dir / name
            _sqlite_online_snapshot(source, target)
            entries.append((name, target))
        else:
            # JSON/cache saves are atomic replacements. Stream those files
            # directly into the ZIP instead of copying large OHLC files first.
            entries.append((name, source))
    if "config.json" not in {name for name, _ in entries}:
        raise BackupError("The current configuration file is missing; no backup was created.")
    return entries


def _manifest_from_archive(archive: zipfile.ZipFile) -> dict[str, Any]:
    names = archive.namelist()
    if len(names) > len(MANAGED_FILES) + 1:
        raise BackupError("Backup archive contains too many entries.")
    if len(names) != len(set(names)):
        raise BackupError("Backup archive contains duplicate entries.")
    if MANIFEST_NAME not in names:
        raise BackupError("Backup archive has no manifest.")
    manifest_info = archive.getinfo(MANIFEST_NAME)
    if manifest_info.file_size > MAX_MANIFEST_BYTES:
        raise BackupError("Backup manifest is unexpectedly large.")
    try:
        manifest_bytes = archive.read(MANIFEST_NAME)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError(f"Backup manifest is invalid: {exc}") from exc
    if not isinstance(manifest, dict):
        raise BackupError("Backup manifest must be a JSON object.")
    if manifest.get("format") != BACKUP_FORMAT:
        raise BackupError("This is not a Veltrix backup archive.")
    format_version = manifest.get("format_version")
    if isinstance(format_version, bool) or format_version != BACKUP_FORMAT_VERSION:
        raise BackupError("This backup uses an unsupported format version.")
    managed = manifest.get("managed_files")
    if managed != list(MANAGED_FILES):
        raise BackupError("Backup manifest does not match the current data-file policy.")
    records = manifest.get("files")
    if not isinstance(records, list):
        raise BackupError("Backup manifest has no file inventory.")
    record_names: list[str] = []
    total_size = 0
    for record in records:
        if not isinstance(record, dict):
            raise BackupError("Backup manifest contains an invalid file record.")
        name = record.get("name")
        size = record.get("size_bytes")
        digest = record.get("sha256")
        if name not in MANAGED_FILES or name in record_names:
            raise BackupError("Backup contains an unknown or duplicate user-data filename.")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise BackupError(f"Backup has an invalid size for {name}.")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise BackupError(f"Backup has an invalid SHA-256 digest for {name}.")
        record_names.append(name)
        total_size += size
    if "config.json" not in record_names:
        raise BackupError("Backup does not contain the required configuration file.")
    if total_size > MAX_TOTAL_UNCOMPRESSED_BYTES:
        raise BackupError("Backup exceeds the maximum supported uncompressed size.")

    expected_names = set(record_names) | {MANIFEST_NAME}
    if set(names) != expected_names:
        raise BackupError("Backup archive contains unexpected or missing entries.")
    for info in archive.infolist():
        if info.filename not in expected_names:
            raise BackupError("Backup archive contains an unexpected path.")
        if info.is_dir():
            raise BackupError("Backup archive contains an unexpected directory.")
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise BackupError("Backup archive contains a symbolic link.")
        if info.filename != MANIFEST_NAME:
            record = next(item for item in records if item["name"] == info.filename)
            if info.file_size != record["size_bytes"]:
                raise BackupError(f"Archive size does not match the manifest for {info.filename}.")
    created_at = manifest.get("created_at")
    if not isinstance(created_at, str):
        raise BackupError("Backup manifest has no creation timestamp.")
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError("timestamp has no timezone")
    except ValueError as exc:
        raise BackupError("Backup creation timestamp is invalid.") from exc
    return manifest


def inspect_backup(backup_path: str | Path) -> dict[str, Any]:
    """Read archive metadata without re-hashing potentially large OHLC datasets."""
    path = Path(backup_path)
    if path.is_symlink() or not path.is_file():
        raise BackupError("Selected backup file does not exist or is not a regular file.")
    try:
        with zipfile.ZipFile(path, "r") as archive:
            manifest = _manifest_from_archive(archive)
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        if isinstance(exc, BackupError):
            raise
        raise BackupError(f"Could not read backup archive: {exc}") from exc
    total = sum(int(item["size_bytes"]) for item in manifest["files"])
    return {
        "name": path.name,
        "created_at": manifest["created_at"],
        "app_version": str(manifest.get("app_version") or "unknown"),
        "files": [dict(item) for item in manifest["files"]],
        "file_count": len(manifest["files"]),
        "total_size_bytes": total,
        "archive_size_bytes": path.stat().st_size,
        "verified": False,
    }


def verify_backup(backup_path: str | Path) -> dict[str, Any]:
    """Verify ZIP CRC, every file length and each SHA-256 digest."""
    path = Path(backup_path)
    summary = inspect_backup(path)
    try:
        with zipfile.ZipFile(path, "r") as archive:
            manifest = _manifest_from_archive(archive)
            for record in manifest["files"]:
                size, digest = _sha256_zip_member(archive, record["name"])
                if size != record["size_bytes"]:
                    raise BackupError(f"Size verification failed for {record['name']}.")
                if digest != record["sha256"]:
                    raise BackupError(f"SHA-256 verification failed for {record['name']}.")
    except (OSError, zipfile.BadZipFile, RuntimeError, EOFError) as exc:
        if isinstance(exc, BackupError):
            raise
        raise BackupError(f"Backup verification failed: {exc}") from exc
    summary["verified"] = True
    return summary


def list_backups(data_dir: str | Path) -> list[dict[str, Any]]:
    """List timestamped local archives, leaving full digest verification on demand."""
    directory = _backup_dir(data_dir)
    if directory.is_symlink() or not directory.is_dir():
        return []
    results: list[dict[str, Any]] = []
    for path in directory.iterdir():
        if not path.name.startswith(BACKUP_PREFIX) or path.suffix.lower() != ".zip":
            continue
        if path.is_symlink() or not path.is_file():
            continue
        try:
            results.append(inspect_backup(path))
        except BackupError as exc:
            results.append({
                "name": path.name,
                "created_at": "",
                "app_version": "unknown",
                "files": [],
                "file_count": 0,
                "total_size_bytes": 0,
                "archive_size_bytes": path.stat().st_size,
                "verified": False,
                "error": str(exc),
            })
    results.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return results


def latest_backup(data_dir: str | Path) -> dict[str, Any] | None:
    for item in list_backups(data_dir):
        if not item.get("error") and item.get("created_at"):
            return item
    return None


def _prune_backups(
    directory: Path,
    retention: int,
    *,
    preserve_names: Iterable[str] = (),
) -> None:
    keep = max(1, min(100, int(retention)))
    preserve = set(preserve_names)
    valid: list[tuple[str, Path]] = []
    for path in directory.glob(f"{BACKUP_PREFIX}*.zip"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            item = inspect_backup(path)
        except BackupError:
            continue
        valid.append((str(item["created_at"]), path))
    valid.sort(key=lambda item: item[0], reverse=True)
    retained = {path.name for _, path in valid[:keep]} | preserve
    for _, path in valid:
        if path.name not in retained:
            try:
                path.unlink()
            except OSError:
                # Retention failure must not invalidate a verified new backup.
                pass


def create_backup(
    data_dir: str | Path,
    *,
    app_version: str = "unknown",
    retention: int = DEFAULT_RETENTION,
    preserve_names: Iterable[str] = (),
) -> dict[str, Any]:
    """Create and verify an atomic compressed snapshot of known user data."""
    source_dir = Path(data_dir).expanduser().resolve()
    if not source_dir.is_dir():
        raise BackupError("Veltrix user-data directory does not exist.")
    directory = _backup_dir(source_dir)
    if directory.is_symlink():
        raise BackupError("Backup directory must not be a symbolic link.")
    directory.mkdir(parents=True, exist_ok=True)
    now = _utc_now()
    backup_name = (
        f"{BACKUP_PREFIX}{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}.zip"
    )
    final_path = directory / backup_name
    temporary_path = directory / f".{backup_name}.{uuid.uuid4().hex}.tmp"
    try:
        with tempfile.TemporaryDirectory(prefix=".veltrix-stage-", dir=directory) as stage_name:
            staging_dir = Path(stage_name)
            file_entries = _file_entries_for_backup(source_dir, staging_dir)
            records: list[dict[str, Any]] = []
            with zipfile.ZipFile(
                temporary_path, "w", compression=zipfile.ZIP_DEFLATED,
                compresslevel=3, allowZip64=True,
            ) as archive:
                for name, staged_file in file_entries:
                    size, digest = _write_file_to_zip(archive, name, staged_file)
                    records.append({"name": name, "size_bytes": size, "sha256": digest})
                manifest = {
                    "format": BACKUP_FORMAT,
                    "format_version": BACKUP_FORMAT_VERSION,
                    "app_version": str(app_version),
                    "created_at": now.isoformat(),
                    "managed_files": list(MANAGED_FILES),
                    "files": records,
                }
                archive.writestr(
                    MANIFEST_NAME,
                    json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
                )
        with temporary_path.open("rb+") as stream:
            os.fsync(stream.fileno())
        verified = verify_backup(temporary_path)
        os.replace(temporary_path, final_path)
        _prune_backups(directory, retention, preserve_names=preserve_names)
        verified["name"] = final_path.name
        verified["archive_size_bytes"] = final_path.stat().st_size
        verified["path"] = str(final_path)
        return verified
    except BackupError:
        raise
    except (OSError, sqlite3.Error, zipfile.BadZipFile, ValueError, TypeError) as exc:
        raise BackupError(f"Could not create a verified backup: {exc}") from exc
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _safe_backup_path(data_dir: Path, backup_name: str) -> Path:
    if not isinstance(backup_name, str) or not _BACKUP_NAME_RE.fullmatch(backup_name):
        raise BackupError("Selected backup filename is invalid.")
    raw_directory = _backup_dir(data_dir)
    if raw_directory.is_symlink():
        raise BackupError("Backup directory must not be a symbolic link.")
    directory = raw_directory.resolve()
    path = directory / backup_name
    if path.parent.resolve() != directory or path.is_symlink() or not path.is_file():
        raise BackupError("Selected backup is not stored in the Veltrix backup directory.")
    return path


def read_pending_restore(data_dir: str | Path) -> dict[str, Any] | None:
    marker = _pending_restore_path(data_dir)
    if marker.is_symlink():
        return {"error": "Pending restore request must not be a symbolic link."}
    if not marker.is_file():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": f"Pending restore request is unreadable: {exc}"}
    if not isinstance(payload, dict) or payload.get("format") != BACKUP_FORMAT:
        return {"error": "Pending restore request is invalid."}
    return dict(payload)


def prepare_restore(data_dir: str | Path, backup_name: str) -> dict[str, Any]:
    """Verify and queue a restore to be applied before the next app startup."""
    root = Path(data_dir).expanduser().resolve()
    marker = _pending_restore_path(root)
    if marker.exists():
        raise BackupError("A restore is already queued. Cancel it before scheduling another.")
    backup_path = _safe_backup_path(root, backup_name)
    summary = verify_backup(backup_path)
    request = {
        "format": BACKUP_FORMAT,
        "format_version": BACKUP_FORMAT_VERSION,
        "backup_name": backup_path.name,
        "queued_at": _utc_now().isoformat(),
    }
    _atomic_json(marker, request)
    return {**summary, "queued": True, "queued_at": request["queued_at"]}


def cancel_pending_restore(data_dir: str | Path) -> bool:
    marker = _pending_restore_path(data_dir)
    try:
        marker.unlink()
        return True
    except FileNotFoundError:
        return False


def _stage_verified_archive(
    backup_path: Path,
    staging_dir: Path,
) -> tuple[dict[str, Any], set[str]]:
    with zipfile.ZipFile(backup_path, "r") as archive:
        manifest = _manifest_from_archive(archive)
        for record in manifest["files"]:
            name = record["name"]
            target = staging_dir / name
            size = 0
            digest = hashlib.sha256()
            with archive.open(name, "r") as source, target.open("wb") as destination:
                while True:
                    chunk = source.read(HASH_CHUNK_BYTES)
                    if not chunk:
                        break
                    destination.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                destination.flush()
                os.fsync(destination.fileno())
            if size != record["size_bytes"] or digest.hexdigest() != record["sha256"]:
                raise BackupError(f"Restore staging verification failed for {name}.")
    database = staging_dir / "focus_goals.sqlite3"
    if database.exists():
        try:
            with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
                check = connection.execute("PRAGMA integrity_check").fetchone()
                if not check or str(check[0]).lower() != "ok":
                    raise BackupError("Focus database failed its integrity check.")
        except sqlite3.Error as exc:
            raise BackupError(f"Focus database could not be validated: {exc}") from exc
    return manifest, {record["name"] for record in manifest["files"]}


def _commit_staged_restore(data_dir: Path, staging_dir: Path, included: set[str]) -> None:
    # Recovery runs before FocusStore is constructed, so no SQLite handles are open.
    database = data_dir / "focus_goals.sqlite3"
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(database) + suffix)
        try:
            sidecar.unlink()
        except FileNotFoundError:
            pass
    for name in _RESTORE_ORDER:
        destination = data_dir / name
        staged = staging_dir / name
        if name in included:
            os.replace(staged, destination)
        else:
            try:
                destination.unlink()
            except FileNotFoundError:
                pass


def _apply_archive(data_dir: Path, backup_path: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=".veltrix-restore-", dir=data_dir) as stage_name:
        staging_dir = Path(stage_name)
        manifest, included = _stage_verified_archive(backup_path, staging_dir)
        _commit_staged_restore(data_dir, staging_dir, included)
    return {
        "backup_name": backup_path.name,
        "created_at": manifest["created_at"],
        "restored_files": [name for name in _RESTORE_ORDER if name in included],
    }


def apply_pending_restore(data_dir: str | Path, *, app_version: str = "unknown") -> dict[str, Any] | None:
    """Apply a queued restore on startup, with an automatic pre-restore snapshot."""
    root = Path(data_dir).expanduser().resolve()
    marker = _pending_restore_path(root)
    if not marker.exists():
        return None
    request = read_pending_restore(root)
    if not request or request.get("error"):
        raise BackupError(
            str(request.get("error")) if request else "Pending restore request is invalid."
        )
    if request.get("format_version") != BACKUP_FORMAT_VERSION:
        raise BackupError("Pending restore request uses an unsupported format.")
    backup_path = _safe_backup_path(root, request.get("backup_name"))

    # Stage, hash and validate the selected snapshot exactly once before taking
    # the safety copy. Recovery is intentionally performed before the app opens
    # configuration or SQLite connections.
    try:
        with tempfile.TemporaryDirectory(prefix=".veltrix-restore-", dir=root) as stage_name:
            staging_dir = Path(stage_name)
            manifest, included = _stage_verified_archive(backup_path, staging_dir)
            safety = create_backup(
                root, app_version=app_version, preserve_names=(backup_path.name,)
            )
            safety_path = Path(safety["path"])
            try:
                _commit_staged_restore(root, staging_dir, included)
            except Exception as restore_error:
                try:
                    _apply_archive(root, safety_path)
                    cancel_pending_restore(root)
                except Exception as rollback_error:
                    raise BackupError(
                        "Restore failed and automatic rollback also failed. "
                        f"Keep the safety archive {safety_path.name}; details: "
                        f"restore={restore_error}; rollback={rollback_error}"
                    ) from rollback_error
                raise BackupError(
                    "Restore failed. Veltrix restored the pre-restore data from "
                    f"{safety_path.name}. No selected backup was applied. Details: {restore_error}"
                ) from restore_error
            result = {
                "backup_name": backup_path.name,
                "created_at": manifest["created_at"],
                "restored_files": [name for name in _RESTORE_ORDER if name in included],
            }
    except BackupError:
        raise
    except (OSError, zipfile.BadZipFile, sqlite3.Error) as exc:
        raise BackupError(f"Could not apply the selected restore: {exc}") from exc

    cancel_pending_restore(root)
    result["pre_restore_backup"] = safety_path.name
    result["safety_backup_path"] = str(safety_path)
    return result
