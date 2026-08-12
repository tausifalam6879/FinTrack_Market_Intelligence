import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from document_rag import (
    LOCAL_EMBEDDING_PROVIDER,
    OfficialDocumentRequest,
    answer_document_question,
    chunk_pages,
    ingest_pdf,
    ingest_text_evidence,
    document_preparation_support,
    list_documents,
    prepare_sec_10k_document,
    prepare_documents,
)
from persistence import Database


class DocumentRagTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        root = Path(self.temp_directory.name)
        self.database = Database(f"sqlite:///{root / 'rag.db'}")
        self.database.initialize_schema()
        self.pdf_path = root / "annual-report.pdf"
        self.pdf_path.write_bytes(b"%PDF-1.4 controlled test document")
        os.environ["RAG_USE_LLM"] = "false"

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_page_chunking_preserves_page_numbers_and_overlap(self):
        page_text = " ".join(f"word{index}" for index in range(260))
        chunks = chunk_pages([(7, page_text)], chunk_words=100, overlap_words=20)
        self.assertGreaterEqual(len(chunks), 3)
        self.assertTrue(all(chunk["page_number"] == 7 for chunk in chunks))
        self.assertIn("word80", chunks[0]["text"])
        self.assertIn("word80", chunks[1]["text"])

    def test_pdf_ingestion_and_retrieval_return_page_citations(self):
        page_one = Mock()
        page_one.extract_text.return_value = (
            "Reliance Retail revenue grew during the reporting period. The retail business expanded its "
            "store network and improved digital commerce operations. " * 8
        )
        page_two = Mock()
        page_two.extract_text.return_value = (
            "The company reported debt and finance cost details. Net debt was managed through operating "
            "cash flow and disciplined capital allocation. " * 8
        )
        reader = Mock()
        reader.pages = [page_one, page_two]

        with patch("document_rag.PdfReader", return_value=reader):
            result = ingest_pdf(
                "RELIANCE.NS", self.pdf_path, "Reliance Integrated Annual Report 2024-25",
                reporting_period="FY 2024-25", source_url="https://example.test/annual-report.pdf",
                embedding_provider=LOCAL_EMBEDDING_PROVIDER, database=self.database,
            )

        documents = list_documents("RELIANCE.NS", self.database)
        answer = answer_document_question(
            "RELIANCE.NS", "What does the report say about debt and finance cost?", 3, self.database
        )

        self.assertEqual(2, result["pageCount"])
        self.assertGreater(result["chunkCount"], 0)
        self.assertEqual(1, documents["count"])
        self.assertEqual("retrieval_fallback", answer["generationMode"])
        self.assertGreater(len(answer["citations"]), 0)
        self.assertEqual(2, answer["citations"][0]["page"])
        self.assertIn("[S1 p.2]", answer["answer"])

    def test_symbol_without_documents_returns_honest_empty_answer(self):
        answer = answer_document_question("INFY.NS", "What is the revenue?", 3, self.database)
        self.assertEqual([], answer["citations"])
        self.assertIn("No ingested company document", answer["answer"])

    def test_global_symbol_supports_market_evidence_instead_of_fake_annual_report(self):
        support = document_preparation_support("510370.SS")
        self.assertTrue(support["supported"])
        self.assertTrue(support["autoPrepare"])
        self.assertEqual("market-evidence-on-demand", support["mode"])
        self.assertEqual("market-profile-snapshot", support["evidenceType"])

    def test_text_evidence_is_retrievable_with_source_citation(self):
        result = ingest_text_evidence(
            "CSCO",
            "Cisco Market Evidence Snapshot",
            (
                "Cisco Systems is a technology company listed on NASDAQ. The provider profile identifies "
                "networking infrastructure and security products. Latest market evidence includes an observed "
                "one-year price range and states that this snapshot is not an audited annual report. " * 4
            ),
            "market-profile",
            "Snapshot 2026-08-12",
            "https://finance.yahoo.com/quote/CSCO",
            database=self.database,
        )
        answer = answer_document_question("CSCO", "What kind of company is Cisco?", 3, self.database)

        self.assertEqual("CSCO", result["symbol"])
        self.assertGreater(result["chunkCount"], 0)
        self.assertGreater(len(answer["citations"]), 0)
        self.assertEqual("https://finance.yahoo.com/quote/CSCO", answer["citations"][0]["sourceUrl"])

    @patch("document_rag.fetch_10k_text")
    @patch("document_rag.discover_latest_10k")
    def test_sec_10k_is_indexed_as_official_filing_evidence(self, discover, fetch):
        source_url = "https://www.sec.gov/Archives/edgar/data/1018724/000101872426000010/amzn-20251231.htm"
        discover.return_value = {
            "symbol": "AMZN",
            "companyName": "AMAZON COM INC",
            "reportDate": "2025-12-31",
            "filingDate": "2026-02-06",
            "sourceUrl": source_url,
        }
        fetch.return_value = (
            "Item 1. Business Amazon operates online stores and cloud services. "
            "Item 1A. Risk Factors Competition, regulation and cybersecurity are material risks. " * 80
        )

        result = prepare_sec_10k_document("AMZN", self.database)
        documents = list_documents("AMZN", self.database)

        self.assertEqual("SEC EDGAR", result["provider"])
        self.assertEqual(1, documents["count"])
        self.assertEqual("sec-10-k", documents["items"][0]["documentType"])
        self.assertEqual(source_url, documents["items"][0]["sourceUrl"])

    @patch("document_rag.prepare_market_evidence_document")
    @patch("document_rag.prepare_sec_10k_document", side_effect=RuntimeError("SEC returned 403"))
    def test_sec_failure_returns_market_profile_fallback(self, _prepare_sec, prepare_market):
        prepare_market.return_value = {
            "status": "indexed",
            "provider": "Yahoo Finance public market data",
            "symbol": "AMZN",
            "documentId": "profile-1",
        }
        with patch.dict(os.environ, {"SEC_USER_AGENT": "FinTrack Tests tests@example.com"}):
            result = prepare_documents(OfficialDocumentRequest(symbol="AMZN"))

        self.assertEqual("fallback-indexed", result["status"])
        self.assertEqual("SEC EDGAR", result["preferredProvider"])
        self.assertIn("SEC returned 403", result["fallbackReason"])


if __name__ == "__main__":
    unittest.main()
