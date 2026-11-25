from __future__ import annotations

import math
import unittest
from datetime import datetime, timedelta, timezone

from market_intelligence_engine import build_market_intelligence_snapshot
from regime_engine import RegimeConfig, analyse_market_regimes


def make_bars(closes, *, start=None):
    origin = start or datetime(2026, 1, 1, 16, tzinfo=timezone.utc)
    rows = []
    for index, close in enumerate(closes):
        stamp = origin + timedelta(days=index)
        price = float(close)
        rows.append({
            "timestamp_utc": stamp.isoformat(),
            "open": price * 0.999,
            "high": price * 1.002,
            "low": price * 0.998,
            "close": price,
            "volume": 1000 + index,
        })
    return rows


def geometric_prices(returns, start=100.0):
    values = [start]
    for value in returns:
        values.append(values[-1] * math.exp(value))
    return values


def market_payload(**assets):
    return {"assets": assets, "fetched_at": "2026-11-24T00:00:00+00:00"}


CONFIG = {
    "lookback": 5,
    "atr_fast_period": 3,
    "atr_slow_period": 10,
    "range_er_max": 0.20,
    "trend_er_min": 0.30,
    "trend_slope_atr_min": 0.10,
    "shock_atr_ratio": 2.0,
    "shock_true_range_multiple": 3.0,
    "forward_horizon": 5,
}


