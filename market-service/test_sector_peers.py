import unittest

from market_intelligence import (
    _build_sector_peer_payload,
    _peer_region_and_suffix,
    sector_peer_intelligence,
)


class SectorPeerIntelligenceTests(unittest.TestCase):
    def test_exchange_metadata_resolves_region_without_company_allowlist(self):
        self.assertEqual(("in", ".NS"), _peer_region_and_suffix("TOTALLYNEW.NS"))
        self.assertEqual(("jp", ".T"), _peer_region_and_suffix("9999.T"))
        self.assertEqual(("us", ""), _peer_region_and_suffix("NEWUSCO"))

    def test_builder_selects_closest_same_listing_peers_and_excludes_selected_from_median(self):
        info = {
            "sector": "Technology",
            "longName": "Dynamic Selected Ltd",
            "marketCap": 100,
            "trailingPE": 30,
            "priceToBook": 6,
            "dividendYield": 1.2,
            "fiftyTwoWeekChangePercent": 20,
            "currency": "INR",
        }
        quotes = [
            {"symbol": "NEAR1.NS", "longName": "Near One", "marketCap": 90, "trailingPE": 10, "priceToBook": 2, "fiftyTwoWeekChangePercent": 5},
            {"symbol": "NEAR2.NS", "longName": "Near Two", "marketCap": 110, "trailingPE": 20, "priceToBook": 4, "fiftyTwoWeekChangePercent": 10},
            {"symbol": "NEAR3.NS", "longName": "Near Three", "marketCap": 120, "trailingPE": 30, "priceToBook": 6, "fiftyTwoWeekChangePercent": 15},
            {"symbol": "NEAR4.NS", "longName": "Near Four", "marketCap": 80, "trailingPE": 40, "priceToBook": 8, "fiftyTwoWeekChangePercent": 20},
            {"symbol": "NEAR5.NS", "longName": "Near Five", "marketCap": 125, "trailingPE": 50, "priceToBook": 10, "fiftyTwoWeekChangePercent": 25},
            {"symbol": "FARAWAY.NS", "longName": "Far Away", "marketCap": 1_000, "trailingPE": 99},
            {"symbol": "DUALLIST.BO", "longName": "Wrong Exchange", "marketCap": 101, "trailingPE": 1},
        ]

        result = _build_sector_peer_payload(
            "DYNAMIC.NS", info, quotes, region="in", suffix=".NS"
        )

        self.assertEqual("available", result["status"])
        peer_symbols = [item["symbol"] for item in result["peers"]]
        self.assertEqual(5, len(peer_symbols))
        self.assertNotIn("DUALLIST.BO", peer_symbols)
        self.assertNotIn("FARAWAY.NS", peer_symbols)
        self.assertEqual(30.0, result["peerMedians"]["trailingPE"])
        self.assertEqual("in line with peer median", result["comparison"]["trailingPE"])
        self.assertEqual(4, result["selected"]["marketCapRank"])

    def test_index_returns_not_applicable_without_provider_call(self):
        result = sector_peer_intelligence("^NSEI")
        self.assertEqual("not_applicable", result["status"])
        self.assertIn("index", result["message"])

    def test_missing_sector_returns_honest_unavailable_state(self):
        result = _build_sector_peer_payload("UNKNOWN", {}, [], region="us", suffix="")
        self.assertEqual("unavailable", result["status"])
        self.assertIn("sector classification", result["message"])


if __name__ == "__main__":
    unittest.main()
