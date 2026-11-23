from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from market_data import OHLCBar
from session_engine import SessionDefinition
from session_performance import analyse_session_performance, export_session_performance_csv


def bar(timestamp: str, open_: float, high: float, low: float, close: float) -> OHLCBar:
    return OHLCBar(timestamp, open_, high, low, close)


class SessionPerformanceTests(unittest.TestCase):
    @staticmethod
    def session(key: str, name: str, zone: str, opens: str, closes: str) -> SessionDefinition:
        return SessionDefinition(
            key, name, name, "", zone,
            time.fromisoformat(opens), time.fromisoformat(closes), (0, 1, 2, 3, 4),
        )

    def test_session_daily_returns_range_volatility_and_positive_rate(self):
        ny = self.session("new_york", "New York", "America/New_York", "08:00", "17:00")
        zone = ZoneInfo("America/New_York")
        bars = [
            bar(datetime(2026, 11, 23, hour, 0, tzinfo=zone).isoformat(), 100, 102, 99, 101)
            for hour in (8, 9, 10)
        ]
        bars += [
            bar(datetime(2026, 11, 24, hour, 0, tzinfo=zone).isoformat(), 100, 101, 98, 99)
            for hour in (8, 9, 10)
        ]
        result = analyse_session_performance(
            bars, [ny], bar_interval_minutes=60,
            minimum_bars_per_session=3, minimum_coverage_pct=25,
        )
        summary = result["sessions"][0]
        self.assertEqual(summary["sample_sessions"], 2)
        self.assertEqual(summary["bars_used"], 6)
        self.assertAlmostEqual(summary["mean_return_pct"], 0.0)
        self.assertAlmostEqual(summary["mean_range_pct"], 3.0)
        self.assertEqual(summary["positive_rate_pct"], 50.0)
        self.assertEqual(len(result["session_daily"]), 2)

    def test_minimum_coverage_excludes_incomplete_session_days_but_keeps_diagnostics(self):
        ny = self.session("ny", "New York", "America/New_York", "08:00", "17:00")
        zone = ZoneInfo("America/New_York")
        bars = [
            bar(datetime(2026, 11, 23, hour, 0, tzinfo=zone).isoformat(), 100, 102, 99, 101)
            for hour in (8, 9, 10)
        ]
        result = analyse_session_performance(
            bars, [ny], bar_interval_minutes=60,
            minimum_bars_per_session=2, minimum_coverage_pct=50,
        )
        self.assertEqual(result["sessions"][0]["sample_sessions"], 0)
        self.assertEqual(result["sessions"][0]["excluded_low_coverage"], 1)
        self.assertFalse(result["session_daily"][0]["included"])
        self.assertEqual(result["session_daily"][0]["exclusion_reason"], "MINIMUM_COVERAGE")

    def test_weekend_bars_are_not_assigned_to_weekday_session(self):
        ny = self.session("ny", "New York", "America/New_York", "08:00", "17:00")
        stamp = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
        result = analyse_session_performance(
            [bar(stamp.isoformat(), 100, 101, 99, 100.5)],
            [ny], bar_interval_minutes=60, minimum_bars_per_session=1,
            minimum_coverage_pct=0,
        )
        self.assertEqual(result["sessions"][0]["observed_dates"], 0)
        self.assertEqual(result["sessions"][0]["sample_sessions"], 0)

    def test_session_allocation_uses_each_sessions_local_timezone(self):
        ny = self.session("ny", "New York", "America/New_York", "08:00", "17:00")
        london = self.session("london", "London", "Europe/London", "08:00", "17:00")
        # 13:00 UTC is 08:00 New York and 13:00 London during this winter date.
        stamp = datetime(2026, 11, 23, 13, 0, tzinfo=timezone.utc)
        bars = [
            bar(stamp.isoformat(), 100, 101, 99, 100.5),
            bar((stamp.replace(minute=30)).isoformat(), 100.5, 102, 100, 101),
        ]
        result = analyse_session_performance(
            bars, [ny, london], bar_interval_minutes=30,
            minimum_bars_per_session=2, minimum_coverage_pct=0,
        )
        self.assertEqual({item["session"] for item in result["sessions"] if item["sample_sessions"]}, {"New York", "London"})

    def test_pairwise_overlap_returns_are_calculated_only_for_shared_bars(self):
        london = self.session("london", "London", "UTC", "08:00", "12:00")
        ny = self.session("ny", "New York", "UTC", "10:00", "14:00")
        bars = [
            bar(datetime(2026, 11, 23, hour, 0, tzinfo=timezone.utc).isoformat(),
                100, 110, 99, close)
            for hour, close in ((8, 101), (9, 101), (10, 102), (11, 103), (12, 104), (13, 105))
        ]
        result = analyse_session_performance(
            bars, [london, ny], bar_interval_minutes=60,
            minimum_bars_per_session=1, minimum_coverage_pct=0,
        )
        self.assertEqual(len(result["overlaps"]), 1)
        overlap = result["overlaps"][0]
        self.assertEqual(overlap["pair"], "London + New York")
        self.assertEqual(overlap["sample_days"], 1)
        self.assertEqual(overlap["bars_used"], 2)
        expected = ((102 / 100) * (103 / 100) - 1) * 100
        self.assertAlmostEqual(overlap["mean_return_pct"], expected)

    def test_overlap_days_are_excluded_when_below_minimum_bars(self):
        london = self.session("london", "London", "UTC", "08:00", "12:00")
        ny = self.session("ny", "New York", "UTC", "10:00", "14:00")
        bars = [
            bar(datetime(2026, 11, 23, hour, 0, tzinfo=timezone.utc).isoformat(),
                100, 101, 99, 100.5)
            for hour in (10, 11)
        ]
        result = analyse_session_performance(
            bars, [london, ny], bar_interval_minutes=60,
            minimum_bars_per_session=3, minimum_coverage_pct=0,
        )
        self.assertEqual(result["overlaps"][0]["sample_days"], 0)
        self.assertEqual(result["overlaps"][0]["excluded_low_bars"], 1)
        self.assertFalse(result["overlap_daily"][0]["included"])

    def test_overlap_days_are_excluded_when_below_minimum_coverage(self):
        london = self.session("london", "London", "UTC", "08:00", "12:00")
        ny = self.session("ny", "New York", "UTC", "10:00", "14:00")
        bars = [
            bar(datetime(2026, 11, 23, hour, 0, tzinfo=timezone.utc).isoformat(),
                100, 101, 99, 100.5)
            for hour in (10,)
        ]
        result = analyse_session_performance(
            bars, [london, ny], bar_interval_minutes=60,
            minimum_bars_per_session=1, minimum_coverage_pct=75,
        )
        self.assertEqual(result["overlaps"][0]["sample_days"], 0)
        self.assertEqual(result["overlaps"][0]["excluded_low_coverage"], 1)
        self.assertEqual(result["overlap_daily"][0]["coverage_pct"], 50.0)
        self.assertFalse(result["overlap_daily"][0]["included"])

    def test_dst_transition_uses_local_calendar_dates_and_utc_timestamps(self):
        ny = self.session("ny", "New York", "America/New_York", "08:00", "17:00")
        zone = ZoneInfo("America/New_York")
        bars = []
        for day in (datetime(2026, 3, 6), datetime(2026, 3, 9)):
            for hour in (8, 9, 10):
                stamp = datetime(day.year, day.month, day.day, hour, tzinfo=zone)
                bars.append(bar(stamp.isoformat(), 100, 101, 99, 100.5))
        result = analyse_session_performance(
            bars, [ny], bar_interval_minutes=60,
            minimum_bars_per_session=3, minimum_coverage_pct=25,
        )
        self.assertEqual(result["sessions"][0]["sample_sessions"], 2)
        self.assertEqual(
            [item["date"] for item in result["session_daily"] if item["included"]],
            ["2026-03-06", "2026-03-09"],
        )

    def test_naive_timestamps_are_rejected_by_analysis_not_silently_localised(self):
        ny = self.session("ny", "New York", "America/New_York", "08:00", "17:00")
        raw = {"timestamp_utc": "2026-11-23T10:00:00", "open": 100, "high": 101, "low": 99, "close": 100}
        with self.assertRaisesRegex(ValueError, "timezone or UTC offset"):
            analyse_session_performance(
                [raw], [ny], bar_interval_minutes=60,
                minimum_bars_per_session=1, minimum_coverage_pct=0,
            )

    def test_overlap_coverage_uses_actual_pairwise_schedule_intersection(self):
        london = self.session("london", "London", "UTC", "08:00", "12:00")
        ny = self.session("ny", "New York", "UTC", "10:00", "14:00")
        bars = [
            bar(datetime(2026, 11, 23, hour, 0, tzinfo=timezone.utc).isoformat(),
                100, 101, 99, 100.5)
            for hour in (10, 11)
        ]
        result = analyse_session_performance(
            bars, [london, ny], bar_interval_minutes=60,
            minimum_bars_per_session=1, minimum_coverage_pct=0,
        )
        self.assertEqual(result["overlaps"][0]["sample_days"], 1)
        self.assertEqual(result["overlap_daily"][0]["expected_bars"], 2)
        self.assertEqual(result["overlap_daily"][0]["coverage_pct"], 100.0)

    def test_daily_bar_interval_is_too_coarse_for_intraday_sessions(self):
        ny = self.session("ny", "New York", "America/New_York", "08:00", "17:00")
        stamp = datetime(2026, 11, 23, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "too coarse"):
            analyse_session_performance(
                [bar(stamp.isoformat(), 100, 102, 99, 101)],
                [ny], bar_interval_minutes=1440,
            )

    def test_export_writes_session_and_overlap_rows(self):
        london = self.session("london", "London", "UTC", "08:00", "12:00")
        ny = self.session("ny", "New York", "UTC", "10:00", "14:00")
        bars = [
            bar(datetime(2026, 11, 23, hour, 0, tzinfo=timezone.utc).isoformat(),
                100, 110, 99, 101 + index)
            for index, hour in enumerate((8, 9, 10, 11, 12, 13))
        ]
        analysis = analyse_session_performance(
            bars, [london, ny], bar_interval_minutes=60,
            minimum_bars_per_session=1, minimum_coverage_pct=0,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session-performance.csv"
            export_session_performance_csv(path, analysis)
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertTrue(any(row["row_type"] == "SESSION" for row in rows))
        self.assertTrue(any(row["row_type"] == "OVERLAP" for row in rows))

    def test_invalid_ohlc_bar_is_excluded(self):
        ny = self.session("ny", "New York", "UTC", "08:00", "17:00")
        bars = [
            bar("2026-11-23T08:00:00+00:00", 100, 101, 99, 102),
            bar("2026-11-23T09:00:00+00:00", 100, 103, 99, 102),
        ]
        result = analyse_session_performance(
            bars, [ny], bar_interval_minutes=60,
            minimum_bars_per_session=1, minimum_coverage_pct=0,
        )
        self.assertEqual(result["metadata"]["input_bars"], 2)
        self.assertEqual(result["metadata"]["valid_bars"], 1)
        self.assertEqual(result["sessions"][0]["bars_used"], 1)

    def test_rolling_metrics_are_trailing_only_and_include_drawdown_and_compounding(self):
        ny = self.session("ny", "New York", "UTC", "08:00", "12:00")
        bars = [
            bar(f"2026-11-{day:02d}T08:00:00+00:00", 100, max(close, 101), min(close, 99), close)
            for day, close in ((23, 110), (24, 90), (25, 120))
        ]
        result = analyse_session_performance(
            bars, [ny], bar_interval_minutes=60,
            minimum_bars_per_session=1, minimum_coverage_pct=0,
            rolling_window_sessions=2, ranking_min_samples=2,
        )
        rows = result["session_daily"]
        self.assertEqual(rows[0]["rolling_sample_sessions"], 1)
        latest = rows[-1]
        self.assertEqual(latest["rolling_sample_sessions"], 2)
        self.assertAlmostEqual(latest["rolling_mean_return_pct"], 5.0)
        self.assertAlmostEqual(latest["rolling_positive_rate_pct"], 50.0)
        self.assertAlmostEqual(latest["rolling_compounded_return_pct"], 8.0)
        self.assertAlmostEqual(latest["rolling_max_drawdown_pct"], -10.0)
        self.assertAlmostEqual(latest["rolling_consistency_score"], 66.6666667)
        summary = result["sessions"][0]
        self.assertEqual(summary["rank"], 1)
        self.assertEqual(len(result["ranked_sessions"]), 1)

    def test_ranking_is_withheld_until_minimum_rolling_sample_is_met(self):
        ny = self.session("ny", "New York", "UTC", "08:00", "12:00")
        bars = [
            bar(f"2026-11-{day:02d}T08:00:00+00:00", 100, 102, 99, 101)
            for day in (23, 24)
        ]
        result = analyse_session_performance(
            bars, [ny], bar_interval_minutes=60,
            minimum_bars_per_session=1, minimum_coverage_pct=0,
            rolling_window_sessions=3, ranking_min_samples=3,
        )
        self.assertEqual(result["sessions"][0]["rolling_sample_sessions"], 2)
        self.assertFalse(result["sessions"][0]["ranking_eligible"])
        self.assertIsNone(result["sessions"][0]["rank"])
        self.assertEqual(result["ranked_sessions"], [])

    def test_regime_breakdown_uses_dominant_causal_label_and_latest_tie_break(self):
        ny = self.session("ny", "New York", "UTC", "08:00", "12:00")
        bars = []
        labels = {}
        regime_days = {
            23: ("TREND_UP", "TREND_UP", "TREND_UP", "RANGE"),
            24: ("RANGE", "RANGE", "TREND_DOWN", "TREND_DOWN"),
            25: ("WARMUP", "WARMUP", "WARMUP", "WARMUP"),
        }
        for day, regimes in regime_days.items():
            for hour, regime in zip((8, 9, 10, 11), regimes):
                stamp = f"2026-11-{day:02d}T{hour:02d}:00:00+00:00"
                bars.append(bar(stamp, 100, 102, 99, 101))
                labels[stamp] = regime
        result = analyse_session_performance(
            bars, [ny], bar_interval_minutes=60,
            minimum_bars_per_session=1, minimum_coverage_pct=0,
            regime_labels=labels, minimum_regime_coverage_pct=50,
        )
        daily = result["session_daily"]
        self.assertEqual(daily[0]["dominant_regime"], "TREND_UP")
        self.assertEqual(daily[1]["dominant_regime"], "TREND_DOWN")
        self.assertEqual(daily[1]["regime_coverage_pct"], 100.0)
        self.assertEqual(daily[2]["dominant_regime"], "WARMUP")
        self.assertFalse(daily[2]["regime_eligible"])
        breakdown = {row["regime"]: row for row in result["regime_breakdown"]}
        self.assertEqual(set(breakdown), {"TREND_UP", "TREND_DOWN"})
        self.assertEqual(breakdown["TREND_UP"]["sample_days"], 1)
        self.assertEqual(breakdown["TREND_DOWN"]["sample_days"], 1)

    def test_regime_label_timestamps_are_normalised_from_explicit_offsets(self):
        ny = self.session("ny", "New York", "UTC", "08:00", "12:00")
        stamp = "2026-11-23T08:00:00+00:00"
        equivalent = "2026-11-23T11:00:00+03:00"
        result = analyse_session_performance(
            [bar(stamp, 100, 102, 99, 101)], [ny], bar_interval_minutes=60,
            minimum_bars_per_session=1, minimum_coverage_pct=0,
            regime_labels={equivalent: "RANGE"}, minimum_regime_coverage_pct=100,
        )
        self.assertEqual(result["session_daily"][0]["dominant_regime"], "RANGE")
        self.assertEqual(result["session_daily"][0]["regime_coverage_pct"], 100.0)

    def test_rolling_and_regime_thresholds_are_validated(self):
        ny = self.session("ny", "New York", "UTC", "08:00", "12:00")
        bars = [bar("2026-11-23T08:00:00+00:00", 100, 102, 99, 101)]
        with self.assertRaisesRegex(ValueError, "Rolling window"):
            analyse_session_performance(
                bars, [ny], bar_interval_minutes=60, rolling_window_sessions=1,
            )
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            analyse_session_performance(
                bars, [ny], bar_interval_minutes=60,
                rolling_window_sessions=5, ranking_min_samples=6,
            )
        with self.assertRaisesRegex(ValueError, "Minimum regime coverage"):
            analyse_session_performance(
                bars, [ny], bar_interval_minutes=60, minimum_regime_coverage_pct=101,
            )

    def test_empty_or_invalid_data_is_rejected(self):
        ny = self.session("ny", "New York", "America/New_York", "08:00", "17:00")
        with self.assertRaisesRegex(ValueError, "No valid"):
            analyse_session_performance(
                [], [ny], bar_interval_minutes=60,
            )
        with self.assertRaisesRegex(ValueError, "Bar interval"):
            analyse_session_performance(
                [bar("2026-11-23T13:00:00+00:00", 100, 101, 99, 100)],
                [ny], bar_interval_minutes=0,
            )


if __name__ == "__main__":
    unittest.main()
