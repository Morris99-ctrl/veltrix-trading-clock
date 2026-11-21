"""Best-effort Windows 10/11 toast notifications for Veltrix Trading Clock."""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationResult:
    sent: bool
    provider: str
    message: str = ""


def send_desktop_notification(title: str, message: str, *, enabled: bool = True) -> NotificationResult:
    """Send a Windows toast when available; never break the main application."""
    if not enabled:
        return NotificationResult(False, "disabled", "Desktop notifications are disabled.")
    if sys.platform != "win32":
        return NotificationResult(False, "unsupported", "Windows desktop notifications are only available on Windows.")

    try:
        from windows_toasts import Toast, WindowsToaster

        toaster = WindowsToaster("Veltrix Capital")
        toast = Toast()
        toast.text_fields = [str(title)[:120], str(message)[:500]]
        toaster.show_toast(toast)
        return NotificationResult(True, "windows-toasts")
    except ImportError:
        return NotificationResult(
            False, "unavailable", "Install windows-toasts with: python -m pip install windows-toasts"
        )
    except Exception as exc:  # Toast failures must not interrupt clock/alarm logic.
        return NotificationResult(False, "error", f"Windows toast could not be shown: {exc}")
