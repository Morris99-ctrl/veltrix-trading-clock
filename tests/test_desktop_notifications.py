import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from desktop_notifications import send_desktop_notification  # noqa: E402


class DesktopNotificationTests(unittest.TestCase):
    def test_disabled_notification_does_not_send(self):
        result = send_desktop_notification("Title", "Message", enabled=False)
        self.assertFalse(result.sent)
        self.assertEqual(result.provider, "disabled")


    @patch("desktop_notifications.sys.platform", "win32")
    def test_windows_toast_is_sent_when_windows_toasts_is_available(self):
        calls = {}

        class FakeToast:
            def __init__(self):
                self.text_fields = []

        class FakeToaster:
            def __init__(self, app_name):
                calls["app_name"] = app_name

            def show_toast(self, toast):
                calls["text_fields"] = list(toast.text_fields)

        fake_module = types.ModuleType("windows_toasts")
        fake_module.Toast = FakeToast
        fake_module.WindowsToaster = FakeToaster
        with patch.dict(sys.modules, {"windows_toasts": fake_module}):
            result = send_desktop_notification("Test title", "Test message")

        self.assertTrue(result.sent)
        self.assertEqual(result.provider, "windows-toasts")
        self.assertEqual(calls["app_name"], "Veltrix Capital")
        self.assertEqual(calls["text_fields"], ["Test title", "Test message"])

    @patch("desktop_notifications.sys.platform", "linux")
    def test_non_windows_platform_falls_back_safely(self):
        result = send_desktop_notification("Title", "Message")
        self.assertFalse(result.sent)
        self.assertEqual(result.provider, "unsupported")


if __name__ == "__main__":
    unittest.main()
