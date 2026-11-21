import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from data_gateway import (
    DataGatewayError,
    ENV_FILE_PATH,
    audit_ohlc_bars,
    compare_ohlc_datasets,
    fetch_massive_bars,
    fetch_twelve_data_bars,
    get_api_key,
    load_local_env,
    parse_massive_payload,
    parse_twelve_data_payload,
    provider_statuses,
    test_provider_connection as check_provider_connection,
)


class DataGatewayTests(unittest.TestCase):
    def test_default_dotenv_path_uses_application_data_directory(self):
        from app_paths import APP_DATA_DIR
        self.assertEqual(ENV_FILE_PATH, APP_DATA_DIR / ".env")

    def test_local_dotenv_file_loads_provider_keys(self):
        with TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "MASSIVE_API_KEY=massive-from-file\nTWELVE_DATA_API_KEY=\"twelve-from-file\"\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                self.assertTrue(load_local_env(env_file))
                self.assertEqual(get_api_key("massive"), "massive-from-file")
                self.assertEqual(get_api_key("twelve_data"), "twelve-from-file")

    def test_process_environment_overrides_local_dotenv_values(self):
        with TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("MASSIVE_API_KEY=dotenv-value\n", encoding="utf-8")
            with patch.dict(os.environ, {"MASSIVE_API_KEY": "windows-user-value"}, clear=True):
                self.assertTrue(load_local_env(env_file))
                self.assertEqual(get_api_key("massive"), "windows-user-value")

    def test_dotenv_interpolation_uses_process_environment_first(self):
        with TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "API_BASE=file.example\nAPI_URL=https://${API_BASE}/data\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"API_BASE": "user.example"}, clear=True):
                self.assertTrue(load_local_env(env_file))
                self.assertEqual(os.environ["API_URL"], "https://user.example/data")

    def test_missing_dotenv_file_is_optional(self):
        with TemporaryDirectory() as directory:
            missing_file = Path(directory) / ".env"
            self.assertFalse(load_local_env(missing_file))

    def test_provider_status_reads_environment_without_exposing_secret(self):
        with patch.dict(os.environ, {"MASSIVE_API_KEY": "secret-value"}, clear=True):
            statuses = {item.provider_id: item for item in provider_statuses()}
        self.assertTrue(statuses["massive"].credential_configured)
        self.assertFalse(statuses["twelve_data"].credential_configured)
        self.assertNotIn("secret-value", repr(statuses["massive"].to_dict()))

    def test_twelve_data_payload_normalises_utc_and_sorts(self):
        payload = {
            "meta": {"symbol": "XAU/USD", "interval": "5min", "exchange_timezone": "UTC"},
            "values": [
                {"datetime": "2026-11-12 10:10:00", "open": "100.0", "high": "102.0", "low": "99.0", "close": "101.0", "volume": "12"},
                {"datetime": "2026-11-12 10:05:00", "open": "99.0", "high": "101.0", "low": "98.0", "close": "100.0", "volume": "10"},
            ],
        }
        bars, meta = parse_twelve_data_payload(payload)
        self.assertEqual(len(bars), 2)
        self.assertLess(bars[0].timestamp, bars[1].timestamp)
        self.assertEqual(bars[0].timestamp.tzinfo, timezone.utc)
        self.assertEqual(meta["provider"], "Twelve Data")


    def test_massive_forex_metadata_identifies_bid_quotes_and_quote_count_not_volume(self):
        bars, meta = parse_massive_payload({"status": "OK", "results": [
            {"t": 1794487200000, "o": 100, "h": 102, "l": 99, "c": 101, "v": 38, "n": 38},
        ]}, asset_class="forex", symbol="C:XAUUSD")
        self.assertEqual(len(bars), 1)
        self.assertIn("Bid-price", meta["price_basis"])
        self.assertIn("Quote count", meta["volume_semantics"])

    def test_provider_parsers_report_invalid_and_duplicate_rows_removed(self):
        payload = {"meta": {"symbol": "XAU/USD", "interval": "5min"}, "values": [
            {"datetime": "2026-11-12 10:00:00", "open": "100", "high": "101", "low": "99", "close": "100"},
            {"datetime": "2026-11-12 10:00:00", "open": "100", "high": "102", "low": "99", "close": "101"},
            {"datetime": "bad", "open": "100", "high": "101", "low": "99", "close": "100"},
        ]}
        bars, meta = parse_twelve_data_payload(payload)
        self.assertEqual(len(bars), 1)
        self.assertEqual(meta["invalid_rows_skipped"], 1)
        self.assertEqual(meta["duplicate_timestamps_removed"], 1)

    def test_twelve_data_error_payload_is_rejected(self):
        with self.assertRaises(DataGatewayError):
            parse_twelve_data_payload({"status": "error", "message": "invalid symbol"})

    def test_massive_payload_handles_nanosecond_futures_timestamps(self):
        ts = int(datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc).timestamp() * 1_000_000_000)
        bars, meta = parse_massive_payload({"status": "OK", "results": [
            {"window_start": ts, "o": 100, "h": 102, "l": 99, "c": 101, "v": 30},
        ]}, asset_class="futures", symbol="ESZ6")
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].timestamp, datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(meta["price_basis"], "Exchange trades for futures aggregate bars.")

    def test_massive_payload_rejects_inconsistent_ohlc(self):
        with self.assertRaisesRegex(DataGatewayError, "no valid OHLC bars"):
            parse_massive_payload({"status": "OK", "results": [
                {"t": 1794487200000, "o": 100, "h": 90, "l": 95, "c": 99},
            ]}, asset_class="indices", symbol="I:SPX")

    def test_fetch_twelve_data_builds_utc_request_and_normalises(self):
        payload = {"values": [{"datetime": "2026-11-12 10:00:00", "open": "100", "high": "101", "low": "99", "close": "100.5"}]}
        with patch("data_gateway._request_json", return_value=payload) as request:
            bars, meta = fetch_twelve_data_bars(
                "XAU/USD", interval="5m", start_date="2026-11-10", end_date="2026-11-12", api_key="test-key"
            )
        self.assertEqual(len(bars), 1)
        self.assertEqual(meta["requested_interval"], "5m")
        self.assertIn("timezone=UTC", request.call_args.args[0])
        self.assertNotIn("outputsize", request.call_args.args[0])

    def test_fetch_massive_selects_futures_route(self):
        payload = {"status": "OK", "results": [
            {"window_start": 1794487200000000000, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 30}
        ]}
        with patch("data_gateway._request_json", return_value=payload) as request:
            bars, meta = fetch_massive_bars(
                "ESZ6", asset_class="futures", interval="5m", start_date="2026-11-10",
                end_date="2026-11-12", api_key="test-key"
            )
        self.assertEqual(len(bars), 1)
        self.assertIn("/futures/v1/aggs/ESZ6", request.call_args.args[0])
        self.assertEqual(meta["asset_class"], "futures")
        self.assertIn("sort=window_start.asc", request.call_args.args[0])

    def test_massive_pagination_follows_next_url_and_normalises_futures_fields(self):
        first = {"status": "OK", "results": [
            {"window_start": 1794487200000000000, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 30}
        ], "next_url": "/futures/v1/aggs/ESZ6?cursor=next"}
        second = {"status": "OK", "results": [
            {"window_start": 1794487500000000000, "open": 101, "high": 103, "low": 100, "close": 102, "volume": 40}
        ]}
        with patch("data_gateway._request_json", side_effect=[first, second]) as request:
            bars, meta = fetch_massive_bars(
                "ESZ6", asset_class="futures", interval="5m", start_date="2026-11-10",
                end_date="2026-11-12", api_key="test-key"
            )
        self.assertEqual(len(bars), 2)
        self.assertEqual(meta["pagination_pages"], 2)
        self.assertTrue(meta["pagination_complete"])
        self.assertIn("apiKey=test-key", request.call_args_list[1].args[0])

    def test_twelve_data_daily_naive_timestamp_uses_exchange_timezone(self):
        payload = {
            "meta": {"symbol": "AAPL", "interval": "1day", "exchange_timezone": "America/New_York"},
            "values": [{"datetime": "2026-11-12 00:00:00", "open": "100", "high": "101", "low": "99", "close": "100.5"}],
        }
        bars, _ = parse_twelve_data_payload(payload)
        self.assertEqual(bars[0].timestamp, datetime(2026, 11, 12, 5, 0, tzinfo=timezone.utc))

    def test_invalid_date_range_rejected_before_request(self):
        with patch("data_gateway._request_json") as request:
            with self.assertRaises(ValueError):
                fetch_twelve_data_bars("XAU/USD", interval="5m", start_date="2026-11-13", end_date="2026-11-12", api_key="x")
        request.assert_not_called()

    def test_connection_test_reports_provider_smoke_test_not_instrument_entitlement(self):
        # Invoke the provider request after arranging the credential in the process environment.
        with patch.dict(os.environ, {"MASSIVE_API_KEY": "masked"}, clear=True), \
             patch("data_gateway._request_json", return_value={"status": "OK", "results": []}):
            result = check_provider_connection("massive")
        self.assertTrue(result["connected"])
        self.assertIn("entitlement", result["detail"])

    def test_twelve_data_connection_test_checks_account_usage_not_symbol_entitlement(self):
        with patch.dict(os.environ, {"TWELVE_DATA_API_KEY": "masked"}, clear=True), \
             patch("data_gateway._request_json", return_value={"plan": "Basic", "credits": {"used": 1, "left": 7}}) as request:
            result = check_provider_connection("twelve_data")
        self.assertTrue(result["connected"])
        self.assertIn("one API credit", result["detail"])
        self.assertIn("/api_usage?", request.call_args.args[0])

    def test_databento_connection_is_not_claimed_until_adapter_exists(self):
        with patch.dict(os.environ, {"DATABENTO_API_KEY": "configured"}, clear=True):
            with self.assertRaisesRegex(DataGatewayError, "not enabled"):
                check_provider_connection("databento")

    def test_audit_detects_duplicate_invalid_and_gaps_without_calling_them_missing(self):
        bars = [
            {"timestamp_utc": "2026-11-12T10:00:00+00:00", "open": 100, "high": 102, "low": 99, "close": 101},
            {"timestamp_utc": "2026-11-12T10:05:00+00:00", "open": 101, "high": 103, "low": 100, "close": 102},
            {"timestamp_utc": "2026-11-12T10:05:00+00:00", "open": 101, "high": 103, "low": 100, "close": 102},
            {"timestamp_utc": "2026-11-12T10:10:00+00:00", "open": 103, "high": 102, "low": 104, "close": 101},
            {"timestamp_utc": "2026-11-12T10:30:00+00:00", "open": 102, "high": 103, "low": 101, "close": 102},
        ]
        audit = audit_ohlc_bars(bars)
        self.assertEqual(audit["valid_bars"], 3)
        self.assertEqual(audit["duplicate_timestamps"], 1)
        self.assertEqual(audit["invalid_bars"], 1)
        self.assertIn("not automatically missing", audit["gap_note"])

    def test_dataset_comparison_requires_same_canonical_symbol_and_interval(self):
        sample = [
            {"timestamp_utc": f"2026-11-12T10:{minute:02d}:00+00:00", "close": 100 + minute}
            for minute in (0, 5, 10)
        ]
        with self.assertRaisesRegex(ValueError, "canonical instrument"):
            compare_ohlc_datasets(sample, sample, left_group="XAUUSD", right_group="EURUSD", left_interval=5, right_interval=5)
        with self.assertRaisesRegex(ValueError, "same bar interval"):
            compare_ohlc_datasets(sample, sample, left_group="XAUUSD", right_group="XAUUSD", left_interval=5, right_interval=1)

    def test_dataset_comparison_computes_price_difference_and_return_correlation(self):
        base = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
        left = []
        right = []
        for index, price in enumerate((100.0, 101.0, 100.5, 102.0, 103.0)):
            stamp = (base + timedelta(minutes=index * 5)).isoformat()
            left.append({"timestamp_utc": stamp, "close": price})
            right.append({"timestamp_utc": stamp, "close": price * 1.0001})
        result = compare_ohlc_datasets(left, right, left_group="XAUUSD_SPOT", right_group="xauusd_spot", left_interval=5, right_interval=5)
        self.assertEqual(result["matched_timestamps"], 5)
        self.assertAlmostEqual(result["mean_absolute_close_difference_bps"], 1.0, places=3)
        self.assertAlmostEqual(result["matched_return_correlation"], 1.0, places=5)


if __name__ == "__main__":
    unittest.main()
