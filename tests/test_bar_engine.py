import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bar_engine import (
    MarketTick, build_fixed_tick_bars, build_tick_imbalance_bars, import_tick_csv,
)


def ticks_from_prices(prices, *, start=None, seconds=1):
    start = start or datetime(2026, 11, 10, tzinfo=timezone.utc)
    return [
        MarketTick((start + timedelta(seconds=i * seconds)).isoformat(), float(price),
                   float(price) - 0.1, float(price) + 0.1, 1.0)
        for i, price in enumerate(prices)
    ]


class TickImportTests(unittest.TestCase):
    def test_mt5_date_time_bid_ask_quote_csv_uses_midpoint_proxy(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "quotes.csv"
            path.write_text(
                "<DATE>,<TIME>,<BID>,<ASK>,<LAST>,<TICKVOL>\n"
                "2026.11.09,09:00:00,2000.0,2000.2,,3\n"
                "2026.11.09,09:00:01,2000.1,2000.3,,4\n"
                "2026.11.09,09:00:02,2000.2,2000.4,,5\n",
                encoding="utf-8",
            )
            ticks, meta = import_tick_csv(path, naive_timezone="Africa/Nairobi")
            self.assertEqual(len(ticks), 3)
            self.assertEqual(ticks[0].price, 2000.1)
            self.assertEqual(ticks[0].timestamp, datetime(2026, 11, 9, 6, 0, tzinfo=timezone.utc))
            self.assertEqual(meta["price_source"], "bid_ask_midquote_proxy")
            self.assertIn("not traded order flow", meta["price_source_description"])

    def test_last_price_is_preferred_and_rows_without_last_are_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "trades.csv"
            path.write_text(
                "timestamp,bid,ask,last,volume\n"
                "2026-11-09T09:00:00Z,2000,2000.2,2000.1,1\n"
                "2026-11-09T09:00:01Z,2000.1,2000.3,2000.2,2\n"
                "2026-11-09T09:00:02Z,2000.2,2000.4,2000.3,1\n"
                "2026-11-09T09:00:03Z,2000.3,2000.5,,0\n",
                encoding="utf-8",
            )
            ticks, meta = import_tick_csv(path)
            self.assertEqual(len(ticks), 3)
            self.assertEqual([item.price for item in ticks], [2000.1, 2000.2, 2000.3])
            self.assertEqual(meta["price_source"], "last_price_tick_rule")
            self.assertEqual(meta["missing_selected_price_rows"], 1)

    def test_unsorted_ticks_are_sorted_but_duplicate_timestamps_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ordered.csv"
            path.write_text(
                "timestamp,last\n"
                "2026-11-09T09:00:02Z,3\n"
                "2026-11-09T09:00:01Z,2\n"
                "2026-11-09T09:00:01Z,2.1\n",
                encoding="utf-8",
            )
            ticks, meta = import_tick_csv(path)
            self.assertEqual(len(ticks), 3)
            self.assertTrue(meta["input_was_out_of_order"])
            self.assertEqual(ticks[0].price, 2.0)
            self.assertEqual(ticks[1].price, 2.1)

    def test_bad_optional_volume_does_not_discard_valid_last_tick(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "optional_volume.csv"
            path.write_text(
                "timestamp,bid,ask,last,volume\n"
                "2026-11-09T09:00:00Z,2000,2000.2,2000.1,not-a-volume\n"
                "2026-11-09T09:00:01Z,2000.1,2000.3,2000.2,-1\n"
                "2026-11-09T09:00:02Z,2000.2,2000.4,2000.3,1\n",
                encoding="utf-8",
            )
            ticks, meta = import_tick_csv(path)
            self.assertEqual(len(ticks), 3)
            self.assertEqual(meta["invalid_rows"], 0)
            self.assertEqual([item.volume for item in ticks], [None, None, 1.0])

    def test_import_rejects_files_without_usable_price_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.csv"
            path.write_text("timestamp,volume\n2026-11-09T09:00:00Z,1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                import_tick_csv(path)


class TickBarConstructionTests(unittest.TestCase):
    def test_fixed_tick_bars_preserve_ohlc_and_discard_trailing_incomplete_bar(self):
        ticks = ticks_from_prices([100, 101, 99, 102, 103, 101, 104, 105, 103, 106, 107])
        bars, meta = build_fixed_tick_bars(ticks, ticks_per_bar=5)
        self.assertEqual(len(bars), 2)
        self.assertEqual((bars[0].open, bars[0].high, bars[0].low, bars[0].close), (100, 103, 99, 103))
        self.assertEqual(meta["source_ticks_used"], 10)
        self.assertEqual(meta["trailing_ticks_discarded"], 1)
        self.assertTrue(meta["variable_interval_bars"])
        self.assertEqual(meta["bar_stats"][0]["tick_count"], 5)

    def test_fixed_tick_bars_can_include_partial_when_explicitly_requested(self):
        bars, meta = build_fixed_tick_bars(ticks_from_prices(range(11)), ticks_per_bar=5, include_partial=True)
        self.assertEqual(len(bars), 3)
        self.assertTrue(meta["bar_stats"][-1]["is_partial"])

    def test_tib_emits_calibration_bar_and_adaptive_imbalance_bars(self):
        # Monotonic seed and continuation create a deliberately directional stream.
        prices = list(range(100, 140)) + list(range(140, 300))
        bars, meta = build_tick_imbalance_bars(
            ticks_from_prices(prices), seed_ticks=40, ewma_span=10,
            min_expected_imbalance_fraction=0.05,
        )
        self.assertGreaterEqual(len(bars), 3)
        self.assertTrue(meta["bar_stats"][0]["is_calibration_bar"])
        self.assertEqual(meta["bar_stats"][0]["tick_count"], 40)
        self.assertTrue(all(item["expected_threshold"] is not None for item in meta["bar_stats"][1:]))
        self.assertTrue(all(item["tick_count"] >= 1 for item in meta["bar_stats"]))
        self.assertEqual(meta["bar_construction"], "tick_imbalance")
        self.assertGreaterEqual(meta["trailing_ticks_discarded"], 0)

    def test_tib_uses_separate_bar_length_and_tick_level_ewma_spans(self):
        seed_ticks = 40
        bar_span = 20
        tick_span = 4
        prices = list(range(100, 600))
        bars, meta = build_tick_imbalance_bars(
            ticks_from_prices(prices), seed_ticks=seed_ticks,
            ewma_span=bar_span, imbalance_ewma_span=tick_span,
            min_expected_imbalance_fraction=0.05,
        )
        stats = meta["bar_stats"]
        self.assertGreaterEqual(len(stats), 3)
        # Seed price path contains 39 up ticks and one unknown first direction.
        seed_rate = 39 / 40
        alpha_bar = 2 / (bar_span + 1)
        alpha_tick = 2 / (tick_span + 1)
        second_bar_ticks = stats[1]["tick_count"]
        expected_ticks = (1 - alpha_bar) * seed_ticks + alpha_bar * second_bar_ticks
        # The second bar is monotonic, so its tick-level EWMA moves toward +1 once
        # per tick, not once per completed bar.
        expected_imbalance = 1 - (1 - alpha_tick) ** second_bar_ticks * (1 - seed_rate)
        expected_threshold = max(1.0, expected_ticks * max(abs(expected_imbalance), 0.05))
        self.assertAlmostEqual(stats[2]["expected_ticks_at_open"], expected_ticks)
        self.assertAlmostEqual(stats[2]["expected_imbalance_fraction_at_open"], expected_imbalance)
        self.assertAlmostEqual(stats[2]["expected_threshold"], expected_threshold)
        self.assertEqual(meta["expected_bar_length_ewma_span_bars"], bar_span)
        self.assertEqual(meta["expected_tick_imbalance_ewma_span_ticks"], tick_span)

    def test_tib_threshold_is_causal_and_not_recomputed_inside_open_bar(self):
        prefix = list(range(100, 140)) + list(range(140, 180))
        later_a = list(range(180, 260))
        later_b = list(range(180, 220)) + list(range(220, 260))
        bars_a, meta_a = build_tick_imbalance_bars(
            ticks_from_prices(prefix + later_a), seed_ticks=40, ewma_span=10,
        )
        bars_b, meta_b = build_tick_imbalance_bars(
            ticks_from_prices(prefix + later_b), seed_ticks=40, ewma_span=10,
        )
        self.assertEqual(bars_a[0], bars_b[0])
        self.assertEqual(meta_a["bar_stats"][1]["expected_threshold"], meta_b["bar_stats"][1]["expected_threshold"])
        self.assertEqual(bars_a[1], bars_b[1])

    def test_tib_rejects_too_small_or_invalid_calibration(self):
        ticks = ticks_from_prices(range(100, 200))
        with self.assertRaises(ValueError):
            build_tick_imbalance_bars(ticks, seed_ticks=100)
        with self.assertRaises(ValueError):
            build_tick_imbalance_bars(ticks, seed_ticks=20, ewma_span=1)
        with self.assertRaises(ValueError):
            build_tick_imbalance_bars(ticks, seed_ticks=20, min_expected_imbalance_fraction=0)


if __name__ == "__main__":
    unittest.main()
