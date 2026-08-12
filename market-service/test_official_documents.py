import unittest
from unittest.mock import patch

from official_documents import (
    _is_trusted_nse_pdf,
    discover_nse_annual_reports,
    official_document_support,
)


class OfficialDocumentsTests(unittest.TestCase):
    def test_support_is_dynamic_for_valid_nse_symbols(self):
        self.assertTrue(official_document_support("INFY.NS")["supported"])
        self.assertTrue(official_document_support("M&M.NS")["supported"])
        self.assertFalse(official_document_support("AAPL")["supported"])

    def test_only_official_nse_pdf_urls_are_trusted(self):
        self.assertTrue(_is_trusted_nse_pdf(
            "https://nsearchives.nseindia.com/annual_reports/AR_123_INFY.pdf"
        ))
        self.assertFalse(_is_trusted_nse_pdf("https://example.com/report.pdf"))
        self.assertFalse(_is_trusted_nse_pdf(
            "https://nsearchives.nseindia.com/annual_reports/archive.zip"
        ))

    @patch("official_documents._nse_api_payload")
    def test_discovery_filters_untrusted_and_legacy_zip_files(self, payload):
        payload.return_value = {"data": [
            {
                "companyName": "Infosys Limited",
                "fromYr": "2025",
                "toYr": "2026",
                "submission_type": "New",
                "fileName": "https://nsearchives.nseindia.com/annual_reports/AR_INFY_2026.pdf",
            },
            {"fileName": "https://nsearchives.nseindia.com/annual_reports/old.zip"},
            {"fileName": "https://attacker.example/report.pdf"},
        ]}

        reports = discover_nse_annual_reports("infy.ns")

        self.assertEqual(1, len(reports))
        self.assertEqual("INFY.NS", reports[0]["symbol"])
        self.assertEqual("FY 2025-26", reports[0]["reportingPeriod"])
        self.assertIn("Infosys Limited", reports[0]["title"])


if __name__ == "__main__":
    unittest.main()
