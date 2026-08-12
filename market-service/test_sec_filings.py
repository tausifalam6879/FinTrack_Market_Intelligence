import json
import os
import unittest
from unittest.mock import patch

from sec_filings import (
    discover_latest_10k,
    filing_html_to_text,
    sec_filing_support,
)


class SecFilingsTests(unittest.TestCase):
    def setUp(self):
        self.previous_user_agent = os.environ.get("SEC_USER_AGENT")
        os.environ["SEC_USER_AGENT"] = "FinTrack Tests tests@example.com"

    def tearDown(self):
        if self.previous_user_agent is None:
            os.environ.pop("SEC_USER_AGENT", None)
        else:
            os.environ["SEC_USER_AGENT"] = self.previous_user_agent

    def test_plain_us_ticker_is_eligible_when_user_agent_is_configured(self):
        support = sec_filing_support("AMZN")
        self.assertTrue(support["eligible"])
        self.assertTrue(support["supported"])
        self.assertEqual("sec-10-k-on-demand", support["mode"])
        self.assertFalse(sec_filing_support("510370.SS")["eligible"])

    @patch("sec_filings._sec_json")
    def test_latest_10k_builds_only_an_official_archive_url(self, sec_json):
        sec_json.side_effect = [
            {"fields": ["cik", "name", "ticker", "exchange"], "data": [[1018724, "AMAZON COM INC", "AMZN", "Nasdaq"]]},
            {
                "name": "AMAZON COM INC",
                "filings": {"recent": {
                    "form": ["10-Q", "10-K"],
                    "accessionNumber": ["0001018724-26-000001", "0001018724-26-000010"],
                    "filingDate": ["2026-05-01", "2026-02-06"],
                    "reportDate": ["2026-03-31", "2025-12-31"],
                    "primaryDocument": ["amzn-q1.htm", "amzn-20251231.htm"],
                }},
            },
        ]
        report = discover_latest_10k("AMZN")
        self.assertEqual("10-K", report["form"])
        self.assertEqual("2025-12-31", report["reportDate"])
        self.assertEqual(
            "https://www.sec.gov/Archives/edgar/data/1018724/000101872426000010/amzn-20251231.htm",
            report["sourceUrl"],
        )

    def test_html_parser_excludes_script_and_keeps_filing_sections(self):
        html = (
            "<html><body><h1>Item 1. Business</h1><p>Amazon operates online stores and cloud services. "
            + ("Material annual filing evidence. " * 500)
            + "</p><script>secretNoise()</script><h2>Item 1A. Risk Factors</h2>"
            + ("Competition and regulation are material risks. " * 200)
            + "</body></html>"
        ).encode()
        text = filing_html_to_text(html)
        self.assertIn("Item 1. Business", text)
        self.assertIn("Risk Factors", text)
        self.assertNotIn("secretNoise", text)


if __name__ == "__main__":
    unittest.main()
