"""Low-overhead, read-only runtime health metrics for Veltrix Trading Clock."""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SystemHealthSample:
    sampled_at: datetime
    process_cpu_percent: float
    system_cpu_percent: float | None
    process_rss_mb: float | None
    system_memory_percent: float | None
    thread_count: int


def calculate_process_cpu_percent(
    process_seconds: float,
    wall_seconds: float,
    logical_cpus: int | None = None,
) -> float:
    """Return process CPU as a percentage of total logical machine capacity."""
    elapsed = max(0.0, float(wall_seconds))
    if elapsed <= 0:
        return 0.0
    cores = max(1, int(logical_cpus or os.cpu_count() or 1))
    used = max(0.0, float(process_seconds))
    return min(100.0, max(0.0, (used / elapsed / cores) * 100.0))


def calculate_system_cpu_percent(
    previous: tuple[int, int] | None,
    current: tuple[int, int] | None,
) -> float | None:
    """Convert cumulative (idle_ticks, total_ticks) counters into CPU usage."""
    if previous is None or current is None:
        return None
    idle_delta = current[0] - previous[0]
    total_delta = current[1] - previous[1]
    if idle_delta < 0 or total_delta <= 0:
        return None
    return min(100.0, max(0.0, (1.0 - (idle_delta / total_delta)) * 100.0))


def parse_linux_cpu_counters(line: str) -> tuple[int, int] | None:
    """Parse the aggregate first row from /proc/stat."""
    fields = str(line).strip().split()
    if not fields or fields[0] != "cpu" or len(fields) < 5:
        return None
    try:
        values = [int(value) for value in fields[1:]]
    except ValueError:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values[:8])
    return (idle, total) if total >= idle else None


def parse_linux_memory_percent(contents: str) -> float | None:
    """Estimate physical-memory pressure using MemAvailable, with safe fallback."""
    values: dict[str, int] = {}
    for line in str(contents).splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].endswith(":"):
            try:
                values[parts[0][:-1]] = int(parts[1])
            except ValueError:
                continue
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable")
    if available is None:
        available = sum(values.get(key, 0) for key in ("MemFree", "Buffers", "Cached"))
    if total <= 0:
        return None
    return min(100.0, max(0.0, (total - available) / total * 100.0))


def _filetime_value(value: Any) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def _read_windows_cpu_counters() -> tuple[int, int] | None:
    if sys.platform != "win32":
        return None
    try:
        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

        kernel = FILETIME()
        user = FILETIME()
        idle = FILETIME()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_times = kernel32.GetSystemTimes
        get_times.argtypes = [
            ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME)
        ]
        get_times.restype = ctypes.c_int
        if not get_times(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        idle_ticks = _filetime_value(idle)
        total_ticks = _filetime_value(kernel) + _filetime_value(user)
        return idle_ticks, total_ticks
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def read_system_cpu_counters(platform_name: str | None = None) -> tuple[int, int] | None:
    platform_value = platform_name or sys.platform
    if platform_value == "win32":
        return _read_windows_cpu_counters()
    if platform_value.startswith("linux"):
        try:
            return parse_linux_cpu_counters(Path("/proc/stat").read_text(encoding="ascii").splitlines()[0])
        except (OSError, IndexError, ValueError):
            return None
    return None


def _read_windows_process_rss_bytes() -> int | None:
    try:
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        get_current_process = kernel32.GetCurrentProcess
        get_current_process.restype = wintypes.HANDLE
        get_info = psapi.GetProcessMemoryInfo
        get_info.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
            wintypes.DWORD,
        ]
        get_info.restype = wintypes.BOOL
        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(counters)
        if get_info(get_current_process(), ctypes.byref(counters), counters.cb):
            return int(counters.WorkingSetSize)
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    return None


def read_process_rss_bytes(platform_name: str | None = None) -> int | None:
    platform_value = platform_name or sys.platform
    if platform_value == "win32":
        return _read_windows_process_rss_bytes()
    if platform_value.startswith("linux"):
        try:
            resident_pages = int(Path("/proc/self/statm").read_text(encoding="ascii").split()[1])
            return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
        except (OSError, IndexError, ValueError):
            return None
    # macOS has no portable stdlib API for current resident-set size.
    return None


def _read_windows_system_memory_percent() -> float | None:
    try:
        from ctypes import wintypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_status = kernel32.GlobalMemoryStatusEx
        get_status.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
        get_status.restype = wintypes.BOOL
        if get_status(ctypes.byref(status)):
            return float(status.dwMemoryLoad)
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    return None


def read_system_memory_percent(platform_name: str | None = None) -> float | None:
    platform_value = platform_name or sys.platform
    if platform_value == "win32":
        return _read_windows_system_memory_percent()
    if platform_value.startswith("linux"):
        try:
            return parse_linux_memory_percent(Path("/proc/meminfo").read_text(encoding="ascii"))
        except OSError:
            return None
    return None


