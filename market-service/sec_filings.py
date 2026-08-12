"""Fair-access client for discovering and reading official SEC 10-K filings."""

from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import json
import os
import re
from threading import Lock
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from data_pipeline import normalize_symbol
from persistence import utc_now


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_SUBMISSIONS_ROOT = "https://data.sec.gov/submissions"
SEC_ARCHIVES_ROOT = "https://www.sec.gov/Archives/edgar/data"
SEC_MAX_HTML_BYTES = 35 * 1024 * 1024
SEC_MIN_REQUEST_INTERVAL_SECONDS = 0.15
_US_TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9-]{0,9}$")
_request_lock = Lock()
_last_request_at = 0.0
_ticker_cache: Optional[Dict[str, Dict[str, Any]]] = None
_ticker_cache_at = 0.0


def sec_user_agent() -> Optional[str]:
    value = " ".join(os.getenv("SEC_USER_AGENT", "").strip().split())
    if len(value) < 12 or "@" not in value:
        return None
    return value


def sec_filing_support(symbol: str) -> Dict[str, Any]:
    normalized = normalize_symbol(symbol)
    eligible = bool(_US_TICKER_PATTERN.fullmatch(normalized))
    configured = sec_user_agent() is not None
    return {
        "symbol": normalized,
        "eligible": eligible,
        "configured": configured,
        "supported": eligible and configured,
        "provider": "SEC EDGAR" if eligible else None,
        "mode": "sec-10-k-on-demand" if eligible and configured else "not-configured" if eligible else "not-applicable",
        "sourcePage": f"https://www.sec.gov/edgar/search/#/q={quote(normalized)}" if eligible else None,
        "message": (
            "FinTrack can discover and index the latest official SEC Form 10-K."
            if eligible and configured else
            "Set SEC_USER_AGENT to a project name and monitored contact email to enable official SEC 10-K retrieval."
            if eligible else
            "This symbol is not a plain US ticker supported by SEC ticker discovery."
        ),
    }


def _fair_access_wait() -> None:
    global _last_request_at
    with _request_lock:
        remaining = SEC_MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - _last_request_at)
        if remaining > 0:
            time.sleep(remaining)
        _last_request_at = time.monotonic()


def _sec_bytes(url: str, timeout: int = 30, max_bytes: int = SEC_MAX_HTML_BYTES) -> bytes:
    user_agent = sec_user_agent()
    if not user_agent:
        raise RuntimeError("SEC_USER_AGENT must contain a project name and monitored contact email.")
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in {"www.sec.gov", "data.sec.gov"}:
        raise ValueError("SEC retrieval rejected a non-official URL.")
    _fair_access_wait()
    request = Request(url, headers={
        "User-Agent": user_agent,
        "Accept": "application/json,text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.8",
    })
    with urlopen(request, timeout=timeout) as response:
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > max_bytes:
            raise ValueError("SEC response exceeds the configured size limit.")
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("SEC response exceeds the configured size limit.")
    return data


