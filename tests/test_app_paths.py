import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from app_paths import APP_NAME, PROJECT_DIR, get_app_data_dir, initialize_app_data, resource_path


class AppPathTests(unittest.TestCase):
    def test_source_mode_keeps_data_beside_project(self):
        with tempfile.TemporaryDirectory() as directory:
            actual = get_app_data_dir(frozen=False, project_dir=directory)
            self.assertEqual(actual, Path(directory).resolve())

    def test_frozen_windows_uses_local_appdata(self):
        actual = get_app_data_dir(
            frozen=True,
            platform="win32",
            env={"LOCALAPPDATA": r"C:\Users\Trader\AppData\Local"},
            home=r"C:\Users\Trader",
        )
        self.assertEqual(actual, Path(r"C:\Users\Trader\AppData\Local") / APP_NAME)

    def test_frozen_windows_falls_back_to_home_when_localappdata_missing(self):
        actual = get_app_data_dir(
            frozen=True, platform="win32", env={}, home=r"C:\Users\Trader"
        )
        self.assertEqual(actual, Path(r"C:\Users\Trader") / "AppData" / "Local" / APP_NAME)

    def test_initialize_seeds_defaults_without_overwriting_user_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            existing_config = target / "config.json"
            existing_config.write_text('{"theme": "VIOLET"}', encoding="utf-8")

            initialized = initialize_app_data(target)

            self.assertEqual(initialized, target)
            self.assertEqual(existing_config.read_text(encoding="utf-8"), '{"theme": "VIOLET"}')
            self.assertTrue((target / ".env.example").is_file())
            self.assertTrue((target / "tick_data").is_dir())
            self.assertFalse((target / ".env").exists())

    def test_bundled_resources_resolve_from_project_in_source_mode(self):
        self.assertEqual(resource_path("config.json"), PROJECT_DIR / "config.json")
        self.assertTrue(resource_path("assets/veltrix.ico").is_file())

    def test_resource_path_uses_pyinstaller_bundle_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            (bundle / "config.json").write_text("{}", encoding="utf-8")
            with patch("app_paths.sys._MEIPASS", str(bundle), create=True):
                self.assertEqual(resource_path("config.json"), bundle / "config.json")


if __name__ == "__main__":
    unittest.main()
