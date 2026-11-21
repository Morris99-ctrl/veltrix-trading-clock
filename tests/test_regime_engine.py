from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from market_data import OHLCBar
from regime_engine import RegimeConfig, analyse_market_regimes, export_regime_analysis_csv


def make_bars(closes: list[float], *, half_range: float = 0.15) -> list[OHLCBar]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    for index, close in enumerate(closes):
        bars.append(OHLCBar(
            timestamp_utc=(start + timedelta(minutes=5 * index)).isoformat(),
            open=close, high=close + half_range, low=close - half_range, close=close,
            volume=100.0,
        ))
    return bars


class RegimeEngineTests(unittest.TestCase):
    def test_config_rejects_invalid_period_order(self):
        with self.assertRaises(ValueError):
            RegimeConfig(atr_fast_period=50, atr_slow_period=20).validate()

    def test_config_rejects_overlapping_er_thresholds(self):
        with self.assertRaises(ValueError):
            RegimeConfig(range_er_max=0.4, trend_er_min=0.3).validate()

    def test_uptrend_is_classified_directionally(self):
        bars = make_bars([100.0 + i * 0.2 for i in range(180)])
        result = analyse_market_regimes(bars)
        latest = result["latest"]
        self.assertEqual(latest["regime"], "TREND_UP")
        self.assertGreater(latest["efficiency_ratio"], 0.9)
        self.assertGreater(latest["normalised_slope_atr"], 0)

    def test_downtrend_is_classified_directionally(self):
        bars = make_bars([200.0 - i * 0.2 for i in range(180)])
        result = analyse_market_regimes(bars)
        self.assertEqual(result["latest"]["regime"], "TREND_DOWN")
        self.assertLess(result["latest"]["normalised_slope_atr"], 0)

    def test_sideways_market_is_classified_as_range(self):
        import math
        closes = [100.0 + 0.18 * math.sin(i * 0.7) for i in range(240)]
        result = analyse_market_regimes(make_bars(closes, half_range=0.2))
        self.assertEqual(result["latest"]["regime"], "RANGE")

    def test_large_true_range_is_classified_as_volatility_shock(self):
        closes = [100.0 + i * 0.02 for i in range(100)]
        closes[100 - 1] += 5.0
        result = analyse_market_regimes(make_bars(closes, half_range=0.1))
        self.assertEqual(result["records"][-1]["regime"], "VOLATILITY_SHOCK")

    def test_initial_history_is_marked_warmup(self):
        bars = make_bars([100.0 + i * 0.1 for i in range(60)])
        result = analyse_market_regimes(bars)
        self.assertEqual(result["records"][0]["regime"], "WARMUP")
        self.assertTrue(all(item["regime"] == "WARMUP" for item in result["records"][:49]))
        self.assertNotEqual(result["records"][49]["regime"], "WARMUP")

    def test_labels_are_causal_and_do_not_change_when_future_bars_are_appended(self):
        closes = [100 + i * 0.08 + ((i % 5) - 2) * 0.025 for i in range(160)]
        shorter = analyse_market_regimes(make_bars(closes[:110]))
        longer = analyse_market_regimes(make_bars(closes))
        for left, right in zip(shorter["records"], longer["records"][:110]):
            self.assertEqual(left["regime"], right["regime"])
            self.assertEqual(left["efficiency_ratio"], right["efficiency_ratio"])
            self.assertEqual(left["normalised_slope_atr"], right["normalised_slope_atr"])
            self.assertEqual(left["atr_slow"], right["atr_slow"])

    def test_forward_outcomes_are_separate_from_labels(self):
        bars = make_bars([100 + i * 0.15 for i in range(100)])
        result = analyse_market_regimes(bars, RegimeConfig(forward_horizon=5))
        self.assertIsNotNone(result["records"][-6]["forward_return_pct"])
        self.assertIsNone(result["records"][-1]["forward_return_pct"])
        self.assertFalse(result["metadata"]["classification_uses_future_data"])
        self.assertTrue(result["metadata"]["forward_returns_are_outcomes_only"])

    def test_distribution_percentages_sum_to_100_when_classified(self):
        bars = make_bars([100 + i * 0.12 for i in range(130)])
        result = analyse_market_regimes(bars)
        total = sum(item["frequency_pct"] for item in result["distribution"].values())
        self.assertAlmostEqual(total, 100.0, places=6)

    def test_transition_matrix_counts_adjacent_classified_bars(self):
        bars = make_bars([100 + i * 0.1 for i in range(120)])
        result = analyse_market_regimes(bars)
        matrix_count = sum(sum(row.values()) for row in result["transitions"].values())
        expected = sum(
            1 for left, right in zip(result["records"], result["records"][1:])
            if left["regime"] != "WARMUP" and right["regime"] != "WARMUP"
        )
        self.assertEqual(matrix_count, expected)

    def test_invalid_and_duplicate_bars_are_removed(self):
        bars = make_bars([100 + i * 0.1 for i in range(80)])
        duplicate = bars[-1]
        invalid = OHLCBar(
            timestamp_utc=(datetime(2025, 1, 1, tzinfo=timezone.utc)).isoformat(),
            open=10, high=9, low=11, close=10,
        )
        result = analyse_market_regimes(bars + [duplicate, invalid])
        self.assertEqual(result["metadata"]["input_bars"], 82)
        self.assertEqual(result["metadata"]["valid_bars"], 80)

    def test_empty_data_raises_clear_error(self):
        with self.assertRaisesRegex(ValueError, "No valid OHLC bars"):
            analyse_market_regimes([])

    def test_csv_export_contains_label_and_outcome_fields(self):
        result = analyse_market_regimes(make_bars([100 + i * 0.1 for i in range(90)]))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "regimes.csv"
            export_regime_analysis_csv(path, result)
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 90)
            self.assertIn("regime", rows[0])
            self.assertIn("forward_return_pct", rows[0])


if __name__ == "__main__":
    unittest.main()
