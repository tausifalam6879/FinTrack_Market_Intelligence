import time
import unittest
from unittest.mock import patch

import market_intelligence as market


class CurrencyRateResilienceTests(unittest.TestCase):
    def setUp(self):
        market._cache.clear()

    def tearDown(self):
        market._cache.clear()

    def test_currency_payload_rejects_missing_and_zero_rates(self):
        self.assertFalse(market._currency_payload_usable({"currencies": [{"inrValue": None}, {"inrValue": 0}]}))
        self.assertTrue(market._currency_payload_usable({"currencies": [{"inrValue": 94.96}]}))

    @patch("market_intelligence.market_snapshot", side_effect=RuntimeError("provider offline"))
    @patch("market_intelligence._reference_inr_rates", return_value={})
    def test_refresh_keeps_last_usable_currency_response(self, _reference_rates, _market_snapshot):
        stale = {
            "baseCurrency": "INR",
            "currencies": [{"code": "USD", "inrValue": 94.96, "status": "available"}],
            "referenceRates": {"USD": 0.01053},
            "generatedAt": "2026-09-02T12:00:00+00:00",
        }
        market._cache["inr-currency-rates"] = {"created_at": time.time() - 3600, "value": stale}

        self.assertEqual(stale, market.inr_currency_rates(refresh=True))

    @patch("market_intelligence.market_snapshot", side_effect=RuntimeError("provider offline"))
    @patch("market_intelligence._reference_inr_rates", return_value={})
    def test_empty_provider_response_is_not_cached_as_live_data(self, _reference_rates, _market_snapshot):
        with self.assertRaisesRegex(RuntimeError, "no usable positive INR rates"):
            market.inr_currency_rates(refresh=True)

        self.assertNotIn("inr-currency-rates", market._cache)


if __name__ == "__main__":
    unittest.main()
