import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backtest_engine import (
    BacktestConfig, _Position, _intrabar_exit, export_backtest_html, export_trades_csv,
    run_backtest, run_out_of_sample, run_walk_forward,
)
from market_data import OHLCBar


def synthetic_bars(count=900):
    bars = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    previous = 100.0
    for index in range(count):
        # Deterministic trend reversals create repeated MA crossovers.
        close = 100 + index * 0.008 + 3.2 * __import__("math").sin(index / 13.0) + 1.1 * __import__("math").sin(index / 4.1)
        open_price = previous
        high = max(open_price, close) + 0.35
        low = min(open_price, close) - 0.35
        bars.append(OHLCBar(
            (start + timedelta(hours=index)).isoformat(), open_price, high, low, close, 1000
        ))
        previous = close
    return bars


class BacktestEngineTests(unittest.TestCase):
    def setUp(self):
        self.bars = synthetic_bars()
        self.config = BacktestConfig(
            fast_period=8, slow_period=24, atr_period=10,
            stop_atr_multiple=1.8, target_r_multiple=2.0,
            direction="both", initial_capital=10_000,
            risk_per_trade_pct=0.5, commission_bps=0.5,
            slippage_bps=0.5, point_value=1, quantity_step=0.001,
            max_leverage=2,
        )

    def test_backtest_generates_trades_with_next_bar_execution(self):
        result = run_backtest(self.bars, self.config)
        self.assertGreater(result["metrics"]["trade_count"], 0)
        for trade in result["trades"]:
            self.assertGreater(trade["entry_time"], trade["signal_time"])
            self.assertGreater(trade["exit_time"], trade["entry_time"])
            self.assertIn(trade["side"], {"LONG", "SHORT"})

    def test_costs_reduce_net_pnl_for_same_trade_series(self):
        no_cost = BacktestConfig.from_mapping({**self.config.__dict__, "commission_bps": 0, "slippage_bps": 0})
        costly = BacktestConfig.from_mapping({**self.config.__dict__, "commission_bps": 8, "slippage_bps": 5})
        first = run_backtest(self.bars, no_cost)
        second = run_backtest(self.bars, costly)
        self.assertEqual(first["metrics"]["trade_count"], second["metrics"]["trade_count"])
        self.assertLess(second["metrics"]["net_pnl"], first["metrics"]["net_pnl"])
        self.assertGreater(second["metrics"]["total_commission"], 0)
        self.assertGreater(second["metrics"]["total_slippage_cost"], 0)

    def test_ambiguous_bar_is_resolved_stop_first(self):
        position = _Position(
            side=1, signal_time="2025-01-01T00:00:00+00:00", entry_time="2025-01-01T01:00:00+00:00",
            entry_reference=100, entry_fill=100, quantity=1, atr_at_signal=1,
            stop_price=98, target_price=104, risk_amount=2, equity_at_entry=10_000, entry_fee=0, entry_slippage_cost=0,
        )
        bar = OHLCBar("2025-01-01T02:00:00+00:00", 100, 105, 97, 102, 1)
        self.assertEqual(_intrabar_exit(position, bar), (98, "STOP_AMBIGUOUS_BAR"))

    def test_position_size_respects_max_leverage_cap(self):
        config = BacktestConfig.from_mapping({**self.config.__dict__, "max_leverage": 0.25})
        result = run_backtest(self.bars, config)
        for trade in result["trades"]:
            notional = trade["entry_notional"]
            self.assertLessEqual(notional, trade["equity_at_entry"] * config.max_leverage + 1e-6)

    def test_out_of_sample_is_chronological_and_separates_test_trades(self):
        result = run_out_of_sample(self.bars, self.config, train_fraction=0.7)
        split = result["split_timestamp"]
        self.assertGreater(result["train"]["bars_tested"], result["test"]["bars_tested"])
        self.assertTrue(all(trade["entry_time"] >= split for trade in result["test"]["trades"]))
        self.assertIn("fixed strategy parameters", result["methodology"].lower())

    def test_walk_forward_folds_are_ordered_and_non_overlapping(self):
        result = run_walk_forward(self.bars, self.config, train_fraction=0.5, folds=3)
        folds = result["folds"]
        self.assertEqual(len(folds), 3)
        for previous, current in zip(folds, folds[1:]):
            self.assertLess(previous["test_end"], current["test_start"])
            self.assertGreater(current["training_bars"], previous["training_bars"])

    def test_walk_forward_rejects_insufficient_test_data(self):
        with self.assertRaises(ValueError):
            run_walk_forward(self.bars[:65], self.config, train_fraction=0.8, folds=5)

    def test_config_rejects_lookahead_prone_invalid_periods_and_costs(self):
        with self.assertRaises(ValueError):
            BacktestConfig.from_mapping({"fast_period": 50, "slow_period": 20})
        with self.assertRaises(ValueError):
            BacktestConfig.from_mapping({"slippage_bps": -1})

    def test_exports_write_trade_csv_and_html_report(self):
        oos = run_out_of_sample(self.bars, self.config)
        wf = run_walk_forward(self.bars, self.config, train_fraction=0.5, folds=3)
        with tempfile.TemporaryDirectory() as temp:
            csv_path = export_trades_csv(Path(temp) / "trades.csv", oos["test"]["trades"])
            html_path = export_backtest_html(
                Path(temp) / "report.html", asset_name="Gold & Silver", source="Broker CSV",
                interval_minutes=60, config=self.config, oos=oos, walk_forward=wf,
                sampling_label="Tick Imbalance Bars (TIB)",
            )
            with csv_path.open(encoding="utf-8-sig", newline="") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), len(oos["test"]["trades"]))
            report = html_path.read_text(encoding="utf-8")
            self.assertIn("Gold &amp; Silver", report)
            self.assertIn("Out-of-sample", report)
            self.assertIn("Tick Imbalance Bars (TIB)", report)

    def test_duplicate_timestamps_are_deduplicated_and_ordered(self):
        modified = self.bars[:100]
        modified.append(modified[-1])
        modified.reverse()
        result = run_backtest(modified, self.config)
        self.assertEqual(result["bars_tested"], 100)


if __name__ == "__main__":
    unittest.main()