class MarketIntelligenceEngineTests(unittest.TestCase):
    def setUp(self):
        self.instruments = [
            {"key": "gold", "name": "SPOT GOLD", "symbol": "XAUUSD=X", "unit": "USD/oz"},
            {"key": "spx", "name": "S&P 500", "symbol": "^GSPC", "unit": "pts"},
            {"key": "es", "name": "E-MINI S&P 500", "symbol": "ES=F", "unit": "pts"},
        ]

    def build(self, snapshot, *, fresh=True, instruments=None, breadth=None):
        return build_market_intelligence_snapshot(
            snapshot,
            instruments or self.instruments,
            market_is_fresh=fresh,
            now_utc=datetime(2026, 11, 24, tzinfo=timezone.utc),
            regime_config=CONFIG,
            breadth_universe=breadth,
        )

    def test_cached_market_data_is_never_labelled_updated(self):
        bars = make_bars([100 + index for index in range(90)])
        result = self.build(market_payload(gold={"daily_bars": bars}), fresh=False)
        self.assertEqual(result["assets"]["gold"]["freshness"], "CACHED")
        self.assertEqual(result["feed_state"], "CACHED")

    def test_fresh_partial_asset_is_labelled_partial(self):
        bars = make_bars([100 + index for index in range(90)])
        result = self.build(market_payload(gold={"daily_bars": bars, "error": "intraday unavailable"}))
        self.assertEqual(result["assets"]["gold"]["freshness"], "PARTIAL")

    def test_missing_market_data_remains_unavailable_not_zero(self):
        result = self.build(market_payload())
        asset = result["assets"]["gold"]
        self.assertEqual(asset["freshness"], "NO DATA")
        self.assertIsNone(asset["quote"])
        self.assertIsNone(asset["volatility"]["atr14"])
        self.assertEqual(asset["regime"]["state"], "INSUFFICIENT DATA")

    def test_trending_history_receives_causal_directional_label(self):
        bars = make_bars([100 + index * 1.4 for index in range(120)])
        result = self.build(market_payload(gold={"daily_bars": bars}))
        regime = result["assets"]["gold"]["regime"]
        self.assertEqual(regime["label"], "TREND_UP")
        self.assertFalse(regime["uses_future_data_for_label"])
        self.assertGreater(regime["evidence"]["efficiency_ratio"], 0.9)

    def test_regime_label_at_a_timestamp_is_unchanged_by_later_bars(self):
        closes = [100 + index * 0.7 + (index % 4) * 0.03 for index in range(130)]
        prefix = make_bars(closes[:100])
        extended = make_bars(closes)
        config = RegimeConfig(**CONFIG)
        prefix_result = analyse_market_regimes(prefix, config)
        extended_result = analyse_market_regimes(extended, config)
        prefix_latest = prefix_result["latest"]
        matching = next(
            row for row in extended_result["records"]
            if row["timestamp_utc"] == prefix_latest["timestamp_utc"]
        )
        self.assertEqual(prefix_latest["regime"], "TREND_UP")
        self.assertEqual(prefix_latest["regime"], matching["regime"])
        self.assertAlmostEqual(
            prefix_latest["efficiency_ratio"], matching["efficiency_ratio"], places=12
        )

    def test_volatility_stats_have_sample_gates_and_expected_move(self):
        closes = [100 * math.exp(0.001 * index + 0.01 * math.sin(index * 0.8)) for index in range(100)]
        result = self.build(market_payload(gold={"daily_bars": make_bars(closes)}))
        vol = result["assets"]["gold"]["volatility"]
        self.assertIsNotNone(vol["realised_vol_10d_ann_pct"])
        self.assertIsNotNone(vol["realised_vol_20d_ann_pct"])
        self.assertIsNotNone(vol["realised_vol_60d_ann_pct"])
        self.assertIsNotNone(vol["atr14_pct"])
        self.assertIsNotNone(vol["expected_move_1d_pct"])
        self.assertGreaterEqual(vol["rv20_percentile_lookback"], 0)
        self.assertLessEqual(vol["rv20_percentile_lookback"], 100)

    def test_insufficient_history_does_not_invent_volatility(self):
        result = self.build(market_payload(gold={"daily_bars": make_bars([100, 101, 102, 103, 104])}))
        vol = result["assets"]["gold"]["volatility"]
        self.assertEqual(vol["state"], "INSUFFICIENT DATA")
        self.assertIsNone(vol["realised_vol_20d_ann_pct"])
        self.assertIsNone(vol["atr14"])
        self.assertIsNone(vol["expected_move_1d_pct"])

    def test_correlations_use_aligned_daily_log_returns(self):
        base_returns = [0.002 * math.sin(index * 0.7) + 0.0005 * math.cos(index * 0.2)
                        for index in range(85)]
        gold = make_bars(geometric_prices(base_returns))
        spx = make_bars(geometric_prices([2 * value for value in base_returns]))
        es = make_bars(geometric_prices([-1.5 * value for value in base_returns]))
        result = self.build(market_payload(
            gold={"daily_bars": gold},
            spx={"daily_bars": spx},
            es={"daily_bars": es},
        ))
        pairs = {(row["left_key"], row["right_key"]): row for row in result["correlations"]}
        self.assertAlmostEqual(pairs[("gold", "spx")]["correlation_20d"], 1.0, places=8)
        self.assertAlmostEqual(pairs[("gold", "es")]["correlation_60d"], -1.0, places=8)
        self.assertEqual(pairs[("gold", "spx")]["samples_20d"], 20)

    def test_correlation_is_na_when_history_or_variance_is_insufficient(self):
        flat = make_bars([100] * 80)
        short = make_bars([100, 101, 102, 103, 104])
        result = self.build(market_payload(gold={"daily_bars": flat}, spx={"daily_bars": short}))
        pair = result["correlations"][0]
        self.assertIsNone(pair["correlation_20d"])
        self.assertIsNone(pair["correlation_60d"])

    def test_breadth_is_unavailable_without_constituent_universe(self):
        result = self.build(market_payload())
        self.assertEqual(result["breadth"]["state"], "UNAVAILABLE")
        self.assertIsNone(result["breadth"]["advance_share_pct"])
        self.assertIn("No constituent-level", result["breadth"]["reason"])

    def test_breadth_is_calculated_only_from_supplied_constituents(self):
        universe = {
            "AAA": make_bars([100, 101, 102]),
            "BBB": make_bars([100, 99, 98]),
            "CCC": make_bars([100, 100, 100]),
        }
        result = self.build(market_payload(), breadth=universe)
        breadth = result["breadth"]
        self.assertEqual(breadth["state"], "AVAILABLE")
        self.assertEqual((breadth["advancers"], breadth["decliners"], breadth["unchanged"]), (1, 1, 1))
        self.assertEqual(breadth["advance_share_pct"], 50.0)

    def test_snapshot_rejects_naive_generation_timestamp(self):
        with self.assertRaises(ValueError):
            build_market_intelligence_snapshot(
                market_payload(), self.instruments, market_is_fresh=True,
                now_utc=datetime(2026, 11, 24),
            )

    def test_volatility_percentile_uses_latest_sixty_rolling_windows(self):
        closes = [
            100.0 * math.exp(
                0.0008 * index
                + 0.012 * math.sin(index * 0.31)
                + 0.003 * math.cos(index * 0.09)
            )
            for index in range(260)
        ]
        bars = make_bars(closes)
        result = self.build(market_payload(gold={"daily_bars": bars}))
        volatility = result["assets"]["gold"]["volatility"]

        returns = [
            math.log(right / left)
            for left, right in zip(closes, closes[1:])
        ]
        rolling = [
            math.sqrt(252) * 100.0 * __import__("statistics").stdev(returns[end - 20:end])
            for end in range(20, len(returns) + 1)
        ][-60:]
        expected_current = math.sqrt(252) * 100.0 * __import__("statistics").stdev(returns[-20:])
        expected_percentile = (
            sum(value <= expected_current for value in rolling) / len(rolling) * 100.0
        )

        self.assertEqual(volatility["rv20_percentile_samples"], 60)
        self.assertAlmostEqual(
            volatility["rv20_percentile_lookback"], expected_percentile, places=12
        )

    def test_breadth_uses_latest_two_common_dates_for_staggered_histories(self):
        universe = {
            "AAA": make_bars(
                [100, 101, 102, 103, 104],
                start=datetime(2026, 1, 1, 16, tzinfo=timezone.utc),
            ),
            "BBB": make_bars(
                [50, 49, 50, 51],
                start=datetime(2026, 1, 2, 16, tzinfo=timezone.utc),
            ),
            "CCC": make_bars(
                [200, 201, 202, 201],
                start=datetime(2026, 1, 2, 16, tzinfo=timezone.utc),
            ),
        }
        result = self.build(market_payload(), breadth=universe)
        breadth = result["breadth"]

        self.assertEqual(breadth["state"], "AVAILABLE")
        self.assertEqual(breadth["as_of_utc"], "2026-01-05")
        self.assertEqual(
            (breadth["advancers"], breadth["decliners"], breadth["unchanged"]),
            (2, 1, 0),
        )


if __name__ == "__main__":
    unittest.main()
