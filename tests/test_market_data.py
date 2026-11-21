import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from market_data import (
    parse_chart_payload, OHLCBar, fetch_market_snapshot, load_market_cache, save_market_cache,
)


class MarketDataTests(unittest.TestCase):
    def test_parse_chart_payload_filters_null_and_sorts(self):
        first = int(datetime(2026, 11, 10, 14, 30, tzinfo=timezone.utc).timestamp())
        second = first + 300
        payload = {
            "chart": {"result": [{
                "meta": {"symbol": "^GSPC", "currency": "USD", "exchangeTimezoneName": "America/New_York"},
                "timestamp": [second, first, first + 600],
                "indicators": {"quote": [{
                    "open": [101, 100, None], "high": [102, 101, None],
                    "low": [100, 99, None], "close": [101.5, 100.5, None],
                    "volume": [120, 110, None],
                }]},
            }], "error": None}
        }
        bars, meta = parse_chart_payload(payload)
        self.assertEqual(len(bars), 2)
        self.assertLess(bars[0].timestamp, bars[1].timestamp)
        self.assertEqual(meta["symbol"], "^GSPC")
        self.assertEqual(meta["exchange_timezone"], "America/New_York")

    def test_rejects_empty_provider_response(self):
        with self.assertRaises(ValueError):
            parse_chart_payload({"chart": {"result": [], "error": None}})


    def test_snapshot_keeps_partial_instrument_errors(self):
        instruments = [
            {"key": "gold", "name": "GOLD", "symbol": "XAUUSD=X", "unit": "USD/oz"},
            {"key": "spx", "name": "SPX", "symbol": "^GSPC", "unit": "pts"},
        ]
        sample = [OHLCBar("2026-11-10T14:30:00+00:00", 100, 102, 99, 101, 10)]

        def fake_fetch(symbol, *, interval, range_):
            if symbol == "^GSPC" and interval == "5m":
                raise RuntimeError("intraday unavailable")
            return sample, {"symbol": symbol, "currency": "USD", "exchange_timezone": "UTC"}

        with patch("market_data.fetch_chart", side_effect=fake_fetch), patch("market_data.time.sleep"):
            snapshot = fetch_market_snapshot(instruments)
        self.assertIn("gold", snapshot["assets"])
        self.assertEqual(len(snapshot["assets"]["gold"]["intraday_bars"]), 1)
        self.assertIn("intraday unavailable", snapshot["assets"]["spx"]["error"])
        self.assertEqual(len(snapshot["assets"]["spx"]["daily_bars"]), 1)

    def test_market_cache_round_trip(self):
        payload = {"provider": "test", "fetched_at": "2026-11-10T12:00:00+00:00",
                   "assets": {"gold": {"intraday_bars": [], "daily_bars": []}}}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market_cache.json"
            save_market_cache(path, payload)
            loaded = load_market_cache(path)
        self.assertEqual(loaded, payload)

    def test_bar_round_trip(self):
        bar = OHLCBar("2026-11-10T14:30:00+00:00", 100, 102, 99, 101, 55)
        restored = OHLCBar.from_dict(bar.to_dict())
        self.assertEqual(restored, bar)


if __name__ == "__main__":
    unittest.main()
