from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from regime_data import (
    import_ohlc_csv,
    infer_bar_interval_minutes,
    load_regime_datasets,
    save_regime_datasets,
    snapshot_ohlc_records,
)


class RegimeDataTests(unittest.TestCase):
    def test_analysis_snapshot_reuses_large_ohlc_row_records(self):
        rows = [
            {"timestamp_utc": "2026-11-12T10:00:00+00:00", "close": 100.0},
            {"timestamp_utc": "2026-11-12T10:05:00+00:00", "close": 101.0},
        ]

        snapshot = snapshot_ohlc_records(rows)

        self.assertIsInstance(snapshot, tuple)
        self.assertEqual(snapshot, tuple(rows))
        self.assertIs(snapshot[0], rows[0])
        self.assertIs(snapshot[1], rows[1])


    def write_csv(self, directory: str, name: str, contents: str) -> Path:
        path = Path(directory) / name
        path.write_text(contents, encoding="utf-8")
        return path

    def test_imports_mt5_separate_date_time_columns_and_normalises_to_utc(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_csv(
                directory,
                "gold.csv",
                "Date,Time,Open,High,Low,Close,TickVolume\n"
                "2026.11.12,10:00:00,100,102,99,101,12\n"
                "2026.11.12,10:05:00,101,103,100,102,13\n",
            )
            bars, metadata = import_ohlc_csv(source, naive_timezone="Africa/Nairobi")

        self.assertEqual(len(bars), 2)
        self.assertEqual(
            bars[0].timestamp,
            datetime(2026, 11, 12, 7, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(metadata["valid_bars"], 2)
        self.assertEqual(metadata["invalid_rows"], 0)
        self.assertEqual(metadata["timezone_for_naive_timestamps"], "Africa/Nairobi")

    def test_import_sorts_bars_and_last_duplicate_timestamp_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_csv(
                directory,
                "duplicate.csv",
                "timestamp,open,high,low,close\n"
                "2026-11-12T10:05:00Z,101,103,100,102\n"
                "2026-11-12T10:00:00Z,100,102,99,101\n"
                "2026-11-12T10:05:00Z,101,104,100,103\n",
            )
            bars, metadata = import_ohlc_csv(source)

        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].close, 101)
        self.assertEqual(bars[1].close, 103)
        self.assertEqual(metadata["duplicate_timestamps"], 1)

    def test_import_skips_invalid_rows_and_rejects_non_positive_prices(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_csv(
                directory,
                "bad-row.csv",
                "timestamp,open,high,low,close\n"
                "2026-11-12T10:00:00Z,100,102,99,101\n"
                "2026-11-12T10:05:00Z,0,102,99,101\n"
                "not-a-time,100,102,99,101\n",
            )
            bars, metadata = import_ohlc_csv(source)

        self.assertEqual(len(bars), 1)
        self.assertEqual(metadata["invalid_rows"], 2)

    def test_import_rejects_unknown_timezone_and_empty_valid_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_csv(
                directory,
                "one.csv",
                "timestamp,open,high,low,close\n"
                "2026-11-12T10:00:00,100,102,99,101\n",
            )
            with self.assertRaisesRegex(ValueError, "Unknown IANA timezone"):
                import_ohlc_csv(source, naive_timezone="Mars/Olympus")
            invalid = self.write_csv(
                directory,
                "invalid.csv",
                "timestamp,open,high,low,close\n"
                "2026-11-12T10:00:00Z,100,90,95,99\n",
            )
            with self.assertRaisesRegex(ValueError, "No valid OHLC rows"):
                import_ohlc_csv(invalid)

    def test_interval_inference_uses_median_positive_timestamp_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_csv(
                directory,
                "interval.csv",
                "timestamp,open,high,low,close\n"
                "2026-11-12T10:00:00Z,100,102,99,101\n"
                "2026-11-12T10:05:00Z,101,103,100,102\n"
                "2026-11-12T10:10:00Z,102,104,101,103\n",
            )
            bars, _ = import_ohlc_csv(source)

        self.assertEqual(infer_bar_interval_minutes(bars), 5.0)

    def test_legacy_migration_keeps_regular_ohlc_and_skips_tick_datasets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "research_cache.json"
            destination = root / "regime_data.json"
            regular = {
                "name": "Gold",
                "source": "Broker CSV",
                "bars": [{
                    "timestamp_utc": "2026-11-12T10:00:00+00:00",
                    "open": 100, "high": 102, "low": 99, "close": 101, "volume": 10,
                }],
            }
            tick = {
                "name": "Gold TIB",
                "source": "Tick bars",
                "variable_interval_bars": True,
                "bars": regular["bars"],
                "metadata": {"bar_construction": "tick_imbalance"},
            }
            legacy.write_text(json.dumps({
                "assets": {"broker_gold": regular, "gold_tib": tick},
                "provider_assets": {"provider_gold": regular},
            }), encoding="utf-8")

            result = load_regime_datasets(destination, legacy)

            # The migration reads the previous cache but must never delete it.
            self.assertTrue(legacy.exists())

        self.assertTrue(result["migrated_from_legacy"])
        self.assertEqual(set(result["datasets"]), {"broker_gold", "provider_gold"})
        self.assertEqual(result["skipped_tick_datasets"], 1)
        self.assertFalse(destination.exists())

    def test_existing_regime_store_takes_precedence_over_legacy_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "regime_data.json"
            legacy = root / "research_cache.json"
            save_regime_datasets(destination, {"local_gold": {
                "name": "Local Gold",
                "bars": [{
                    "timestamp_utc": "2026-11-12T10:00:00+00:00",
                    "open": 100, "high": 102, "low": 99, "close": 101, "volume": None,
                }],
            }})
            legacy.write_text(json.dumps({"assets": {"old": {"bars": []}}}), encoding="utf-8")

            result = load_regime_datasets(destination, legacy)

        self.assertFalse(result["migrated_from_legacy"])
        self.assertEqual(list(result["datasets"]), ["local_gold"])

    def test_dataset_persistence_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "regime_data.json"
            datasets = {"gold": {
                "name": "Spot Gold",
                "source": "Local CSV",
                "bar_interval_minutes": 5.0,
                "bars": [{
                    "timestamp_utc": "2026-11-12T10:00:00+00:00",
                    "open": 100, "high": 102, "low": 99, "close": 101, "volume": 10,
                }],
            }}
            save_regime_datasets(destination, datasets)
            result = load_regime_datasets(destination)

        self.assertEqual(result["datasets"]["gold"]["name"], "Spot Gold")
        self.assertEqual(len(result["datasets"]["gold"]["bars"]), 1)


if __name__ == "__main__":
    unittest.main()
