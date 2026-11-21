import sys
import tempfile
import unittest
from pathlib import Path

from secure_credentials import (
    CredentialFileError,
    _PROTECTED_PREFIX,
    _protect_windows_data,
    _unprotect_windows_data,
    load_env_file,
)


class SecureCredentialTests(unittest.TestCase):
    def test_windows_plaintext_file_is_atomically_sealed_and_reopened(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            original = b"MASSIVE_API_KEY=secret-value\n"
            path.write_bytes(original)

            first_load = load_env_file(
                path,
                platform="win32",
                protect=lambda value: value[::-1],
                unprotect=lambda value: value[::-1],
            )

            self.assertIn("MASSIVE_API_KEY=secret-value", first_load)
            protected_file = path.read_bytes()
            self.assertTrue(protected_file.startswith(_PROTECTED_PREFIX))
            self.assertNotIn(b"secret-value", protected_file)

            second_load = load_env_file(
                path,
                platform="win32",
                unprotect=lambda value: value[::-1],
            )
            self.assertEqual(second_load, first_load)

    def test_non_windows_plaintext_file_remains_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            contents = b"MASSIVE_API_KEY=dev-value\n"
            path.write_bytes(contents)

            values = load_env_file(
                path,
                platform="linux",
                protect=lambda value: self.fail("Linux must not invoke Windows protection"),
            )

            self.assertIn("MASSIVE_API_KEY=dev-value", values)
            self.assertEqual(path.read_bytes(), contents)

    def test_invalid_protected_file_fails_without_falling_back_to_plaintext(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_bytes(_PROTECTED_PREFIX + b"not-valid-base64")

            with self.assertRaisesRegex(CredentialFileError, "protected API credential file is invalid"):
                load_env_file(path, platform="win32")

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI integration test")
    def test_windows_dpapi_round_trip(self):
        secret = b"MASSIVE_API_KEY=dpapi-test-value\n"
        protected = _protect_windows_data(secret)

        self.assertNotIn(b"dpapi-test-value", protected)
        self.assertEqual(_unprotect_windows_data(protected), secret)


if __name__ == "__main__":
    unittest.main()
