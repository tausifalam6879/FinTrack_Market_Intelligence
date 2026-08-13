import unittest
from datetime import datetime, timezone

from market_intelligence import _news_intelligence, _normalize_news_item


class NewsIntelligenceTests(unittest.TestCase):
    @staticmethod
    def _article(title, publisher, published_at):
        return _normalize_news_item({
            "content": {
                "title": title,
                "provider": {"displayName": publisher},
                "pubDate": published_at,
                "canonicalUrl": {"url": "https://example.com/article"},
            }
        })

    def test_headline_evidence_builds_distribution_sources_themes_and_freshness(self):
        articles = [
            self._article("Acme beats earnings forecast with record profit", "Wire One", "2026-08-14T08:00:00Z"),
            self._article("Acme faces lawsuit risk after weak sales", "Wire Two", "2026-08-13T09:00:00Z"),
            self._article("Acme launches AI cloud platform", "Wire Three", "2026-08-13T07:00:00Z"),
            self._article("Acme announces partnership deal", "Wire One", "2026-08-12T10:00:00Z"),
        ]

        result = _news_intelligence(
            articles,
            now=datetime(2026, 8, 14, 12, tzinfo=timezone.utc),
        )

        self.assertEqual("available", result["status"])
        self.assertEqual(4, result["articleCount"])
        self.assertEqual({"positive": 1, "mixed/neutral": 2, "negative": 1}, result["distribution"])
        self.assertEqual(3, result["sourceCount"])
        self.assertEqual("moderate", result["coverage"])
        self.assertEqual("fresh", result["freshness"])
        self.assertEqual("Earnings & outlook", result["themes"][0]["theme"])
        self.assertEqual(3, len(result["dailyTone"]))

    def test_normalized_article_exposes_transparent_keyword_basis(self):
        result = self._article(
            "Company profit beats forecast despite tariff risk",
            "Evidence Wire",
            "2026-08-14T08:00:00Z",
        )

        self.assertEqual(["beats", "profit"], result["sentimentBasis"]["positiveTerms"])
        self.assertEqual(["risk", "tariff"], result["sentimentBasis"]["negativeTerms"])
        self.assertEqual("mixed/neutral", result["sentimentLabel"])
        self.assertIn("Earnings & outlook", result["themes"])
        self.assertIn("Regulation & legal", result["themes"])

    def test_empty_provider_feed_does_not_invent_news_conclusion(self):
        result = _news_intelligence([])

        self.assertEqual("unavailable", result["status"])
        self.assertEqual(0, result["articleCount"])
        self.assertEqual([], result["themes"])
        self.assertIn("does not invent", result["disclaimer"])


if __name__ == "__main__":
    unittest.main()
