"""Dynamic public-company discovery backed by Yahoo Finance search.

The market overview deliberately fetches a bounded quote board so a public page
does not create hundreds of upstream requests.  This module provides the
separate discovery layer: visitors can search by company name or ticker and
then open the existing on-demand research flow for any supported symbol.
"""

from datetime import datetime, timezone
from threading import Lock
import re
import time
from typing import Any, Dict, List

import yfinance as yf
from fastapi import APIRouter, HTTPException, Query

from market_intelligence import MARKET_BOARD


router = APIRouter(prefix="/market", tags=["Company Discovery"])

COMPANY_SEARCH_CACHE_SECONDS = 60 * 60
_company_search_cache: Dict[str, Dict[str, Any]] = {}
_company_search_lock = Lock()


def _clean_query(query: str) -> str:
    value = " ".join(str(query or "").strip().split())
    if len(value) < 2:
        raise ValueError("Enter at least two characters to search companies.")
    if len(value) > 80 or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("Invalid company search query.")
    return value


def _fallback_companies(query: str, limit: int) -> List[Dict[str, Any]]:
    needle = query.casefold()
    results: List[Dict[str, Any]] = []
    for symbol, metadata in MARKET_BOARD.items():
        if metadata.get("kind") != "company":
            continue
        name = str(metadata.get("name") or symbol)
        if needle not in symbol.casefold() and needle not in name.casefold():
            continue
        results.append({
            "symbol": symbol,
            "name": name,
            "exchange": "NSE" if symbol.endswith(".NS") else "BSE" if symbol.endswith(".BO") else "US",
            "sector": metadata.get("sector") or "Not available",
            "industry": "Not available",
            "quoteType": "EQUITY",
            "source": "FinTrack verified board",
        })
    return results[:limit]


def _normalize_company(item: Dict[str, Any]) -> Dict[str, Any] | None:
    provider_type = str(item.get("quoteType") or "").upper()
    if provider_type not in {"EQUITY", "ETF", "MUTUALFUND"}:
        return None
    symbol = str(item.get("symbol") or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9.^=&\-]{1,20}", symbol):
        return None
    name = item.get("longname") or item.get("shortname") or symbol
    return {
        "symbol": symbol,
        "name": str(name),
        "exchange": item.get("exchDisp") or item.get("exchange") or "Not available",
        "sector": item.get("sectorDisp") or item.get("sector") or "Not available",
        "industry": item.get("industryDisp") or item.get("industry") or "Not available",
        "quoteType": provider_type,
        "instrumentType": "fund" if provider_type in {"ETF", "MUTUALFUND"} or re.search(r"\bETF\b", str(name), re.IGNORECASE) else "company",
        "source": "Yahoo Finance Search",
    }


def _company_priority(item: Dict[str, Any], query: str, provider_position: int) -> tuple:
    """Keep exact matches first and prefer Indian listings for name searches."""
    normalized_query = query.casefold()
    symbol = item["symbol"].casefold()
    name = item["name"].casefold()
    exact_symbol = symbol == normalized_query
    name_match = name == normalized_query or name.startswith(f"{normalized_query} ")
    market_rank = 0 if symbol.endswith(".ns") else 1 if symbol.endswith(".bo") else 2
    return (not exact_symbol, not name_match, market_rank, provider_position)


def search_companies(query: str, limit: int = 8) -> Dict[str, Any]:
    cleaned = _clean_query(query)
    safe_limit = max(1, min(int(limit), 20))
    cache_key = f"{cleaned.casefold()}:{safe_limit}"
    now = time.time()

    with _company_search_lock:
        cached = _company_search_cache.get(cache_key)
        if cached and now - cached["createdAt"] < COMPANY_SEARCH_CACHE_SECONDS:
            return cached["value"]

    results: List[Dict[str, Any]] = []
    mode = "live"
    resolved_query = cleaned
    search_terms = [cleaned]
    without_wrong_indian_suffix = re.sub(r"\.(?:NS|BO)$", "", cleaned, flags=re.IGNORECASE).strip()
    if without_wrong_indian_suffix and without_wrong_indian_suffix.casefold() != cleaned.casefold():
        search_terms.append(without_wrong_indian_suffix)
    try:
        for search_term in search_terms:
            response = yf.Search(
                search_term,
                max_results=min(50, max(safe_limit * 3, 12)),
                news_count=0,
                lists_count=0,
                include_nav_links=False,
                include_research=False,
                timeout=15,
                raise_errors=False,
            )
            seen = set()
            candidates = []
            for provider_position, raw_item in enumerate(response.quotes or []):
                item = _normalize_company(raw_item)
                if not item or item["symbol"] in seen:
                    continue
                seen.add(item["symbol"])
                candidates.append((_company_priority(item, search_term, provider_position), item))
            candidates.sort(key=lambda candidate: candidate[0])
            results = [item for _, item in candidates[:safe_limit]]
            if results:
                resolved_query = search_term
                break
    except Exception:
        mode = "fallback"

    if not results:
        for search_term in search_terms:
            results = _fallback_companies(search_term, safe_limit)
            if results:
                resolved_query = search_term
                break
        mode = "fallback"

    payload = {
        "query": cleaned,
        "resolvedQuery": resolved_query,
        "correctionApplied": resolved_query.casefold() != cleaned.casefold(),
        "items": results,
        "count": len(results),
        "mode": mode,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "notice": "Search results identify securities; live prices load only after a company is opened.",
    }
    with _company_search_lock:
        _company_search_cache[cache_key] = {"createdAt": now, "value": payload}
    return payload


@router.get("/companies")
def get_companies(
    q: str = Query(min_length=2, max_length=80),
    limit: int = Query(default=8, ge=1, le=20),
):
    """Search public companies by ticker or company name without requiring login."""
    try:
        return search_companies(q, limit)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
