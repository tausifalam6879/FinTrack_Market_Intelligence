"""Trusted, on-demand discovery and ingestion of official company reports.

Only provider-owned URLs are accepted.  The public API never accepts an arbitrary
download URL, which keeps on-demand indexing useful without turning it into an
SSRF or unrestricted file-download endpoint.
"""

from __future__ import annotations

import argparse
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import re
from threading import Lock
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlencode, urlparse
from urllib.request import build_opener, HTTPCookieProcessor, Request

from data_pipeline import normalize_symbol
from persistence import Database, utc_now


NSE_ANNUAL_REPORT_PAGE = (
    "https://www.nseindia.com/companies-listing/corporate-filings-annual-reports"
)
NSE_ANNUAL_REPORT_API = "https://www.nseindia.com/api/annual-reports"
NSE_ARCHIVE_HOSTS = {"nsearchives.nseindia.com"}
DEFAULT_DOCUMENT_DIRECTORY = Path(__file__).resolve().parent / "data" / "source-documents" / "official-nse"
DEFAULT_MAX_DOWNLOAD_BYTES = 80 * 1024 * 1024
_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9&-]{1,30}$")
_LOCKS: Dict[str, Lock] = {}
_LOCKS_GUARD = Lock()


class OfficialDocumentBusyError(RuntimeError):
    """Raised when the same symbol is already being prepared in this process."""


def official_document_support(symbol: str) -> Dict[str, Any]:
    """Describe whether a symbol has a trusted automatic document provider."""
    normalized = normalize_symbol(symbol)
    supported = normalized.endswith(".NS") and bool(_SYMBOL_PATTERN.fullmatch(normalized[:-3]))
    return {
        "symbol": normalized,
        "supported": supported,
        "provider": "NSE Corporate Filings" if supported else None,
        "mode": "official-on-demand" if supported else "manual-trusted-pdf",
        "sourcePage": NSE_ANNUAL_REPORT_PAGE if supported else None,
        "message": (
            "The latest official NSE annual report can be discovered and indexed on demand."
            if supported else
            "Automatic official-report discovery currently supports NSE equity symbols ending in .NS."
        ),
    }


def _nse_symbol(symbol: str) -> str:
    support = official_document_support(symbol)
    if not support["supported"]:
        raise ValueError("Official on-demand indexing supports NSE equity symbols ending in .NS.")
    return support["symbol"][:-3]


def _nse_api_payload(nse_symbol: str, timeout: int = 30) -> Dict[str, Any]:
    page_url = f"{NSE_ANNUAL_REPORT_PAGE}?{urlencode({'symbol': nse_symbol, 'tabIndex': 'equity'})}"
    api_url = f"{NSE_ANNUAL_REPORT_API}?{urlencode({'index': 'equities', 'symbol': nse_symbol})}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": page_url,
    }
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with opener.open(Request(page_url, headers=headers), timeout=timeout) as response:
        response.read(512)
    with opener.open(Request(api_url, headers=headers), timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise RuntimeError("NSE returned an unexpected annual-report response.")
    return payload


def _is_trusted_nse_pdf(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() in NSE_ARCHIVE_HOSTS
        and parsed.path.lower().endswith(".pdf")
    )


def discover_nse_annual_reports(symbol: str, timeout: int = 30) -> List[Dict[str, Any]]:
    """Return official PDF reports for any valid NSE equity symbol."""
    normalized = normalize_symbol(symbol)
    nse_symbol = _nse_symbol(normalized)
    payload = _nse_api_payload(nse_symbol, timeout)
    reports: List[Dict[str, Any]] = []
    seen_urls = set()
    for item in payload["data"]:
        source_url = str(item.get("fileName") or "").strip()
        if not _is_trusted_nse_pdf(source_url) or source_url in seen_urls:
            continue
        seen_urls.add(source_url)
        from_year = str(item.get("fromYr") or "").strip()
        to_year = str(item.get("toYr") or "").strip()
        reporting_period = f"FY {from_year}-{to_year[-2:]}" if from_year and to_year else None
        company_name = str(item.get("companyName") or nse_symbol).strip()
        reports.append({
            "symbol": normalized,
            "companyName": company_name,
            "title": f"{company_name} Annual Report {reporting_period or ''}".strip(),
            "documentType": "annual-report",
            "reportingPeriod": reporting_period,
            "sourceUrl": source_url,
            "submissionType": str(item.get("submission_type") or "").strip() or None,
            "publishedAt": str(item.get("disseminationDateTime") or item.get("broadcast_dttm") or "").strip() or None,
            "reportedSize": item.get("attFileSize"),
            "provider": "NSE Corporate Filings",
        })
    return reports


def discover_official_documents(symbol: str, timeout: int = 30) -> Dict[str, Any]:
    support = official_document_support(symbol)
    reports = discover_nse_annual_reports(symbol, timeout) if support["supported"] else []
    return {
        **support,
        "reports": reports,
        "count": len(reports),
        "generatedAt": utc_now(),
    }


def _download_official_pdf(
    source_url: str,
    destination: Path,
    timeout: int = 90,
    max_bytes: Optional[int] = None,
) -> Path:
    if not _is_trusted_nse_pdf(source_url):
        raise ValueError("The discovered document URL is not an approved NSE PDF URL.")
    byte_limit = int(max_bytes or os.getenv("RAG_MAX_OFFICIAL_PDF_BYTES", DEFAULT_MAX_DOWNLOAD_BYTES))
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    last_error: Optional[Exception] = None
    for _attempt in range(3):
        total = 0
        first_bytes = b""
        declared_size: Optional[int] = None
        request = Request(source_url, headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
            ),
            "Accept": "application/pdf,*/*;q=0.8",
            "Referer": NSE_ANNUAL_REPORT_PAGE,
        })
        try:
            temporary.unlink(missing_ok=True)
            with build_opener().open(request, timeout=timeout) as response, temporary.open("wb") as output:
                header_size = response.headers.get("Content-Length")
                declared_size = int(header_size) if header_size else None
                if declared_size and declared_size > byte_limit:
                    raise ValueError("The official PDF exceeds the configured download limit.")
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    if not first_bytes:
                        first_bytes = block[:5]
                    total += len(block)
                    if total > byte_limit:
                        raise ValueError("The official PDF exceeds the configured download limit.")
                    output.write(block)
            if first_bytes != b"%PDF-":
                raise ValueError("The official source did not return a valid PDF header.")
            if declared_size is not None and total != declared_size:
                raise ValueError("The official PDF download was incomplete.")
            with temporary.open("rb") as downloaded:
                downloaded.seek(max(0, total - 4096))
                if b"%%EOF" not in downloaded.read():
                    raise ValueError("The official PDF download has no valid end marker.")
            temporary.replace(destination)
            return destination
        except Exception as error:
            last_error = error
            temporary.unlink(missing_ok=True)
    raise RuntimeError("The official PDF could not be downloaded completely after three attempts.") from last_error


