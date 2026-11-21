import math
import unittest
from datetime import datetime, timedelta, timezone

from market_data import OHLCBar
from session_engine import SessionDefinition
from volatility_engine import (
    calculate_atr, calculate_daily_expected_move, realised_volatility,
    session_volatility_report,
)


def bar(at, o, h, l, c):
    return OHLCBar(at.isoformat(), o, h, l, c, 100)


class VolatilityEngineTests(unittest.TestCase):
    def test_realised_volatility_matches_sum_of_squared_log_returns(self):
        start = datetime(2026, 11, 10, 14, 30, tzinfo=timezone.utc)
        bars = [bar(start, 100, 101, 99, 100), bar(start + timedelta(minutes=5), 100, 102, 99, 101),
                bar(start + timedelta(minutes=10), 101, 103, 100, 102)]
        result = realised_volatility(bars)
        expected = math.sqrt(math.log(101 / 100) ** 2 + math.log(102 / 101) ** 2) * 100
        self.assertAlmostEqual(result["realised_vol_pct"], expected, places=10)
        self.assertEqual(result["returns"], 2)

    def test_realised_volatility_does_not_bridge_large_gaps(self):
        start = datetime(2026, 11, 10, 14, 30, tzinfo=timezone.utc)
        bars = [bar(start, 100, 101, 99, 100), bar(start + timedelta(hours=3), 100, 102, 99, 101)]
        self.assertIsNone(realised_volatility(bars)["realised_vol_pct"])

    def test_atr_wilder_constant_range(self):
        start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        bars = []
        previous_close = 100.0
        for i in range(16):
            day = start + timedelta(days=i)
            bars.append(bar(day, previous_close, previous_close + 2, previous_close - 1, previous_close + 0.5))
            previous_close += 0.5
        atr = calculate_atr(bars, 14)
        self.assertIsNotNone(atr)
        self.assertGreater(atr, 2.0)
        self.assertLess(atr, 4.0)

    def test_expected_move_is_positive_and_uses_last_close(self):
        start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        bars = []
        close = 100.0
        changes = [0.01, -0.005, 0.007, -0.012, 0.004, 0.009, -0.008, 0.003, 0.006, -0.004]
        for i in range(25):
            change = changes[i % len(changes)]
            new_close = close * math.exp(change)
            bars.append(bar(start + timedelta(days=i), close, max(close, new_close) * 1.002,
                            min(close, new_close) * 0.998, new_close))
            close = new_close
        result = calculate_daily_expected_move(bars, lookback=20)
        self.assertGreater(result["expected_move_pct"], 0)
        self.assertGreater(result["expected_move_abs"], 0)
        self.assertEqual(result["reference_close"], bars[-1].close)

    def test_session_report_separates_sessions_and_uses_local_time(self):
        session = SessionDefinition("tokyo", "TOKYO", "Tokyo", "JP", "Asia/Tokyo",
                                    datetime.strptime("09:00", "%H:%M").time(),
                                    datetime.strptime("18:00", "%H:%M").time())
        # 00:00 UTC = 09:00 Tokyo. Three five-minute bars produce two returns.
        start = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)
        bars = [bar(start + timedelta(minutes=5 * i), 100 + i, 101 + i, 99 + i, 100 + i)
                for i in range(3)]
        report = session_volatility_report(bars, [session], now=datetime(2026, 11, 10, 1, tzinfo=timezone.utc))
        self.assertEqual(report[0]["session_key"], "tokyo")
        self.assertEqual(report[0]["date"], "2026-11-10")
        self.assertEqual(report[0]["bars"], 3)


    def test_regime_expansion_compares_same_elapsed_window_with_prior_sessions(self):
        session = SessionDefinition("tokyo", "TOKYO", "Tokyo", "JP", "Asia/Tokyo",
                                    datetime.strptime("09:00", "%H:%M").time(),
                                    datetime.strptime("18:00", "%H:%M").time())
        bars = []
        # Three completed Tokyo sessions with low realised volatility.
        for day in (4, 5, 6):
            start = datetime(2026, 11, day, 0, 0, tzinfo=timezone.utc)
            for i in range(5):
                price = 100.0 * (1.0001 ** i)
                bars.append(bar(start + timedelta(minutes=5 * i), price, price * 1.0002,
                                price * 0.9998, price))
        # Current Monday session has much larger moves over the same 20-minute window.
        start = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)
        prices = [100.0, 100.25, 100.50, 100.75, 101.00]
        for i, price in enumerate(prices):
            bars.append(bar(start + timedelta(minutes=5 * i), price, price * 1.002,
                            price * 0.998, price))
        report = session_volatility_report(
            bars, [session], now=datetime(2026, 11, 9, 0, 20, tzinfo=timezone.utc),
            baseline_sessions=3, expansion_multiple=1.5, contraction_multiple=0.67,
        )[0]
        self.assertEqual(report["state"], "LIVE SESSION")
        self.assertEqual(report["regime"], "EXPANSION")
        self.assertGreater(report["ratio"], 1.5)
        self.assertEqual(report["baseline_count"], 3)


    def test_live_regime_waits_for_enough_prior_sessions(self):
        session = SessionDefinition("tokyo", "TOKYO", "Tokyo", "JP", "Asia/Tokyo",
                                    datetime.strptime("09:00", "%H:%M").time(),
                                    datetime.strptime("18:00", "%H:%M").time())
        start = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)
        bars = [bar(start + timedelta(minutes=5 * i), 100 + i, 102 + i, 99 + i, 101 + i)
                for i in range(5)]
        report = session_volatility_report(
            bars, [session], now=datetime(2026, 11, 10, 0, 20, tzinfo=timezone.utc),
            baseline_sessions=3,
        )[0]
        self.assertEqual(report["regime"], "WARMING UP")
        self.assertEqual(report["baseline_count"], 0)

    def test_no_data_is_not_reported_as_zero_volatility(self):
        session = SessionDefinition("london", "LONDON", "London", "UK", "Europe/London",
                                    datetime.strptime("08:00", "%H:%M").time(),
                                    datetime.strptime("17:00", "%H:%M").time())
        report = session_volatility_report([], [session])
        self.assertEqual(report[0]["state"], "NO DATA")
        self.assertIsNone(report[0]["realised_vol_pct"])


if __name__ == "__main__":
    unittest.main()
