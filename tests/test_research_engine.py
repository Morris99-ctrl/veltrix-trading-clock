import csv
import math
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from market_data import OHLCBar
from research_engine import (
    analyse_research_assets, analyse_session_history, build_session_observations,
    export_daily_observations_csv, export_html_report, export_summary_csv, import_ohlc_csv,
    load_research_cache, save_research_cache,
)
from session_engine import SessionDefinition


def bar(at, price, change=0.001):
    close = price * (1 + change)
    return OHLCBar(at.isoformat(), price, max(price, close) * 1.001,
                   min(price, close) * 0.999, close, 100)


class ResearchEngineTests(unittest.TestCase):
    def setUp(self):
        self.tokyo = SessionDefinition(
            "tokyo", "TOKYO", "Tokyo", "JP", "Asia/Tokyo",
            datetime.strptime("09:00", "%H:%M").time(),
            datetime.strptime("18:00", "%H:%M").time(),
        )

    def test_csv_import_parses_mt5_style_date_time_and_headers(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "broker.csv"
            path.write_text(
                "<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<TICKVOL>\n"
                "2026.11.09,09:00:00,100,101,99,100.5,12\n"
                "2026.11.09,09:05:00,100.5,102,100,101.5,15\n",
                encoding="utf-8",
            )
            bars, meta = import_ohlc_csv(path, naive_timezone="Asia/Tokyo")
            self.assertEqual(len(bars), 2)
            self.assertEqual(bars[0].timestamp, datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc))
            self.assertEqual(meta["valid_bars"], 2)
            self.assertEqual(bars[0].volume, 12)

    def test_csv_import_accepts_unix_milliseconds_and_skips_bad_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "epoch.csv"
            path.write_text(
                "timestamp,open,high,low,close\n"
                "1794182400000,100,102,99,101\n"
                "1794182700000,0,102,99,101\n",
                encoding="utf-8",
            )
            bars, meta = import_ohlc_csv(path)
            self.assertEqual(len(bars), 1)
            self.assertEqual(meta["invalid_rows"], 1)

    def test_csv_import_accepts_single_time_column_with_epoch_milliseconds(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "chart_export.csv"
            path.write_text(
                "time,open,high,low,close\n"
                "1794182400000,100,102,99,101\n"
                "1794182700000,101,103,100,102\n",
                encoding="utf-8",
            )
            bars, meta = import_ohlc_csv(path)
            self.assertEqual(len(bars), 2)
            self.assertEqual(meta["valid_bars"], 2)

    def test_csv_import_rejects_unknown_timezone_and_missing_headers(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.csv"
            path.write_text("timestamp,open,high,low,close\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                import_ohlc_csv(path, naive_timezone="Mars/Olympus")
            path.write_text("x,y,z\n1,2,3\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                import_ohlc_csv(path)

    def test_csv_duplicate_timestamp_last_row_wins(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "dupes.csv"
            path.write_text(
                "timestamp,open,high,low,close\n"
                "2026-11-09T00:00:00Z,100,102,99,101\n"
                "2026-11-09T00:00:00Z,101,103,100,102\n",
                encoding="utf-8",
            )
            bars, meta = import_ohlc_csv(path)
            self.assertEqual(len(bars), 1)
            self.assertEqual(bars[0].close, 102)
            self.assertEqual(meta["duplicate_timestamps"], 1)

    def test_session_observations_use_local_date_and_realised_volatility(self):
        start = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)  # 09:00 Tokyo
        bars = [bar(start + timedelta(minutes=60 * i), 100 + i) for i in range(4)]
        result = build_session_observations(bars, [self.tokyo], bar_interval_minutes=60)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["date"], "2026-11-09")
        self.assertEqual(result[0]["bars"], 4)
        self.assertEqual(result[0]["returns"], 4)
        self.assertIsNotNone(result[0]["realised_vol_pct"])

    def test_large_gap_is_not_bridged_for_hourly_bars(self):
        start = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)
        bars = [bar(start, 100), bar(start + timedelta(hours=4), 101)]
        result = build_session_observations(bars, [self.tokyo], bar_interval_minutes=60)
        self.assertFalse(result[0]["valid"])
        self.assertEqual(result[0]["returns"], 1)  # Only the first bar's own open-to-close return remains.
        self.assertIsNotNone(result[0]["realised_vol_pct"])

    def test_30_60_90_day_reports_include_distribution_and_percentile(self):
        bars = []
        start_day = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
        for day in range(90):
            start = start_day + timedelta(days=day)
            # Four hourly Tokyo bars per day, changing volatility gradually.
            for idx in range(4):
                bars.append(bar(start + timedelta(hours=idx), 100 + day + idx, 0.0005 * (idx + 1) * (1 + day / 100)))
        rows, observations = analyse_session_history(
            {"gold": bars}, {"gold": {"name": "Gold", "symbol": "XAUUSD=X", "source": "test", "bar_interval_minutes": 60}},
            [self.tokyo], windows=(30, 60, 90),
        )
        self.assertEqual([row["window_days"] for row in rows], [30, 60, 90])
        self.assertGreaterEqual(rows[0]["sample_count"], 19)
        self.assertGreaterEqual(rows[1]["sample_count"], 40)
        self.assertGreaterEqual(rows[2]["sample_count"], 60)
        self.assertIsNotNone(rows[0]["p90_rv_pct"])
        self.assertGreaterEqual(rows[0]["latest_percentile"], 0)
        self.assertLessEqual(rows[0]["latest_percentile"], 100)
        self.assertEqual(len(observations["gold"]), 64)

    def test_open_current_session_is_marked_partial_and_excluded_from_history(self):
        previous = datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc)
        current = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)
        bars = [bar(previous + timedelta(minutes=5 * i), 100 + i) for i in range(4)]
        bars.extend(bar(current + timedelta(minutes=5 * i), 110 + i) for i in range(3))
        now = datetime(2026, 11, 9, 0, 15, tzinfo=timezone.utc)  # 09:15 Tokyo
        rows, observations = analyse_session_history(
            {"gold": bars}, {"gold": {"name": "Gold", "bar_interval_minutes": 5}},
            [self.tokyo], windows=(30,), now=now,
        )
        self.assertEqual(rows[0]["sample_count"], 1)
        self.assertEqual(rows[0]["latest_date"], "2026-11-06")
        current_observation = max(observations["gold"], key=lambda item: item["date"])
        self.assertTrue(current_observation["is_partial"])

    def test_worker_friendly_analysis_parses_cached_records_and_returns_compact_metadata(self):
        start = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)
        bars = [bar(start + timedelta(hours=idx), 100 + idx) for idx in range(4)]
        rows, observations, metadata = analyse_research_assets(
            {"gold": {"bars": [item.to_dict() for item in bars], "name": "Gold",
                      "symbol": "XAUUSD=X", "source": "test", "bar_interval_minutes": 60}},
            [self.tokyo], windows=(30, 60, 90), now=datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(metadata["gold"]["bar_count"], 4)
        self.assertNotIn("bars", metadata["gold"])
        self.assertEqual(len(observations["gold"]), 1)
        self.assertEqual(len(rows), 3)

    def test_analysis_helper_skips_invalid_cached_bar_records(self):
        start = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)
        bars = [bar(start + timedelta(hours=idx), 100 + idx) for idx in range(3)]
        records = [item.to_dict() for item in bars] + [{"timestamp": "not-a-time"}]
        _rows, observations, metadata = analyse_research_assets(
            {"gold": {"bars": records, "bar_interval_minutes": 60}},
            [self.tokyo], now=datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(metadata["gold"]["bar_count"], 3)
        self.assertEqual(observations["gold"][0]["bars"], 3)

    def test_variable_interval_bars_do_not_apply_time_bar_gap_filter(self):
        start = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)  # 09:00 Tokyo
        bars = [bar(start + timedelta(minutes=minute), 100 + minute) for minute in (0, 10, 30)]
        fixed = build_session_observations(
            bars, [self.tokyo], bar_interval_minutes=5,
            now=datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc),
        )[0]
        event = build_session_observations(
            bars, [self.tokyo], bar_interval_minutes=5, variable_interval=True,
            now=datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc),
        )[0]
        self.assertEqual(fixed["returns"], 1)
        self.assertEqual(event["returns"], 3)
        self.assertTrue(event["variable_interval_bars"])

    def test_tick_dataset_nested_metadata_propagates_variable_interval_flag(self):
        start = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)  # 09:00 Tokyo
        bars = [bar(start + timedelta(minutes=minute), 100 + minute) for minute in (0, 10, 30)]
        _rows, observations, metadata = analyse_research_assets(
            {"event": {
                "bars": [item.to_dict() for item in bars],
                "name": "Tick Event Bars", "source": "Broker tick CSV",
                "bar_interval_minutes": 5,
                "metadata": {"variable_interval_bars": True, "bar_construction": "tick_imbalance"},
            }},
            [self.tokyo], now=datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(metadata["event"]["variable_interval_bars"])
        self.assertEqual(observations["event"][0]["returns"], 3)
        self.assertTrue(observations["event"][0]["variable_interval_bars"])

    def test_no_session_data_is_reported_as_n_a_not_zero(self):
        rows, _ = analyse_session_history(
            {"cash": []}, {"cash": {"name": "Cash index"}}, [self.tokyo]
        )
        self.assertEqual(rows[0]["sample_count"], 0)
        self.assertIsNone(rows[0]["median_rv_pct"])
        self.assertIsNone(rows[0]["latest_percentile"])

    def test_csv_and_html_exports_are_created_and_escape_html(self):
        rows = [{"asset_name": "Gold & Silver", "symbol": "XAUUSD=X", "session_name": "TOKYO",
                 "window_days": 30, "sample_count": 4, "median_rv_pct": 0.2}]
        observations = {"gold": [{"session_name": "TOKYO", "date": "2026-11-09",
                                  "realised_vol_pct": 0.2, "range_pct": 0.4,
                                  "session_return_pct": 0.1, "bars": 4, "returns": 3}]}
        with tempfile.TemporaryDirectory() as temp:
            csv_path = export_summary_csv(Path(temp) / "summary.csv", rows)
            html_path = export_html_report(Path(temp) / "report.html", rows, observations)
            self.assertTrue(csv_path.is_file())
            self.assertTrue(html_path.is_file())
            self.assertIn("Gold &amp; Silver", html_path.read_text(encoding="utf-8"))
            with csv_path.open(encoding="utf-8-sig", newline="") as file:
                self.assertEqual(len(list(csv.DictReader(file))), 1)

    def test_csv_exports_neutralize_formula_text_and_preserve_numeric_values(self):
        with tempfile.TemporaryDirectory() as temp:
            summary_path = export_summary_csv(
                Path(temp) / "summary.csv",
                [{"asset_name": " =HYPERLINK(\"https://example.invalid\")",
                  "symbol": "@SUM(1,1)", "mean_rv_pct": -1.25}],
            )
            daily_path = export_daily_observations_csv(
                Path(temp) / "daily.csv",
                {"=2+2": [{"session_name": "\t=1+1", "realised_vol_pct": -0.5}]},
            )

            with summary_path.open(encoding="utf-8-sig", newline="") as file:
                summary = next(csv.DictReader(file))
            with daily_path.open(encoding="utf-8-sig", newline="") as file:
                daily = next(csv.DictReader(file))

            self.assertEqual(summary["asset_name"], "' =HYPERLINK(\"https://example.invalid\")")
            self.assertEqual(summary["symbol"], "'@SUM(1,1)")
            self.assertEqual(summary["mean_rv_pct"], "-1.25")
            self.assertEqual(daily["asset_key"], "'=2+2")
            self.assertEqual(daily["session_name"], "'\t=1+1")
            self.assertEqual(daily["realised_vol_pct"], "-0.5")

    def test_research_cache_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "research.json"
            payload = {"assets": {"gold": {"bars": [], "source": "CSV"}}}
            save_research_cache(path, payload)
            self.assertEqual(load_research_cache(path), payload)


if __name__ == "__main__":
    unittest.main()