def _symbol_lock(symbol: str) -> Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(symbol, Lock())


def prepare_latest_official_document(
    symbol: str,
    database: Optional[Database] = None,
    embedding_provider: str = "local-hashing-v1",
    document_directory: Optional[Path] = None,
    ingest_callback: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Discover, download and index the latest official report for one symbol."""
    normalized = normalize_symbol(symbol)
    _nse_symbol(normalized)
    repository = database or Database()
    repository.initialize_schema()
    lock = _symbol_lock(normalized)
    if not lock.acquire(blocking=False):
        raise OfficialDocumentBusyError(f"{normalized} is already being indexed.")
    try:
        discovery = discover_official_documents(normalized)
        if not discovery["reports"]:
            raise ValueError(f"NSE did not return a PDF annual report for {normalized}.")
        existing = repository.document_sources(normalized)
        existing_by_url = {source.get("source_url"): source for source in existing}
        latest_existing = existing_by_url.get(discovery["reports"][0]["sourceUrl"])
        if latest_existing:
            return {
                "status": "already-indexed",
                "symbol": normalized,
                "documentId": latest_existing["id"],
                "title": latest_existing["title"],
                "sourceUrl": latest_existing["source_url"],
                "pageCount": latest_existing["page_count"],
                "chunkCount": latest_existing["chunk_count"],
                "completedAt": utc_now(),
            }

        root = Path(document_directory or DEFAULT_DOCUMENT_DIRECTORY).resolve()
        errors = []
        for report in discovery["reports"][:4]:
            if report["sourceUrl"] in existing_by_url:
                source = existing_by_url[report["sourceUrl"]]
                return {
                    "status": "existing-fallback",
                    "symbol": normalized,
                    "documentId": source["id"],
                    "title": source["title"],
                    "sourceUrl": source["source_url"],
                    "pageCount": source["page_count"],
                    "chunkCount": source["chunk_count"],
                    "completedAt": utc_now(),
                    "warnings": errors,
                }
            try:
                filename = Path(urlparse(report["sourceUrl"]).path).name
                local_path = _download_official_pdf(report["sourceUrl"], root / normalized / filename)
                callback = ingest_callback
                if callback is None:
                    from document_rag import ingest_pdf
                    callback = ingest_pdf
                indexed = callback(
                    normalized,
                    local_path,
                    report["title"],
                    report["documentType"],
                    report["reportingPeriod"],
                    report["sourceUrl"],
                    embedding_provider,
                    repository,
                )
                return {"status": "indexed", "provider": report["provider"], **indexed}
            except Exception as error:
                errors.append(f"{report.get('reportingPeriod') or 'unknown period'}: {error}")
        raise RuntimeError("No discovered NSE PDF could be indexed. " + " | ".join(errors))
    finally:
        lock.release()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover and index the latest official NSE annual report for arbitrary symbols."
    )
    parser.add_argument("--symbols", nargs="+", required=True, help="Yahoo symbols such as INFY.NS TCS.NS")
    parser.add_argument("--database-url")
    parser.add_argument("--embedding-provider", default="local-hashing-v1")
    arguments = parser.parse_args()
    database = Database(arguments.database_url)
    results = []
    for symbol in arguments.symbols:
        try:
            results.append(prepare_latest_official_document(symbol, database, arguments.embedding_provider))
        except Exception as error:
            results.append({"status": "failed", "symbol": symbol, "error": str(error)})
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
