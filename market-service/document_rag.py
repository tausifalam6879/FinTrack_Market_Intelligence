"""Page-cited company document RAG with optional Gemini semantic embeddings."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen
from uuid import uuid4

import numpy as np
import yfinance as yf
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from pypdf import PdfReader
from sklearn.feature_extraction.text import HashingVectorizer

from data_pipeline import normalize_symbol
from market_intelligence import _provider_chat
from official_documents import (
    OfficialDocumentBusyError,
    discover_official_documents,
    official_document_support,
    prepare_latest_official_document,
)
from persistence import Database, utc_now
from sec_filings import discover_latest_10k, fetch_10k_text, sec_filing_support


router = APIRouter(prefix="/market", tags=["Company Document RAG"])
LOCAL_EMBEDDING_PROVIDER = "local-hashing-v1"
GEMINI_EMBEDDING_PROVIDER = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768
MARKET_EVIDENCE_VERSION = "evidence-v2"
_MARKET_EVIDENCE_LOCKS: Dict[str, Lock] = {}
_MARKET_EVIDENCE_LOCKS_GUARD = Lock()


class DocumentQuestion(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    question: str = Field(min_length=3, max_length=1200)
    limit: int = Field(default=5, ge=1, le=8)


class OfficialDocumentRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def chunk_pages(
    pages: Iterable[tuple[int, str]], chunk_words: int = 180, overlap_words: int = 35
) -> List[Dict[str, Any]]:
    if chunk_words < 40 or overlap_words < 0 or overlap_words >= chunk_words:
        raise ValueError("Invalid document chunking configuration.")
    chunks: List[Dict[str, Any]] = []
    step = chunk_words - overlap_words
    for page_number, raw_text in pages:
        words = _clean_text(raw_text).split()
        if not words:
            continue
        page_chunk_index = 0
        for start in range(0, len(words), step):
            text = " ".join(words[start:start + chunk_words])
            if len(text) < 80:
                continue
            chunks.append({
                "page_number": int(page_number),
                "chunk_index": page_chunk_index,
                "text": text,
            })
            page_chunk_index += 1
            if start + chunk_words >= len(words):
                break
    if not chunks:
        raise ValueError("The PDF contains no extractable text. Scanned PDFs require OCR before ingestion.")
    return chunks


def _local_embeddings(texts: List[str]) -> np.ndarray:
    vectorizer = HashingVectorizer(
        n_features=EMBEDDING_DIMENSIONS,
        alternate_sign=False,
        norm="l2",
        ngram_range=(1, 2),
        lowercase=True,
    )
    return vectorizer.transform(texts).toarray().astype(np.float32)


def _gemini_embeddings(texts: List[str]) -> np.ndarray:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured for semantic embeddings.")
    timeout = max(10, int(os.getenv("RAG_EMBEDDING_TIMEOUT_MS", "30000")) // 1000)
    vectors: List[List[float]] = []
    endpoint = "https://generativelanguage.googleapis.com/v1beta/openai/embeddings"
    for start in range(0, len(texts), 20):
        batch = texts[start:start + 20]
        body = json.dumps({
            "model": GEMINI_EMBEDDING_PROVIDER,
            "input": batch,
            "dimensions": EMBEDDING_DIMENSIONS,
        }).encode("utf-8")
        request = UrlRequest(endpoint, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }, method="POST")
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise RuntimeError("Gemini embedding request failed.") from error
        ordered = sorted(payload.get("data") or [], key=lambda item: item.get("index", 0))
        vectors.extend(item.get("embedding") or [] for item in ordered)
    if len(vectors) != len(texts) or any(len(vector) != EMBEDDING_DIMENSIONS for vector in vectors):
        raise RuntimeError("Gemini returned an invalid embedding batch.")
    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)


def embed_texts(texts: List[str], provider: str) -> np.ndarray:
    if provider == GEMINI_EMBEDDING_PROVIDER:
        return _gemini_embeddings(texts)
    if provider == LOCAL_EMBEDDING_PROVIDER:
        return _local_embeddings(texts)
    raise ValueError(f"Unsupported embedding provider: {provider}")


def ingest_pdf(
    symbol: str,
    pdf_path: Path,
    title: str,
    document_type: str = "annual-report",
    reporting_period: Optional[str] = None,
    source_url: Optional[str] = None,
    embedding_provider: str = LOCAL_EMBEDDING_PROVIDER,
    database: Optional[Database] = None,
) -> Dict[str, Any]:
    normalized = normalize_symbol(symbol)
    path = Path(pdf_path).resolve()
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise ValueError("A readable local PDF file is required.")
    clean_title = _clean_text(title)
    if len(clean_title) < 3 or len(clean_title) > 200:
        raise ValueError("Document title must contain 3-200 characters.")
    file_bytes = path.read_bytes()
    file_sha256 = hashlib.sha256(file_bytes).hexdigest()
    reader = PdfReader(str(path))
    pages = [(index + 1, page.extract_text() or "") for index, page in enumerate(reader.pages)]
    chunks = chunk_pages(pages)
    matrix = embed_texts([chunk["text"] for chunk in chunks], embedding_provider)
    document_id = hashlib.sha256(
        f"{normalized}|{file_sha256}|{embedding_provider}".encode("utf-8")
    ).hexdigest()[:32]
    stored_chunks = [{
        **chunk,
        "id": f"{document_id}:{chunk['page_number']}:{chunk['chunk_index']}",
        "embedding": matrix[index].tolist(),
    } for index, chunk in enumerate(chunks)]
    repository = database or Database()
    repository.initialize_schema()
    repository.replace_document({
        "id": document_id,
        "symbol": normalized,
        "title": clean_title,
        "document_type": _clean_text(document_type) or "document",
        "reporting_period": _clean_text(reporting_period or "") or None,
        "source_url": _clean_text(source_url or "") or None,
        "file_sha256": file_sha256,
        "page_count": len(reader.pages),
        "embedding_provider": embedding_provider,
        "created_at": utc_now(),
    }, stored_chunks)
    return {
        "documentId": document_id,
        "symbol": normalized,
        "title": clean_title,
        "pageCount": len(reader.pages),
        "chunkCount": len(stored_chunks),
        "embeddingProvider": embedding_provider,
        "fileSha256": file_sha256,
        "sourceUrl": source_url,
        "ingestedAt": utc_now(),
    }


def ingest_text_evidence(
    symbol: str,
    title: str,
    text: str,
    document_type: str,
    reporting_period: Optional[str],
    source_url: str,
    embedding_provider: str = LOCAL_EMBEDDING_PROVIDER,
    database: Optional[Database] = None,
) -> Dict[str, Any]:
    """Index a cited provider evidence snapshot when no annual-report PDF exists."""
    normalized = normalize_symbol(symbol)
    clean_title = _clean_text(title)
    clean_text = _clean_text(text)
    if len(clean_title) < 3 or len(clean_title) > 200:
        raise ValueError("Evidence title must contain 3-200 characters.")
    if len(clean_text) < 80:
        raise ValueError("The market provider returned insufficient evidence to index.")
    chunks = chunk_pages([(1, clean_text)])
    matrix = embed_texts([chunk["text"] for chunk in chunks], embedding_provider)
    content_sha256 = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()
    document_id = hashlib.sha256(
        f"{normalized}|{content_sha256}|{embedding_provider}".encode("utf-8")
    ).hexdigest()[:32]
    stored_chunks = [{
        **chunk,
        "id": f"{document_id}:1:{chunk['chunk_index']}",
        "embedding": matrix[index].tolist(),
    } for index, chunk in enumerate(chunks)]
    repository = database or Database()
    repository.initialize_schema()
    repository.replace_document({
        "id": document_id,
        "symbol": normalized,
        "title": clean_title,
        "document_type": _clean_text(document_type) or "market-evidence",
        "reporting_period": _clean_text(reporting_period or "") or None,
        "source_url": source_url,
        "file_sha256": content_sha256,
        "page_count": 1,
        "embedding_provider": embedding_provider,
        "created_at": utc_now(),
    }, stored_chunks)
    return {
        "documentId": document_id,
        "symbol": normalized,
        "title": clean_title,
        "pageCount": 1,
        "chunkCount": len(stored_chunks),
        "embeddingProvider": embedding_provider,
        "fileSha256": content_sha256,
        "sourceUrl": source_url,
        "ingestedAt": utc_now(),
    }


def document_preparation_support(symbol: str) -> Dict[str, Any]:
    normalized = normalize_symbol(symbol)
    official = official_document_support(normalized)
    if official["supported"]:
        return {
            **official,
            "autoPrepare": False,
            "evidenceType": "official-annual-report",
        }
    if normalized.startswith("^"):
        return {
            **official,
            "supported": False,
            "mode": "index-not-applicable",
            "autoPrepare": False,
            "message": "An index has no company annual report. Use its market analytics and research agent instead.",
        }
    sec = sec_filing_support(normalized)
    if sec["supported"]:
        return {
            **sec,
            "supported": True,
            "autoPrepare": True,
            "evidenceType": "official-sec-10-k",
            "fallbackProvider": "Yahoo Finance public market data",
            "message": "FinTrack will try the latest official SEC Form 10-K and use a cited market profile if SEC is unavailable.",
        }
    return {
        "symbol": normalized,
        "supported": True,
        "provider": "Yahoo Finance public market data",
        "mode": "market-evidence-on-demand",
        "autoPrepare": True,
        "evidenceType": "market-profile-snapshot",
        "sourcePage": f"https://finance.yahoo.com/quote/{quote(normalized, safe='')}",
        "message": (
            "No supported official filing provider exists for this exchange. "
            "FinTrack can automatically index a cited market-profile evidence snapshot instead."
        ),
    }


def _market_evidence_lock(symbol: str) -> Lock:
    with _MARKET_EVIDENCE_LOCKS_GUARD:
        return _MARKET_EVIDENCE_LOCKS.setdefault(symbol, Lock())


def _display_value(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, float):
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return f"{value:,}"
    return _clean_text(str(value))


def prepare_market_evidence_document(
    symbol: str,
    database: Optional[Database] = None,
    embedding_provider: str = LOCAL_EMBEDDING_PROVIDER,
) -> Dict[str, Any]:
    """Build a lightweight RAG source for a globally listed company or fund."""
    normalized = normalize_symbol(symbol)
    if normalized.startswith("^"):
        raise ValueError("Company-document RAG is not applicable to an index.")
    repository = database or Database()
    repository.initialize_schema()
    lock = _market_evidence_lock(normalized)
    with lock:
        period = f"Snapshot {datetime.now(timezone.utc).date().isoformat()} · {MARKET_EVIDENCE_VERSION}"
        existing = [
            item for item in repository.document_sources(normalized)
            if item.get("document_type") == "market-profile" and item.get("reporting_period") == period
        ]
        if existing:
            source = existing[0]
            return {
                "status": "already-indexed",
                "symbol": normalized,
                "documentId": source["id"],
                "title": source["title"],
                "sourceUrl": source.get("source_url"),
                "pageCount": source["page_count"],
                "chunkCount": source["chunk_count"],
                "completedAt": utc_now(),
            }

        ticker = yf.Ticker(normalized)
        try:
            info = ticker.get_info() or {}
        except Exception:
            info = {}
        try:
            history = ticker.history(period="1y", interval="1d", auto_adjust=False)
        except Exception:
            history = None
        if not info and (history is None or history.empty):
            raise ValueError("The market provider returned no verifiable profile evidence for this symbol.")

        name = _clean_text(info.get("longName") or info.get("shortName") or normalized)
        provider_quote_type = _clean_text(info.get("quoteType") or "market security").upper()
        fund_markers = " ".join(_clean_text(info.get(key) or "") for key in (
            "longName", "shortName", "fundFamily", "category"
        ))
        is_fund = (
            provider_quote_type in {"ETF", "MUTUALFUND"}
            or bool(re.search(r"\b(?:ETF|FUND)\b", fund_markers, re.IGNORECASE))
            or info.get("fundFamily") is not None
        )
        instrument_type = "ETF or investment fund" if is_fund else provider_quote_type
        evidence = [
            f"Evidence source: Yahoo Finance public market data for {normalized}.",
            f"Instrument name: {name}.",
            f"Instrument classification: {instrument_type}.",
            f"Provider quote type: {provider_quote_type}.",
            f"Exchange: {_display_value(info.get('exchange') or info.get('fullExchangeName')) or 'not supplied'}.",
            f"Currency: {_display_value(info.get('currency')) or 'not supplied'}.",
            f"Country: {_display_value(info.get('country')) or 'not supplied'}.",
            f"Sector: {_display_value(info.get('sector')) or 'not supplied'}.",
            f"Industry: {_display_value(info.get('industry')) or 'not supplied'}.",
        ]
        summary = _clean_text(info.get("longBusinessSummary") or info.get("description") or "")
        if summary:
            evidence.append(f"Provider profile summary: {summary}")
        field_labels = {
            "marketCap": "Market capitalization",
            "enterpriseValue": "Enterprise value",
            "trailingPE": "Trailing P/E",
            "forwardPE": "Forward P/E",
            "priceToBook": "Price-to-book ratio",
            "trailingEps": "Trailing EPS",
            "dividendYield": "Dividend yield",
            "beta": "Beta",
            "totalAssets": "Fund total assets",
            "navPrice": "Fund NAV price",
            "fundFamily": "Fund family",
            "category": "Fund category",
            "threeYearAverageReturn": "Three-year average return",
            "fiveYearAverageReturn": "Five-year average return",
        }
        for key, label in field_labels.items():
            value = _display_value(info.get(key))
            if value is not None:
                evidence.append(f"{label}: {value}.")
        if history is not None and not history.empty and "Close" in history:
            close = history["Close"].dropna()
            if not close.empty:
                evidence.extend([
                    f"Latest available close: {_display_value(float(close.iloc[-1]))}.",
                    f"One-year observed low close: {_display_value(float(close.min()))}.",
                    f"One-year observed high close: {_display_value(float(close.max()))}.",
                    f"Price evidence date: {close.index[-1].strftime('%Y-%m-%d')}.",
                ])
        evidence.append(
            "Evidence limitation: this is a provider market-profile snapshot, not an audited annual report "
            "and not an investment recommendation. Unavailable fields are not inferred."
        )
        indexed = ingest_text_evidence(
            normalized,
            f"{name} Market Evidence Snapshot",
            " ".join(evidence),
            "market-profile",
            period,
            f"https://finance.yahoo.com/quote/{quote(normalized, safe='')}",
            embedding_provider,
            repository,
        )
        repository.delete_documents(normalized, "market-profile", indexed["documentId"])
        return {"status": "indexed", "provider": "Yahoo Finance public market data", **indexed}


def prepare_sec_10k_document(
    symbol: str,
    database: Optional[Database] = None,
    embedding_provider: str = LOCAL_EMBEDDING_PROVIDER,
) -> Dict[str, Any]:
    normalized = normalize_symbol(symbol)
    repository = database or Database()
    repository.initialize_schema()
    report = discover_latest_10k(normalized)
    existing = [
        source for source in repository.document_sources(normalized)
        if source.get("source_url") == report["sourceUrl"]
    ]
    if existing:
        source = existing[0]
        return {
            "status": "already-indexed",
            "provider": "SEC EDGAR",
            "symbol": normalized,
            "documentId": source["id"],
            "title": source["title"],
            "sourceUrl": source.get("source_url"),
            "pageCount": source["page_count"],
            "chunkCount": source["chunk_count"],
            "completedAt": utc_now(),
        }
    filing_text = fetch_10k_text(report)
    indexed = ingest_text_evidence(
        normalized,
        f"{report['companyName']} SEC Form 10-K",
        filing_text,
        "sec-10-k",
        report.get("reportDate") or report.get("filingDate"),
        report["sourceUrl"],
        embedding_provider,
        repository,
    )
    repository.delete_documents(normalized, "sec-10-k", indexed["documentId"])
    return {"status": "indexed", "provider": "SEC EDGAR", "filing": report, **indexed}


def list_documents(symbol: str, database: Optional[Database] = None) -> Dict[str, Any]:
    normalized = normalize_symbol(symbol)
    repository = database or Database()
    repository.initialize_schema()
    items = repository.document_sources(normalized)
    preparation = document_preparation_support(normalized)
    document_types = {item.get("document_type") for item in items}
    if preparation.get("mode") == "sec-10-k-on-demand":
        preparation["needsPreparation"] = "sec-10-k" not in document_types
    elif preparation.get("mode") == "market-evidence-on-demand":
        preparation["needsPreparation"] = "market-profile" not in document_types
    elif preparation.get("mode") == "official-on-demand":
        preparation["needsPreparation"] = "annual-report" not in document_types
    else:
        preparation["needsPreparation"] = False
    return {
        "symbol": normalized,
        "items": [{
            "id": item["id"],
            "title": item["title"],
            "documentType": item["document_type"],
            "reportingPeriod": item.get("reporting_period"),
            "sourceUrl": item.get("source_url"),
            "pageCount": item["page_count"],
            "chunkCount": item["chunk_count"],
            "embeddingProvider": item["embedding_provider"],
            "createdAt": str(item["created_at"]),
        } for item in items],
        "count": len(items),
        "preparation": preparation,
        "generatedAt": utc_now(),
    }


def retrieve_chunks(
    symbol: str, question: str, limit: int = 5, database: Optional[Database] = None
) -> Dict[str, Any]:
    normalized = normalize_symbol(symbol)
    clean_question = _clean_text(question)
    if len(clean_question) < 3:
        raise ValueError("Ask a document question containing at least three characters.")
    repository = database or Database()
    repository.initialize_schema()
    sources = repository.document_sources(normalized)
    if not sources:
        return {"symbol": normalized, "question": clean_question, "matches": [], "provider": None}

    providers = [source["embedding_provider"] for source in sources]
    provider = GEMINI_EMBEDDING_PROVIDER if GEMINI_EMBEDDING_PROVIDER in providers else providers[0]
    rows = repository.document_chunks(normalized, provider)
    if not rows:
        return {"symbol": normalized, "question": clean_question, "matches": [], "provider": provider}
    query_vector = embed_texts([clean_question], provider)[0]
    matrix = np.asarray([json.loads(row["embedding_json"]) for row in rows], dtype=np.float32)
    matrix_norms = np.linalg.norm(matrix, axis=1)
    scores = matrix @ query_vector / np.maximum(matrix_norms * np.linalg.norm(query_vector), 1e-12)
    ranked = np.argsort(scores)[::-1][:max(1, min(int(limit), 8))]
    matches = []
    for rank, row_index in enumerate(ranked, start=1):
        row = rows[int(row_index)]
        text = row["text"]
        matches.append({
            "citation": f"S{rank}",
            "documentId": row["document_id"],
            "title": row["title"],
            "documentType": row["document_type"],
            "reportingPeriod": row.get("reporting_period"),
            "sourceUrl": row.get("source_url"),
            "page": row["page_number"],
            "score": round(float(scores[int(row_index)]), 4),
            "text": text,
            "snippet": text[:520] + ("…" if len(text) > 520 else ""),
        })
    return {"symbol": normalized, "question": clean_question, "matches": matches, "provider": provider}


def _deterministic_rag_answer(question: str, matches: List[Dict[str, Any]]) -> str:
    if not matches:
        return "No ingested company document contains retrievable evidence for this question."
    lines = ["Retrieved document evidence:"]
    for match in matches[:4]:
        lines.append(f"- [{match['citation']} p.{match['page']}] {match['snippet']}")
    lines.append("\nThis is document retrieval evidence, not an investment recommendation.")
    return "\n".join(lines)


def answer_document_question(
    symbol: str, question: str, limit: int = 5, database: Optional[Database] = None
) -> Dict[str, Any]:
    retrieval = retrieve_chunks(symbol, question, limit, database)
    matches = retrieval["matches"]
    answer = _deterministic_rag_answer(question, matches)
    generation_mode = "retrieval_fallback"
    if matches and os.getenv("RAG_USE_LLM", "false").strip().lower() in {"1", "true", "yes"}:
        evidence = "\n\n".join(
            f"[{item['citation']} p.{item['page']}] {item['text']}" for item in matches
        )
        allowed = {f"[{item['citation']} p.{item['page']}]" for item in matches}
        try:
            candidate, provider = _provider_chat([
                {"role": "system", "content": (
                    "Answer only from the supplied document evidence. Cite every factual claim using the exact "
                    "citation tokens supplied. If evidence is insufficient, say so. Do not give investment advice."
                )},
                {"role": "user", "content": f"Question: {question}\n\nEvidence:\n{evidence}"},
            ])
            used = set(re.findall(r"\[S\d+ p\.\d+\]", candidate))
            if candidate.strip() and used and used.issubset(allowed):
                answer = candidate.strip()
                generation_mode = f"{provider}_grounded"
        except RuntimeError:
            pass
    return {
        "symbol": retrieval["symbol"],
        "question": retrieval["question"],
        "answer": answer,
        "generationMode": generation_mode,
        "embeddingProvider": retrieval["provider"],
        "citations": [{key: match[key] for key in (
            "citation", "documentId", "title", "reportingPeriod", "sourceUrl", "page", "score", "snippet"
        )} for match in matches],
        "generatedAt": utc_now(),
        "disclaimer": "Document-grounded educational research; not investment advice.",
    }


@router.get("/documents")
def get_documents(symbol: str = Query(default="RELIANCE.NS", min_length=1, max_length=20)):
    try:
        return list_documents(symbol)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/documents/ask")
def ask_documents(payload: DocumentQuestion):
    try:
        return answer_document_question(payload.symbol, payload.question, payload.limit)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Document retrieval is unavailable: {error}") from error


@router.get("/documents/discover")
def discover_documents(symbol: str = Query(min_length=1, max_length=20)):
    try:
        return discover_official_documents(symbol)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Official document discovery is unavailable: {error}") from error


@router.post("/documents/prepare")
def prepare_documents(payload: OfficialDocumentRequest):
    try:
        support = document_preparation_support(payload.symbol)
        if not support["supported"]:
            raise ValueError(support["message"])
        if support["mode"] == "official-on-demand":
            return prepare_latest_official_document(payload.symbol)
        if support["mode"] == "sec-10-k-on-demand":
            try:
                return prepare_sec_10k_document(payload.symbol)
            except Exception as error:
                fallback = prepare_market_evidence_document(payload.symbol)
                return {
                    **fallback,
                    "status": "fallback-indexed" if fallback.get("status") == "indexed" else fallback.get("status"),
                    "preferredProvider": "SEC EDGAR",
                    "fallbackProvider": "Yahoo Finance public market data",
                    "fallbackReason": f"SEC retrieval was unavailable: {error}",
                }
        return prepare_market_evidence_document(payload.symbol)
    except OfficialDocumentBusyError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Official document indexing is unavailable: {error}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a page-cited company PDF into FinTrack RAG storage.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--document-type", default="annual-report")
    parser.add_argument("--reporting-period")
    parser.add_argument("--source-url")
    parser.add_argument("--embedding-provider", choices=[LOCAL_EMBEDDING_PROVIDER, GEMINI_EMBEDDING_PROVIDER], default=LOCAL_EMBEDDING_PROVIDER)
    parser.add_argument("--database-url")
    arguments = parser.parse_args()
    result = ingest_pdf(
        arguments.symbol, Path(arguments.pdf), arguments.title, arguments.document_type,
        arguments.reporting_period, arguments.source_url, arguments.embedding_provider,
        Database(arguments.database_url),
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
