import json
import tempfile
import unittest
from pathlib import Path

from config_store import load_config, save_config


class ConfigStoreTests(unittest.TestCase):
    def valid_config(self):
        return {
            "home_timezone": "UTC",
            "sessions": [{
                "key": "london", "name": "LONDON", "city": "London", "timezone": "Europe/London",
                "open": "08:00", "close": "17:00",
            }],
        }

    def test_load_validates_top_level_and_session_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "JSON object"):
                load_config(path)

            path.write_text(json.dumps({"sessions": [{"key": "bad"}]}), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "invalid trading session"):
                load_config(path)

    def test_save_is_atomic_and_round_trips_config_version(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text('{"theme":"ICE"}', encoding="utf-8")
            config = self.valid_config()

            save_config(path, config)

            self.assertEqual(load_config(path)["schema_version"], 1)
            self.assertEqual(load_config(path)["sessions"], config["sessions"])
            self.assertEqual(list(Path(temp).glob(".config.json.*.tmp")), [])

    def test_session_profiles_must_be_a_mapping_and_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            config = self.valid_config()
            config["session_profiles"] = {
                "selected": "Equities Cash",
                "base_sessions": config["sessions"],
                "custom": {},
            }
            save_config(path, config)
            self.assertEqual(load_config(path)["session_profiles"]["selected"], "Equities Cash")

            config["session_profiles"] = ["invalid"]
            save_config(path, config)
            with self.assertRaisesRegex(RuntimeError, "session_profiles.*JSON object"):
                load_config(path)

    def test_failed_serialization_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text('{"theme":"ICE"}', encoding="utf-8")

            with self.assertRaises(TypeError):
                save_config(path, {"unsupported": object()})

            self.assertEqual(path.read_text(encoding="utf-8"), '{"theme":"ICE"}')
            self.assertEqual(list(Path(temp).glob(".config.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
