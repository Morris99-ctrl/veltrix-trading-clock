from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from system_health import (
    SystemHealthMonitor,
    calculate_process_cpu_percent,
    calculate_system_cpu_percent,
    collect_worker_snapshot,
    parse_linux_cpu_counters,
    parse_linux_memory_percent,
)


class SystemHealthEngineTests(unittest.TestCase):
    def test_process_cpu_is_normalised_by_logical_machine_capacity(self):
        self.assertAlmostEqual(calculate_process_cpu_percent(0.5, 1.0, 2), 25.0)
        self.assertAlmostEqual(calculate_process_cpu_percent(2.0, 1.0, 2), 100.0)
        self.assertEqual(calculate_process_cpu_percent(1.0, 0.0, 4), 0.0)

    def test_system_cpu_uses_idle_and_total_counter_deltas(self):
        self.assertAlmostEqual(calculate_system_cpu_percent((100, 200), (125, 300)), 75.0)
        self.assertIsNone(calculate_system_cpu_percent(None, (125, 300)))
        self.assertIsNone(calculate_system_cpu_percent((100, 200), (90, 180)))

    def test_linux_cpu_counter_parser_includes_idle_and_iowait(self):
        self.assertEqual(
            parse_linux_cpu_counters("cpu  100 20 30 400 50 10 5 5 0 0"),
            (450, 620),
        )
        self.assertIsNone(parse_linux_cpu_counters("intr 100"))

    def test_linux_memory_parser_prefers_memavailable(self):
        self.assertAlmostEqual(
            parse_linux_memory_percent(
                "MemTotal: 1000 kB\nMemFree: 100 kB\nMemAvailable: 400 kB\n"
            ),
            60.0,
        )

    def test_linux_memory_parser_has_safe_fallback(self):
        self.assertAlmostEqual(
            parse_linux_memory_percent(
                "MemTotal: 1000 kB\nMemFree: 100 kB\nBuffers: 100 kB\nCached: 200 kB\n"
            ),
            60.0,
        )
        self.assertIsNone(parse_linux_memory_percent("MemFree: 100 kB"))

    def test_worker_snapshot_reports_existing_work_without_starting_new_threads(self):
        app = SimpleNamespace(
            market_fetch_in_progress=True,
            calendar_fetch_in_progress=False,
            regime_cache_loading=False,
            regime_import_in_progress=False,
            regime_in_progress=True,
            session_performance_in_progress=False,
            regime_cache_writer_thread=None,
            market_result_queue=SimpleQueue(2),
            calendar_result_queue=SimpleQueue(0),
            regime_cache_load_queue=SimpleQueue(0),
            regime_import_result_queue=SimpleQueue(1),
            regime_result_queue=SimpleQueue(0),
            session_performance_result_queue=SimpleQueue(0),
        )

        before = __import__("threading").active_count()
        snapshot = collect_worker_snapshot(app)
        after = __import__("threading").active_count()

        self.assertEqual(before, after)
        self.assertEqual(snapshot["active_workers"], 2)
        self.assertEqual(snapshot["queued_results"], 3)
        self.assertEqual(
            [item["status"] for item in snapshot["workers"][:6]],
            ["RUNNING", "IDLE", "IDLE", "IDLE", "RUNNING", "IDLE"],
        )

    def test_sampler_returns_cpu_memory_and_thread_metrics(self):
        with (
            patch("system_health.time.process_time", side_effect=[2.0, 2.5]),
            patch("system_health.time.perf_counter", side_effect=[10.0, 11.0]),
            patch("system_health.read_system_cpu_counters", side_effect=[(100, 200), (125, 300)]),
            patch("system_health.read_process_rss_bytes", return_value=100 * 1024 * 1024),
            patch("system_health.read_system_memory_percent", return_value=62.5),
            patch("system_health.os.cpu_count", return_value=2),
        ):
            monitor = SystemHealthMonitor()
            sample = monitor.sample()

        self.assertAlmostEqual(sample.process_cpu_percent, 25.0)
        self.assertAlmostEqual(sample.system_cpu_percent, 75.0)
        self.assertAlmostEqual(sample.process_rss_mb, 100.0)
        self.assertAlmostEqual(sample.system_memory_percent, 62.5)
        self.assertGreaterEqual(sample.thread_count, 1)


    def test_error_history_is_bounded_and_thread_safe_to_read(self):
        monitor = SystemHealthMonitor()
        for index in range(15):
            monitor.record_error("Market data", f"Failure {index}")

        errors = monitor.recent_errors()

        self.assertEqual(len(errors), 12)
        self.assertEqual(errors[-1]["detail"], "Failure 14")
        self.assertEqual(errors[-1]["source"], "Market data")


class SimpleQueue:
    def __init__(self, size: int):
        self.size = size

    def qsize(self):
        return self.size


if __name__ == "__main__":
    unittest.main()
