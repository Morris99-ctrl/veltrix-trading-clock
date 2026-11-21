import unittest

from research_engine import build_research_instrument_choices, custom_research_asset_key


class CustomResearchInstrumentTests(unittest.TestCase):
    def test_custom_asset_key_is_stable_and_namespaced(self):
        self.assertEqual(custom_research_asset_key("Spot Gold / Broker A"), "csv_spot_gold_broker_a")
        self.assertEqual(custom_research_asset_key("Spot Gold / Broker A"), "csv_spot_gold_broker_a")

    def test_blank_custom_asset_name_is_rejected(self):
        with self.assertRaises(ValueError):
            custom_research_asset_key("  !!!  ")

    def test_broker_csv_dataset_is_added_to_selector(self):
        builtins = [
            {"key": "gold_spot", "name": "SPOT GOLD", "symbol": "XAUUSD=X"},
            {"key": "spx_cash", "name": "S&P 500 CASH", "symbol": "^GSPC"},
        ]
        datasets = {
            "csv_spot_gold_broker_a": {
                "name": "SPOT GOLD · BROKER A", "symbol": "",
                "source": "Broker CSV · XAUUSD_M5.csv", "bars": [{"timestamp": "2026-01-01T00:00:00+00:00"}],
            }
        }
        labels, mapping = build_research_instrument_choices(builtins, datasets)
        self.assertIn("SPOT GOLD · XAUUSD=X", labels)
        self.assertIn("SPOT GOLD · BROKER A · BROKER CSV", labels)
        self.assertEqual(mapping["SPOT GOLD · BROKER A · BROKER CSV"], "csv_spot_gold_broker_a")

    def test_builtin_dataset_is_not_duplicated(self):
        builtins = [{"key": "gold_spot", "name": "SPOT GOLD", "symbol": "XAUUSD=X"}]
        datasets = {"gold_spot": {"name": "SPOT GOLD", "source": "Broker CSV", "bars": [{"close": 1}]}}
        labels, mapping = build_research_instrument_choices(builtins, datasets)
        self.assertEqual(labels, ["SPOT GOLD · XAUUSD=X"])
        self.assertEqual(mapping[labels[0]], "gold_spot")

    def test_empty_custom_datasets_are_not_offered(self):
        labels, mapping = build_research_instrument_choices(
            [], {"csv_empty": {"name": "Empty", "source": "Broker CSV", "bars": []}}
        )
        self.assertEqual(labels, [])
        self.assertEqual(mapping, {})


if __name__ == "__main__":
    unittest.main()