class SystemHealthMonitor:
    """Sample process/system resource use without blocking or background polling."""

    def __init__(self) -> None:
        self.started_monotonic = time.monotonic()
        self._error_lock = threading.Lock()
        self._recent_errors: deque[dict[str, str]] = deque(maxlen=12)
        self._previous_process_cpu: float | None = None
        self._previous_wall: float | None = None
        self._previous_system_cpu = read_system_cpu_counters()
        self.reset_baseline()

    def reset_baseline(self) -> None:
        """Discard elapsed time while the health workspace was not visible."""
        self._previous_process_cpu = time.process_time()
        self._previous_wall = time.perf_counter()
        self._previous_system_cpu = read_system_cpu_counters()

    def sample(self) -> SystemHealthSample:
        now_wall = time.perf_counter()
        now_process = time.process_time()
        if self._previous_wall is None or self._previous_process_cpu is None:
            process_cpu = 0.0
        else:
            process_cpu = calculate_process_cpu_percent(
                now_process - self._previous_process_cpu,
                now_wall - self._previous_wall,
            )
        self._previous_wall = now_wall
        self._previous_process_cpu = now_process

        current_system_cpu = read_system_cpu_counters()
        system_cpu = calculate_system_cpu_percent(self._previous_system_cpu, current_system_cpu)
        self._previous_system_cpu = current_system_cpu

        rss_bytes = read_process_rss_bytes()
        system_memory = read_system_memory_percent()
        return SystemHealthSample(
            sampled_at=datetime.now(timezone.utc),
            process_cpu_percent=process_cpu,
            system_cpu_percent=system_cpu,
            process_rss_mb=(rss_bytes / (1024.0 * 1024.0)) if rss_bytes is not None else None,
            system_memory_percent=system_memory,
            thread_count=threading.active_count(),
        )

    def record_error(self, source: str, detail: object) -> None:
        message = str(detail or "Unknown error").strip().replace("\n", " ")
        if not message:
            message = "Unknown error"
        event = {
            "time": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
            "source": str(source or "Application")[:48],
            "detail": message[:240],
        }
        with self._error_lock:
            self._recent_errors.append(event)

    def recent_errors(self) -> tuple[dict[str, str], ...]:
        with self._error_lock:
            return tuple(dict(item) for item in self._recent_errors)


def _queue_size(app: Any, attribute: str) -> int:
    value = getattr(app, attribute, None)
    try:
        return max(0, int(value.qsize())) if value is not None else 0
    except (AttributeError, NotImplementedError, TypeError, ValueError):
        return 0


def collect_worker_snapshot(app: Any) -> dict[str, Any]:
    """Describe existing application workers and result queues without starting work."""
    workers: list[dict[str, str]] = []

    def add(label: str, active: bool, idle_detail: str = "Waiting for a request",
            active_detail: str = "Background task is running") -> None:
        workers.append({
            "label": label,
            "status": "RUNNING" if active else "IDLE",
            "detail": active_detail if active else idle_detail,
        })

    add("Market data fetch", bool(getattr(app, "market_fetch_in_progress", False)))
    add("Economic calendar fetch", bool(getattr(app, "calendar_fetch_in_progress", False)))
    add("OHLC library load", bool(getattr(app, "regime_cache_loading", False)))
    add("OHLC CSV import", bool(getattr(app, "regime_import_in_progress", False)))
    add("Regime classification", bool(getattr(app, "regime_in_progress", False)))
    add("Session performance study", bool(getattr(app, "session_performance_in_progress", False)))

    writer = getattr(app, "regime_cache_writer_thread", None)
    writer_alive = bool(writer is not None and writer.is_alive())
    pending_writes = _queue_size(app, "regime_cache_write_queue")
    workers.append({
        "label": "Local dataset cache writer",
        "status": "WRITING" if writer_alive and pending_writes else ("READY" if writer_alive else "STOPPED"),
        "detail": (
            f"{pending_writes} pending save(s)" if pending_writes
            else ("Waiting for local saves" if writer_alive else "Not running")
        ),
    })

    result_queues = (
        "market_result_queue", "calendar_result_queue", "regime_cache_load_queue",
        "regime_import_result_queue", "regime_result_queue", "session_performance_result_queue",
    )
    queued_results = sum(_queue_size(app, name) for name in result_queues)
    active_workers = sum(item["status"] == "RUNNING" for item in workers)
    if workers[-1]["status"] == "WRITING":
        active_workers += 1
    background_threads = sum(
        thread.name.startswith("Veltrix") for thread in threading.enumerate()
    )
    return {
        "workers": workers,
        "active_workers": active_workers,
        "background_threads": background_threads,
        "queued_results": queued_results,
        "thread_count": threading.active_count(),
    }
