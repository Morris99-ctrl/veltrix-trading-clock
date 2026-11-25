from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from pathlib import Path

from backup_recovery import (
    BACKUP_FORMAT,
    MANAGED_FILES,
    BackupError,
    apply_pending_restore,
    cancel_pending_restore,
    create_backup,
    latest_backup,
    list_backups,
    prepare_restore,
    read_pending_restore,
    verify_backup,
)


class BackupRecoveryTests(unittest.TestCase):
    def make_data_dir(self, root: Path, *, theme: str = "CYAN", focus_title: str = "Original goal") -> Path:
        data = root / "user-data"
        data.mkdir(parents=True)
        (data / "config.json").write_text(
            json.dumps({"theme": theme, "sessions": [{"name": "Tokyo"}]}),
            encoding="utf-8",
        )
        (data / "alarm_state.json").write_text(
            json.dumps({"state": "scheduled", "alarm_datetime": "2027-01-01T09:00:00+03:00"}),
            encoding="utf-8",
        )
        (data / "calendar_cache.json").write_text(json.dumps({"events": [{"id": "event-1"}]}), encoding="utf-8")
        (data / "market_cache.json").write_text(json.dumps({"assets": {"gold": {"close": 2000}}}), encoding="utf-8")
        (data / "regime_data.json").write_text(json.dumps({"datasets": {"gold": {"bars": []}}}), encoding="utf-8")
        (data / "research_cache.json").write_text(json.dumps({"legacy": True}), encoding="utf-8")
        (data / "alarm.mp3").write_bytes(b"fake-audio-payload")
        database = sqlite3.connect(data / "focus_goals.sqlite3")
        database.execute("CREATE TABLE goals (title TEXT NOT NULL)")
        database.execute("INSERT INTO goals(title) VALUES (?)", (focus_title,))
        database.commit()
        database.close()
        return data

    def test_create_and_verify_backup_includes_known_user_state(self):
        with tempfile.TemporaryDirectory() as folder:
            data = self.make_data_dir(Path(folder))

            backup = create_backup(data, app_version="10.19")

            verified = verify_backup(backup["path"])
            included = {item["name"] for item in verified["files"]}
            self.assertEqual(included, set(MANAGED_FILES))
            self.assertTrue(verified["verified"])
            self.assertEqual(verified["app_version"], "10.19")
            self.assertTrue(Path(backup["path"]).is_file())

    def test_sqlite_online_snapshot_contains_committed_focus_records(self):
        with tempfile.TemporaryDirectory() as folder:
            data = self.make_data_dir(Path(folder))
            backup = create_backup(data)
            with zipfile.ZipFile(backup["path"]) as archive:
                restored_db = Path(folder) / "focus-snapshot.sqlite3"
                restored_db.write_bytes(archive.read("focus_goals.sqlite3"))
            with sqlite3.connect(restored_db) as connection:
                title = connection.execute("SELECT title FROM goals").fetchone()[0]
            self.assertEqual(title, "Original goal")

    def test_list_and_latest_backup_are_chronological(self):
        with tempfile.TemporaryDirectory() as folder:
            data = self.make_data_dir(Path(folder))
            first = create_backup(data)
            second = create_backup(data)
            listed = list_backups(data)
            self.assertGreaterEqual(len(listed), 2)
            self.assertEqual(latest_backup(data)["name"], second["name"])
            self.assertEqual(listed[0]["name"], second["name"])
            self.assertNotEqual(first["name"], second["name"])

    def test_retention_keeps_only_the_configured_number_of_archives(self):
        with tempfile.TemporaryDirectory() as folder:
            data = self.make_data_dir(Path(folder))
            for _ in range(4):
                create_backup(data, retention=2)
            self.assertEqual(len(list_backups(data)), 2)

    def test_retention_preserves_an_explicitly_selected_restore_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            data = self.make_data_dir(Path(folder))
            first = create_backup(data, retention=1)
            for _ in range(3):
                create_backup(data, retention=1, preserve_names=(first["name"],))
            names = {item["name"] for item in list_backups(data)}
            self.assertIn(first["name"], names)
            self.assertLessEqual(len(names), 2)

    def test_verify_detects_member_content_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            data = self.make_data_dir(Path(folder))
            backup = create_backup(data)
            corrupt = Path(folder) / "tampered.zip"
            with zipfile.ZipFile(backup["path"], "r") as source:
                with zipfile.ZipFile(corrupt, "w", compression=zipfile.ZIP_DEFLATED) as target:
                    for name in source.namelist():
                        payload = source.read(name)
                        if name == "config.json":
                            payload += b" "
                        target.writestr(name, payload)
            with self.assertRaisesRegex(BackupError, "Archive size does not match|Size verification failed|SHA-256 verification failed"):
                verify_backup(corrupt)

    def test_unknown_archive_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            data = self.make_data_dir(Path(folder))
            backup = create_backup(data)
            malicious = Path(folder) / "path-traversal.zip"
            with zipfile.ZipFile(backup["path"], "r") as source:
                with zipfile.ZipFile(malicious, "w", compression=zipfile.ZIP_DEFLATED) as target:
                    for name in source.namelist():
                        target.writestr(name, source.read(name))
                    target.writestr("../../outside.txt", b"bad")
            with self.assertRaisesRegex(BackupError, "unexpected|too many entries"):
                verify_backup(malicious)

    def test_prepare_restore_verifies_archive_and_queues_for_next_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            data = self.make_data_dir(Path(folder))
            backup = create_backup(data)

            prepared = prepare_restore(data, backup["name"])

            self.assertTrue(prepared["queued"])
            self.assertEqual(read_pending_restore(data)["backup_name"], backup["name"])
            with self.assertRaisesRegex(BackupError, "already queued"):
                prepare_restore(data, backup["name"])
            self.assertTrue(cancel_pending_restore(data))
            self.assertIsNone(read_pending_restore(data))

    def test_restore_is_applied_at_startup_and_creates_pre_restore_safety_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            data = self.make_data_dir(Path(folder), theme="CYAN", focus_title="Before restore")
            backup = create_backup(data)
            (data / "config.json").write_text(
                json.dumps({"theme": "VIOLET", "sessions": [{"name": "London"}]}),
                encoding="utf-8",
            )
            database = sqlite3.connect(data / "focus_goals.sqlite3")
            database.execute("INSERT INTO goals(title) VALUES ('After backup')")
            database.commit()
            database.close()
            (data / "alarm_state.json").unlink()

            prepare_restore(data, backup["name"])
            result = apply_pending_restore(data, app_version="10.19")

            restored_config = json.loads((data / "config.json").read_text(encoding="utf-8"))
            with sqlite3.connect(data / "focus_goals.sqlite3") as connection:
                titles = [row[0] for row in connection.execute("SELECT title FROM goals")]
            self.assertEqual(restored_config["theme"], "CYAN")
            self.assertEqual(titles, ["Before restore"])
            self.assertTrue((data / "alarm_state.json").is_file())
            self.assertIn("pre_restore_backup", result)
            self.assertTrue(Path(result["safety_backup_path"]).is_file())
            self.assertIsNone(read_pending_restore(data))

    def test_restore_removes_files_that_did_not_exist_in_selected_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            data = self.make_data_dir(Path(folder))
            (data / "alarm_state.json").unlink()
            backup = create_backup(data)
            (data / "alarm_state.json").write_text('{"state":"idle"}', encoding="utf-8")

            prepare_restore(data, backup["name"])
            apply_pending_restore(data)

            self.assertFalse((data / "alarm_state.json").exists())

    def test_backup_folder_symlink_is_not_followed_for_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = self.make_data_dir(root)
            outside = root / "outside"
            outside.mkdir()
            try:
                (data / "backups").symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Directory symlinks are unavailable on this platform")
            with self.assertRaisesRegex(BackupError, "symbolic link"):
                create_backup(data)
            with self.assertRaisesRegex(BackupError, "symbolic link"):
                prepare_restore(data, "veltrix-backup-20261125T000000Z-abcdef12.zip")

    def test_restore_rolls_back_current_data_when_a_file_replace_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            data = self.make_data_dir(Path(folder), theme="CYAN", focus_title="Before restore")
            selected = create_backup(data)
            (data / "config.json").write_text(
                json.dumps({"theme": "VIOLET", "sessions": [{"name": "Current"}]}),
                encoding="utf-8",
            )
            (data / "market_cache.json").write_text(
                json.dumps({"assets": {"current": {"close": 2200}}}),
                encoding="utf-8",
            )
            prepare_restore(data, selected["name"])

            import backup_recovery
            real_replace = backup_recovery.os.replace
            failed = {"value": False}

            def fail_once(source, destination):
                if str(destination).endswith("config.json") and not failed["value"]:
                    failed["value"] = True
                    raise OSError("simulated disk replacement failure")
                return real_replace(source, destination)

            with patch("backup_recovery.os.replace", side_effect=fail_once):
                with self.assertRaisesRegex(BackupError, "pre-restore data"):
                    apply_pending_restore(data, app_version="10.19")

            current_config = json.loads((data / "config.json").read_text(encoding="utf-8"))
            current_market = json.loads((data / "market_cache.json").read_text(encoding="utf-8"))
            self.assertEqual(current_config["theme"], "VIOLET")
            self.assertIn("current", current_market["assets"])
            self.assertIsNone(read_pending_restore(data))
            self.assertGreaterEqual(len(list_backups(data)), 2)

    def test_invalid_configuration_is_not_archived_or_restored(self):
        with tempfile.TemporaryDirectory() as folder:
            data = self.make_data_dir(Path(folder))
            (data / "config.json").write_text("{invalid json", encoding="utf-8")

            with self.assertRaisesRegex(BackupError, "Configuration cannot be safely backed up"):
                create_backup(data)

    def test_prepare_restore_rejects_path_traversal_names(self):
        with tempfile.TemporaryDirectory() as folder:
            data = self.make_data_dir(Path(folder))
            with self.assertRaises(BackupError):
                prepare_restore(data, "../../config.json")

    def test_missing_required_config_prevents_backup_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / "data"
            data.mkdir()
            with self.assertRaisesRegex(BackupError, "configuration file is missing"):
                create_backup(data)


if __name__ == "__main__":
    unittest.main()