def _sec_json(url: str, timeout: int = 30) -> Dict[str, Any]:
    payload = json.loads(_sec_bytes(url, timeout, 20 * 1024 * 1024).decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("SEC returned an unexpected JSON response.")
    return payload


def _ticker_directory() -> Dict[str, Dict[str, Any]]:
    global _ticker_cache, _ticker_cache_at
    if _ticker_cache is not None and time.time() - _ticker_cache_at < 24 * 60 * 60:
        return _ticker_cache
    payload = _sec_json(SEC_TICKERS_URL)
    fields = payload.get("fields") or []
    rows = payload.get("data") or []
    directory: Dict[str, Dict[str, Any]] = {}
    for values in rows:
        item = dict(zip(fields, values))
        ticker = str(item.get("ticker") or "").strip().upper()
        if ticker:
            directory[ticker] = item
    if not directory:
        raise RuntimeError("SEC ticker directory was empty.")
    _ticker_cache = directory
    _ticker_cache_at = time.time()
    return directory


def _recent_filings(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    recent = ((payload.get("filings") or {}).get("recent") or {})
    columns = [key for key, value in recent.items() if isinstance(value, list)]
    count = max((len(recent[key]) for key in columns), default=0)
    return [{key: recent[key][index] if index < len(recent[key]) else None for key in columns} for index in range(count)]


def _trusted_filing_url(url: str, cik: int) -> bool:
    parsed = urlparse(url)
    expected_prefix = f"/Archives/edgar/data/{int(cik)}/"
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() == "www.sec.gov"
        and parsed.path.startswith(expected_prefix)
        and parsed.path.lower().endswith((".htm", ".html"))
    )


def discover_latest_10k(symbol: str) -> Dict[str, Any]:
    normalized = normalize_symbol(symbol)
    support = sec_filing_support(normalized)
    if not support["supported"]:
        raise ValueError(support["message"])
    company = _ticker_directory().get(normalized)
    if not company:
        raise ValueError(f"SEC ticker directory has no filer association for {normalized}.")
    cik = int(company["cik"])
    submissions = _sec_json(f"{SEC_SUBMISSIONS_ROOT}/CIK{cik:010d}.json")
    filing = next((item for item in _recent_filings(submissions) if item.get("form") == "10-K"), None)
    if not filing:
        raise ValueError(f"SEC submissions contain no recent Form 10-K for {normalized}.")
    accession = str(filing.get("accessionNumber") or "")
    primary_document = str(filing.get("primaryDocument") or "")
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.html?", primary_document, re.IGNORECASE):
        raise RuntimeError("SEC returned invalid filing path metadata.")
    accession_path = accession.replace("-", "")
    source_url = f"{SEC_ARCHIVES_ROOT}/{cik}/{accession_path}/{primary_document}"
    if not _trusted_filing_url(source_url, cik):
        raise RuntimeError("SEC filing URL failed the official-host validation.")
    return {
        "symbol": normalized,
        "companyName": str(submissions.get("name") or company.get("name") or normalized),
        "cik": cik,
        "form": "10-K",
        "accessionNumber": accession,
        "filingDate": filing.get("filingDate"),
        "reportDate": filing.get("reportDate"),
        "primaryDocument": primary_document,
        "sourceUrl": source_url,
        "filingIndexUrl": f"{SEC_ARCHIVES_ROOT}/{cik}/{accession_path}/{accession}-index.html",
        "provider": "SEC EDGAR",
        "generatedAt": utc_now(),
    }


class _FilingHTMLParser(HTMLParser):
    BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"}
    SKIP_TAGS = {"script", "style", "noscript", "svg", "ix:hidden", "ix:header"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        lowered = tag.lower()
        if lowered in self.SKIP_TAGS:
            self.skip_depth += 1
        elif not self.skip_depth and lowered in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in self.SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and lowered in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def filing_html_to_text(html_bytes: bytes) -> str:
    parser = _FilingHTMLParser()
    parser.feed(html_bytes.decode("utf-8", errors="replace"))
    lines: List[str] = []
    previous = None
    for raw_line in "".join(parser.parts).splitlines():
        line = re.sub(r"\s+", " ", unescape(raw_line)).strip()
        if len(line) < 2 or line == previous:
            continue
        lines.append(line)
        previous = line
    text = "\n".join(lines)
    if len(text) < 10_000:
        raise ValueError("SEC filing contained insufficient extractable text.")
    return text[:8_000_000]


def fetch_10k_text(report: Dict[str, Any], timeout: int = 60) -> str:
    source_url = str(report.get("sourceUrl") or "")
    cik = int(report.get("cik") or 0)
    if not _trusted_filing_url(source_url, cik):
        raise ValueError("SEC filing download rejected an untrusted URL.")
    return filing_html_to_text(_sec_bytes(source_url, timeout, SEC_MAX_HTML_BYTES))
