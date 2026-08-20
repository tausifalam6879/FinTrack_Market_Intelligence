import json
import logging
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from threading import Lock
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

# All estimators in this public service use one worker. Some minimal Windows/CI
# images do not expose WMIC, so declare that limit before joblib is imported.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import numpy as np
import pandas as pd
import yfinance as yf
from fastapi import APIRouter, HTTPException, Request as FastApiRequest
from pydantic import BaseModel, Field
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from agent_orchestrator import build_agent_plan, tool_trace
from data_pipeline import bars_from_frame
from model_registry import approved_model, record_prediction as record_persistent_prediction
from persistence import Database


router = APIRouter(prefix="/market", tags=["Global Market Intelligence"])
logger = logging.getLogger(__name__)

GLOBAL_INDICES = {
    "^GSPC": {"name": "S&P 500", "region": "United States", "currency": "USD"},
    "^IXIC": {"name": "Nasdaq Composite", "region": "United States", "currency": "USD"},
    "^DJI": {"name": "Dow Jones", "region": "United States", "currency": "USD"},
    "^FTSE": {"name": "FTSE 100", "region": "United Kingdom", "currency": "GBP"},
    "^GDAXI": {"name": "DAX", "region": "Germany", "currency": "EUR"},
    "^N225": {"name": "Nikkei 225", "region": "Japan", "currency": "JPY"},
    "^HSI": {"name": "Hang Seng", "region": "Hong Kong", "currency": "HKD"},
    "^NSEI": {"name": "Nifty 50", "region": "India", "currency": "INR"},
    "^BSESN": {"name": "BSE Sensex", "region": "India", "currency": "INR"},
}

BENCHMARKS = {
    "^GSPC": "S&P 500",
    "^NSEI": "Nifty 50",
    "^BSESN": "BSE Sensex",
    "^FTSE": "FTSE 100",
    "^GDAXI": "DAX",
    "^N225": "Nikkei 225",
    "^HSI": "Hang Seng",
    "^AXJO": "S&P/ASX 200",
    "^GSPTSE": "S&P/TSX Composite",
    "^FCHI": "CAC 40",
    "^AEX": "AEX",
    "^SSMI": "Swiss Market Index",
    "^KS11": "KOSPI Composite",
    "000001.SS": "SSE Composite",
}

# Exchange suffixes keep benchmark selection dynamic; no company allowlist is used.
BENCHMARK_SUFFIXES = (
    (".NS", "^NSEI"), (".BO", "^BSESN"), (".L", "^FTSE"),
    (".DE", "^GDAXI"), (".T", "^N225"), (".HK", "^HSI"),
    (".AX", "^AXJO"), (".TO", "^GSPTSE"), (".PA", "^FCHI"),
    (".AS", "^AEX"), (".SW", "^SSMI"), (".KS", "^KS11"),
    (".KQ", "^KS11"), (".SS", "000001.SS"), (".SZ", "000001.SS"),
)

# Yahoo's equity screener uses market regions rather than exchange names. This
# mapping is exchange-level metadata only; peer companies are always discovered
# at request time and are never maintained in a company allowlist.
PEER_REGION_SUFFIXES = (
    (".NS", "in"), (".BO", "in"), (".L", "gb"), (".DE", "de"),
    (".T", "jp"), (".HK", "hk"), (".AX", "au"), (".TO", "ca"),
    (".PA", "fr"), (".AS", "nl"), (".SW", "ch"), (".KS", "kr"),
    (".KQ", "kr"), (".SS", "cn"), (".SZ", "cn"),
)

RISK_QUERY_TERMS = (
    "risk", "benchmark", "beta", "correlation", "drawdown", "tracking error",
    "historical var", "value at risk", "relative return", "outperform", "underperform",
    "volatility", "broad market", "market comparison", "behaved versus",
)

CATALYST_QUERY_TERMS = (
    "earnings date", "earnings calendar", "next earnings", "analyst rating", "analyst recommendation", "price target",
    "target price", "consensus", "ex-dividend", "ex dividend", "eps surprise", "catalyst",
)

NEWS_QUERY_TERMS = (
    "news", "headline", "announcement", "sentiment", "latest update", "publisher",
    "news theme", "coverage", "source diversity",
)

FINANCIAL_TREND_QUERY_TERMS = (
    "financial statement", "financial statements", "revenue trend", "profit trend",
    "cash flow trend", "free cash flow", "margin trend", "year over year", "yoy", "cagr",
    "annual revenue", "quarterly revenue", "debt trend",
)

OWNERSHIP_QUERY_TERMS = (
    "ownership", "shareholding", "shareholders", "institutional holder", "institutional holding",
    "mutual fund holder", "fund holding", "insider transaction", "insider buying", "insider selling",
    "insider activity", "promoter holding", "top holder", "ownership concentration",
)

ESTIMATE_REVISION_QUERY_TERMS = (
    "analyst estimate", "earnings estimate", "eps estimate", "revenue estimate",
    "estimate revision", "estimate revisions", "eps revision", "eps revisions",
    "estimate trend", "earnings outlook", "consensus eps", "consensus revenue",
    "upward revision", "downward revision", "revision breadth",
)

DIVIDEND_ACTION_QUERY_TERMS = (
    "dividend history", "dividend growth", "dividend yield", "payout ratio",
    "dividend consistency", "distribution history", "corporate action",
    "stock split", "split history", "capital gain distribution", "ex-dividend",
    "ex dividend", "dividend payment", "trailing dividend",
)

EARNINGS_QUALITY_QUERY_TERMS = (
    "earnings quality", "cash conversion", "profit to cash", "operating cash conversion",
    "fcf conversion", "free cash flow conversion", "capital allocation", "buyback",
    "share repurchase", "stock repurchase", "stock issuance", "share issuance",
    "debt repayment", "debt issuance", "cash deployment", "shareholder return",
)

LIQUIDITY_DEBT_QUERY_TERMS = (
    "balance sheet health", "balance sheet strength", "liquidity", "liquidity trend",
    "cash position", "cash balance", "net debt", "debt capacity", "debt trend",
    "working capital", "current ratio", "interest coverage", "debt to ebitda",
    "debt to equity", "debt to assets", "cash to debt", "leverage trend",
)

PROFITABILITY_RETURN_QUERY_TERMS = (
    "profitability", "return on equity", " roe ", "return on assets", " roa ",
    "return on invested capital", " roic ", "gross margin", "net margin",
    "asset turnover", "capital efficiency", "equity multiplier", "dupont", "du pont",
    "effective tax rate", "return ratio", "return ratios",
)

MARKET_BOARD = {
    "^NSEI": {"name": "Nifty 50", "region": "India", "currency": "INR", "kind": "index", "sector": "Indices"},
    "^BSESN": {"name": "BSE Sensex", "region": "India", "currency": "INR", "kind": "index", "sector": "Indices"},
    "RELIANCE.NS": {"name": "Reliance", "region": "India", "currency": "INR", "kind": "company", "sector": "Energy"},
    "ONGC.NS": {"name": "ONGC", "region": "India", "currency": "INR", "kind": "company", "sector": "Energy"},
    "HDFCBANK.NS": {"name": "HDFC Bank", "region": "India", "currency": "INR", "kind": "company", "sector": "Banking"},
    "ICICIBANK.NS": {"name": "ICICI Bank", "region": "India", "currency": "INR", "kind": "company", "sector": "Banking"},
    "SBIN.NS": {"name": "SBI", "region": "India", "currency": "INR", "kind": "company", "sector": "Banking"},
    "INFY.NS": {"name": "Infosys", "region": "India", "currency": "INR", "kind": "company", "sector": "Technology"},
    "TCS.NS": {"name": "TCS", "region": "India", "currency": "INR", "kind": "company", "sector": "Technology"},
    "WIPRO.NS": {"name": "Wipro", "region": "India", "currency": "INR", "kind": "company", "sector": "Technology"},
    "AAPL": {"name": "Apple", "region": "United States", "currency": "USD", "kind": "company", "sector": "Technology"},
    "MSFT": {"name": "Microsoft", "region": "United States", "currency": "USD", "kind": "company", "sector": "Technology"},
    "GOOGL": {"name": "Alphabet", "region": "United States", "currency": "USD", "kind": "company", "sector": "Technology"},
    "MARUTI.NS": {"name": "Maruti Suzuki", "region": "India", "currency": "INR", "kind": "company", "sector": "Automobile"},
    "EICHERMOT.NS": {"name": "Eicher Motors", "region": "India", "currency": "INR", "kind": "company", "sector": "Automobile"},
    "BAJAJ-AUTO.NS": {"name": "Bajaj Auto", "region": "India", "currency": "INR", "kind": "company", "sector": "Automobile"},
    "TSLA": {"name": "Tesla", "region": "United States", "currency": "USD", "kind": "company", "sector": "Automobile"},
    "ITC.NS": {"name": "ITC", "region": "India", "currency": "INR", "kind": "company", "sector": "Consumer"},
    "HINDUNILVR.NS": {"name": "Hindustan Unilever", "region": "India", "currency": "INR", "kind": "company", "sector": "Consumer"},
    "AMZN": {"name": "Amazon", "region": "United States", "currency": "USD", "kind": "company", "sector": "Consumer"},
    "SUNPHARMA.NS": {"name": "Sun Pharma", "region": "India", "currency": "INR", "kind": "company", "sector": "Healthcare"},
    "BHARTIARTL.NS": {"name": "Bharti Airtel", "region": "India", "currency": "INR", "kind": "company", "sector": "Telecom"},
    "NETWORK18.NS": {"name": "Network18", "region": "India", "currency": "INR", "kind": "company", "sector": "Media"},
    "NYT": {"name": "New York Times", "region": "United States", "currency": "USD", "kind": "company", "sector": "Media"},
}

# The dashboard keeps a small, clearly labelled live INR board.  A full
# provider currency directory is added as reference data below; only these
# liquid pairs are requested intraday so a page refresh does not make hundreds
# of upstream requests.
INR_CURRENCY_BOARD = {
    "USDINR=X": {"code": "USD", "name": "US Dollar", "country": "United States", "digits": 2},
    "EURINR=X": {"code": "EUR", "name": "Euro", "country": "Eurozone", "digits": 2},
    "GBPINR=X": {"code": "GBP", "name": "British Pound", "country": "United Kingdom", "digits": 2},
    "AEDINR=X": {"code": "AED", "name": "UAE Dirham", "country": "United Arab Emirates", "digits": 2},
    "JPYINR=X": {"code": "JPY", "name": "Japanese Yen", "country": "Japan", "digits": 4},
    "SGDINR=X": {"code": "SGD", "name": "Singapore Dollar", "country": "Singapore", "digits": 2},
    "AUDINR=X": {"code": "AUD", "name": "Australian Dollar", "country": "Australia", "digits": 2},
    "CADINR=X": {"code": "CAD", "name": "Canadian Dollar", "country": "Canada", "digits": 2},
}

MACRO_FACTORS = {
    "GC=F": {
        "name": "Gold",
        "unit": "USD/oz",
        "theme": "Safe haven and input cost",
        "positiveImpact": "Gold miners and defensive allocation",
        "negativeImpact": "Jewellery margins when input costs rise",
    },
    "CL=F": {
        "name": "Crude Oil",
        "unit": "USD/barrel",
        "theme": "Inflation and transport cost",
        "positiveImpact": "Oil producers and upstream energy",
        "negativeImpact": "Airlines, paints, logistics and oil-importing economies",
    },
    "INR=X": {
        "name": "USD/INR",
        "unit": "INR per USD",
        "theme": "Rupee and import cost",
        "positiveImpact": "Exporters with foreign-currency revenue",
        "negativeImpact": "Imported electronics, fuel and auto components",
    },
    "^TNX": {
        "name": "US 10Y Yield",
        "unit": "% yield",
        "theme": "Global cost of capital",
        "positiveImpact": "Some lenders when spreads improve",
        "negativeImpact": "High-valuation growth and rate-sensitive assets",
    },
    "^VIX": {
        "name": "US VIX",
        "unit": "index",
        "theme": "Global risk and volatility",
        "positiveImpact": "Hedges and defensive positioning",
        "negativeImpact": "Risk assets when volatility rises sharply",
    },
    "BTC-USD": {
        "name": "Bitcoin",
        "unit": "USD",
        "theme": "Speculative risk appetite",
        "positiveImpact": "Crypto-linked risk sentiment when participation broadens",
        "negativeImpact": "Signals risk reduction when it falls with equities",
    },
}

INDIA_WATCHLIST = {
    "RELIANCE.NS": "Reliance Industries",
    "HDFCBANK.NS": "HDFC Bank",
    "ICICIBANK.NS": "ICICI Bank",
    "INFY.NS": "Infosys",
    "TCS.NS": "TCS",
    "BHARTIARTL.NS": "Bharti Airtel",
    "SBIN.NS": "State Bank of India",
    "ITC.NS": "ITC",
    "LT.NS": "Larsen & Toubro",
    "MARUTI.NS": "Maruti Suzuki",
    "SUNPHARMA.NS": "Sun Pharma",
    "BAJAJ-AUTO.NS": "Bajaj Auto",
    "AXISBANK.NS": "Axis Bank",
    "HINDUNILVR.NS": "Hindustan Unilever",
    "ONGC.NS": "ONGC",
    "ETERNAL.NS": "Eternal",
}

SYMBOL_ALIASES = {
    "nifty": "^NSEI",
    "nifty 50": "^NSEI",
    "sensex": "^BSESN",
    "s&p": "^GSPC",
    "s&p 500": "^GSPC",
    "nasdaq": "^IXIC",
    "dow": "^DJI",
    "dow jones": "^DJI",
    "ftse": "^FTSE",
    "dax": "^GDAXI",
    "nikkei": "^N225",
    "hang seng": "^HSI",
    "gold price": "GC=F",
    "gold": "GC=F",
    "crude oil": "CL=F",
    "oil price": "CL=F",
    "oil": "CL=F",
    "usd inr": "INR=X",
    "rupee": "INR=X",
    "dollar": "INR=X",
    "us 10 year": "^TNX",
    "yield": "^TNX",
    "vix": "^VIX",
    "bitcoin": "BTC-USD",
    "btc": "BTC-USD",
}

POSITIVE_WORDS = {
    "accelerate", "accelerates", "beat", "beats", "boost", "boosts", "bullish", "gain",
    "gains", "growth", "higher", "jump", "jumps", "optimism", "outperform", "positive",
    "profit", "raise", "raises", "rally", "record", "recovery", "rise", "rises", "strong",
    "surge", "up", "upgrade", "upgrades", "win", "wins",
}
NEGATIVE_WORDS = {
    "bearish", "concern", "crash", "cut", "decline", "down", "downgrade", "downgrades",
    "drop", "fall", "falling", "falls", "fear", "fraud", "inflation", "loss", "lower",
    "miss", "plunge", "plunges", "probe", "recession", "risk", "slide", "slides", "slump",
    "tariff", "war", "warning", "weak",
}

NEWS_THEME_KEYWORDS = {
    "Earnings & outlook": (
        "earnings", "revenue", "profit", "margin", "guidance", "forecast", "quarter",
        "eps", "sales", "results",
    ),
    "Products & innovation": (
        "product", "launch", "ai", "artificial intelligence", "cloud", "chip", "platform",
        "technology", "software", "patent",
    ),
    "Deals & capital": (
        "acquisition", "acquire", "merger", "deal", "partnership", "stake", "buyback",
        "dividend", "funding", "investment",
    ),
    "Regulation & legal": (
        "regulator", "regulation", "lawsuit", "court", "probe", "antitrust", "compliance",
        "fine", "tax", "tariff",
    ),
    "Leadership & workforce": (
        "ceo", "cfo", "executive", "leadership", "board", "layoff", "workforce", "jobs",
        "appoint", "resign",
    ),
    "Market & demand": (
        "demand", "market", "consumer", "economy", "inflation", "rates", "competition",
        "supply", "export", "import",
    ),
}

CACHE_TTL_SECONDS = int(os.getenv("MARKET_CACHE_TTL_SECONDS", "120"))
QUOTE_CACHE_TTL_SECONDS = int(os.getenv("MARKET_QUOTE_CACHE_TTL_SECONDS", "15"))
OVERVIEW_CACHE_TTL_SECONDS = int(os.getenv("MARKET_OVERVIEW_CACHE_TTL_SECONDS", "900"))
PREDICTION_CACHE_TTL_SECONDS = int(os.getenv("MARKET_PREDICTION_CACHE_TTL_SECONDS", "900"))
PEER_CACHE_TTL_SECONDS = int(os.getenv("MARKET_PEER_CACHE_TTL_SECONDS", "1800"))
_cache: Dict[str, Dict[str, Any]] = {}
_overview_lock = Lock()
_prediction_audit: Dict[str, List[Dict[str, Any]]] = {}
_prediction_audit_lock = Lock()


class MarketAgentRequest(BaseModel):
    message: str = Field(min_length=2, max_length=3000)
    symbol: Optional[str] = Field(default=None, max_length=20)
    recent_messages: List[Dict[str, Any]] = Field(default_factory=list)


def _cache_get(key: str, ttl_seconds: int = CACHE_TTL_SECONDS) -> Optional[Any]:
    item = _cache.get(key)
    if item and time.time() - item["created_at"] < ttl_seconds:
        return item["value"]
    return None


def _cache_put(key: str, value: Any) -> Any:
    _cache[key] = {"created_at": time.time(), "value": value}
    return value


def clear_market_cache() -> None:
    _cache.clear()


def clear_market_cache_prefix(prefix: str) -> None:
    for key in [item for item in _cache if item.startswith(prefix)]:
        _cache.pop(key, None)


def _sanitize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9.^=&\-]{1,20}", normalized):
        raise ValueError("Invalid market symbol.")
    return normalized


def _infer_symbol(message: str, supplied_symbol: Optional[str]) -> str:
    # The dashboard's explicit selection is the research anchor. A benchmark or
    # company name mentioned inside the question must not silently replace it.
    if supplied_symbol:
        return _sanitize_symbol(supplied_symbol)
    lowered = message.lower()
    for alias, symbol in SYMBOL_ALIASES.items():
        if alias in lowered:
            return symbol
    ticker_match = re.search(r"(?:ticker|symbol)\s+([A-Za-z0-9.^=\-]{1,20})", message, re.IGNORECASE)
    return _sanitize_symbol(ticker_match.group(1)) if ticker_match else "^NSEI"


def _history(symbol: str, period: str) -> pd.DataFrame:
    key = f"history:{symbol}:{period}"
    cached = _cache_get(key)
    if cached is not None:
        return cached.copy()
    frame = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=False)
    if frame is None or frame.empty or "Close" not in frame:
        raise ValueError(f"Market data is unavailable for {symbol}.")
    frame = frame.dropna(subset=["Close"]).copy()
    return _cache_put(key, frame).copy()


def _persist_research_history(symbol: str, name: str, frame: pd.DataFrame) -> int:
    """Add an opened symbol to the demand-driven offline operations universe."""
    try:
        repository = Database()
        repository.initialize_schema()
        bars = bars_from_frame(symbol, frame, source="Yahoo Finance research")
        board = MARKET_BOARD.get(symbol, {})
        repository.upsert_company({
            "symbol": symbol,
            "name": name or board.get("name") or symbol,
            "exchange": "NSE" if symbol.endswith(".NS") else "BSE" if symbol.endswith(".BO") else None,
            "sector": board.get("sector"),
            "region": board.get("region"),
            "currency": board.get("currency"),
            "source": "On-demand public research",
            "metadata": {"discoveryMode": "demand-driven", "historyRows": len(bars)},
        })
        return repository.upsert_market_bars(bars)
    except Exception as error:
        logger.warning("Persistent research history failed for %s: %s", symbol, error)
        return 0


MONTH_ALIASES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def _extract_requested_date(message: str) -> Optional[date]:
    """Extract a date from common English/Hinglish market questions."""
    text = str(message or "").strip()
    named = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-/]+"
        r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
        r"[\s,\-/]+(\d{4})\b",
        text,
        re.IGNORECASE,
    )
    if named:
        try:
            return date(int(named.group(3)), MONTH_ALIASES[named.group(2).lower()], int(named.group(1)))
        except ValueError:
            return None
    for pattern, order in (
        (r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", "ymd"),
        (r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", "dmy"),
    ):
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            values = [int(item) for item in match.groups()]
            return date(values[0], values[1], values[2]) if order == "ymd" else date(values[2], values[1], values[0])
        except ValueError:
            return None
    return None


def _historical_session(symbol: str, requested_date: date) -> Dict[str, Any]:
    """Return the nearest available trading session with transparent calculations."""
    frame = _history(symbol, "5y")
    sessions = [(index, index.date()) for index in frame.index]
    if not sessions:
        raise ValueError(f"Historical market data is unavailable for {symbol}.")
    nearest_index, session_date = min(
        sessions,
        key=lambda item: (abs((item[1] - requested_date).days), item[1] > requested_date),
    )
    position = frame.index.get_loc(nearest_index)
    if isinstance(position, slice):
        position = position.start
    row = frame.iloc[int(position)]
    previous_close = float(frame.iloc[int(position) - 1]["Close"]) if int(position) > 0 else None
    close = float(row["Close"])
    change_percent = ((close / previous_close) - 1) * 100 if previous_close else None
    next_session = None
    if int(position) + 1 < len(frame):
        next_row = frame.iloc[int(position) + 1]
        next_close = float(next_row["Close"])
        next_session = {
            "date": frame.index[int(position) + 1].date().isoformat(),
            "close": _round(next_close),
            "changePercent": _round(((next_close / close) - 1) * 100, 2),
        }
    return {
        "requestedDate": requested_date.isoformat(),
        "sessionDate": session_date.isoformat(),
        "exactSession": session_date == requested_date,
        "open": _round(row.get("Open")),
        "high": _round(row.get("High")),
        "low": _round(row.get("Low")),
        "close": _round(close),
        "previousClose": _round(previous_close),
        "change": _round(close - previous_close) if previous_close else None,
        "changePercent": _round(change_percent, 2),
        "intradayRange": _round(float(row.get("High", close)) - float(row.get("Low", close))),
        "volume": _round(row.get("Volume"), 0),
        "nextSession": next_session,
        "source": "Yahoo Finance via yfinance",
    }


def _build_analysis_brief(snapshot: Dict[str, Any], prediction: Dict[str, Any]) -> Dict[str, Any]:
    """Pre-calculate arithmetic so an LLM explains numbers instead of inventing them."""
    price = float(snapshot.get("price") or prediction.get("lastClose") or 0)
    expected_range = prediction.get("expectedRange") or {}
    low = float(expected_range.get("low") or price)
    high = float(expected_range.get("high") or price)
    probability_up = float(prediction.get("probabilityUp") or 50)
    balanced_accuracy = float(prediction.get("model", {}).get("balancedAccuracy") or 0)
    return {
        "currentPrice": _round(price),
        "dailyChangePercent": _round(snapshot.get("changePercent"), 2),
        "probabilityUp": _round(probability_up, 1),
        "probabilityDown": _round(100 - probability_up, 1),
        "distanceFromNeutralPoints": _round(abs(probability_up - 50), 1),
        "expectedDownsidePoints": _round(max(price - low, 0)),
        "expectedUpsidePoints": _round(max(high - price, 0)),
        "expectedDownsidePercent": _round(((low / price) - 1) * 100, 2) if price else None,
        "expectedUpsidePercent": _round(((high / price) - 1) * 100, 2) if price else None,
        "expectedRangeWidth": _round(high - low),
        "balancedAccuracy": _round(balanced_accuracy, 1),
        "modelHasReliableDirectionalEdge": balanced_accuracy >= 53,
    }


def _intraday_history(symbol: str) -> pd.DataFrame:
    """Return recent minute bars without making every browser poll hit Yahoo."""
    key = f"history:{symbol}:5d:1m"
    cached = _cache_get(key, QUOTE_CACHE_TTL_SECONDS)
    if cached is not None:
        return cached.copy()
    frame = yf.Ticker(symbol).history(period="5d", interval="1m", auto_adjust=False, prepost=False)
    if frame is None or frame.empty or "Close" not in frame:
        raise ValueError(f"Intraday market data is unavailable for {symbol}.")
    frame = frame.dropna(subset=["Close"]).copy()
    return _cache_put(key, frame).copy()


def _round(value: Any, digits: int = 2) -> Optional[float]:
    try:
        numeric = float(value)
        return round(numeric, digits) if math.isfinite(numeric) else None
    except (TypeError, ValueError):
        return None


def _snapshot_from_frame(
    symbol: str,
    frame: pd.DataFrame,
    quote_mode: str,
    include_average_volume: bool = True,
    daily_frame: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Build the common quote payload from an already downloaded price frame."""
    latest = frame.iloc[-1]
    latest_date = frame.index[-1].date()
    session_mask = [index.date() == latest_date for index in frame.index]
    session = frame.loc[session_mask]
    previous_session = frame.loc[[index.date() < latest_date for index in frame.index]]
    previous_close = float(previous_session.iloc[-1]["Close"]) if not previous_session.empty else None
    if previous_close is None:
        if daily_frame is None:
            daily_frame = _history(symbol, "1mo")
        daily_previous = daily_frame.loc[[index.date() < latest_date for index in daily_frame.index]]
        previous_close = float(daily_previous.iloc[-1]["Close"]) if not daily_previous.empty else float(latest["Close"])

    close = float(latest["Close"])
    change = close - previous_close
    metadata = GLOBAL_INDICES.get(symbol, MARKET_BOARD.get(symbol, MACRO_FACTORS.get(symbol, {})))
    volume = _round(session["Volume"].sum(), 0) if "Volume" in session else _round(latest.get("Volume"), 0)
    if include_average_volume and daily_frame is None:
        daily_frame = _history(symbol, "1mo")
    average_volume = (
        _round(daily_frame["Volume"].tail(20).mean(), 0)
        if daily_frame is not None and "Volume" in daily_frame else None
    )
    return {
        "symbol": symbol,
        "name": metadata.get("name", symbol),
        "region": metadata.get("region", "Global"),
        "currency": metadata.get("currency", metadata.get("unit", "Local currency")),
        "price": _round(close),
        "open": _round(session.iloc[0].get("Open")),
        "high": _round(session["High"].max()) if "High" in session else _round(latest.get("High")),
        "low": _round(session["Low"].min()) if "Low" in session else _round(latest.get("Low")),
        "previousClose": _round(previous_close),
        "volume": volume,
        "averageVolume20d": average_volume,
        "change": _round(change),
        "changePercent": _round((change / previous_close) * 100 if previous_close else 0),
        "dataAsOf": frame.index[-1].isoformat(),
        "source": "Yahoo Finance via yfinance",
        "quoteMode": quote_mode,
        "status": "available",
    }


def market_snapshot(symbol: str, include_average_volume: bool = True) -> Dict[str, Any]:
    symbol = _sanitize_symbol(symbol)
    daily_frame: Optional[pd.DataFrame] = None
    quote_mode = "end-of-day"
    try:
        frame = _intraday_history(symbol)
        quote_mode = "intraday"
    except Exception:
        daily_frame = _history(symbol, "1mo")
        frame = daily_frame

    return _snapshot_from_frame(symbol, frame, quote_mode, include_average_volume, daily_frame)


def macro_factors() -> Dict[str, Any]:
    factors: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        jobs = {executor.submit(market_snapshot, symbol): symbol for symbol in MACRO_FACTORS}
        for job in as_completed(jobs):
            symbol = jobs[job]
            metadata = MACRO_FACTORS[symbol]
            try:
                snapshot = job.result()
                factors.append({**snapshot, **metadata})
            except Exception as error:
                factors.append({
                    "symbol": symbol,
                    "name": metadata["name"],
                    "status": "unavailable",
                    "error": str(error),
                    **metadata,
                })
    order = {symbol: index for index, symbol in enumerate(MACRO_FACTORS)}
    factors.sort(key=lambda item: order.get(item["symbol"], 999))
    return {
        "factors": factors,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "Yahoo Finance via yfinance",
        "interpretation": "Directional relationships are contextual, not guaranteed causal effects.",
    }


def market_breadth() -> Dict[str, Any]:
    quotes: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        jobs = {executor.submit(market_snapshot, symbol): symbol for symbol in INDIA_WATCHLIST}
        for job in as_completed(jobs):
            symbol = jobs[job]
            try:
                quote = job.result()
                quote["name"] = INDIA_WATCHLIST[symbol]
                quotes.append(quote)
            except Exception:
                continue
    quotes.sort(key=lambda item: float(item.get("changePercent") or 0), reverse=True)
    advances = sum(float(item.get("changePercent") or 0) > 0.05 for item in quotes)
    declines = sum(float(item.get("changePercent") or 0) < -0.05 for item in quotes)
    unchanged = len(quotes) - advances - declines
    active = sorted(
        quotes,
        key=lambda item: (
            (float(item.get("volume") or 0) / float(item.get("averageVolume20d") or 1))
            if item.get("averageVolume20d") else 0
        ),
        reverse=True,
    )[:5]
    return {
        "coverage": "Representative liquid India watchlist",
        "coverageCount": len(quotes),
        "advances": advances,
        "declines": declines,
        "unchanged": unchanged,
        "topGainers": quotes[:5],
        "topLosers": list(reversed(quotes[-5:])),
        "mostActive": active,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "Yahoo Finance via yfinance",
        "disclaimer": "Breadth covers the displayed watchlist, not every NSE-listed security.",
    }


def _download_overview_frames(symbols: List[str]) -> Dict[str, pd.DataFrame]:
    """Download dashboard quotes in one batch instead of one upstream request per card."""
    downloaded = yf.download(
        tickers=" ".join(symbols),
        period="5d",
        interval="5m",
        group_by="ticker",
        auto_adjust=False,
        prepost=False,
        threads=True,
        progress=False,
        timeout=8,
    )
    if downloaded is None or downloaded.empty:
        raise ValueError("The market quote provider returned an empty overview response.")

    frames: Dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            frame = downloaded[symbol] if isinstance(downloaded.columns, pd.MultiIndex) else downloaded
            frame = frame.dropna(subset=["Close"]).copy()
            if not frame.empty:
                frames[symbol] = frame
        except (KeyError, TypeError, ValueError):
            continue
    return frames


def global_overview() -> Dict[str, Any]:
    cached = _cache_get("global-overview", OVERVIEW_CACHE_TTL_SECONDS)
    if cached is not None:
        return cached

    # FastAPI may receive the dashboard and a Spring proxy request together.
    # Only one request should perform the relatively expensive Yahoo download.
    with _overview_lock:
        cached = _cache_get("global-overview", OVERVIEW_CACHE_TTL_SECONDS)
        if cached is not None:
            return cached

        return _build_global_overview()


def _build_global_overview() -> Dict[str, Any]:
    quotes_by_symbol: Dict[str, Dict[str, Any]] = {}
    requested_symbols = list(dict.fromkeys([*GLOBAL_INDICES, *MARKET_BOARD]))
    frames = _download_overview_frames(requested_symbols)
    for symbol in requested_symbols:
        try:
            quotes_by_symbol[symbol] = _snapshot_from_frame(
                symbol,
                frames[symbol],
                quote_mode="intraday-5-minute",
                include_average_volume=False,
            )
        except Exception as error:
            metadata = GLOBAL_INDICES.get(symbol) or MARKET_BOARD[symbol]
            quotes_by_symbol[symbol] = {
                "symbol": symbol,
                "name": metadata["name"],
                "region": metadata["region"],
                "currency": metadata["currency"],
                "status": "unavailable",
                "error": str(error),
            }
    snapshots = [quotes_by_symbol[symbol] for symbol in GLOBAL_INDICES]
    watchlist = [
        {**quotes_by_symbol[symbol], "kind": metadata["kind"], "sector": metadata["sector"]}
        for symbol, metadata in MARKET_BOARD.items()
    ]
    available = [item for item in snapshots if item["status"] == "available"]
    result = {
        "markets": snapshots,
        "watchlist": watchlist,
        "availableMarkets": len(available),
        "totalMarkets": len(snapshots),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "refreshIntervalSeconds": OVERVIEW_CACHE_TTL_SECONDS,
        "dataDelayNotice": "Five-minute dashboard quotes refresh every 15 minutes or on request, and may be delayed by the upstream provider and exchange rules.",
    }
    return _cache_put("global-overview", result)


def _reference_inr_rates() -> Dict[str, float]:
    """Read the broad currency directory server-side, avoiding browser CORS/proxy failures."""
    cached = _cache_get("inr-reference-rates", 60 * 60)
    if cached is not None:
        return cached
    request = UrlRequest(
        "https://open.er-api.com/v6/latest/INR",
        headers={"User-Agent": "FinTrack-market-service/1.0"},
    )
    with urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rates = payload.get("rates", {}) if payload.get("result") == "success" else {}
    usable = {str(code).upper(): float(rate) for code, rate in rates.items() if _round(rate) and float(rate) > 0}
    return _cache_put("inr-reference-rates", usable)


def inr_currency_rates(refresh: bool = False) -> Dict[str, Any]:
    if refresh:
        _cache.pop("inr-currency-rates", None)
    cached = _cache_get("inr-currency-rates", QUOTE_CACHE_TTL_SECONDS)
    if cached is not None:
        return cached

    try:
        reference_rates = _reference_inr_rates()
    except Exception:
        reference_rates = {}

    quotes_by_symbol: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(INR_CURRENCY_BOARD)) as executor:
        jobs = {executor.submit(market_snapshot, symbol, False): symbol for symbol in INR_CURRENCY_BOARD}
        for job in as_completed(jobs):
            symbol = jobs[job]
            try:
                quotes_by_symbol[symbol] = job.result()
            except Exception:
                continue

    currencies = []
    for symbol, metadata in INR_CURRENCY_BOARD.items():
        quote = quotes_by_symbol.get(symbol)
        price = _round(quote.get("price")) if quote else None
        reference_rate = _round(1 / reference_rates[metadata["code"]]) if reference_rates.get(metadata["code"]) else None
        currencies.append({
            **metadata,
            "symbol": symbol,
            "inrValue": price or reference_rate,
            "quoteMode": "intraday" if price else "reference",
            "dataAsOf": quote.get("dataAsOf") if quote else None,
            "source": quote.get("source") if quote else "ExchangeRate-API reference",
            "status": "available" if (price or reference_rate) else "unavailable",
        })

    result = {
        "baseCurrency": "INR",
        "currencies": currencies,
        "referenceRates": reference_rates,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "refreshIntervalSeconds": QUOTE_CACHE_TTL_SECONDS,
        "source": "Yahoo Finance via yfinance for featured pairs; ExchangeRate-API reference directory",
        "dataDelayNotice": "Currency quotes may be delayed by the upstream provider and are not bank conversion rates.",
    }
    return _cache_put("inr-currency-rates", result)


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0).rolling(period).mean()
    losses = -delta.clip(upper=0).rolling(period).mean()
    relative_strength = gains / losses.replace(0, np.nan)
    return (100 - (100 / (1 + relative_strength))).fillna(50)


def _features(frame: pd.DataFrame) -> pd.DataFrame:
    close = frame["Close"].astype(float)
    volume = frame["Volume"].astype(float) if "Volume" in frame else pd.Series(0, index=frame.index)
    result = pd.DataFrame(index=frame.index)
    result["return_1"] = close.pct_change()
    result["return_5"] = close.pct_change(5)
    result["sma_10_ratio"] = close / close.rolling(10).mean() - 1
    result["sma_20_ratio"] = close / close.rolling(20).mean() - 1
    result["volatility_10"] = result["return_1"].rolling(10).std()
    result["volume_change"] = volume.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0)
    result["rsi_14"] = _rsi(close, 14) / 100
    return result.replace([np.inf, -np.inf], np.nan)


def _sentiment_label(score: Any) -> str:
    numeric = float(score or 0)
    return "positive" if numeric > 0.15 else "negative" if numeric < -0.15 else "mixed/neutral"


def _headline_themes(title: str) -> List[str]:
    normalized = " ".join(re.findall(r"[a-z0-9]+", str(title or "").lower()))
    themes = []
    for theme, keywords in NEWS_THEME_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(keyword)}\b", normalized) for keyword in keywords):
            themes.append(theme)
    return themes or ["General company update"]


def _published_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        parsed = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.to_pydatetime()
    except (TypeError, ValueError, OverflowError):
        return None


def _news_intelligence(
    articles: List[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Summarize bounded publisher-headline evidence without semantic invention."""
    evaluated_at = now or datetime.now(timezone.utc)
    if evaluated_at.tzinfo is None:
        evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)
    if not articles:
        return {
            "status": "unavailable",
            "articleCount": 0,
            "sentimentScore": 0.0,
            "sentimentLabel": "mixed/neutral",
            "distribution": {"positive": 0, "mixed/neutral": 0, "negative": 0},
            "sourceCount": 0,
            "coverage": "unavailable",
            "freshness": "unavailable",
            "latestPublishedAt": None,
            "topSources": [],
            "themes": [],
            "dailyTone": [],
            "method": "Transparent headline keyword counts; no article body or LLM sentiment is inferred.",
            "disclaimer": "No recent provider headlines were returned, so FinTrack does not invent a news conclusion.",
        }

    distribution = {"positive": 0, "mixed/neutral": 0, "negative": 0}
    source_counts: Dict[str, int] = {}
    theme_counts: Dict[str, int] = {}
    daily: Dict[str, List[float]] = {}
    timestamps = []
    for article in articles:
        score = float(article.get("sentiment") or 0)
        label = str(article.get("sentimentLabel") or _sentiment_label(score))
        distribution[label] = distribution.get(label, 0) + 1
        publisher = str(article.get("publisher") or "Unknown")
        source_counts[publisher] = source_counts.get(publisher, 0) + 1
        for theme in article.get("themes") or ["General company update"]:
            theme_counts[theme] = theme_counts.get(theme, 0) + 1
        published_at = _published_datetime(article.get("publishedAt"))
        if published_at:
            timestamps.append(published_at)
            daily.setdefault(published_at.date().isoformat(), []).append(score)

    score = float(np.mean([float(item.get("sentiment") or 0) for item in articles]))
    latest = max(timestamps) if timestamps else None
    age_hours = max(0.0, (evaluated_at - latest).total_seconds() / 3600) if latest else None
    freshness = (
        "fresh" if age_hours is not None and age_hours <= 48 else
        "recent" if age_hours is not None and age_hours <= 168 else
        "stale" if age_hours is not None else "date unavailable"
    )
    source_count = len([name for name in source_counts if name.lower() != "unknown"])
    coverage = (
        "broader" if len(articles) >= 6 and source_count >= 3 else
        "moderate" if len(articles) >= 3 and source_count >= 2 else "limited"
    )
    return {
        "status": "available",
        "articleCount": len(articles),
        "sentimentScore": _round(score, 3),
        "sentimentLabel": _sentiment_label(score),
        "distribution": distribution,
        "sourceCount": source_count,
        "coverage": coverage,
        "freshness": freshness,
        "latestPublishedAt": latest.isoformat() if latest else None,
        "topSources": [
            {"publisher": publisher, "articleCount": count}
            for publisher, count in sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))[:4]
        ],
        "themes": [
            {"theme": theme, "articleCount": count}
            for theme, count in sorted(theme_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
        ],
        "dailyTone": [
            {
                "date": day,
                "articleCount": len(values),
                "sentimentScore": _round(float(np.mean(values)), 3),
                "sentimentLabel": _sentiment_label(float(np.mean(values))),
            }
            for day, values in sorted(daily.items())
        ],
        "method": "Transparent title-only keyword counts aggregated across the returned publisher headlines.",
        "disclaimer": "Headline tone is limited evidence, can miss context or sarcasm, and remains separate from FinTrack ML and investment advice.",
    }


def _normalize_news_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    content = item.get("content") if isinstance(item.get("content"), dict) else item
    title = content.get("title") or item.get("title")
    if not title:
        return None
    provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
    click_url = content.get("clickThroughUrl") if isinstance(content.get("clickThroughUrl"), dict) else {}
    canonical_url = content.get("canonicalUrl") if isinstance(content.get("canonicalUrl"), dict) else {}
    published = content.get("pubDate") or item.get("providerPublishTime")
    thumbnail = content.get("thumbnail") if isinstance(content.get("thumbnail"), dict) else item.get("thumbnail")
    resolutions = thumbnail.get("resolutions") if isinstance(thumbnail, dict) else []
    image_url = next(
        (
            resolution.get("url")
            for resolution in (resolutions or [])
            if isinstance(resolution, dict)
            and str(resolution.get("url") or "").startswith(("https://", "http://"))
        ),
        None,
    )
    if isinstance(published, (int, float)):
        published = datetime.fromtimestamp(published, tz=timezone.utc).isoformat()
    words = re.findall(r"[a-z]+", title.lower())
    positive_terms = sorted({word for word in words if word in POSITIVE_WORDS})
    negative_terms = sorted({word for word in words if word in NEGATIVE_WORDS})
    raw_score = len(positive_terms) - len(negative_terms)
    sentiment = max(-1.0, min(1.0, raw_score / 3))
    return {
        "title": title,
        "publisher": provider.get("displayName") or item.get("publisher") or "Unknown",
        "url": item.get("link") or click_url.get("url") or canonical_url.get("url"),
        "imageUrl": image_url,
        "publishedAt": published,
        "sentiment": _round(sentiment, 3),
        "sentimentLabel": _sentiment_label(sentiment),
        "sentimentBasis": {"positiveTerms": positive_terms, "negativeTerms": negative_terms},
        "themes": _headline_themes(title),
    }


def market_news(symbol: str, limit: int = 8) -> Dict[str, Any]:
    symbol = _sanitize_symbol(symbol)
    key = f"news:{symbol}:{limit}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        raw_news = yf.Ticker(symbol).news or []
    except Exception:
        raw_news = []
    articles = []
    for item in raw_news:
        normalized = _normalize_news_item(item)
        if normalized:
            articles.append(normalized)
        if len(articles) >= limit:
            break
    intelligence = _news_intelligence(articles)
    result = {
        "symbol": symbol,
        "articles": articles,
        "sentimentScore": intelligence["sentimentScore"],
        "sentimentLabel": intelligence["sentimentLabel"],
        "intelligence": intelligence,
        "method": "Transparent headline keyword sentiment; not a trading signal.",
    }
    return _cache_put(key, result)


def _period_return(close: pd.Series, sessions: int) -> Optional[float]:
    if close.empty:
        return None
    start_index = max(0, len(close) - sessions - 1)
    start = float(close.iloc[start_index])
    end = float(close.iloc[-1])
    return _round(((end / start) - 1) * 100, 2) if start else None


def _percentage_from_fraction(value: Any) -> Optional[float]:
    numeric = _round(value, 6)
    return _round(numeric * 100, 2) if numeric is not None else None


def _company_financial_sections(info: Dict[str, Any]) -> Dict[str, Dict[str, Optional[float]]]:
    """Normalize Yahoo company fields without inventing a composite score."""
    return {
        "valuation": {
            "marketCap": _round(info.get("marketCap"), 0),
            "enterpriseValue": _round(info.get("enterpriseValue"), 0),
            "trailingPE": _round(info.get("trailingPE")),
            "forwardPE": _round(info.get("forwardPE")),
            "priceToBook": _round(info.get("priceToBook")),
            "priceToSales": _round(info.get("priceToSalesTrailing12Months")),
        },
        "profitability": {
            "returnOnEquityPercent": _percentage_from_fraction(info.get("returnOnEquity")),
            "profitMarginPercent": _percentage_from_fraction(info.get("profitMargins")),
            "operatingMarginPercent": _percentage_from_fraction(info.get("operatingMargins")),
        },
        "growth": {
            "revenueGrowthPercent": _percentage_from_fraction(info.get("revenueGrowth")),
            "earningsGrowthPercent": _percentage_from_fraction(info.get("earningsGrowth")),
        },
        "balanceSheet": {
            "debtToEquity": _round(info.get("debtToEquity")),
            "currentRatio": _round(info.get("currentRatio")),
            "quickRatio": _round(info.get("quickRatio")),
            "totalCash": _round(info.get("totalCash"), 0),
            "totalDebt": _round(info.get("totalDebt"), 0),
        },
        "cashFlowAndIncome": {
            "totalRevenue": _round(info.get("totalRevenue"), 0),
            "ebitda": _round(info.get("ebitda"), 0),
            "netIncomeToCommon": _round(info.get("netIncomeToCommon"), 0),
            "operatingCashflow": _round(info.get("operatingCashflow"), 0),
            "freeCashflow": _round(info.get("freeCashflow"), 0),
        },
        "shareholderReturns": {
            # Yahoo's current quote payload already exposes dividend yield as
            # percentage points (for example 0.35 means 0.35%).
            "dividendYieldPercent": _round(info.get("dividendYield")),
            "payoutRatioPercent": _percentage_from_fraction(info.get("payoutRatio")),
        },
    }


def _statement_value(
    frame: Optional[pd.DataFrame],
    row_names: tuple[str, ...],
    period: Any,
) -> Optional[float]:
    if frame is None or frame.empty or period not in frame.columns:
        return None
    for row_name in row_names:
        if row_name not in frame.index:
            continue
        value = frame.loc[row_name, period]
        if isinstance(value, pd.Series):
            value = value.iloc[0] if not value.empty else None
        return _round(value, 0)
    return None


def _safe_percent_change(current: Any, previous: Any) -> Optional[float]:
    current_value = _round(current, 6)
    previous_value = _round(previous, 6)
    if current_value is None or previous_value in (None, 0):
        return None
    return _round(((current_value / previous_value) - 1) * 100, 2)


def _safe_margin(numerator: Any, denominator: Any) -> Optional[float]:
    numerator_value = _round(numerator, 6)
    denominator_value = _round(denominator, 6)
    if numerator_value is None or denominator_value in (None, 0):
        return None
    return _round((numerator_value / denominator_value) * 100, 2)


def _compact_amount(value: Any, currency: Optional[str] = None) -> str:
    numeric = _round(value, 6)
    if numeric is None:
        return "unavailable"
    magnitude = abs(numeric)
    scale, suffix = (
        (1_000_000_000_000, "T") if magnitude >= 1_000_000_000_000 else
        (1_000_000_000, "B") if magnitude >= 1_000_000_000 else
        (1_000_000, "M") if magnitude >= 1_000_000 else
        (1_000, "K") if magnitude >= 1_000 else (1, "")
    )
    formatted = f"{numeric / scale:.2f}".rstrip("0").rstrip(".")
    return f"{formatted}{suffix}{f' {currency}' if currency else ''}"


def _series_trend(values: List[Any]) -> str:
    numeric = [float(value) for value in values if _round(value, 6) is not None]
    if len(numeric) < 2:
        return "unavailable"
    changes = [((current / previous) - 1) * 100 for previous, current in zip(numeric, numeric[1:]) if previous]
    material = [change for change in changes if abs(change) >= 2]
    if material and all(change > 0 for change in material):
        return "growing"
    if material and all(change < 0 for change in material):
        return "declining"
    if not material:
        return "stable"
    return "mixed"


def _financial_statement_trends(
    income_statement: Optional[pd.DataFrame],
    balance_sheet: Optional[pd.DataFrame],
    cash_flow: Optional[pd.DataFrame],
    quarterly_income: Optional[pd.DataFrame],
) -> Dict[str, Any]:
    """Build comparable annual/quarterly evidence from provider statements."""
    frames = [frame for frame in (income_statement, balance_sheet, cash_flow) if frame is not None and not frame.empty]
    annual_periods = sorted({period for frame in frames for period in frame.columns}, key=pd.Timestamp)[-5:]
    annual = []
    for period in annual_periods:
        revenue = _statement_value(income_statement, ("Total Revenue", "Operating Revenue"), period)
        net_income = _statement_value(
            income_statement,
            ("Net Income", "Net Income Common Stockholders", "Net Income Including Noncontrolling Interests"),
            period,
        )
        operating_income = _statement_value(income_statement, ("Operating Income",), period)
        gross_profit = _statement_value(income_statement, ("Gross Profit",), period)
        total_debt = _statement_value(balance_sheet, ("Total Debt",), period)
        equity = _statement_value(
            balance_sheet,
            ("Stockholders Equity", "Total Stockholder Equity", "Total Equity Gross Minority Interest"),
            period,
        )
        operating_cash_flow = _statement_value(
            cash_flow,
            ("Operating Cash Flow", "Total Cash From Operating Activities"),
            period,
        )
        free_cash_flow = _statement_value(cash_flow, ("Free Cash Flow",), period)
        capital_expenditure = _statement_value(
            cash_flow,
            ("Capital Expenditure", "Capital Expenditures"),
            period,
        )
        if not any(value is not None for value in (
            revenue, net_income, operating_income, total_debt, operating_cash_flow, free_cash_flow,
        )):
            continue
        annual.append({
            "period": _provider_date(period),
            "revenue": revenue,
            "netIncome": net_income,
            "operatingIncome": operating_income,
            "grossProfit": gross_profit,
            "operatingCashFlow": operating_cash_flow,
            "freeCashFlow": free_cash_flow,
            "capitalExpenditure": capital_expenditure,
            "totalDebt": total_debt,
            "stockholdersEquity": equity,
            "operatingMarginPercent": _safe_margin(operating_income, revenue),
            "netMarginPercent": _safe_margin(net_income, revenue),
            "freeCashFlowMarginPercent": _safe_margin(free_cash_flow, revenue),
            "debtToEquityRatio": _round(total_debt / equity, 3) if total_debt is not None and equity not in (None, 0) else None,
        })
    for index, record in enumerate(annual):
        previous = annual[index - 1] if index else {}
        record["revenueYoYPercent"] = _safe_percent_change(record.get("revenue"), previous.get("revenue"))
        record["netIncomeYoYPercent"] = _safe_percent_change(record.get("netIncome"), previous.get("netIncome"))
        record["freeCashFlowYoYPercent"] = _safe_percent_change(record.get("freeCashFlow"), previous.get("freeCashFlow"))
        record["debtYoYPercent"] = _safe_percent_change(record.get("totalDebt"), previous.get("totalDebt"))

    quarterly_periods = [] if quarterly_income is None or quarterly_income.empty else sorted(
        quarterly_income.columns, key=pd.Timestamp,
    )[-5:]
    quarterly = []
    for period in quarterly_periods:
        revenue = _statement_value(quarterly_income, ("Total Revenue", "Operating Revenue"), period)
        net_income = _statement_value(
            quarterly_income,
            ("Net Income", "Net Income Common Stockholders", "Net Income Including Noncontrolling Interests"),
            period,
        )
        operating_income = _statement_value(quarterly_income, ("Operating Income",), period)
        if revenue is None and net_income is None:
            continue
        quarterly.append({
            "period": _provider_date(period),
            "revenue": revenue,
            "netIncome": net_income,
            "operatingIncome": operating_income,
            "operatingMarginPercent": _safe_margin(operating_income, revenue),
        })
    for index, record in enumerate(quarterly):
        previous = quarterly[index - 1] if index else {}
        comparable_quarter = False
        if record.get("period") and previous.get("period"):
            gap_days = (date.fromisoformat(record["period"]) - date.fromisoformat(previous["period"])).days
            comparable_quarter = 45 <= gap_days <= 135
        record["revenueQoQPercent"] = (
            _safe_percent_change(record.get("revenue"), previous.get("revenue")) if comparable_quarter else None
        )
        record["netIncomeQoQPercent"] = (
            _safe_percent_change(record.get("netIncome"), previous.get("netIncome")) if comparable_quarter else None
        )
        record["previousQuarterComparable"] = comparable_quarter

    if not annual and not quarterly:
        return {
            "status": "unavailable",
            "annual": [],
            "quarterly": [],
            "summary": {},
            "source": "Yahoo Finance company statements via yfinance",
            "method": "No comparable financial-statement periods were returned.",
            "disclaimer": "FinTrack does not estimate missing statement values.",
        }

    first = annual[0] if annual else {}
    latest = annual[-1] if annual else {}
    year_span = None
    if first.get("period") and latest.get("period"):
        year_span = max(1.0, (date.fromisoformat(latest["period"]) - date.fromisoformat(first["period"])).days / 365.25)
    revenue_cagr = None
    if year_span and first.get("revenue") and latest.get("revenue") and first["revenue"] > 0 and latest["revenue"] > 0:
        revenue_cagr = _round(((latest["revenue"] / first["revenue"]) ** (1 / year_span) - 1) * 100, 2)
    prior = annual[-2] if len(annual) > 1 else {}
    margin_change = (
        _round(latest["operatingMarginPercent"] - prior["operatingMarginPercent"], 2)
        if latest.get("operatingMarginPercent") is not None and prior.get("operatingMarginPercent") is not None else None
    )
    return {
        "status": "available",
        "annual": annual,
        "quarterly": quarterly,
        "summary": {
            "latestAnnualPeriod": latest.get("period"),
            "annualPeriodCount": len(annual),
            "quarterlyPeriodCount": len(quarterly),
            "revenueCagrPercent": revenue_cagr,
            "revenueTrend": _series_trend([item.get("revenue") for item in annual]),
            "netIncomeTrend": _series_trend([item.get("netIncome") for item in annual]),
            "freeCashFlowTrend": _series_trend([item.get("freeCashFlow") for item in annual]),
            "latestOperatingMarginPercent": latest.get("operatingMarginPercent"),
            "operatingMarginChangePoints": margin_change,
            "latestFreeCashFlow": latest.get("freeCashFlow"),
            "latestDebtToEquityRatio": latest.get("debtToEquityRatio"),
            "latestDebtYoYPercent": latest.get("debtYoYPercent"),
        },
        "source": "Yahoo Finance annual and quarterly company statements via yfinance",
        "method": "Provider statement rows aligned by reported fiscal period; growth, margins, CAGR and debt/equity are calculated by FinTrack.",
        "disclaimer": "Statements can be restated and fiscal periods differ by company. Missing values are shown as unavailable, not estimated; this is not an accounting audit or investment advice.",
    }


def _statement_outflow(value: Any) -> Optional[float]:
    """Return a reported cash outflow magnitude without reclassifying positive reversals."""
    numeric = _round(value, 6)
    if numeric is None:
        return None
    if numeric < 0:
        return _round(abs(numeric), 0)
    if numeric == 0:
        return 0.0
    return None


def _statement_inflow(value: Any) -> Optional[float]:
    numeric = _round(value, 6)
    if numeric is None:
        return None
    return _round(numeric, 0) if numeric >= 0 else None


def _earnings_quality_intelligence(
    info: Dict[str, Any],
    financial_trends: Dict[str, Any],
    cash_flow: Optional[pd.DataFrame],
) -> Dict[str, Any]:
    """Align cash generation and capital-allocation rows by reported fiscal period."""
    base_annual = financial_trends.get("annual") or []
    annual: List[Dict[str, Any]] = []
    for base in base_annual:
        period_label = base.get("period")
        period = next(
            (
                column for column in cash_flow.columns
                if _provider_date(column) == period_label
            ),
            None,
        ) if cash_flow is not None and not cash_flow.empty else None

        dividends_raw = _statement_value(
            cash_flow,
            ("Cash Dividends Paid", "Common Stock Dividend Paid", "Common Stock Dividend Payments"),
            period,
        )
        repurchases_raw = _statement_value(
            cash_flow,
            ("Repurchase Of Capital Stock", "Common Stock Issuance Or Purchase", "Repurchase Of Stock"),
            period,
        )
        stock_issuance_raw = _statement_value(
            cash_flow,
            ("Issuance Of Capital Stock", "Common Stock Issuance"),
            period,
        )
        net_stock_issuance = _statement_value(cash_flow, ("Net Common Stock Issuance",), period)
        debt_repayment_raw = _statement_value(
            cash_flow,
            ("Repayment Of Debt", "Long Term Debt Payments"),
            period,
        )
        debt_issuance_raw = _statement_value(
            cash_flow,
            ("Issuance Of Debt", "Long Term Debt Issuance"),
            period,
        )
        net_debt_issuance = _statement_value(
            cash_flow,
            ("Net Issuance Payments Of Debt", "Net Long Term Debt Issuance"),
            period,
        )
        net_income = base.get("netIncome")
        operating_cash_flow = base.get("operatingCashFlow")
        free_cash_flow = base.get("freeCashFlow")
        capital_expenditure = _statement_outflow(base.get("capitalExpenditure"))
        dividends_paid = _statement_outflow(dividends_raw)
        share_repurchases = _statement_outflow(repurchases_raw)
        share_issuance = _statement_inflow(stock_issuance_raw)
        debt_repayment = _statement_outflow(debt_repayment_raw)
        debt_issuance = _statement_inflow(debt_issuance_raw)
        shareholder_returns = (
            _round((dividends_paid or 0) + (share_repurchases or 0), 0)
            if dividends_paid is not None or share_repurchases is not None else None
        )
        operating_conversion = (
            _safe_margin(operating_cash_flow, net_income)
            if net_income is not None and net_income > 0 else None
        )
        free_cash_conversion = (
            _safe_margin(free_cash_flow, net_income)
            if net_income is not None and net_income > 0 else None
        )
        returns_to_fcf = (
            _safe_margin(shareholder_returns, free_cash_flow)
            if free_cash_flow is not None and free_cash_flow > 0 else None
        )
        capex_to_ocf = (
            _safe_margin(capital_expenditure, operating_cash_flow)
            if operating_cash_flow is not None and operating_cash_flow > 0 else None
        )
        evidence = [
            net_income, operating_cash_flow, free_cash_flow, capital_expenditure,
            dividends_paid, share_repurchases, share_issuance, debt_repayment,
            debt_issuance, net_stock_issuance, net_debt_issuance,
        ]
        if not any(value is not None for value in evidence):
            continue
        annual.append({
            "period": period_label,
            "netIncome": net_income,
            "operatingCashFlow": operating_cash_flow,
            "freeCashFlow": free_cash_flow,
            "earningsCashGap": (
                _round(operating_cash_flow - net_income, 0)
                if operating_cash_flow is not None and net_income is not None else None
            ),
            "operatingCashConversionPercent": operating_conversion,
            "freeCashFlowConversionPercent": free_cash_conversion,
            "capitalExpenditure": capital_expenditure,
            "capitalExpenditureToOperatingCashFlowPercent": capex_to_ocf,
            "dividendsPaid": dividends_paid,
            "shareRepurchases": share_repurchases,
            "shareIssuance": share_issuance,
            "netCommonStockIssuance": net_stock_issuance,
            "shareholderCashReturns": shareholder_returns,
            "shareholderReturnsToFreeCashFlowPercent": returns_to_fcf,
            "freeCashFlowAfterShareholderReturns": (
                _round(free_cash_flow - shareholder_returns, 0)
                if free_cash_flow is not None and shareholder_returns is not None else None
            ),
            "debtRepayment": debt_repayment,
            "debtIssuance": debt_issuance,
            "netDebtIssuance": net_debt_issuance,
            "conversionBasis": (
                "positive reported net income"
                if net_income is not None and net_income > 0 else
                "not meaningful because reported net income is non-positive"
                if net_income is not None else "net income unavailable"
            ),
        })

    if not annual:
        return {
            "status": "unavailable",
            "coverageLevel": "unavailable",
            "annual": [],
            "summary": {},
            "source": "Yahoo Finance company cash-flow and income statements via yfinance",
            "method": "No comparable annual income/cash-flow periods were returned.",
            "disclaimer": "FinTrack does not estimate missing cash-flow or capital-allocation rows.",
        }

    latest = annual[-1]
    sector = str(info.get("sector") or "")
    industry = str(info.get("industry") or "")
    financial_sector_caution = (
        "financial" in sector.lower()
        or any(term in industry.lower() for term in ("bank", "insurance", "credit", "capital markets"))
    )
    cash_periods = [item for item in annual if item.get("operatingCashFlow") is not None]
    positive_fcf_periods = [item for item in annual if item.get("freeCashFlow") is not None and item["freeCashFlow"] > 0]
    allocation_components = [
        latest.get("dividendsPaid"), latest.get("shareRepurchases"), latest.get("shareIssuance"),
        latest.get("debtRepayment"), latest.get("debtIssuance"),
    ]
    latest_core = all(latest.get(key) is not None for key in ("netIncome", "operatingCashFlow", "freeCashFlow"))
    coverage_level = "broad" if len(cash_periods) >= 3 and latest_core and any(value is not None for value in allocation_components) else "partial"
    return {
        "status": "available",
        "coverageLevel": coverage_level,
        "currency": info.get("currency"),
        "sector": sector or None,
        "industry": industry or None,
        "financialSectorCaution": financial_sector_caution,
        "annual": annual,
        "summary": {
            "latestPeriod": latest.get("period"),
            "periodCount": len(annual),
            "latestOperatingCashConversionPercent": latest.get("operatingCashConversionPercent"),
            "latestFreeCashFlowConversionPercent": latest.get("freeCashFlowConversionPercent"),
            "latestEarningsCashGap": latest.get("earningsCashGap"),
            "latestCapitalExpenditure": latest.get("capitalExpenditure"),
            "latestCapitalExpenditureToOperatingCashFlowPercent": latest.get("capitalExpenditureToOperatingCashFlowPercent"),
            "latestShareholderCashReturns": latest.get("shareholderCashReturns"),
            "latestShareholderReturnsToFreeCashFlowPercent": latest.get("shareholderReturnsToFreeCashFlowPercent"),
            "latestFreeCashFlowAfterShareholderReturns": latest.get("freeCashFlowAfterShareholderReturns"),
            "latestNetCommonStockIssuance": latest.get("netCommonStockIssuance"),
            "latestNetDebtIssuance": latest.get("netDebtIssuance"),
            "positiveFreeCashFlowPeriods": len(positive_fcf_periods),
            "freeCashFlowPeriodCount": sum(item.get("freeCashFlow") is not None for item in annual),
        },
        "source": "Yahoo Finance annual company cash-flow and income statements via yfinance",
        "method": "FinTrack aligns reported fiscal periods, divides operating/free cash flow by positive reported net income, and separates dividends, repurchases, issuance and debt flows. Positive reversals in outflow rows are not reclassified as spending.",
        "disclaimer": (
            "Cash conversion is descriptive, not an accounting-quality score. Statements can be restated and missing rows are not zero. "
            + ("For financial institutions, debt and operating cash-flow classifications reflect the business model and are not directly comparable with industrial companies. " if financial_sector_caution else "")
            + "Capital allocation evidence is not a standalone investment signal or recommendation."
        ),
    }


def _safe_ratio(numerator: Any, denominator: Any, digits: int = 3) -> Optional[float]:
    numerator_value = _round(numerator, 6)
    denominator_value = _round(denominator, 6)
    if numerator_value is None or denominator_value in (None, 0):
        return None
    return _round(numerator_value / denominator_value, digits)


def _profitability_returns_intelligence(
    info: Dict[str, Any],
    income_statement: Optional[pd.DataFrame],
    balance_sheet: Optional[pd.DataFrame],
) -> Dict[str, Any]:
    """Calculate statement-aligned margins, returns and capital efficiency.

    Return ratios require both beginning and ending balance-sheet values. This
    avoids presenting a year-end balance as if it represented capital employed
    throughout the fiscal period.
    """
    frames = [
        frame for frame in (income_statement, balance_sheet)
        if frame is not None and not frame.empty
    ]
    if not frames:
        return {
            "status": "unavailable",
            "coverageLevel": "unavailable",
            "annual": [],
            "summary": {},
            "source": "Yahoo Finance annual company income statements and balance sheets via yfinance",
            "method": "No annual income-statement or balance-sheet periods were returned.",
            "disclaimer": "FinTrack does not estimate missing profitability or return-on-capital rows.",
        }

    sector = str(info.get("sector") or "")
    industry = str(info.get("industry") or "")
    financial_sector_caution = (
        "financial" in sector.lower()
        or any(term in industry.lower() for term in ("bank", "insurance", "credit", "capital markets"))
    )
    periods = sorted({period for frame in frames for period in frame.columns}, key=pd.Timestamp)[-5:]
    annual: List[Dict[str, Any]] = []
    for period in periods:
        revenue = _statement_value(income_statement, ("Total Revenue", "Operating Revenue"), period)
        gross_profit = _statement_value(income_statement, ("Gross Profit",), period)
        operating_income = _statement_value(income_statement, ("Operating Income",), period)
        ebit = _statement_value(income_statement, ("EBIT", "Operating Income"), period)
        net_income = _statement_value(
            income_statement,
            ("Net Income", "Net Income Common Stockholders", "Net Income Including Noncontrolling Interests"),
            period,
        )
        pretax_income = _statement_value(income_statement, ("Pretax Income", "Income Before Tax"), period)
        tax_provision = _statement_value(income_statement, ("Tax Provision", "Income Tax Expense"), period)
        total_assets = _statement_value(balance_sheet, ("Total Assets",), period)
        equity = _statement_value(
            balance_sheet,
            ("Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"),
            period,
        )
        total_debt = _statement_value(balance_sheet, ("Total Debt",), period)
        liquid_funds = _statement_value(
            balance_sheet,
            ("Cash Cash Equivalents And Short Term Investments", "Cash And Short Term Investments"),
            period,
        )
        liquidity_basis = "cash, cash equivalents and short-term investments"
        if liquid_funds is None:
            liquid_funds = _statement_value(
                balance_sheet,
                ("Cash And Cash Equivalents", "Cash Financial", "Cash"),
                period,
            )
            liquidity_basis = "cash and cash equivalents only"
        effective_tax_rate = None
        if pretax_income is not None and pretax_income > 0 and tax_provision is not None and tax_provision >= 0:
            candidate_rate = _safe_margin(tax_provision, pretax_income)
            if candidate_rate is not None and 0 <= candidate_rate <= 50:
                effective_tax_rate = candidate_rate
        invested_capital = (
            _round(total_debt + equity - liquid_funds, 0)
            if total_debt is not None and equity is not None and liquid_funds is not None else None
        )
        evidence = (
            revenue, gross_profit, operating_income, ebit, net_income, pretax_income,
            tax_provision, total_assets, equity, total_debt, liquid_funds,
        )
        if not any(value is not None for value in evidence):
            continue
        annual.append({
            "period": _provider_date(period),
            "revenue": revenue,
            "grossProfit": gross_profit,
            "operatingIncome": operating_income,
            "ebit": ebit,
            "netIncome": net_income,
            "pretaxIncome": pretax_income,
            "taxProvision": tax_provision,
            "effectiveTaxRatePercent": effective_tax_rate,
            "totalAssets": total_assets,
            "stockholdersEquity": equity,
            "totalDebt": total_debt,
            "liquidFunds": liquid_funds,
            "liquidityBasis": liquidity_basis if liquid_funds is not None else "unavailable",
            "investedCapital": invested_capital if invested_capital is None or invested_capital > 0 else None,
            "grossMarginPercent": _safe_margin(gross_profit, revenue),
            "operatingMarginPercent": _safe_margin(operating_income, revenue),
            "netMarginPercent": _safe_margin(net_income, revenue),
        })

    if not annual:
        return {
            "status": "unavailable",
            "coverageLevel": "unavailable",
            "annual": [],
            "summary": {},
            "source": "Yahoo Finance annual company income statements and balance sheets via yfinance",
            "method": "No usable aligned profitability periods were returned.",
            "disclaimer": "FinTrack does not estimate missing profitability or return-on-capital rows.",
        }

    for index, item in enumerate(annual):
        previous = annual[index - 1] if index else {}
        previous_balance_comparable = False
        if item.get("period") and previous.get("period"):
            period_gap = (date.fromisoformat(item["period"]) - date.fromisoformat(previous["period"])).days
            previous_balance_comparable = 270 <= period_gap <= 460
        average_assets = (
            _round((item["totalAssets"] + previous["totalAssets"]) / 2, 2)
            if previous_balance_comparable and item.get("totalAssets") is not None and item["totalAssets"] > 0
            and previous.get("totalAssets") is not None and previous["totalAssets"] > 0 else None
        )
        average_equity = (
            _round((item["stockholdersEquity"] + previous["stockholdersEquity"]) / 2, 2)
            if previous_balance_comparable and item.get("stockholdersEquity") is not None and item["stockholdersEquity"] > 0
            and previous.get("stockholdersEquity") is not None and previous["stockholdersEquity"] > 0 else None
        )
        average_invested_capital = (
            _round((item["investedCapital"] + previous["investedCapital"]) / 2, 2)
            if previous_balance_comparable and item.get("investedCapital") is not None and item["investedCapital"] > 0
            and previous.get("investedCapital") is not None and previous["investedCapital"] > 0 else None
        )
        nopat = (
            _round(item["ebit"] * (1 - item["effectiveTaxRatePercent"] / 100), 0)
            if not financial_sector_caution and item.get("ebit") is not None
            and item.get("effectiveTaxRatePercent") is not None else None
        )
        item.update({
            "previousBalanceComparable": previous_balance_comparable,
            "averageTotalAssets": average_assets,
            "averageStockholdersEquity": average_equity,
            "averageInvestedCapital": average_invested_capital,
            "returnOnAssetsPercent": _safe_margin(item.get("netIncome"), average_assets),
            "returnOnEquityPercent": _safe_margin(item.get("netIncome"), average_equity),
            "assetTurnoverRatio": _safe_ratio(item.get("revenue"), average_assets),
            "equityMultiplierRatio": _safe_ratio(average_assets, average_equity),
            "nopat": nopat,
            "returnOnInvestedCapitalPercent": (
                _safe_margin(nopat, average_invested_capital)
                if not financial_sector_caution else None
            ),
        })
        for metric, output in (
            ("grossMarginPercent", "grossMarginChangePoints"),
            ("operatingMarginPercent", "operatingMarginChangePoints"),
            ("netMarginPercent", "netMarginChangePoints"),
            ("returnOnAssetsPercent", "returnOnAssetsChangePoints"),
            ("returnOnEquityPercent", "returnOnEquityChangePoints"),
            ("returnOnInvestedCapitalPercent", "returnOnInvestedCapitalChangePoints"),
        ):
            item[output] = (
                _round(item[metric] - previous[metric], 2)
                if item.get(metric) is not None and previous.get(metric) is not None else None
            )

    latest = annual[-1]
    coverage = {
        "margins": any(latest.get(key) is not None for key in ("grossMarginPercent", "operatingMarginPercent", "netMarginPercent")),
        "returns": any(latest.get(key) is not None for key in ("returnOnAssetsPercent", "returnOnEquityPercent")),
        "efficiency": latest.get("assetTurnoverRatio") is not None,
        "roic": latest.get("returnOnInvestedCapitalPercent") is not None,
    }
    broad_components = (coverage["margins"] and coverage["returns"] and coverage["efficiency"])
    if not financial_sector_caution:
        broad_components = broad_components and coverage["roic"]
    return {
        "status": "available",
        "coverageLevel": "broad" if len(annual) >= 3 and broad_components else "partial",
        "coverage": coverage,
        "currency": info.get("currency"),
        "sector": sector or None,
        "industry": industry or None,
        "financialSectorCaution": financial_sector_caution,
        "annual": annual,
        "summary": {
            "latestPeriod": latest.get("period"),
            "periodCount": len(annual),
            "latestGrossMarginPercent": latest.get("grossMarginPercent"),
            "latestOperatingMarginPercent": latest.get("operatingMarginPercent"),
            "latestNetMarginPercent": latest.get("netMarginPercent"),
            "latestGrossMarginChangePoints": latest.get("grossMarginChangePoints"),
            "latestOperatingMarginChangePoints": latest.get("operatingMarginChangePoints"),
            "latestNetMarginChangePoints": latest.get("netMarginChangePoints"),
            "latestReturnOnAssetsPercent": latest.get("returnOnAssetsPercent"),
            "latestReturnOnEquityPercent": latest.get("returnOnEquityPercent"),
            "latestReturnOnInvestedCapitalPercent": latest.get("returnOnInvestedCapitalPercent"),
            "latestReturnOnAssetsChangePoints": latest.get("returnOnAssetsChangePoints"),
            "latestReturnOnEquityChangePoints": latest.get("returnOnEquityChangePoints"),
            "latestReturnOnInvestedCapitalChangePoints": latest.get("returnOnInvestedCapitalChangePoints"),
            "latestAssetTurnoverRatio": latest.get("assetTurnoverRatio"),
            "latestEquityMultiplierRatio": latest.get("equityMultiplierRatio"),
            "latestEffectiveTaxRatePercent": latest.get("effectiveTaxRatePercent"),
            "latestNopat": latest.get("nopat"),
            "latestAverageInvestedCapital": latest.get("averageInvestedCapital"),
            "operatingMarginTrend": _series_trend([item.get("operatingMarginPercent") for item in annual]),
            "returnOnEquityTrend": _series_trend([item.get("returnOnEquityPercent") for item in annual]),
            "returnOnInvestedCapitalTrend": _series_trend([item.get("returnOnInvestedCapitalPercent") for item in annual]),
        },
        "source": "Yahoo Finance annual company income statements and balance sheets via yfinance",
        "method": "FinTrack aligns reported fiscal periods; margins use reported revenue, return ratios require comparable adjacent fiscal periods and use average beginning and ending assets/equity, and industrial ROIC uses NOPAT divided by average debt plus equity minus disclosed liquid funds.",
        "disclaimer": (
            "These are descriptive accounting ratios, not a profitability score, moat rating or investment recommendation. Statements can be restated and missing rows are not zero. "
            + ("For financial institutions, ROA and ROE remain descriptive but industrial ROIC is intentionally withheld because debt and cash are operating inputs. " if financial_sector_caution else "ROIC depends on a provider-derived effective tax rate and the disclosed liquid-funds basis; it is an approximation, not company-reported ROIC. ")
            + "Cross-company comparisons require consistent fiscal periods and accounting policies."
        ),
    }


def _liquidity_debt_intelligence(
    info: Dict[str, Any],
    income_statement: Optional[pd.DataFrame],
    balance_sheet: Optional[pd.DataFrame],
) -> Dict[str, Any]:
    """Build aligned balance-sheet liquidity and debt-capacity evidence."""
    if balance_sheet is None or balance_sheet.empty:
        return {
            "status": "unavailable",
            "coverageLevel": "unavailable",
            "annual": [],
            "summary": {},
            "source": "Yahoo Finance company balance sheets via yfinance",
            "method": "No annual balance-sheet periods were returned.",
            "disclaimer": "FinTrack does not estimate missing liquidity or leverage rows.",
        }

    sector = str(info.get("sector") or "")
    industry = str(info.get("industry") or "")
    financial_sector_caution = (
        "financial" in sector.lower()
        or any(term in industry.lower() for term in ("bank", "insurance", "credit", "capital markets"))
    )
    periods = sorted(balance_sheet.columns, key=pd.Timestamp)[-5:]
    annual: List[Dict[str, Any]] = []
    for period in periods:
        liquid_funds = _statement_value(
            balance_sheet,
            ("Cash Cash Equivalents And Short Term Investments", "Cash And Short Term Investments"),
            period,
        )
        liquidity_basis = "cash, cash equivalents and short-term investments"
        if liquid_funds is None:
            liquid_funds = _statement_value(
                balance_sheet,
                ("Cash And Cash Equivalents", "Cash Financial", "Cash"),
                period,
            )
            liquidity_basis = "cash and cash equivalents only"
        cash_only = _statement_value(
            balance_sheet,
            ("Cash And Cash Equivalents", "Cash Financial", "Cash"),
            period,
        )
        total_debt = _statement_value(balance_sheet, ("Total Debt",), period)
        provider_net_debt = _statement_value(balance_sheet, ("Net Debt",), period)
        current_assets = _statement_value(balance_sheet, ("Current Assets", "Total Current Assets"), period)
        current_liabilities = _statement_value(
            balance_sheet,
            ("Current Liabilities", "Total Current Liabilities"),
            period,
        )
        working_capital = _statement_value(balance_sheet, ("Working Capital",), period)
        if working_capital is None and current_assets is not None and current_liabilities is not None:
            working_capital = _round(current_assets - current_liabilities, 0)
        equity = _statement_value(
            balance_sheet,
            ("Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"),
            period,
        )
        total_assets = _statement_value(balance_sheet, ("Total Assets",), period)
        total_liabilities = _statement_value(
            balance_sheet,
            ("Total Liabilities Net Minority Interest", "Total Liabilities"),
            period,
        )
        inventory = _statement_value(balance_sheet, ("Inventory",), period)
        receivables = _statement_value(balance_sheet, ("Accounts Receivable", "Receivables"), period)
        ebit = _statement_value(income_statement, ("EBIT", "Operating Income"), period)
        ebitda = _statement_value(income_statement, ("EBITDA", "Normalized EBITDA"), period)
        interest_expense = _statement_value(
            income_statement,
            ("Interest Expense Non Operating", "Interest Expense"),
            period,
        )
        interest_expense_magnitude = abs(interest_expense) if interest_expense not in (None, 0) else interest_expense
        debt_after_liquid_funds = (
            _round(total_debt - liquid_funds, 0)
            if total_debt is not None and liquid_funds is not None else None
        )
        provider_net_debt_difference = (
            _round(provider_net_debt - debt_after_liquid_funds, 0)
            if provider_net_debt is not None and debt_after_liquid_funds is not None else None
        )
        mismatch_denominator = max(abs(provider_net_debt or 0), abs(debt_after_liquid_funds or 0), 1)
        provider_basis_mismatch = (
            provider_net_debt_difference is not None
            and abs(provider_net_debt_difference) / mismatch_denominator > 0.05
        )
        evidence = (
            liquid_funds, total_debt, provider_net_debt, current_assets, current_liabilities,
            working_capital, equity, total_assets, total_liabilities, ebit, ebitda,
            interest_expense,
        )
        if not any(value is not None for value in evidence):
            continue
        annual.append({
            "period": _provider_date(period),
            "liquidFunds": liquid_funds,
            "cashAndCashEquivalents": cash_only,
            "liquidityBasis": liquidity_basis,
            "totalDebt": total_debt,
            "providerNetDebt": provider_net_debt,
            "debtAfterLiquidFunds": debt_after_liquid_funds,
            "providerNetDebtDifference": provider_net_debt_difference,
            "providerNetDebtBasisMismatch": provider_basis_mismatch,
            "balancePosition": (
                "net cash after liquid funds" if debt_after_liquid_funds is not None and debt_after_liquid_funds < 0 else
                "net debt after liquid funds" if debt_after_liquid_funds is not None and debt_after_liquid_funds > 0 else
                "balanced debt and liquid funds" if debt_after_liquid_funds == 0 else "unavailable"
            ),
            "currentAssets": current_assets,
            "currentLiabilities": current_liabilities,
            "workingCapital": working_capital,
            "currentRatio": _safe_ratio(current_assets, current_liabilities),
            "stockholdersEquity": equity,
            "totalAssets": total_assets,
            "totalLiabilities": total_liabilities,
            "totalDebtToEquityRatio": _safe_ratio(total_debt, equity),
            "totalDebtToAssetsPercent": _safe_margin(total_debt, total_assets),
            "liabilitiesToAssetsPercent": _safe_margin(total_liabilities, total_assets),
            "liquidFundsToDebtPercent": _safe_margin(liquid_funds, total_debt),
            "ebit": ebit,
            "ebitda": ebitda,
            "interestExpense": interest_expense_magnitude,
            "interestCoverageRatio": (
                _safe_ratio(ebit, interest_expense_magnitude)
                if not financial_sector_caution and ebit is not None and ebit > 0 and interest_expense_magnitude not in (None, 0)
                else None
            ),
            "debtToEbitdaRatio": (
                _safe_ratio(total_debt, ebitda)
                if not financial_sector_caution and ebitda is not None and ebitda > 0
                else None
            ),
            "inventory": inventory,
            "accountsReceivable": receivables,
        })

    if not annual:
        return {
            "status": "unavailable",
            "coverageLevel": "unavailable",
            "annual": [],
            "summary": {},
            "source": "Yahoo Finance company balance sheets via yfinance",
            "method": "No usable annual liquidity or leverage rows were returned.",
            "disclaimer": "FinTrack does not estimate missing liquidity or leverage rows.",
        }

    for index, item in enumerate(annual):
        previous = annual[index - 1] if index else {}
        item["liquidFundsYoYPercent"] = _safe_percent_change(item.get("liquidFunds"), previous.get("liquidFunds"))
        item["totalDebtYoYPercent"] = _safe_percent_change(item.get("totalDebt"), previous.get("totalDebt"))
        item["workingCapitalChange"] = (
            _round(item["workingCapital"] - previous["workingCapital"], 0)
            if item.get("workingCapital") is not None and previous.get("workingCapital") is not None else None
        )

    latest = annual[-1]
    basis_mismatch_periods = [item["period"] for item in annual if item.get("providerNetDebtBasisMismatch")]
    coverage_components = {
        "liquidFunds": latest.get("liquidFunds") is not None,
        "debt": latest.get("totalDebt") is not None,
        "workingCapital": latest.get("workingCapital") is not None,
        "capitalStructure": latest.get("stockholdersEquity") is not None and latest.get("totalAssets") is not None,
        "interestCoverage": latest.get("interestCoverageRatio") is not None,
    }
    evidence_count = sum(coverage_components.values())
    return {
        "status": "available",
        "coverageLevel": "broad" if len(annual) >= 3 and evidence_count >= 4 else "partial",
        "coverage": coverage_components,
        "currency": info.get("currency"),
        "sector": sector or None,
        "industry": industry or None,
        "financialSectorCaution": financial_sector_caution,
        "annual": annual,
        "summary": {
            "latestPeriod": latest.get("period"),
            "periodCount": len(annual),
            "latestLiquidFunds": latest.get("liquidFunds"),
            "latestLiquidityBasis": latest.get("liquidityBasis"),
            "latestTotalDebt": latest.get("totalDebt"),
            "latestDebtAfterLiquidFunds": latest.get("debtAfterLiquidFunds"),
            "latestBalancePosition": latest.get("balancePosition"),
            "latestCurrentRatio": latest.get("currentRatio"),
            "latestWorkingCapital": latest.get("workingCapital"),
            "latestTotalDebtToEquityRatio": latest.get("totalDebtToEquityRatio"),
            "latestTotalDebtToAssetsPercent": latest.get("totalDebtToAssetsPercent"),
            "latestLiquidFundsToDebtPercent": latest.get("liquidFundsToDebtPercent"),
            "latestInterestCoverageRatio": latest.get("interestCoverageRatio"),
            "latestDebtToEbitdaRatio": latest.get("debtToEbitdaRatio"),
            "liquidFundsTrend": _series_trend([item.get("liquidFunds") for item in annual]),
            "totalDebtTrend": _series_trend([item.get("totalDebt") for item in annual]),
            "providerNetDebtBasisMismatchPeriods": basis_mismatch_periods,
        },
        "source": "Yahoo Finance annual balance sheets and income statements via yfinance",
        "method": "FinTrack aligns reported fiscal periods, calculates debt after liquid funds as total debt minus the disclosed liquidity basis, and keeps the provider net-debt field separate. Current ratio, capital-structure and coverage ratios use only returned statement rows.",
        "disclaimer": (
            "This is descriptive balance-sheet evidence, not a credit rating or synthetic health score. Statements can be restated and missing rows are not zero. "
            + ("For financial institutions, debt, liquidity and interest classifications reflect the business model; industrial-company coverage ratios are intentionally withheld. " if financial_sector_caution else "")
            + "Debt capacity also depends on maturities, covenants and cash-flow stability that may not be present in these provider statements."
        ),
    }


def _normalize_holder_rows(frame: Optional[pd.DataFrame], limit: int = 8) -> List[Dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    records = []
    for _, row in frame.head(limit).iterrows():
        holder = str(row.get("Holder") or "").strip()
        if not holder:
            continue
        records.append({
            "holder": holder,
            "dateReported": _provider_date(row.get("Date Reported")),
            "percentHeld": _percentage_from_fraction(row.get("pctHeld")),
            "shares": _round(row.get("Shares"), 0),
            "reportedValue": _round(row.get("Value"), 0),
            "positionChangePercent": _percentage_from_fraction(row.get("pctChange")),
        })
    return records


def _insider_transaction_type(text: Any, transaction: Any = None) -> str:
    normalized = f"{transaction or ''} {text or ''}".lower()
    if "sale" in normalized or "sell" in normalized:
        return "sale"
    if "purchase" in normalized or "buy" in normalized:
        return "purchase"
    if "award" in normalized or "grant" in normalized:
        return "award/grant"
    if "gift" in normalized:
        return "gift"
    return "other"


def _ownership_intelligence(
    major_holders: Optional[pd.DataFrame],
    institutional_holders: Optional[pd.DataFrame],
    mutual_fund_holders: Optional[pd.DataFrame],
    insider_transactions: Optional[pd.DataFrame],
    insider_purchases: Optional[pd.DataFrame],
    insider_roster: Optional[pd.DataFrame],
) -> Dict[str, Any]:
    major_values: Dict[str, Any] = {}
    if major_holders is not None and not major_holders.empty and "Value" in major_holders.columns:
        for index, value in major_holders["Value"].items():
            major_values[str(index)] = value
    major = {
        "insidersPercentHeld": _percentage_from_fraction(major_values.get("insidersPercentHeld")),
        "institutionsPercentHeld": _percentage_from_fraction(major_values.get("institutionsPercentHeld")),
        "institutionsFloatPercentHeld": _percentage_from_fraction(major_values.get("institutionsFloatPercentHeld")),
        "institutionsCount": int(_round(major_values.get("institutionsCount"), 0) or 0),
    }
    institutions = _normalize_holder_rows(institutional_holders, 10)
    funds = _normalize_holder_rows(mutual_fund_holders, 10)

    purchase_summary: Dict[str, Dict[str, Any]] = {}
    if insider_purchases is not None and not insider_purchases.empty:
        label_column = "Insider Purchases Last 6m"
        if label_column in insider_purchases.columns:
            for _, row in insider_purchases.iterrows():
                label = str(row.get(label_column) or "").strip().lower()
                if label:
                    purchase_summary[label] = {
                        "shares": _round(row.get("Shares"), 6 if label.startswith("%") else 0),
                        "transactions": int(_round(row.get("Trans"), 0) or 0),
                    }
    purchases = purchase_summary.get("purchases", {})
    sales = purchase_summary.get("sales", {})
    net = purchase_summary.get("net shares purchased (sold)", {})
    total_held = purchase_summary.get("total insider shares held", {})
    percent_net = purchase_summary.get("% net shares purchased (sold)", {})
    insider_summary = {
        "period": "last 6 months",
        "purchaseShares": purchases.get("shares"),
        "purchaseTransactions": purchases.get("transactions", 0),
        "saleShares": sales.get("shares"),
        "saleTransactions": sales.get("transactions", 0),
        "netSharesPurchased": net.get("shares"),
        "totalInsiderSharesHeld": total_held.get("shares"),
        "netSharesPercent": _percentage_from_fraction(percent_net.get("shares")),
        "netActivity": (
            "net buying" if (net.get("shares") or 0) > 0 else
            "net selling" if (net.get("shares") or 0) < 0 else "balanced/no reported net change"
        ),
    }

    transactions = []
    if insider_transactions is not None and not insider_transactions.empty:
        sorted_transactions = insider_transactions.copy()
        if "Start Date" in sorted_transactions.columns:
            sorted_transactions = sorted_transactions.sort_values("Start Date", ascending=False)
        for _, row in sorted_transactions.head(10).iterrows():
            transactions.append({
                "date": _provider_date(row.get("Start Date")),
                "insider": str(row.get("Insider") or "Unknown").strip(),
                "position": str(row.get("Position") or "Not reported").strip(),
                "type": _insider_transaction_type(row.get("Text"), row.get("Transaction")),
                "shares": _round(row.get("Shares"), 0),
                "reportedValue": _round(row.get("Value"), 0),
                "description": str(row.get("Text") or "Transaction detail unavailable").strip(),
                "ownership": str(row.get("Ownership") or "Not reported").strip(),
            })

    roster = []
    if insider_roster is not None and not insider_roster.empty:
        for _, row in insider_roster.head(8).iterrows():
            roster.append({
                "name": str(row.get("Name") or "Unknown").strip(),
                "position": str(row.get("Position") or "Not reported").strip(),
                "latestTransaction": str(row.get("Most Recent Transaction") or "Not reported").strip(),
                "latestTransactionDate": _provider_date(row.get("Latest Transaction Date")),
                "sharesOwnedDirectly": _round(row.get("Shares Owned Directly"), 0),
            })

    top_institution_percent = _round(sum(float(item.get("percentHeld") or 0) for item in institutions), 2)
    top_fund_percent = _round(sum(float(item.get("percentHeld") or 0) for item in funds), 2)
    components = {
        "majorOwnership": any(value not in (None, 0) for value in major.values()),
        "institutionalHolders": bool(institutions),
        "mutualFundHolders": bool(funds),
        "insiderActivity": bool(transactions) or bool(purchase_summary),
    }
    evidence_count = sum(components.values())
    if not evidence_count:
        return {
            "status": "unavailable",
            "majorOwnership": major,
            "institutionalHolders": [],
            "mutualFundHolders": [],
            "insiderSummary": insider_summary,
            "recentInsiderTransactions": [],
            "insiderRoster": [],
            "coverage": components,
            "source": "Yahoo Finance holder and insider datasets via yfinance",
            "method": "No ownership dataset was returned for this listing.",
            "disclaimer": "FinTrack does not estimate missing ownership or insider activity.",
        }
    return {
        "status": "available",
        "coverageLevel": "broad" if evidence_count >= 3 else "partial",
        "coverage": components,
        "majorOwnership": major,
        "institutionalHolders": institutions,
        "mutualFundHolders": funds,
        "concentration": {
            "returnedInstitutionCount": len(institutions),
            "topInstitutionsPercentHeld": top_institution_percent,
            "returnedFundCount": len(funds),
            "topFundsPercentHeld": top_fund_percent,
        },
        "insiderSummary": insider_summary,
        "recentInsiderTransactions": transactions,
        "insiderRoster": roster,
        "latestInsiderTransactionDate": next((item["date"] for item in transactions if item.get("date")), None),
        "source": "Yahoo Finance holder and insider datasets via yfinance",
        "method": "Provider ownership percentages and top-holder tables are normalized; returned-holder concentration and six-month insider net activity are calculated without extrapolating missing holders.",
        "disclaimer": "Holder reports can be delayed, duplicated across fund families or unavailable by exchange. Insider transactions need context and are not a standalone bullish/bearish signal or investment advice.",
    }


def _fifty_two_week_position(price: Any, low: Any, high: Any) -> Optional[float]:
    current = _round(price, 6)
    lower = _round(low, 6)
    upper = _round(high, 6)
    if current is None or lower is None or upper is None or upper <= lower:
        return None
    return _round(max(0.0, min(100.0, ((current - lower) / (upper - lower)) * 100)), 1)


def _company_currency(info: Dict[str, Any], snapshot: Dict[str, Any]) -> str:
    """Prefer provider ISO currency metadata over a generic board fallback."""
    for value in (info.get("currency"), snapshot.get("currency")):
        raw_value = str(value or "").strip()
        if re.fullmatch(r"[A-Z]{3}", raw_value):
            return raw_value
    # Some exchanges publish a non-ISO trading unit such as GBp (pence).
    # Preserve that label for plain-number rendering instead of relabelling it GBP.
    provider_value = str(info.get("currency") or "").strip()
    if provider_value and len(provider_value) <= 20:
        return provider_value
    return "Local currency"


def _provider_date(value: Any) -> Optional[str]:
    if isinstance(value, (list, tuple)):
        for item in value:
            normalized = _provider_date(item)
            if normalized:
                return normalized
        return None
    if value is None:
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        try:
            return datetime.fromtimestamp(float(value), timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.date().isoformat() if isinstance(value, (datetime, pd.Timestamp)) else value.isoformat()
    match = re.match(r"(\d{4}-\d{2}-\d{2})", str(value))
    return match.group(1) if match else None


def _event_status(event_date: Optional[str], today: date) -> str:
    if not event_date:
        return "date-unavailable"
    parsed = date.fromisoformat(event_date)
    if parsed >= today:
        return "upcoming"
    return "recent" if (today - parsed).days <= 30 else "completed"


def _normalized_earnings_history(earnings_dates: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    if earnings_dates is None or earnings_dates.empty:
        return []
    records = []
    for index, row in earnings_dates.iterrows():
        event_date = _provider_date(index)
        if not event_date:
            continue
        estimate = _round(row.get("EPS Estimate"))
        reported = _round(row.get("Reported EPS"))
        surprise = _round(row.get("Surprise(%)"))
        records.append({
            "date": event_date,
            "epsEstimate": estimate,
            "reportedEps": reported,
            "surprisePercent": surprise,
            "status": "reported" if reported is not None else "estimate",
        })
    records.sort(key=lambda item: item["date"], reverse=True)
    return records


def _company_catalysts(
    info: Dict[str, Any],
    calendar: Dict[str, Any],
    earnings_dates: Optional[pd.DataFrame],
    current_price: Any,
    *,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    today = today or datetime.now(timezone.utc).date()
    earnings_history = _normalized_earnings_history(earnings_dates)
    future_earnings = next(
        (item["date"] for item in reversed(earnings_history) if item["status"] == "estimate" and item["date"] >= today.isoformat()),
        None,
    )
    next_earnings = (
        _provider_date(calendar.get("Earnings Date"))
        or future_earnings
        or _provider_date(info.get("earningsTimestampStart"))
        or _provider_date(info.get("earningsTimestamp"))
    )
    ex_dividend = _provider_date(calendar.get("Ex-Dividend Date")) or _provider_date(info.get("exDividendDate"))
    dividend_payment = _provider_date(calendar.get("Dividend Date")) or _provider_date(info.get("dividendDate"))
    events = [
        {"type": "earnings", "label": "Earnings release", "date": next_earnings},
        {"type": "ex-dividend", "label": "Ex-dividend date", "date": ex_dividend},
        {"type": "dividend-payment", "label": "Dividend payment", "date": dividend_payment},
    ]
    events = [
        {**item, "status": _event_status(item["date"], today)}
        for item in events if item["date"]
    ]
    event_order = {"upcoming": 0, "recent": 1, "completed": 2, "date-unavailable": 3}
    events.sort(key=lambda item: (event_order.get(item["status"], 4), item["date"]))

    price = _round(current_price)
    target_mean = _round(info.get("targetMeanPrice"))
    target_gap = (
        _round(((target_mean / price) - 1) * 100, 2)
        if price and target_mean is not None else None
    )
    analyst_consensus = {
        "recommendation": str(info.get("recommendationKey") or "not_available").replace("_", " ").title(),
        "recommendationMean": _round(info.get("recommendationMean")),
        "analystCount": int(info.get("numberOfAnalystOpinions") or 0),
        "targetLow": _round(info.get("targetLowPrice")),
        "targetMean": target_mean,
        "targetMedian": _round(info.get("targetMedianPrice")),
        "targetHigh": _round(info.get("targetHighPrice")),
        "targetGapPercent": target_gap,
        "currentPrice": price,
    }
    reported_history = [item for item in earnings_history if item["status"] == "reported"][:5]
    surprises = [float(item["surprisePercent"]) for item in reported_history if item["surprisePercent"] is not None]
    surprise_summary = {
        "reportedQuarters": len(reported_history),
        "beats": sum(value > 0.05 for value in surprises),
        "misses": sum(value < -0.05 for value in surprises),
        "inLine": sum(-0.05 <= value <= 0.05 for value in surprises),
        "averageSurprisePercent": _round(float(np.mean(surprises)), 2) if surprises else None,
    }
    estimate = {
        "epsLow": _round(calendar.get("Earnings Low")),
        "epsAverage": _round(calendar.get("Earnings Average")),
        "epsHigh": _round(calendar.get("Earnings High")),
        "revenueLow": _round(calendar.get("Revenue Low"), 0),
        "revenueAverage": _round(calendar.get("Revenue Average"), 0),
        "revenueHigh": _round(calendar.get("Revenue High"), 0),
    }
    has_analyst_evidence = analyst_consensus["analystCount"] > 0 or any(
        analyst_consensus[key] is not None
        for key in ("targetLow", "targetMean", "targetMedian", "targetHigh", "recommendationMean")
    )
    has_estimate = any(value is not None for value in estimate.values())
    evidence_count = len(events) + int(has_analyst_evidence) + int(has_estimate) + len(reported_history)
    return {
        "status": "available" if evidence_count else "unavailable",
        "events": events,
        "analystConsensus": analyst_consensus,
        "nextEarningsEstimate": estimate,
        "earningsHistory": reported_history,
        "surpriseSummary": surprise_summary,
        "source": "Yahoo Finance calendar and analyst data via yfinance",
        "method": "Provider calendar, third-party analyst consensus and reported-vs-estimated EPS history are kept separate from FinTrack's ML outlook.",
        "disclaimer": "Calendar dates can change. Analyst targets and recommendations are external opinions, not FinTrack advice or guaranteed future prices.",
    }


def _positive_number(value: Any, digits: int = 6) -> Optional[float]:
    numeric = _round(value, digits)
    return numeric if numeric is not None and numeric > 0 else None


def _distribution_records(series: Optional[pd.Series]) -> List[Dict[str, Any]]:
    if series is None or not isinstance(series, pd.Series) or series.empty:
        return []
    records: List[Dict[str, Any]] = []
    for index, raw_value in series.items():
        event_date = _provider_date(index)
        value = _positive_number(raw_value)
        if not event_date or value is None:
            continue
        records.append({"date": event_date, "amountPerShare": value})
    records.sort(key=lambda item: item["date"], reverse=True)
    return records


def _split_records(series: Optional[pd.Series]) -> List[Dict[str, Any]]:
    if series is None or not isinstance(series, pd.Series) or series.empty:
        return []
    records: List[Dict[str, Any]] = []
    for index, raw_value in series.items():
        event_date = _provider_date(index)
        ratio = _positive_number(raw_value)
        if not event_date or ratio is None or math.isclose(ratio, 1.0):
            continue
        fraction = Fraction(ratio).limit_denominator(20)
        records.append({
            "date": event_date,
            "ratio": _round(ratio, 6),
            "displayRatio": f"{fraction.numerator}-for-{fraction.denominator}",
        })
    records.sort(key=lambda item: item["date"], reverse=True)
    return records


def _corporate_action_intelligence(
    info: Dict[str, Any],
    dividends: Optional[pd.Series],
    splits: Optional[pd.Series],
    capital_gains: Optional[pd.Series],
    catalyst_events: Optional[List[Dict[str, Any]]] = None,
    *,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Normalize distributions and splits while preserving missing-vs-zero evidence."""
    today = today or datetime.now(timezone.utc).date()
    dividend_records = _distribution_records(dividends)
    capital_gain_records = _distribution_records(capital_gains)
    split_records = _split_records(splits)

    annual_map: Dict[int, Dict[str, Any]] = {}
    for item in dividend_records:
        item_date = date.fromisoformat(item["date"])
        if item_date > today:
            continue
        bucket = annual_map.setdefault(item_date.year, {"total": 0.0, "paymentCount": 0})
        bucket["total"] += float(item["amountPerShare"])
        bucket["paymentCount"] += 1
    annual_dividends = [
        {
            "year": year,
            "totalPerShare": _round(values["total"], 6),
            "paymentCount": values["paymentCount"],
            "isPartialYear": year == today.year,
        }
        for year, values in sorted(annual_map.items(), reverse=True)
    ][:7]
    for index, item in enumerate(annual_dividends):
        previous = annual_dividends[index + 1] if index + 1 < len(annual_dividends) else None
        item["changePercent"] = (
            _safe_percent_change(item["totalPerShare"], previous["totalPerShare"])
            if previous and not item["isPartialYear"] and not previous["isPartialYear"] else None
        )

    trailing_start = today - timedelta(days=365)
    previous_start = today - timedelta(days=730)
    trailing = [
        item for item in dividend_records
        if trailing_start < date.fromisoformat(item["date"]) <= today
    ]
    previous = [
        item for item in dividend_records
        if previous_start < date.fromisoformat(item["date"]) <= trailing_start
    ]
    trailing_total = _round(sum(float(item["amountPerShare"]) for item in trailing), 6) if trailing else None
    previous_total = _round(sum(float(item["amountPerShare"]) for item in previous), 6) if previous else None

    completed_years = sorted(
        (item for item in annual_dividends if not item["isPartialYear"] and item["totalPerShare"] > 0),
        key=lambda item: item["year"],
    )
    completed_years = completed_years[-6:]
    dividend_cagr = None
    if len(completed_years) >= 2:
        first, last = completed_years[0], completed_years[-1]
        year_span = last["year"] - first["year"]
        if year_span > 0:
            dividend_cagr = _round(
                ((last["totalPerShare"] / first["totalPerShare"]) ** (1 / year_span) - 1) * 100,
                2,
            )

    upcoming_events = [
        item for item in (catalyst_events or [])
        if item.get("type") in {"ex-dividend", "dividend-payment"}
        and item.get("status") == "upcoming"
    ]
    snapshot = {
        # Current quote-summary yield and five-year average are percentage points.
        "currentYieldPercent": _positive_number(info.get("dividendYield"), 4),
        # Yahoo's trailing yield field is a fraction when populated.
        "trailingYieldPercent": (
            _percentage_from_fraction(info.get("trailingAnnualDividendYield"))
            if _positive_number(info.get("trailingAnnualDividendYield")) is not None else None
        ),
        "fiveYearAverageYieldPercent": _positive_number(info.get("fiveYearAvgDividendYield"), 4),
        "payoutRatioPercent": (
            _percentage_from_fraction(info.get("payoutRatio"))
            if _positive_number(info.get("payoutRatio")) is not None else None
        ),
        "providerTrailingAnnualRate": _positive_number(info.get("trailingAnnualDividendRate"), 6),
        "providerForwardAnnualRate": _positive_number(info.get("forwardAnnualDividendRate"), 6),
    }
    has_snapshot = any(value is not None for value in snapshot.values())
    status = "available" if dividend_records or split_records or capital_gain_records or upcoming_events or has_snapshot else "unavailable"
    coverage_components = sum(bool(value) for value in (
        dividend_records, split_records, capital_gain_records, upcoming_events, has_snapshot,
    ))
    return {
        "status": status,
        "coverageLevel": "broad" if coverage_components >= 3 else ("partial" if status == "available" else "unavailable"),
        "currency": info.get("currency"),
        "quoteType": info.get("quoteType"),
        "snapshot": snapshot,
        "summary": {
            "lastDividendDate": dividend_records[0]["date"] if dividend_records else None,
            "lastDividendAmountPerShare": dividend_records[0]["amountPerShare"] if dividend_records else None,
            "trailing12MonthTotalPerShare": trailing_total,
            "previous12MonthTotalPerShare": previous_total,
            "trailingChangePercent": _safe_percent_change(trailing_total, previous_total),
            "paymentsLast12Months": len(trailing),
            "completedYearDividendCagrPercent": dividend_cagr,
            "completedYearCagrStart": completed_years[0]["year"] if len(completed_years) >= 2 else None,
            "completedYearCagrEnd": completed_years[-1]["year"] if len(completed_years) >= 2 else None,
            "latestSplitDate": split_records[0]["date"] if split_records else None,
            "latestSplitRatio": split_records[0]["displayRatio"] if split_records else None,
        },
        "annualDividends": annual_dividends,
        "recentDividends": dividend_records[:12],
        "recentSplits": split_records[:8],
        "recentCapitalGains": capital_gain_records[:8],
        "upcomingEvents": upcoming_events,
        "source": "Yahoo Finance distributions and corporate actions via yfinance",
        "method": "FinTrack sums positive per-share payment history for trailing and calendar-year totals. Completed-year CAGR excludes the current partial year; provider yield and payout snapshots remain separate.",
        "disclaimer": "Historical distributions are not guaranteed. Current calendar-year totals are partial, provider corporate-action coverage can vary, and a stock split does not create economic value by itself. Missing data is not treated as zero.",
    }


ESTIMATE_PERIOD_LABELS = {
    "0q": "Current quarter",
    "+1q": "Next quarter",
    "0y": "Current year",
    "+1y": "Next year",
}


def _analysis_frame_row(frame: Optional[pd.DataFrame], period: str) -> Dict[str, Any]:
    if frame is None or frame.empty or period not in frame.index:
        return {}
    row = frame.loc[period]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    return row.to_dict() if isinstance(row, pd.Series) else {}


def _revision_direction(net_revisions: Optional[int]) -> str:
    if net_revisions is None:
        return "unavailable"
    if net_revisions > 0:
        return "net upward"
    if net_revisions < 0:
        return "net downward"
    return "balanced/no net revisions"


def _analyst_estimate_intelligence(
    earnings_estimate: Optional[pd.DataFrame],
    revenue_estimate: Optional[pd.DataFrame],
    eps_revisions: Optional[pd.DataFrame],
    eps_trend: Optional[pd.DataFrame],
    growth_estimates: Optional[pd.DataFrame],
) -> Dict[str, Any]:
    periods = []
    for period, label in ESTIMATE_PERIOD_LABELS.items():
        earnings = _analysis_frame_row(earnings_estimate, period)
        revenue = _analysis_frame_row(revenue_estimate, period)
        revisions = _analysis_frame_row(eps_revisions, period)
        trend = _analysis_frame_row(eps_trend, period)
        growth = _analysis_frame_row(growth_estimates, period)
        if not any((earnings, revenue, revisions, trend, growth)):
            continue

        eps_average = _round(earnings.get("avg"), 4)
        trend_current = _round(trend.get("current"), 4)
        basis_comparable = None
        if eps_average is not None and trend_current is not None:
            tolerance = max(0.03, abs(eps_average) * 0.05)
            basis_comparable = abs(eps_average - trend_current) <= tolerance
        has_revision_counts = bool(revisions)
        up_7 = int(_round(revisions.get("upLast7days"), 0) or 0) if has_revision_counts else None
        down_7 = int(_round(revisions.get("downLast7Days"), 0) or 0) if has_revision_counts else None
        up_30 = int(_round(revisions.get("upLast30days"), 0) or 0) if has_revision_counts else None
        down_30 = int(_round(revisions.get("downLast30days"), 0) or 0) if has_revision_counts else None
        trend_7 = _round(trend.get("7daysAgo"), 4)
        trend_30 = _round(trend.get("30daysAgo"), 4)
        trend_60 = _round(trend.get("60daysAgo"), 4)
        trend_90 = _round(trend.get("90daysAgo"), 4)
        net_7 = up_7 - down_7 if up_7 is not None and down_7 is not None else None
        net_30 = up_30 - down_30 if up_30 is not None and down_30 is not None else None
        periods.append({
            "period": period,
            "label": label,
            "eps": {
                "average": eps_average,
                "low": _round(earnings.get("low"), 4),
                "high": _round(earnings.get("high"), 4),
                "yearAgo": _round(earnings.get("yearAgoEps"), 4),
                "analystCount": int(_round(earnings.get("numberOfAnalysts"), 0) or 0),
                "growthPercent": _percentage_from_fraction(earnings.get("growth")),
            },
            "revenue": {
                "average": _round(revenue.get("avg"), 0),
                "low": _round(revenue.get("low"), 0),
                "high": _round(revenue.get("high"), 0),
                "yearAgo": _round(revenue.get("yearAgoRevenue"), 0),
                "analystCount": int(_round(revenue.get("numberOfAnalysts"), 0) or 0),
                "growthPercent": _percentage_from_fraction(revenue.get("growth")),
            },
            "revisionCounts": {
                "upLast7Days": up_7,
                "downLast7Days": down_7,
                "netLast7Days": net_7,
                "upLast30Days": up_30,
                "downLast30Days": down_30,
                "netLast30Days": net_30,
                "signal": _revision_direction(net_30),
            },
            "epsTrend": {
                "current": trend_current,
                "sevenDaysAgo": trend_7,
                "thirtyDaysAgo": trend_30,
                "sixtyDaysAgo": trend_60,
                "ninetyDaysAgo": trend_90,
                "change7Days": _round(trend_current - trend_7, 4) if trend_current is not None and trend_7 is not None else None,
                "change30Days": _round(trend_current - trend_30, 4) if trend_current is not None and trend_30 is not None else None,
                "change90Days": _round(trend_current - trend_90, 4) if trend_current is not None and trend_90 is not None else None,
                "matchesPublishedAverageBasis": basis_comparable,
            },
            "growthComparison": {
                "companyPercent": _percentage_from_fraction(growth.get("stockTrend")),
                "providerIndexPercent": _percentage_from_fraction(growth.get("indexTrend")),
            },
        })

    coverage = {
        "earningsEstimates": earnings_estimate is not None and not earnings_estimate.empty,
        "revenueEstimates": revenue_estimate is not None and not revenue_estimate.empty,
        "epsRevisionCounts": eps_revisions is not None and not eps_revisions.empty,
        "epsTrendHistory": eps_trend is not None and not eps_trend.empty,
        "growthComparison": growth_estimates is not None and not growth_estimates.empty,
    }
    evidence_count = sum(coverage.values())
    if not periods:
        return {
            "status": "unavailable",
            "coverageLevel": "unavailable",
            "coverage": coverage,
            "periods": [],
            "summary": {},
            "source": "Yahoo Finance third-party analyst estimates via yfinance",
            "method": "No analyst-estimate dataset was returned for this listing.",
            "disclaimer": "FinTrack does not create estimates or revisions when provider evidence is missing.",
        }

    current_quarter = next((item for item in periods if item["period"] == "0q"), periods[0])
    next_year = next((item for item in periods if item["period"] == "+1y"), {})
    mismatches = [item["period"] for item in periods if item["epsTrend"].get("matchesPublishedAverageBasis") is False]
    current_revisions = current_quarter.get("revisionCounts") or {}
    return {
        "status": "available",
        "coverageLevel": "broad" if evidence_count >= 4 else "partial",
        "coverage": coverage,
        "periods": periods,
        "summary": {
            "periodCount": len(periods),
            "currentQuarterEpsAverage": current_quarter.get("eps", {}).get("average"),
            "currentQuarterEpsGrowthPercent": current_quarter.get("eps", {}).get("growthPercent"),
            "currentQuarterRevenueAverage": current_quarter.get("revenue", {}).get("average"),
            "currentQuarterRevenueGrowthPercent": current_quarter.get("revenue", {}).get("growthPercent"),
            "currentQuarterAnalystCount": max(
                current_quarter.get("eps", {}).get("analystCount") or 0,
                current_quarter.get("revenue", {}).get("analystCount") or 0,
            ),
            "currentQuarterRevisionSignal": current_revisions.get("signal"),
            "currentQuarterNetRevisions30Days": current_revisions.get("netLast30Days"),
            "currentQuarterEpsChange30Days": current_quarter.get("epsTrend", {}).get("change30Days"),
            "nextYearEpsGrowthPercent": next_year.get("eps", {}).get("growthPercent"),
            "nextYearRevenueGrowthPercent": next_year.get("revenue", {}).get("growthPercent"),
            "periodsWithBasisMismatch": mismatches,
        },
        "source": "Yahoo Finance third-party analyst estimates via yfinance",
        "method": "Provider EPS/revenue ranges, analyst counts, revision counts and EPS trend snapshots are normalized by forecast period. Net revision breadth is upward minus downward revisions; no missing estimate is inferred.",
        "disclaimer": "These are changing third-party analyst estimates, not company guidance, FinTrack ML output or guaranteed results. EPS trend series can use a different basis from the published estimate range; FinTrack flags those periods instead of merging incompatible values.",
    }


def company_research(symbol: str) -> Dict[str, Any]:
    symbol = _sanitize_symbol(symbol)
    key = f"company:{symbol}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    ticker = yf.Ticker(symbol)
    frame = _history(symbol, "1y")
    snapshot = market_snapshot(symbol)
    try:
        info = ticker.get_info() or {}
    except Exception:
        info = {}
    try:
        calendar = ticker.calendar or {}
    except Exception:
        calendar = {}
    try:
        earnings_dates = ticker.get_earnings_dates(limit=6)
    except Exception:
        earnings_dates = None
    try:
        income_statement = ticker.income_stmt
    except Exception:
        income_statement = None
    try:
        balance_sheet = ticker.balance_sheet
    except Exception:
        balance_sheet = None
    try:
        cash_flow = ticker.cashflow
    except Exception:
        cash_flow = None
    try:
        quarterly_income = ticker.quarterly_income_stmt
    except Exception:
        quarterly_income = None
    try:
        major_holders = ticker.major_holders
    except Exception:
        major_holders = None
    try:
        institutional_holders = ticker.institutional_holders
    except Exception:
        institutional_holders = None
    try:
        mutual_fund_holders = ticker.mutualfund_holders
    except Exception:
        mutual_fund_holders = None
    try:
        insider_transactions = ticker.insider_transactions
    except Exception:
        insider_transactions = None
    try:
        insider_purchases = ticker.insider_purchases
    except Exception:
        insider_purchases = None
    try:
        insider_roster = ticker.insider_roster_holders
    except Exception:
        insider_roster = None
    try:
        earnings_estimate = ticker.earnings_estimate
    except Exception:
        earnings_estimate = None
    try:
        revenue_estimate = ticker.revenue_estimate
    except Exception:
        revenue_estimate = None
    try:
        eps_revisions = ticker.eps_revisions
    except Exception:
        eps_revisions = None
    try:
        eps_trend = ticker.eps_trend
    except Exception:
        eps_trend = None
    try:
        growth_estimates = ticker.growth_estimates
    except Exception:
        growth_estimates = None
    try:
        dividends = ticker.dividends
    except Exception:
        dividends = None
    try:
        splits = ticker.splits
    except Exception:
        splits = None
    try:
        capital_gains = ticker.capital_gains
    except Exception:
        capital_gains = None

    close = frame["Close"].astype(float)
    fifty_two_week_low = _round(frame["Low"].min()) if "Low" in frame else None
    fifty_two_week_high = _round(frame["High"].max()) if "High" in frame else None
    range_low = _round(info.get("fiftyTwoWeekLow")) or fifty_two_week_low
    range_high = _round(info.get("fiftyTwoWeekHigh")) or fifty_two_week_high
    financials = _company_financial_sections(info)
    company_quote = {**snapshot, "currency": _company_currency(info, snapshot)}
    catalysts = _company_catalysts(info, calendar, earnings_dates, snapshot.get("price"))
    financial_trends = _financial_statement_trends(
        income_statement,
        balance_sheet,
        cash_flow,
        quarterly_income,
    )
    earnings_quality = _earnings_quality_intelligence(info, financial_trends, cash_flow)
    liquidity_debt = _liquidity_debt_intelligence(info, income_statement, balance_sheet)
    profitability_returns = _profitability_returns_intelligence(info, income_statement, balance_sheet)
    ownership = _ownership_intelligence(
        major_holders,
        institutional_holders,
        mutual_fund_holders,
        insider_transactions,
        insider_purchases,
        insider_roster,
    )
    analyst_estimates = _analyst_estimate_intelligence(
        earnings_estimate,
        revenue_estimate,
        eps_revisions,
        eps_trend,
        growth_estimates,
    )
    corporate_actions = _corporate_action_intelligence(
        info,
        dividends,
        splits,
        capital_gains,
        catalysts.get("events"),
    )
    news_evidence = market_news(symbol, 8)
    result = {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName") or snapshot["name"],
        "sector": info.get("sector") or "Not available",
        "industry": info.get("industry") or "Not available",
        "country": info.get("country") or snapshot.get("region") or "Not available",
        "website": info.get("website"),
        "summary": info.get("longBusinessSummary"),
        "quote": company_quote,
        "performance": {
            "oneDay": snapshot.get("changePercent"),
            "oneMonth": _period_return(close, 22),
            "threeMonths": _period_return(close, 66),
            "sixMonths": _period_return(close, 132),
            "oneYear": _period_return(close, 252),
        },
        "range": {
            "fiftyTwoWeekLow": range_low,
            "fiftyTwoWeekHigh": range_high,
            "currentPositionPercent": _fifty_two_week_position(snapshot.get("price"), range_low, range_high),
        },
        "fundamentals": {
            "marketCap": _round(info.get("marketCap"), 0),
            "trailingPE": _round(info.get("trailingPE")),
            "priceToBook": _round(info.get("priceToBook")),
            "returnOnEquity": _round(float(info.get("returnOnEquity")) * 100, 2) if info.get("returnOnEquity") is not None else None,
            "earningsGrowth": _round(float(info.get("earningsGrowth")) * 100, 2) if info.get("earningsGrowth") is not None else None,
            "revenueGrowth": _round(float(info.get("revenueGrowth")) * 100, 2) if info.get("revenueGrowth") is not None else None,
            "debtToEquity": _round(info.get("debtToEquity")),
            "dividendYield": _round(info.get("dividendYield")),
        },
        "financials": financials,
        "financialTrends": financial_trends,
        "earningsQualityIntelligence": earnings_quality,
        "liquidityDebtIntelligence": liquidity_debt,
        "profitabilityReturnsIntelligence": profitability_returns,
        "ownershipIntelligence": ownership,
        "analystEstimateIntelligence": analyst_estimates,
        "corporateActionIntelligence": corporate_actions,
        "catalysts": catalysts,
        "history": [
            {"date": index.strftime("%Y-%m-%d"), "close": _round(row["Close"])}
            for index, row in frame.tail(120).iterrows()
        ],
        "news": news_evidence["articles"],
        "newsIntelligence": news_evidence["intelligence"],
        "dataAsOf": snapshot["dataAsOf"],
        "source": "Yahoo Finance via yfinance",
        "missingDataNotice": "Some fundamentals may be unavailable for indices, commodities or unsupported listings.",
    }
    return _cache_put(key, result)


def _peer_region_and_suffix(symbol: str) -> tuple[str, str]:
    for suffix, region in PEER_REGION_SUFFIXES:
        if symbol.endswith(suffix):
            return region, suffix
    return "us", ""


def _peer_listing_matches(candidate: str, region: str, suffix: str) -> bool:
    candidate = str(candidate or "").upper()
    if not candidate or candidate.startswith("^"):
        return False
    if suffix:
        return candidate.endswith(suffix)
    # Plain symbols are treated as US listings. Excluding known international
    # suffixes prevents an ADR comparison from silently mixing exchanges.
    return region == "us" and not any(candidate.endswith(item[0]) for item in PEER_REGION_SUFFIXES)


def _peer_quote(raw: Dict[str, Any], selected_symbol: str) -> Dict[str, Any]:
    symbol = str(raw.get("symbol") or "").upper()
    return {
        "symbol": symbol,
        "name": raw.get("longName") or raw.get("shortName") or raw.get("displayName") or symbol,
        "exchange": raw.get("fullExchangeName") or raw.get("exchange") or "Not available",
        "currency": raw.get("currency"),
        "marketCap": _round(raw.get("marketCap") or raw.get("intradaymarketcap"), 0),
        "trailingPE": _round(raw.get("trailingPE")),
        "forwardPE": _round(raw.get("forwardPE")),
        "priceToBook": _round(raw.get("priceToBook")),
        "dividendYield": _round(raw.get("dividendYield")),
        "fiftyTwoWeekReturnPercent": _round(raw.get("fiftyTwoWeekChangePercent")),
        "dailyChangePercent": _round(raw.get("regularMarketChangePercent")),
        "analystRating": raw.get("averageAnalystRating"),
        "isSelected": symbol == selected_symbol,
    }


def _peer_median(rows: List[Dict[str, Any]], field: str) -> Optional[float]:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    return _round(float(np.median(values)), 2) if values else None


def _relative_to_peer_median(value: Any, median: Any) -> str:
    numeric = _round(value, 6)
    midpoint = _round(median, 6)
    if numeric is None or midpoint is None:
        return "not available"
    tolerance = max(abs(midpoint) * 0.05, 0.05)
    if numeric > midpoint + tolerance:
        return "above peer median"
    if numeric < midpoint - tolerance:
        return "below peer median"
    return "in line with peer median"


def _build_sector_peer_payload(
    symbol: str,
    info: Dict[str, Any],
    raw_quotes: List[Dict[str, Any]],
    *,
    region: str,
    suffix: str,
) -> Dict[str, Any]:
    sector = str(info.get("sector") or "").strip()
    if not sector:
        return {
            "status": "unavailable",
            "symbol": symbol,
            "message": "The provider did not publish a sector classification for this listing.",
            "source": "Yahoo Finance via yfinance",
        }

    selected_raw = next(
        (item for item in raw_quotes if str(item.get("symbol") or "").upper() == symbol),
        {},
    )
    selected_source = {
        **info,
        **selected_raw,
        "symbol": symbol,
        "longName": info.get("longName") or selected_raw.get("longName"),
        "shortName": info.get("shortName") or selected_raw.get("shortName"),
        "marketCap": info.get("marketCap") or selected_raw.get("marketCap"),
    }
    selected = _peer_quote(selected_source, symbol)
    candidates = []
    seen = {symbol}
    for raw in raw_quotes:
        candidate_symbol = str(raw.get("symbol") or "").upper()
        quote_type = str(raw.get("quoteType") or "EQUITY").upper()
        if quote_type != "EQUITY" or candidate_symbol in seen or not _peer_listing_matches(candidate_symbol, region, suffix):
            continue
        normalized = _peer_quote(raw, symbol)
        if normalized["marketCap"] is None:
            continue
        seen.add(candidate_symbol)
        candidates.append(normalized)

    target_cap = selected.get("marketCap")
    if target_cap and target_cap > 0:
        candidates.sort(key=lambda item: abs(math.log(max(float(item["marketCap"]), 1) / float(target_cap))))
    else:
        candidates.sort(key=lambda item: float(item.get("marketCap") or 0), reverse=True)
    peers = candidates[:5]
    if not peers:
        return {
            "status": "unavailable",
            "symbol": symbol,
            "sector": sector,
            "region": region.upper(),
            "message": "No comparable same-sector listings were returned for this market.",
            "source": "Yahoo Finance via yfinance",
        }

    medians = {
        "marketCap": _peer_median(peers, "marketCap"),
        "trailingPE": _peer_median(peers, "trailingPE"),
        "priceToBook": _peer_median(peers, "priceToBook"),
        "dividendYield": _peer_median(peers, "dividendYield"),
        "fiftyTwoWeekReturnPercent": _peer_median(peers, "fiftyTwoWeekReturnPercent"),
    }
    comparison = {
        field: _relative_to_peer_median(selected.get(field), median)
        for field, median in medians.items()
    }
    ranked = sorted([selected, *peers], key=lambda item: float(item.get("marketCap") or -1), reverse=True)
    market_cap_rank = next((index + 1 for index, item in enumerate(ranked) if item["symbol"] == symbol), None)
    selected["marketCapRank"] = market_cap_rank

    return {
        "status": "available",
        "symbol": symbol,
        "sector": sector,
        "region": region.upper(),
        "selected": selected,
        "peers": peers,
        "peerMedians": medians,
        "comparison": comparison,
        "method": (
            "Runtime Yahoo equity screener: equities in the same provider sector, market region and listing suffix, "
            "searched around the selected market-cap scale; then the five closest available companies by market-cap "
            "ratio. Medians exclude the selected company."
        ),
        "source": "Yahoo Finance equity screener via yfinance",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "disclaimer": "Relative market evidence only; above/below a peer median is not a buy, sell or valuation recommendation.",
    }


def sector_peer_intelligence(symbol: str) -> Dict[str, Any]:
    symbol = _sanitize_symbol(symbol)
    if symbol.startswith("^"):
        return {
            "status": "not_applicable",
            "symbol": symbol,
            "message": "Sector-company peer comparison does not apply to a broad market index.",
        }
    key = f"sector-peers:{symbol}"
    cached = _cache_get(key, PEER_CACHE_TTL_SECONDS)
    if cached is not None:
        return cached

    try:
        info = yf.Ticker(symbol).get_info() or {}
    except Exception as error:
        logger.warning("Peer profile lookup failed for %s: %s", symbol, error)
        info = {}
    sector = str(info.get("sector") or "").strip()
    region, suffix = _peer_region_and_suffix(symbol)
    if not sector:
        return _cache_put(key, _build_sector_peer_payload(symbol, info, [], region=region, suffix=suffix))

    try:
        base_conditions = [
            yf.EquityQuery("eq", ["sector", sector]),
            yf.EquityQuery("eq", ["region", region]),
        ]
        target_cap = _round(info.get("marketCap"), 0)
        cap_condition = (
            yf.EquityQuery("btwn", [
                "intradaymarketcap",
                max(1_000_000, float(target_cap) / 10),
                float(target_cap) * 10,
            ])
            if target_cap and target_cap > 0
            else yf.EquityQuery("gt", ["intradaymarketcap", 1_000_000])
        )
        query = yf.EquityQuery("and", [*base_conditions, cap_condition])
        response = yf.screen(query, size=100, sortField="intradaymarketcap", sortAsc=False) or {}
        quotes = response.get("quotes") or []
        result = _build_sector_peer_payload(symbol, info, quotes, region=region, suffix=suffix)
        if len(result.get("peers") or []) < 5 and target_cap:
            broad_query = yf.EquityQuery("and", [
                *base_conditions,
                yf.EquityQuery("gt", ["intradaymarketcap", 1_000_000]),
            ])
            broad_response = yf.screen(
                broad_query, size=100, sortField="intradaymarketcap", sortAsc=False
            ) or {}
            quotes = [*quotes, *(broad_response.get("quotes") or [])]
            response["total"] = max(int(response.get("total") or 0), int(broad_response.get("total") or 0))
            result = _build_sector_peer_payload(symbol, info, quotes, region=region, suffix=suffix)
        result["providerCoverage"] = int(response.get("total") or len(quotes))
    except Exception as error:
        logger.warning("Dynamic peer discovery failed for %s: %s", symbol, error)
        result = {
            "status": "unavailable",
            "symbol": symbol,
            "sector": sector,
            "region": region.upper(),
            "message": "Dynamic sector peers are temporarily unavailable from the market-data provider.",
            "source": "Yahoo Finance equity screener via yfinance",
        }
    return _cache_put(key, result)


def market_news_feed(limit: int = 12) -> Dict[str, Any]:
    source_symbols = [
        "^NSEI", "^GSPC", "GC=F", "CL=F", "INR=X",
        "INFY.NS", "MARUTI.NS", "SUNPHARMA.NS", "NETWORK18.NS", "AAPL", "TSLA",
    ]
    articles: List[Dict[str, Any]] = []
    seen = set()
    with ThreadPoolExecutor(max_workers=5) as executor:
        jobs = {executor.submit(market_news, symbol, 6): symbol for symbol in source_symbols}
        for job in as_completed(jobs):
            symbol = jobs[job]
            try:
                for item in job.result()["articles"]:
                    fingerprint = re.sub(r"\W+", "", item["title"].lower())[:120]
                    if fingerprint and fingerprint not in seen:
                        seen.add(fingerprint)
                        articles.append({**item, "relatedSymbol": symbol})
            except Exception:
                continue
    articles.sort(key=lambda item: str(item.get("publishedAt") or ""), reverse=True)
    return {
        "articles": articles[:max(1, min(limit, 20))],
        "topics": [
            "India", "Global equities", "Technology", "Automobile", "Healthcare",
            "Media", "Gold", "Crude oil", "USD/INR",
        ],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "Yahoo Finance headlines via yfinance",
    }


def _macro_adjustment(symbol: str) -> Dict[str, Any]:
    payload = macro_factors()
    factor_map = {item["symbol"]: item for item in payload["factors"] if item.get("status") == "available"}
    sp500 = market_snapshot("^GSPC")
    score = 0.0
    contributions = []

    def add_factor(key: str, weight: float, reason: str) -> None:
        nonlocal score
        factor = factor_map.get(key)
        if not factor:
            return
        contribution = float(factor.get("changePercent") or 0) * weight
        score += contribution
        contributions.append({
            "factor": factor["name"],
            "changePercent": factor.get("changePercent"),
            "scoreContribution": _round(contribution, 3),
            "reason": reason,
        })

    def moved(key: str, up_reason: str, down_reason: str) -> str:
        factor = factor_map.get(key)
        if not factor:
            return "Current factor data is unavailable."
        return up_reason if float(factor.get("changePercent") or 0) >= 0 else down_reason

    is_india = symbol.endswith(".NS") or symbol in {"^NSEI", "^BSESN"}
    add_factor("^VIX", -0.35, moved("^VIX", "VIX rose, signalling higher uncertainty and weaker risk appetite.", "VIX fell, which can support risk appetite."))
    add_factor("^TNX", -0.12, moved("^TNX", "US yields rose, which can pressure equity valuations.", "US yields fell, easing some valuation pressure."))
    add_factor("GC=F", -0.06, moved("GC=F", "Gold rose, which can indicate defensive positioning and higher jewellery input costs.", "Gold fell, reducing the immediate defensive signal and some input-cost pressure."))
    if is_india:
        add_factor("CL=F", -0.18, moved("CL=F", "Crude rose, increasing India's inflation and import-cost risk.", "Crude fell, easing India's oil-import and inflation pressure."))
        add_factor("INR=X", -0.16, moved("INR=X", "USD/INR rose: a weaker rupee can raise import costs while helping exporters.", "USD/INR fell: a stronger rupee can reduce import costs but trim exporter currency gains."))
        global_lead = float(sp500.get("changePercent") or 0) * 0.18
        score += global_lead
        contributions.append({
            "factor": "S&P 500 lead",
            "changePercent": sp500.get("changePercent"),
            "scoreContribution": _round(global_lead, 3),
            "reason": "S&P 500 rose, providing a positive global lead." if global_lead >= 0 else "S&P 500 fell, providing a negative global lead.",
        })
    adjustment_points = max(-5.0, min(5.0, score))
    return {
        "probabilityAdjustmentPoints": _round(adjustment_points, 2),
        "signal": "supportive" if adjustment_points > 0.75 else "adverse" if adjustment_points < -0.75 else "mixed",
        "factors": contributions,
        "method": "Transparent weighted macro overlay capped at +/-5 probability points.",
    }


FEATURE_LABELS = {
    "return_1": "1-session return",
    "return_5": "5-session return",
    "sma_10_ratio": "Price vs SMA 10",
    "sma_20_ratio": "Price vs SMA 20",
    "volatility_10": "10-session volatility",
    "volume_change": "Volume change",
    "rsi_14": "RSI 14",
}


def _candidate_models() -> Dict[str, Dict[str, Any]]:
    """Return fresh estimators so every time-series fold is isolated."""
    return {
        "logistic_regression": {
            "name": "Logistic Regression",
            "estimator": Pipeline([
                ("scale", StandardScaler()),
                ("classifier", LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                    random_state=42,
                    solver="liblinear",
                )),
            ]),
        },
        "random_forest": {
            "name": "Random Forest",
            "estimator": Pipeline([
                ("classifier", RandomForestClassifier(
                    n_estimators=120,
                    max_depth=5,
                    min_samples_leaf=7,
                    class_weight="balanced",
                    random_state=42,
                    # Render's free container has limited CPU. Parallel workers can
                    # make a small model slower because of process start-up cost.
                    n_jobs=1,
                )),
            ]),
        },
        "hist_gradient_boosting": {
            "name": "Histogram Gradient Boosting",
            "estimator": Pipeline([
                ("classifier", HistGradientBoostingClassifier(
                    max_iter=100,
                    learning_rate=0.05,
                    max_depth=3,
                    min_samples_leaf=12,
                    l2_regularization=1.0,
                    random_state=42,
                )),
            ]),
        },
    }


def _classification_metrics(y_true: np.ndarray, predictions: np.ndarray, probabilities: np.ndarray) -> Dict[str, Any]:
    roc_auc = None
    if len(np.unique(y_true)) == 2:
        roc_auc = float(roc_auc_score(y_true, probabilities))
    return {
        "accuracy": float(accuracy_score(y_true, predictions)),
        "balancedAccuracy": float(balanced_accuracy_score(y_true, predictions)),
        "precision": float(precision_score(y_true, predictions, zero_division=0)),
        "recall": float(recall_score(y_true, predictions, zero_division=0)),
        "f1": float(f1_score(y_true, predictions, zero_division=0)),
        "rocAuc": roc_auc,
        "brierScore": float(brier_score_loss(y_true, probabilities)),
    }


def _walk_forward_model_comparison(
    dataset: pd.DataFrame,
    feature_columns: List[str],
) -> Dict[str, Any]:
    """Compare models using expanding-window validation without random shuffle."""
    fold_count = 5 if len(dataset) >= 180 else 4
    splitter = TimeSeriesSplit(n_splits=fold_count, gap=1)
    comparisons: List[Dict[str, Any]] = []

    for model_id, candidate in _candidate_models().items():
        fold_truth: List[int] = []
        fold_predictions: List[int] = []
        fold_probabilities: List[float] = []
        used_folds = 0
        for train_indices, test_indices in splitter.split(dataset):
            train = dataset.iloc[train_indices]
            test = dataset.iloc[test_indices]
            if train["target"].nunique() < 2 or test.empty:
                continue
            estimator = _candidate_models()[model_id]["estimator"]
            estimator.fit(train[feature_columns], train["target"])
            probabilities = estimator.predict_proba(test[feature_columns])[:, 1]
            predictions = (probabilities >= 0.50).astype(int)
            fold_truth.extend(test["target"].astype(int).tolist())
            fold_predictions.extend(predictions.tolist())
            fold_probabilities.extend(probabilities.tolist())
            used_folds += 1

        if not fold_truth:
            continue
        metrics = _classification_metrics(
            np.asarray(fold_truth),
            np.asarray(fold_predictions),
            np.asarray(fold_probabilities),
        )
        auc_component = metrics["rocAuc"] if metrics["rocAuc"] is not None else 0.50
        selection_score = (
            metrics["balancedAccuracy"] * 0.55
            + auc_component * 0.30
            + (1 - metrics["brierScore"]) * 0.15
        )
        comparisons.append({
            "id": model_id,
            "name": candidate["name"],
            "folds": used_folds,
            "testRows": len(fold_truth),
            "selectionScore": selection_score,
            **metrics,
        })

    if not comparisons:
        raise ValueError("Time-series validation could not produce a valid model comparison.")
    comparisons.sort(key=lambda item: item["selectionScore"], reverse=True)
    selected = comparisons[0]
    return {"selected": selected, "comparisons": comparisons, "folds": fold_count}


def _feature_importance(
    estimator: Pipeline,
    dataset: pd.DataFrame,
    feature_columns: List[str],
) -> List[Dict[str, Any]]:
    evaluation_rows = max(30, int(len(dataset) * 0.20))
    evaluation = dataset.tail(evaluation_rows)
    try:
        result = permutation_importance(
            estimator,
            evaluation[feature_columns],
            evaluation["target"],
            scoring="accuracy",
            n_repeats=4,
            random_state=42,
            n_jobs=1,
        )
        raw = np.maximum(result.importances_mean, 0)
    except Exception:
        raw = np.zeros(len(feature_columns))
    total = float(raw.sum())
    normalized = (raw / total * 100) if total > 0 else np.zeros(len(feature_columns))
    values = [
        {
            "feature": feature,
            "label": FEATURE_LABELS.get(feature, feature),
            "importance": _round(float(value), 1),
        }
        for feature, value in zip(feature_columns, normalized)
    ]
    return sorted(values, key=lambda item: item["importance"] or 0, reverse=True)


def _feature_display_value(feature: str, value: float) -> str:
    if feature == "rsi_14":
        return f"{value * 100:.1f}"
    return f"{value * 100:+.2f}%"


def _local_feature_explanation(
    estimator: Pipeline,
    latest_features: pd.DataFrame,
    dataset: pd.DataFrame,
    feature_columns: List[str],
    reliability_weight: float,
    artifact_reference: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Explain one prediction through transparent one-feature counterfactual sensitivity.

    Each feature is replaced by its training reference while all other current
    values stay fixed. The resulting probability change is local and directional,
    but deliberately not presented as causal or additively SHAP-like.
    """
    current = latest_features[feature_columns].iloc[0].astype(float)
    valid_artifact_reference = artifact_reference or {}
    if all(feature in valid_artifact_reference for feature in feature_columns):
        reference = pd.Series(
            {feature: float(valid_artifact_reference[feature]) for feature in feature_columns}
        )
        reference_source = "offline training-window median"
    else:
        reference = dataset[feature_columns].median().astype(float)
        reference_source = "current two-year model-dataset median"

    current_frame = pd.DataFrame([current.to_dict()], columns=feature_columns)
    current_probability = float(estimator.predict_proba(current_frame)[0][1])
    baseline_frame = pd.DataFrame([reference.to_dict()], columns=feature_columns)
    baseline_probability = float(estimator.predict_proba(baseline_frame)[0][1])
    contributions: List[Dict[str, Any]] = []

    for feature in feature_columns:
        counterfactual = current.copy()
        counterfactual[feature] = reference[feature]
        counterfactual_frame = pd.DataFrame([counterfactual.to_dict()], columns=feature_columns)
        without_current_value = float(estimator.predict_proba(counterfactual_frame)[0][1])
        raw_impact_points = (current_probability - without_current_value) * 100
        adjusted_impact_points = raw_impact_points * reliability_weight
        direction = (
            "supports_up" if adjusted_impact_points > 0.05
            else "supports_down" if adjusted_impact_points < -0.05
            else "neutral"
        )
        contributions.append({
            "feature": feature,
            "label": FEATURE_LABELS.get(feature, feature),
            "currentValue": _round(float(current[feature]), 6),
            "referenceValue": _round(float(reference[feature]), 6),
            "currentDisplay": _feature_display_value(feature, float(current[feature])),
            "referenceDisplay": _feature_display_value(feature, float(reference[feature])),
            "rawProbabilityImpactPoints": _round(raw_impact_points, 2),
            "adjustedProbabilityImpactPoints": _round(adjusted_impact_points, 2),
            "direction": direction,
        })

    contributions.sort(
        key=lambda item: abs(float(item["adjustedProbabilityImpactPoints"] or 0)),
        reverse=True,
    )
    positive = next((item for item in contributions if item["direction"] == "supports_up"), None)
    negative = next((item for item in contributions if item["direction"] == "supports_down"), None)
    if positive and negative:
        summary = (
            f"{positive['label']} gives the strongest upward support, while "
            f"{negative['label']} creates the strongest downward pressure."
        )
    elif positive:
        summary = f"{positive['label']} gives the strongest upward support in this prediction."
    elif negative:
        summary = f"{negative['label']} creates the strongest downward pressure in this prediction."
    else:
        summary = "No single feature materially changes the current probability from its reference value."

    return {
        "method": "One-feature-at-a-time counterfactual probability sensitivity.",
        "referenceSource": reference_source,
        "rawModelProbabilityUp": _round(current_probability * 100, 1),
        "allReferenceProbabilityUp": _round(baseline_probability * 100, 1),
        "summary": summary,
        "contributions": contributions,
        "caveat": (
            "Impacts are local sensitivity checks, may overlap when features interact, "
            "and do not prove that a feature caused the market move."
        ),
    }


def _record_prediction(payload: Dict[str, Any], model_data_date: str) -> List[Dict[str, Any]]:
    """Keep an explainable runtime audit and score it when a later session arrives."""
    symbol = payload["symbol"]
    with _prediction_audit_lock:
        records = _prediction_audit.setdefault(symbol, [])
        if records and records[-1]["modelDataDate"] != model_data_date and records[-1]["status"] == "pending":
            previous = records[-1]
            reference = float(previous["referenceClose"])
            actual_return = ((float(payload["lastClose"]) / reference) - 1) * 100 if reference else 0
            actual_direction = "UP" if actual_return > 0.10 else "DOWN" if actual_return < -0.10 else "FLAT"
            expected = previous["outlook"]
            previous["status"] = "evaluated"
            previous["actualReturnPercent"] = _round(actual_return, 2)
            previous["actualDirection"] = actual_direction
            previous["correct"] = (
                (expected == "BULLISH" and actual_direction == "UP")
                or (expected == "BEARISH" and actual_direction == "DOWN")
                or (expected == "NEUTRAL" and abs(actual_return) <= 0.50)
            )

        if not records or records[-1]["modelDataDate"] != model_data_date:
            records.append({
                "id": f"{symbol}:{model_data_date}",
                "symbol": symbol,
                "modelDataDate": model_data_date,
                "issuedAt": payload["generatedAt"],
                "target": "Next trading session",
                "outlook": payload["outlook"],
                "probabilityUp": payload["probabilityUp"],
                "referenceClose": payload["lastClose"],
                "expectedRange": payload["expectedRange"],
                "selectedModel": payload["model"]["type"],
                "status": "pending",
                "actualReturnPercent": None,
                "actualDirection": None,
                "correct": None,
            })
            del records[:-30]
        return [dict(item) for item in reversed(records[-12:])]


def prediction_audit(symbol: str, limit: int = 12) -> Dict[str, Any]:
    symbol = _sanitize_symbol(symbol)
    with _prediction_audit_lock:
        records = [dict(item) for item in reversed(_prediction_audit.get(symbol, [])[-limit:])]
    evaluated = [item for item in records if item["status"] == "evaluated"]
    correct = [item for item in evaluated if item.get("correct")]
    return {
        "symbol": symbol,
        "records": records,
        "evaluatedCount": len(evaluated),
        "observedAccuracy": _round(len(correct) / len(evaluated) * 100, 1) if evaluated else None,
        "storage": "Runtime audit; the browser also caches successful research responses.",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


def _benchmark_for_symbol(symbol: str) -> Optional[str]:
    """Resolve a broad-market benchmark from the listing suffix, not company identity."""
    normalized = _sanitize_symbol(symbol)
    if normalized.startswith("^") or normalized in BENCHMARKS:
        return None
    for suffix, benchmark in BENCHMARK_SUFFIXES:
        if normalized.endswith(suffix):
            return benchmark
    return "^GSPC"


def _close_series(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty or "Close" not in frame:
        raise ValueError("Closing-price history is unavailable.")
    series = pd.to_numeric(frame["Close"], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    series = series[series > 0]
    if len(series) < 40:
        raise ValueError("At least 40 clean sessions are required for risk analytics.")
    return series.tail(253)


def _standalone_risk_metrics(close: pd.Series) -> Dict[str, Any]:
    returns = close.div(close.shift(1)).sub(1).dropna()
    period_return = (float(close.iloc[-1]) / float(close.iloc[0])) - 1
    annualized_return = ((1 + period_return) ** (252 / max(len(returns), 1))) - 1
    annualized_volatility = float(returns.std(ddof=1)) * math.sqrt(252)
    wealth = close.div(float(close.iloc[0]))
    drawdown = wealth.div(wealth.cummax()).sub(1)
    historical_var = max(0.0, -float(returns.quantile(0.05)))
    return_to_volatility = (
        annualized_return / annualized_volatility if annualized_volatility > 0 else None
    )
    maximum_drawdown = float(drawdown.min())
    if annualized_volatility >= 0.35 or maximum_drawdown <= -0.30:
        risk_band = "elevated"
    elif annualized_volatility >= 0.20 or maximum_drawdown <= -0.15:
        risk_band = "moderate"
    else:
        risk_band = "contained"
    return {
        "periodReturnPercent": _round(period_return * 100, 2),
        "annualizedReturnPercent": _round(annualized_return * 100, 2),
        "annualizedVolatilityPercent": _round(annualized_volatility * 100, 2),
        "maxDrawdownPercent": _round(maximum_drawdown * 100, 2),
        "historicalVar95Percent": _round(historical_var * 100, 2),
        "positiveSessionsPercent": _round(float((returns > 0).mean()) * 100, 1),
        "returnToVolatility": _round(return_to_volatility, 2),
        "observations": len(returns),
        "riskBand": risk_band,
    }


def calculate_market_risk_context(
    symbol: str,
    asset_frame: pd.DataFrame,
    benchmark_frame: Optional[pd.DataFrame] = None,
    benchmark_symbol: Optional[str] = None,
) -> Dict[str, Any]:
    """Calculate transparent trailing risk and optional benchmark-relative evidence."""
    normalized_symbol = _sanitize_symbol(symbol)
    asset_close = _close_series(asset_frame)
    asset_metrics = _standalone_risk_metrics(asset_close)
    payload: Dict[str, Any] = {
        "status": "standalone",
        "symbol": normalized_symbol,
        "period": "Up to 252 latest trading sessions",
        "asset": asset_metrics,
        "benchmark": None,
        "comparison": None,
        "normalizedHistory": [],
        "method": (
            "Close-to-close returns; annualized volatility uses sqrt(252), maximum drawdown uses "
            "the trailing wealth peak, and 95% historical VaR is the observed fifth-percentile daily loss."
        ),
        "caveat": "Historical risk and benchmark relationships can change and are not investment advice.",
    }

    if benchmark_frame is None or not benchmark_symbol:
        chart_close = asset_close.tail(90)
        first = float(chart_close.iloc[0])
        payload["normalizedHistory"] = [
            {"date": index.strftime("%Y-%m-%d"), "asset": _round(float(value) / first * 100, 2), "benchmark": None}
            for index, value in chart_close.items()
        ]
        return payload

    benchmark_close = _close_series(benchmark_frame)
    aligned = pd.concat(
        [asset_close.rename("asset"), benchmark_close.rename("benchmark")], axis=1, join="inner"
    ).dropna().tail(253)
    if len(aligned) < 40:
        raise ValueError("Not enough aligned sessions for benchmark comparison.")
    aligned_returns = aligned.div(aligned.shift(1)).sub(1).dropna()
    benchmark_variance = float(aligned_returns["benchmark"].var(ddof=1))
    covariance = float(aligned_returns[["asset", "benchmark"]].cov().iloc[0, 1])
    beta = covariance / benchmark_variance if benchmark_variance > 0 else None
    correlation = float(aligned_returns["asset"].corr(aligned_returns["benchmark"]))
    tracking_error = float((aligned_returns["asset"] - aligned_returns["benchmark"]).std(ddof=1)) * math.sqrt(252)
    asset_return = (float(aligned["asset"].iloc[-1]) / float(aligned["asset"].iloc[0])) - 1
    benchmark_return = (float(aligned["benchmark"].iloc[-1]) / float(aligned["benchmark"].iloc[0])) - 1
    relative_return = asset_return - benchmark_return
    benchmark_normalizer = float(aligned["benchmark"].iloc[0])
    asset_normalizer = float(aligned["asset"].iloc[0])
    chart = aligned.tail(90)

    payload.update({
        "status": "available",
        "benchmark": {
            "symbol": benchmark_symbol,
            "name": BENCHMARKS.get(benchmark_symbol, benchmark_symbol),
            "observations": len(aligned_returns),
        },
        "comparison": {
            "assetReturnPercent": _round(asset_return * 100, 2),
            "benchmarkReturnPercent": _round(benchmark_return * 100, 2),
            "relativeReturnPoints": _round(relative_return * 100, 2),
            "beta": _round(beta, 2),
            "correlation": _round(correlation, 2),
            "trackingErrorPercent": _round(tracking_error * 100, 2),
            "relativePerformance": "outperformed" if relative_return > 0.005 else "underperformed" if relative_return < -0.005 else "in-line",
        },
        "normalizedHistory": [
            {
                "date": index.strftime("%Y-%m-%d"),
                "asset": _round(float(row["asset"]) / asset_normalizer * 100, 2),
                "benchmark": _round(float(row["benchmark"]) / benchmark_normalizer * 100, 2),
            }
            for index, row in chart.iterrows()
        ],
    })
    return payload


def market_risk_context(symbol: str, asset_frame: pd.DataFrame) -> Dict[str, Any]:
    benchmark_symbol = _benchmark_for_symbol(symbol)
    try:
        benchmark_frame = _history(benchmark_symbol, "1y") if benchmark_symbol else None
        return calculate_market_risk_context(
            symbol, asset_frame, benchmark_frame=benchmark_frame, benchmark_symbol=benchmark_symbol
        )
    except Exception as error:
        logger.warning("Risk benchmark calculation failed for %s: %s", symbol, type(error).__name__)
        try:
            fallback = calculate_market_risk_context(symbol, asset_frame)
            fallback["status"] = "benchmark-unavailable" if benchmark_symbol else "standalone"
            fallback["benchmark"] = (
                {"symbol": benchmark_symbol, "name": BENCHMARKS.get(benchmark_symbol, benchmark_symbol)}
                if benchmark_symbol else None
            )
            return fallback
        except Exception:
            return {
                "status": "unavailable",
                "symbol": symbol,
                "message": "Historical risk evidence is temporarily unavailable.",
            }


def _requests_risk_analysis(message: str) -> bool:
    lowered = " ".join(str(message or "").lower().split())
    return any(term in lowered for term in RISK_QUERY_TERMS) or " var " in f" {lowered} "


def _requests_catalyst_analysis(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(term in lowered for term in CATALYST_QUERY_TERMS)


def _requests_news_analysis(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(term in lowered for term in NEWS_QUERY_TERMS)


def _requests_financial_trend_analysis(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(term in lowered for term in FINANCIAL_TREND_QUERY_TERMS)


def _requests_ownership_analysis(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(term in lowered for term in OWNERSHIP_QUERY_TERMS)


def _requests_estimate_revision_analysis(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(term in lowered for term in ESTIMATE_REVISION_QUERY_TERMS)


def _requests_dividend_action_analysis(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(term in lowered for term in DIVIDEND_ACTION_QUERY_TERMS)


def _requests_earnings_quality_analysis(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(term in lowered for term in EARNINGS_QUALITY_QUERY_TERMS)


def _requests_liquidity_debt_analysis(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(term in lowered for term in LIQUIDITY_DEBT_QUERY_TERMS)


def _requests_profitability_return_analysis(message: str) -> bool:
    lowered = f" {' '.join(str(message or '').lower().split())} "
    return (
        any(term in lowered for term in PROFITABILITY_RETURN_QUERY_TERMS)
        or bool(re.search(r"\b(?:roe|roa|roic)\b", lowered))
    )


def market_prediction(symbol: str) -> Dict[str, Any]:
    symbol = _sanitize_symbol(symbol)
    cache_key = f"prediction:{symbol}"
    cached = _cache_get(cache_key, PREDICTION_CACHE_TTL_SECONDS)
    if cached is not None:
        return cached

    frame = _history(symbol, "2y")
    if len(frame) < 100:
        raise ValueError("At least 100 daily observations are required for a next-session outlook.")

    feature_columns = list(FEATURE_LABELS)
    features = _features(frame)
    dataset = features.copy()
    dataset["target"] = (frame["Close"].shift(-1) > frame["Close"]).astype(int)
    dataset = dataset.iloc[:-1].dropna()
    latest_features = features.dropna().iloc[-1:]
    if len(dataset) < 80 or latest_features.empty or dataset["target"].nunique() < 2:
        raise ValueError("Not enough clean historical data to train the direction model.")

    registry_model = None
    try:
        registry_model = approved_model(symbol)
    except Exception as error:
        logger.warning("Approved model lookup failed for %s; using runtime fallback: %s", symbol, error)

    if registry_model:
        run = registry_model["run"]
        registered_metrics = registry_model["metrics"]
        artifact = registry_model["artifact"]
        artifact_features = artifact.get("featureColumns") or []
        if artifact_features != feature_columns:
            raise ValueError("Approved model features do not match the current inference pipeline.")
        model = artifact["estimator"]
        selected = registered_metrics.get("selection") or {
            "id": "approved_artifact",
            "name": run["model_name"],
            "folds": registered_metrics.get("walkForwardFolds", 0),
            "testRows": run["holdout_rows"],
        }
        validation = {
            "selected": selected,
            "comparisons": registered_metrics.get("walkForwardCandidates") or [selected],
            "folds": registered_metrics.get("walkForwardFolds", selected.get("folds", 0)),
        }
        evaluation_metrics = {
            "accuracy": registered_metrics.get("accuracy", run["balanced_accuracy"]),
            "balancedAccuracy": run["balanced_accuracy"],
            "precision": registered_metrics.get("precision", 0.0),
            "recall": registered_metrics.get("recall", 0.0),
            "f1": registered_metrics.get("f1", 0.0),
            "rocAuc": run["roc_auc"],
            "brierScore": run["brier_score"],
        }
        model_run_id = run["id"]
        model_dataset_version = run["dataset_version"]
        serving_mode = "approved_artifact"
        model_training_rows = int(run["training_rows"]) + int(run["holdout_rows"])
        explanation_reference = artifact.get("explainabilityReference")
        selection_description = "Approved offline artifact that passed the final chronological holdout quality gate."
    else:
        validation = _walk_forward_model_comparison(dataset, feature_columns)
        selected = validation["selected"]
        model = _candidate_models()[selected["id"]]["estimator"]
        model.fit(dataset[feature_columns], dataset["target"])
        evaluation_metrics = selected
        model_run_id = None
        model_dataset_version = None
        serving_mode = "runtime_fallback"
        model_training_rows = len(dataset)
        explanation_reference = None
        selection_description = "Runtime fallback: best of three classifiers by walk-forward validation score."

    raw_technical_probability = float(model.predict_proba(latest_features[feature_columns])[0][1])
    balanced_accuracy = float(evaluation_metrics["balancedAccuracy"])
    auc = float(evaluation_metrics["rocAuc"] if evaluation_metrics["rocAuc"] is not None else 0.50)
    reliability_signal = ((balanced_accuracy - 0.50) * 0.65) + ((auc - 0.50) * 0.35)
    reliability_weight = max(0.12, min(1.0, reliability_signal / 0.12))
    technical_probability = 0.50 + ((raw_technical_probability - 0.50) * reliability_weight)

    news = market_news(symbol)
    news_adjustment = float(news["sentimentScore"] or 0) * 0.05
    macro = _macro_adjustment(symbol)
    macro_adjustment = float(macro["probabilityAdjustmentPoints"] or 0) / 100
    probability_up = max(0.05, min(0.95, technical_probability + news_adjustment + macro_adjustment))
    probability_down = 1 - probability_up
    bullish_threshold = 0.58
    bearish_threshold = 0.42
    if probability_up >= bullish_threshold:
        outlook = "BULLISH"
    elif probability_up <= bearish_threshold:
        outlook = "BEARISH"
    else:
        outlook = "NEUTRAL"

    close = float(frame["Close"].iloc[-1])
    daily_volatility = float(frame["Close"].pct_change().tail(20).std())
    range_move = max(0.005, daily_volatility * 1.28)
    rsi_value = float(latest_features["rsi_14"].iloc[0] * 100)
    sma20 = float(frame["Close"].rolling(20).mean().iloc[-1])
    sma50 = float(frame["Close"].rolling(50).mean().iloc[-1])
    snapshot = market_snapshot(symbol)
    baseline_accuracy = max(float(dataset["target"].mean()), 1 - float(dataset["target"].mean()))
    quality = "useful" if balanced_accuracy >= 0.58 and auc >= 0.57 else "weak" if balanced_accuracy < 0.53 else "limited"
    importance = _feature_importance(model, dataset, feature_columns)
    local_explanation = _local_feature_explanation(
        model,
        latest_features,
        dataset,
        feature_columns,
        reliability_weight,
        explanation_reference,
    )
    comparisons = [
        {
            "id": item["id"],
            "name": item["name"],
            "selected": item.get("id") == selected.get("id"),
            "folds": item.get("folds", 0),
            "testRows": item.get("testRows", 0),
            "accuracy": _round(item["accuracy"] * 100, 1),
            "balancedAccuracy": _round(item["balancedAccuracy"] * 100, 1),
            "precision": _round(item["precision"] * 100, 1),
            "recall": _round(item["recall"] * 100, 1),
            "f1": _round(item["f1"] * 100, 1),
            "rocAuc": _round(item["rocAuc"] * 100, 1) if item["rocAuc"] is not None else None,
            "brierScore": _round(item["brierScore"], 3),
        }
        for item in validation["comparisons"]
    ]

    payload = {
        "symbol": symbol,
        "name": snapshot["name"],
        "outlook": outlook,
        "predictionHorizon": "Next trading session",
        "probabilityUp": _round(probability_up * 100, 1),
        "probabilityDown": _round(probability_down * 100, 1),
        "expectedRange": {
            "low": _round(close * (1 - range_move)),
            "high": _round(close * (1 + range_move)),
            "currency": snapshot["currency"],
        },
        "lastClose": _round(close),
        "technicalIndicators": {
            "rsi14": _round(rsi_value, 1),
            "sma20": _round(sma20),
            "sma50": _round(sma50),
            "dailyVolatility20d": _round(daily_volatility * 100, 2),
        },
        "newsFactor": {
            "articleCount": len(news["articles"]),
            "sentimentLabel": news["sentimentLabel"],
            "sentimentScore": news["sentimentScore"],
            "probabilityAdjustmentPoints": _round(news_adjustment * 100, 2),
        },
        "macroFactor": macro,
        "riskBenchmark": market_risk_context(symbol, frame),
        "model": {
            "type": selected["name"],
            "selection": selection_description,
            "servingMode": serving_mode,
            "modelRunId": model_run_id,
            "datasetVersion": model_dataset_version,
            "trainingRows": model_training_rows,
            "testRows": selected.get("testRows", 0),
            "walkForwardFolds": validation["folds"],
            "backtestAccuracy": _round(evaluation_metrics["accuracy"] * 100, 1),
            "balancedAccuracy": _round(balanced_accuracy * 100, 1),
            "precision": _round(evaluation_metrics["precision"] * 100, 1),
            "recall": _round(evaluation_metrics["recall"] * 100, 1),
            "f1": _round(evaluation_metrics["f1"] * 100, 1),
            "rocAuc": _round(evaluation_metrics["rocAuc"] * 100, 1) if evaluation_metrics["rocAuc"] is not None else None,
            "brierScore": _round(evaluation_metrics["brierScore"], 3),
            "naiveAccuracy": _round(baseline_accuracy * 100, 1),
            "quality": quality,
            "rawTechnicalProbabilityUp": _round(raw_technical_probability * 100, 1),
            "reliabilityWeight": _round(reliability_weight, 2),
            "confidenceThresholds": {"bullish": 58, "bearish": 42},
            "calibration": "Out-of-sample skill controls shrinkage toward 50%; low-confidence results remain NEUTRAL.",
            "validation": "Expanding-window TimeSeriesSplit with a one-session gap; no random shuffle.",
            "modelsCompared": comparisons,
            "featureImportance": importance,
            "localExplanation": {
                **local_explanation,
                "probabilityPath": {
                    "rawTechnicalProbabilityUp": _round(raw_technical_probability * 100, 1),
                    "reliabilityAdjustedProbabilityUp": _round(technical_probability * 100, 1),
                    "newsAdjustmentPoints": _round(news_adjustment * 100, 2),
                    "macroAdjustmentPoints": _round(macro_adjustment * 100, 2),
                    "finalProbabilityUp": _round(probability_up * 100, 1),
                },
            },
        },
        "dataAsOf": snapshot["dataAsOf"],
        "modelDataDate": frame.index[-1].strftime("%Y-%m-%d"),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "history": [
            {"date": index.strftime("%Y-%m-%d"), "close": _round(row["Close"])}
            for index, row in frame.tail(90).iterrows()
        ],
        "disclaimer": "Probabilistic next-session research experiment, not a guaranteed price forecast or investment advice.",
    }
    payload["persistentHistoryBars"] = _persist_research_history(
        symbol, snapshot["name"], frame
    )
    payload["predictionAudit"] = _record_prediction(payload, payload["modelDataDate"])
    try:
        record_persistent_prediction(
            payload,
            feature_values={
                feature: float(latest_features.iloc[0][feature])
                for feature in feature_columns
            },
        )
    except Exception as error:
        logger.warning("Persistent prediction audit failed for %s: %s", symbol, error)
    return _cache_put(cache_key, payload)


def _ollama_chat(messages: List[Dict[str, str]]) -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("LLM_MODEL", "llama3.2:3b")
    timeout = max(5, int(os.getenv("LLM_TIMEOUT_MS", "15000")) // 1000)
    body = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": "10m",
        "options": {"temperature": 0.1, "num_predict": 700},
    }).encode("utf-8")
    request = UrlRequest(
        f"{base_url}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return str(payload.get("message", {}).get("content", "")).strip()
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Local Ollama service is unavailable or the configured model is not loaded.") from error


def _gemini_model_candidates(configured_model: str) -> List[str]:
    candidates = [
        configured_model.strip(),
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-flash-latest",
    ]
    return list(dict.fromkeys(model for model in candidates if model))


def _gemini_chat(messages: List[Dict[str, str]]) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Gemini is not configured. Set GEMINI_API_KEY on the Python backend.")
    configured_model = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite").strip()
    timeout = max(5.0, int(os.getenv("LLM_TIMEOUT_MS", "15000")) / 1000)
    deadline = time.monotonic() + timeout
    system_text = "\n".join(item["content"] for item in messages if item.get("role") == "system")
    contents = []
    for item in messages:
        role = item.get("role")
        if role == "system":
            continue
        contents.append({
            "role": "model" if role == "assistant" else "user",
            "parts": [{"text": str(item.get("content", ""))}],
        })
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": system_text}]},
        "contents": contents,
        # Gemini 3.x uses its default sampling behavior. Google deprecated
        # temperature/top-p/top-k for current models, so only cap the concise
        # Keep enough room for evidence, arithmetic, scenarios and caveats.
        "generationConfig": {"maxOutputTokens": 900},
    }).encode("utf-8")
    last_model_error: Optional[HTTPError] = None
    for model in _gemini_model_candidates(configured_model):
        remaining = deadline - time.monotonic()
        if remaining <= 0.25:
            raise RuntimeError("Gemini provider timeout reached before a usable model responded.")
        request = UrlRequest(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            method="POST",
        )
        try:
            # LLM_TIMEOUT_MS is a total budget across model-alias fallbacks,
            # rather than a fresh timeout for every retry.
            with urlopen(request, timeout=max(0.25, remaining)) as response:
                payload = json.loads(response.read().decode("utf-8"))
                parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                logger.info("Gemini connected using model %s", model)
                return "\n".join(str(part.get("text", "")) for part in parts).strip()
        except HTTPError as error:
            # A Blueprint may retain an older model environment value. Try
            # current stable aliases only when Google says that model is not
            # present; authentication, quota and request failures must remain
            # visible and should not trigger duplicate paid calls.
            if error.code == 404:
                last_model_error = error
                logger.warning("Gemini model %s is unavailable; trying a stable fallback", model)
                continue
            logger.warning("Gemini generateContent request rejected with HTTP %s", error.code)
            raise RuntimeError(f"Gemini request rejected (HTTP {error.code}).") from error
        except (URLError, TimeoutError, OSError, json.JSONDecodeError, IndexError) as error:
            logger.warning("Gemini generateContent request failed: %s", type(error).__name__)
            raise RuntimeError("Gemini service is unavailable or rejected the request.") from error

    raise RuntimeError("Gemini request rejected (HTTP 404).") from last_model_error


def _openai_compatible_chat(messages: List[Dict[str, str]], provider: str) -> str:
    if provider == "openai":
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        default_model = "gpt-4o-mini"
    else:
        base_url = os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
        api_key = os.getenv("LOCAL_LLM_API_KEY", "").strip()
        default_model = "local-model"
    if provider == "openai" and not api_key:
        raise RuntimeError("OpenAI is not configured. Set OPENAI_API_KEY on the Python backend.")
    timeout = max(5, int(os.getenv("LLM_TIMEOUT_MS", "15000")) // 1000)
    body = json.dumps({
        "model": os.getenv("LLM_MODEL", default_model),
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 900,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = UrlRequest(f"{base_url}/chat/completions", data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return str(payload.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError, IndexError) as error:
        raise RuntimeError(f"{provider} service is unavailable or rejected the request.") from error


def _provider_chat(messages: List[Dict[str, str]]) -> tuple[str, str]:
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if provider in {"", "none", "off", "disabled"}:
        raise RuntimeError("LLM is not configured; deterministic evidence synthesis is active.")
    if provider in {"ollama", "local"}:
        return _ollama_chat(messages), "ollama"
    if provider == "gemini":
        return _gemini_chat(messages), "gemini"
    if provider in {"openai", "openai-compatible"}:
        return _openai_compatible_chat(messages, provider), provider
    raise RuntimeError(f"Unsupported LLM_PROVIDER: {provider}")


def _llm_failure_code(error: RuntimeError) -> str:
    """Return a safe, user-actionable provider failure category.

    Provider exceptions deliberately contain no credentials or response bodies,
    so this value can be returned to the dashboard without exposing secrets.
    """
    message = str(error).lower()
    if "not configured" in message:
        return "missing_configuration"
    if "http 401" in message or "http 403" in message:
        return "authentication_rejected"
    if "http 429" in message:
        return "quota_exceeded"
    if "http 404" in message:
        return "model_unavailable"
    if "http 400" in message:
        return "request_rejected"
    if "timeout" in message:
        return "provider_timeout"
    if "unavailable" in message:
        return "provider_unavailable"
    return "provider_error"


def _verified_tool_answer(
    message: str,
    snapshot: Dict[str, Any],
    prediction: Dict[str, Any],
    tools: List[str],
    factor_payload: Dict[str, Any],
    breadth: Optional[Dict[str, Any]] = None,
    historical: Optional[Dict[str, Any]] = None,
    document_matches: Optional[List[Dict[str, Any]]] = None,
    document_requested: bool = False,
    company_profile: Optional[Dict[str, Any]] = None,
    news_payload: Optional[Dict[str, Any]] = None,
) -> str:
    news = prediction["newsFactor"]
    model = prediction["model"]
    lowered = message.lower()
    requested = []
    keyword_map = {
        "gold": "GC=F", "crude": "CL=F", "oil": "CL=F", "rupee": "INR=X",
        "dollar": "INR=X", "yield": "^TNX", "vix": "^VIX", "bitcoin": "BTC-USD",
    }
    factors_by_symbol = {item["symbol"]: item for item in factor_payload.get("factors", [])}
    for keyword, factor_symbol in keyword_map.items():
        if keyword in lowered and factor_symbol not in requested:
            requested.append(factor_symbol)
    if not requested:
        requested = [item["symbol"] for item in factor_payload.get("factors", [])[:4]]

    factor_lines = []
    for factor_symbol in requested:
        item = factors_by_symbol.get(factor_symbol)
        if not item or item.get("status") != "available":
            continue
        move = float(item.get("changePercent") or 0)
        if factor_symbol == "CL=F":
            impact = (
                "India ke liye higher oil import bill, inflation aur transport/input costs badha sakta hai."
                if move > 0 else
                "India ke liye lower oil import bill aur inflation pressure ko ease kar sakta hai."
            )
        elif factor_symbol == "GC=F":
            impact = (
                "Rise defensive demand ka signal ho sakta hai aur jewellery input cost badha sakta hai; Nifty direction akela decide nahi karta."
                if move > 0 else
                "Fall defensive demand kam hone ka signal ho sakta hai; Nifty direction akela decide nahi karta."
            )
        elif factor_symbol == "INR=X":
            impact = (
                "USD/INR rise weaker rupee dikhata hai: importers par pressure, kuch exporters ko support."
                if move > 0 else
                "USD/INR fall stronger rupee dikhata hai: import costs ko relief, exporters ka currency benefit kam."
            )
        elif factor_symbol == "^VIX":
            impact = "VIX rise risk badhata hai." if move > 0 else "VIX fall risk appetite ko support kar sakta hai."
        elif factor_symbol == "^TNX":
            impact = "Higher yields valuations par pressure daal sakte hain." if move > 0 else "Lower yields valuation pressure ease kar sakte hain."
        else:
            impact = item.get("theme", "Contextual market factor.")
        factor_lines.append(f"- {item['name']}: {move:+.2f}% - {impact}")

    brief = _build_analysis_brief(snapshot, prediction)
    evidence_lines = [
        f"- {prediction['name']} price: {brief['currentPrice']} {prediction['expectedRange']['currency']}; "
        f"daily move {float(brief['dailyChangePercent'] or 0):+.2f}%.",
        f"- Model outlook: {prediction['outlook']}; probability-up {brief['probabilityUp']}% aur "
        f"probability-down {brief['probabilityDown']}%.",
        f"- Expected range: {prediction['expectedRange']['low']}–{prediction['expectedRange']['high']} "
        f"{prediction['expectedRange']['currency']}; data as of {prediction['dataAsOf']}.",
    ]
    historical_section = ""
    if historical:
        exact_note = "exact trading session" if historical["exactSession"] else "nearest available trading session"
        historical_section = (
            "\n\nHistorical date check\n"
            f"- Requested date {historical['requestedDate']}; {exact_note}: {historical['sessionDate']}.\n"
            f"- Open {historical['open']}, high {historical['high']}, low {historical['low']}, "
            f"close {historical['close']}; change {float(historical.get('changePercent') or 0):+.2f}%.\n"
            f"- Calculation: ({historical['close']} - {historical['previousClose']}) ÷ "
            f"{historical['previousClose']} × 100 = {float(historical.get('changePercent') or 0):+.2f}%."
        )
        if historical.get("nextSession"):
            next_session = historical["nextSession"]
            historical_section += (
                f" Next session {next_session['date']} par close {next_session['close']} "
                f"({float(next_session.get('changePercent') or 0):+.2f}%) tha."
            )

    breadth_line = ""
    if breadth:
        breadth_line = (
            f"\n- Watchlist breadth: {breadth['advances']} advances, {breadth['declines']} declines, "
            f"{breadth['unchanged']} unchanged ({breadth['coverageCount']} covered)."
        )
        if breadth.get("topGainers"):
            top = breadth["topGainers"][0]
            breadth_line += f" Strongest covered mover: {top['name']} {float(top['changePercent']):+.2f}%."
        if breadth.get("topLosers"):
            bottom = breadth["topLosers"][0]
            breadth_line += f" Weakest covered mover: {bottom['name']} {float(bottom['changePercent']):+.2f}%."

    reliability = (
        "Walk-forward balanced accuracy 53% se kam hai, isliye model me reliable directional edge nahi hai."
        if not brief["modelHasReliableDirectionalEdge"] else
        "Walk-forward score 53% threshold ke upar hai, phir bhi prediction probabilistic hai aur certainty nahi."
    )
    document_section = ""
    if document_requested:
        if document_matches:
            document_lines = []
            for match in document_matches[:4]:
                citation = f"[{match['citation']} p.{match['page']}]"
                document_lines.append(
                    f"- {citation} {match['snippet']} (Source: {match['title']})"
                )
            document_section = (
                "\n\nIndexed company-document evidence\n"
                + "\n".join(document_lines)
                + "\n- Document statements are kept separate from current prices and model estimates."
            )
        else:
            document_section = (
                "\n\nIndexed company-document evidence\n"
                "- Is symbol ke liye is question ka retrievable indexed evidence available nahi hai. "
                "Main annual report ya filing ka answer invent nahi kar raha hoon."
            )
    risk_section = ""
    risk_requested = _requests_risk_analysis(lowered)
    risk = prediction.get("riskBenchmark") or {}
    asset_risk = risk.get("asset") or {}
    comparison = risk.get("comparison") or {}
    benchmark = risk.get("benchmark") or {}
    if risk_requested and asset_risk:
        risk_lines = [
            f"- Period return {asset_risk.get('periodReturnPercent')}%; annualized volatility "
            f"{asset_risk.get('annualizedVolatilityPercent')}%.",
            f"- Maximum drawdown {asset_risk.get('maxDrawdownPercent')}%; 95% historical one-day VaR "
            f"{asset_risk.get('historicalVar95Percent')}%.",
        ]
        if comparison:
            risk_lines.append(
                f"- {benchmark.get('name')} comparison: relative return "
                f"{float(comparison.get('relativeReturnPoints') or 0):+.2f} percentage points, beta "
                f"{comparison.get('beta')}, correlation {comparison.get('correlation')}, tracking error "
                f"{comparison.get('trackingErrorPercent')}%."
            )
        else:
            risk_lines.append("- Selected index ke liye self-benchmark comparison intentionally nahi banaya gaya.")
        risk_section = (
            "\n\nHistorical risk and benchmark evidence\n"
            + "\n".join(risk_lines)
            + "\n- Ye trailing historical statistics hain; future loss limit ya recommendation nahi."
        )
        risk_only_question = not any(term in lowered for term in (
            "outlook", "prediction", "forecast", "probability", "rsi", "expected range",
            "news", "headline", "fundamental", "earnings", "document", "report",
        ))
        if risk_only_question:
            relative_return = comparison.get("relativeReturnPoints")
            relative_meaning = (
                f"Selected period me {prediction['name']} benchmark se "
                f"{abs(float(relative_return)):.2f} percentage points "
                f"{'peeche' if float(relative_return) < 0 else 'aage'} raha."
                if relative_return is not None else
                "Is listing ke liye relative-return comparison available nahi hai."
            )
            return (
                f"{prediction['name']} ko broad market se compare karne ka matlab hai: stock ka return aur risk "
                f"usi period ke {benchmark.get('name') or 'selected benchmark'} ke saamne dekhna.\n\n"
                + risk_section.strip()
                + "\n\nIska simple meaning\n- "
                + relative_meaning
                + f" Beta {comparison.get('beta')} market sensitivity batata hai; correlation "
                f"{comparison.get('correlation')} dono ke saath chalne ki strength batata hai.\n"
                + "- Historical numbers future performance ki guarantee nahi hain."
            )
    catalyst_section = ""
    if _requests_catalyst_analysis(lowered):
        catalysts = (company_profile or {}).get("catalysts") or {}
        if catalysts.get("status") == "available":
            event_lines = [
                f"- {item['label']}: {item['date']} ({item['status']})."
                for item in (catalysts.get("events") or [])[:3]
            ]
            consensus = catalysts.get("analystConsensus") or {}
            analyst_line = (
                f"- External analyst consensus: {consensus.get('recommendation')}; "
                f"{consensus.get('analystCount') or 0} opinions; mean target "
                f"{consensus.get('targetMean')}; current-price gap {consensus.get('targetGapPercent')}%."
                if consensus.get("analystCount") or consensus.get("targetMean") is not None else
                "- External analyst target evidence provider ne return nahi kiya."
            )
            surprise = catalysts.get("surpriseSummary") or {}
            catalyst_section = (
                "\n\nCompany catalysts and external expectations\n"
                + ("\n".join(event_lines) if event_lines else "- Dated corporate event provider ne return nahi kiya.")
                + "\n" + analyst_line
                + f"\n- Reported EPS history: {surprise.get('reportedQuarters') or 0} quarters, "
                + f"{surprise.get('beats') or 0} beats, {surprise.get('misses') or 0} misses."
                + "\n- Analyst opinions FinTrack ML prediction se separate hain; target guaranteed future price nahi."
            )
        else:
            catalyst_section = (
                "\n\nCompany catalysts and external expectations\n"
                "- Is listing ke liye provider ne calendar, analyst target ya EPS-surprise evidence return nahi kiya. "
                "Missing catalyst invent nahi kiya gaya."
            )
    news_section = ""
    if _requests_news_analysis(lowered):
        intelligence = (news_payload or {}).get("intelligence") or {}
        articles = (news_payload or {}).get("articles") or []
        if intelligence.get("status") == "available":
            distribution = intelligence.get("distribution") or {}
            themes = intelligence.get("themes") or []
            theme_text = ", ".join(
                f"{item.get('theme')} ({item.get('articleCount')})" for item in themes[:4]
            ) or "no repeated theme"
            headline_lines = [
                f"- {item.get('title')} — {item.get('publisher')} "
                f"({item.get('sentimentLabel')}, {item.get('publishedAt') or 'date unavailable'})."
                for item in articles[:3]
            ]
            news_section = (
                "\n\nCompany headline intelligence\n"
                f"- Aggregate title tone {intelligence.get('sentimentLabel')} at score "
                f"{intelligence.get('sentimentScore')}; {intelligence.get('articleCount')} headlines from "
                f"{intelligence.get('sourceCount')} publishers; coverage {intelligence.get('coverage')}, "
                f"freshness {intelligence.get('freshness')}.\n"
                f"- Distribution: {distribution.get('positive') or 0} positive, "
                f"{distribution.get('mixed/neutral') or 0} mixed/neutral, "
                f"{distribution.get('negative') or 0} negative.\n"
                f"- Dominant title themes: {theme_text}.\n"
                + ("\n".join(headline_lines) if headline_lines else "- No dated headline detail was returned.")
                + "\n- This is transparent title-keyword evidence, not article-body understanding, a fact verdict or a trading signal."
            )
        else:
            news_section = (
                "\n\nCompany headline intelligence\n"
                "- Recent provider headlines available nahi hain, isliye sentiment, theme ya publisher coverage invent nahi kiya gaya."
            )
    financial_trend_section = ""
    if _requests_financial_trend_analysis(lowered):
        trends = (company_profile or {}).get("financialTrends") or {}
        if trends.get("status") == "available":
            summary = trends.get("summary") or {}
            latest = (trends.get("annual") or [{}])[-1]
            financial_currency = prediction.get("expectedRange", {}).get("currency")
            financial_trend_section = (
                "\n\nFinancial statement trend evidence\n"
                f"- Latest annual period {summary.get('latestAnnualPeriod')}; revenue "
                f"{_compact_amount(latest.get('revenue'), financial_currency)}, "
                f"YoY {latest.get('revenueYoYPercent')}%, multi-year CAGR {summary.get('revenueCagrPercent')}%, "
                f"trend {summary.get('revenueTrend')}.\n"
                f"- Net income {_compact_amount(latest.get('netIncome'), financial_currency)}, "
                f"YoY {latest.get('netIncomeYoYPercent')}%, "
                f"trend {summary.get('netIncomeTrend')}; operating margin "
                f"{summary.get('latestOperatingMarginPercent')}% ({summary.get('operatingMarginChangePoints')} points vs prior year).\n"
                f"- Free cash flow {_compact_amount(summary.get('latestFreeCashFlow'), financial_currency)}, "
                f"trend {summary.get('freeCashFlowTrend')}; "
                f"debt/equity {summary.get('latestDebtToEquityRatio')}x and debt YoY "
                f"{summary.get('latestDebtYoYPercent')}%.\n"
                "- These are provider statement periods and FinTrack arithmetic, not estimates or an accounting audit."
            )
        else:
            financial_trend_section = (
                "\n\nFinancial statement trend evidence\n"
                "- Comparable provider statement periods available nahi hain; missing growth, margin ya cash-flow trend invent nahi kiya gaya."
            )
    ownership_section = ""
    if _requests_ownership_analysis(lowered):
        ownership = (company_profile or {}).get("ownershipIntelligence") or {}
        if ownership.get("status") == "available":
            major = ownership.get("majorOwnership") or {}
            concentration = ownership.get("concentration") or {}
            insider = ownership.get("insiderSummary") or {}
            institutions = ownership.get("institutionalHolders") or []
            funds = ownership.get("mutualFundHolders") or []
            transactions = ownership.get("recentInsiderTransactions") or []
            institution_lines = [
                f"- {item.get('holder')}: {item.get('percentHeld')}% held, "
                f"{_compact_amount(item.get('shares'))} shares, reported {item.get('dateReported') or 'date unavailable'}."
                for item in institutions[:3]
            ]
            transaction_lines = [
                f"- {item.get('date') or 'Date unavailable'}: {item.get('insider')} "
                f"({item.get('position')}) reported {item.get('type')} of "
                f"{_compact_amount(item.get('shares'))} shares."
                for item in transactions[:3]
            ]
            ownership_section = (
                "\n\nOwnership and insider activity evidence\n"
                f"- Provider-reported ownership: insiders {major.get('insidersPercentHeld')}%, "
                f"institutions {major.get('institutionsPercentHeld')}%, institutions on float "
                f"{major.get('institutionsFloatPercentHeld')}%, across {major.get('institutionsCount') or 0} reported institutions.\n"
                f"- Returned-holder concentration only: top {concentration.get('returnedInstitutionCount') or 0} "
                f"institution rows total {concentration.get('topInstitutionsPercentHeld')}%; top "
                f"{concentration.get('returnedFundCount') or 0} mutual-fund rows total "
                f"{concentration.get('topFundsPercentHeld')}%. FinTrack does not extrapolate unreturned holders.\n"
                + ("\n".join(institution_lines) if institution_lines else "- Institutional holder rows provider ne return nahi kiye.")
                + ("" if funds else "\n- Mutual-fund holder rows provider ne return nahi kiye.")
                + f"\n- Six-month insider summary: {insider.get('netActivity')}; purchases "
                f"{_compact_amount(insider.get('purchaseShares'))} shares in {insider.get('purchaseTransactions') or 0} "
                f"transactions, sales {_compact_amount(insider.get('saleShares'))} shares in "
                f"{insider.get('saleTransactions') or 0} transactions, net "
                f"{_compact_amount(insider.get('netSharesPurchased'))} shares ({insider.get('netSharesPercent')}%).\n"
                + ("\n".join(transaction_lines) if transaction_lines else "- Recent insider transaction rows provider ne return nahi kiye.")
                + "\n- Holder reports can be delayed, and insider activity needs context; it is not a standalone bullish/bearish signal or investment advice."
            )
        else:
            ownership_section = (
                "\n\nOwnership and insider activity evidence\n"
                "- Is listing ke liye provider ne ownership ya insider dataset return nahi kiya; missing holdings or activity invent nahi ki gayi."
            )
    estimate_revision_section = ""
    if _requests_estimate_revision_analysis(lowered):
        estimates = (company_profile or {}).get("analystEstimateIntelligence") or {}
        if estimates.get("status") == "available":
            summary = estimates.get("summary") or {}
            periods = estimates.get("periods") or []
            current = next((item for item in periods if item.get("period") == "0q"), periods[0] if periods else {})
            eps = current.get("eps") or {}
            revenue = current.get("revenue") or {}
            revisions = current.get("revisionCounts") or {}
            trend = current.get("epsTrend") or {}
            estimate_currency = prediction.get("expectedRange", {}).get("currency")
            shown = lambda value: "unavailable" if value is None else str(value)
            shown_percent = lambda value: "unavailable" if value is None else f"{value}%"
            period_lines = []
            for item in periods:
                item_eps = item.get("eps") or {}
                item_revenue = item.get("revenue") or {}
                item_revisions = item.get("revisionCounts") or {}
                period_lines.append(
                    f"- {item.get('label')}: EPS average {shown(item_eps.get('average'))}, range "
                    f"{shown(item_eps.get('low'))} to {shown(item_eps.get('high'))}, growth {shown_percent(item_eps.get('growthPercent'))}; "
                    f"revenue {_compact_amount(item_revenue.get('average'), estimate_currency)}, growth "
                    f"{shown_percent(item_revenue.get('growthPercent'))}; 30-day revisions "
                    f"{item_revisions.get('signal') or 'unavailable'} (net {shown(item_revisions.get('netLast30Days'))})."
                )
            mismatches = summary.get("periodsWithBasisMismatch") or []
            mismatch_line = (
                f"- EPS trend basis published estimate range se {', '.join(mismatches)} period(s) me mismatch hai; "
                "FinTrack incompatible series ko merge nahi karta."
                if mismatches else
                "- Returned EPS trend snapshots published estimate-range basis ke saath comparable hain."
            )
            estimate_revision_section = (
                "\n\nAnalyst estimates and revision evidence\n"
                f"- Current-quarter external consensus: EPS average {shown(eps.get('average'))} across "
                f"{eps.get('analystCount') or summary.get('currentQuarterAnalystCount') or 0} analysts, "
                f"range {shown(eps.get('low'))} to {shown(eps.get('high'))}, expected growth "
                f"{shown_percent(eps.get('growthPercent'))}.\n"
                f"- Current-quarter revenue average {_compact_amount(revenue.get('average'), estimate_currency)}, "
                f"range {_compact_amount(revenue.get('low'), estimate_currency)} to "
                f"{_compact_amount(revenue.get('high'), estimate_currency)}, expected growth "
                f"{shown_percent(revenue.get('growthPercent'))}.\n"
                f"- Revision breadth: {revisions.get('signal') or 'unavailable'}; 7-day up/down "
                f"{shown(revisions.get('upLast7Days'))}/{shown(revisions.get('downLast7Days'))}, 30-day up/down "
                f"{shown(revisions.get('upLast30Days'))}/{shown(revisions.get('downLast30Days'))}. EPS trend-series "
                f"30-day change {shown(trend.get('change30Days'))}.\n"
                + "\n".join(period_lines)
                + "\n" + mismatch_line
                + "\n- These are changing third-party analyst estimates, not company guidance, FinTrack ML output or guaranteed results."
            )
        else:
            estimate_revision_section = (
                "\n\nAnalyst estimates and revision evidence\n"
                "- Is listing ke liye provider ne analyst estimate/revision dataset return nahi kiya; missing consensus invent nahi kiya gaya."
            )
    dividend_action_section = ""
    if _requests_dividend_action_analysis(lowered):
        actions = (company_profile or {}).get("corporateActionIntelligence") or {}
        if actions.get("status") == "available":
            summary = actions.get("summary") or {}
            action_snapshot = actions.get("snapshot") or {}
            currency = actions.get("currency") or prediction.get("expectedRange", {}).get("currency") or "listing currency"
            shown = lambda value: "unavailable" if value is None else str(value)
            recent_dividends = actions.get("recentDividends") or []
            annual = actions.get("annualDividends") or []
            splits = actions.get("recentSplits") or []
            capital_gains = actions.get("recentCapitalGains") or []
            event_lines = [
                f"- {item.get('label')}: {item.get('date')} ({item.get('status')})."
                for item in (actions.get("upcomingEvents") or [])
            ]
            annual_lines = [
                f"- {item.get('year')}: {item.get('totalPerShare')} {currency} per share across "
                f"{item.get('paymentCount')} payment(s)"
                + (" (partial calendar year)." if item.get("isPartialYear") else
                   f"; annual change {shown(item.get('changePercent'))}%.")
                for item in annual[:5]
            ]
            split_lines = [
                f"- {item.get('date')}: {item.get('displayRatio')} split."
                for item in splits[:4]
            ]
            dividend_action_section = (
                "\n\nDividend and corporate-action evidence\n"
                f"- Trailing 12-month cash distributions: {shown(summary.get('trailing12MonthTotalPerShare'))} "
                f"{currency} per share across {summary.get('paymentsLast12Months') or 0} payment(s); prior trailing "
                f"window {shown(summary.get('previous12MonthTotalPerShare'))}, change "
                f"{shown(summary.get('trailingChangePercent'))}%.\n"
                f"- Current yield {shown(action_snapshot.get('currentYieldPercent'))}%; payout ratio "
                f"{shown(action_snapshot.get('payoutRatioPercent'))}%; completed-year dividend CAGR "
                f"{shown(summary.get('completedYearDividendCagrPercent'))}% "
                f"({shown(summary.get('completedYearCagrStart'))} to {shown(summary.get('completedYearCagrEnd'))}).\n"
                + ("\n".join(annual_lines) if annual_lines else "- Provider payment history is unavailable; no zero dividend was inferred.")
                + ("\n" + "\n".join(split_lines) if split_lines else "\n- No split history was returned by the provider.")
                + (f"\n- Provider returned {len(capital_gains)} capital-gain distribution record(s)." if capital_gains else "")
                + ("\n" + "\n".join(event_lines) if event_lines else "")
                + "\n- Current calendar-year totals are partial. Historical distributions are not guaranteed, missing data is not zero, and a stock split does not create economic value by itself."
            )
        else:
            dividend_action_section = (
                "\n\nDividend and corporate-action evidence\n"
                "- Provider ne is listing ke liye dividend, distribution ya split evidence return nahi kiya. "
                "Missing data ko zero dividend ya no-action claim nahi maana gaya."
            )
    earnings_quality_section = ""
    if _requests_earnings_quality_analysis(lowered):
        quality = (company_profile or {}).get("earningsQualityIntelligence") or {}
        if quality.get("status") == "available":
            summary = quality.get("summary") or {}
            annual = quality.get("annual") or []
            latest = annual[-1] if annual else {}
            quality_currency = quality.get("currency") or prediction.get("expectedRange", {}).get("currency")
            shown_percent = lambda value: "unavailable" if value is None else f"{value}%"
            annual_lines = [
                f"- {item.get('period')}: net income {_compact_amount(item.get('netIncome'), quality_currency)}, "
                f"operating cash {_compact_amount(item.get('operatingCashFlow'), quality_currency)} "
                f"({shown_percent(item.get('operatingCashConversionPercent'))} of positive net income), FCF "
                f"{_compact_amount(item.get('freeCashFlow'), quality_currency)}; shareholder cash returns "
                f"{_compact_amount(item.get('shareholderCashReturns'), quality_currency)}."
                for item in annual[-4:]
            ]
            sector_caution = (
                "\n- Financial-institution caution: debt and operating cash-flow classifications reflect the business model and are not directly comparable with industrial companies."
                if quality.get("financialSectorCaution") else ""
            )
            earnings_quality_section = (
                "\n\nEarnings quality and capital-allocation evidence\n"
                f"- Latest reported period {summary.get('latestPeriod')}: operating-cash conversion "
                f"{shown_percent(summary.get('latestOperatingCashConversionPercent'))}, FCF conversion "
                f"{shown_percent(summary.get('latestFreeCashFlowConversionPercent'))}, earnings-to-operating-cash gap "
                f"{_compact_amount(summary.get('latestEarningsCashGap'), quality_currency)}.\n"
                f"- Capital deployment: capex {_compact_amount(summary.get('latestCapitalExpenditure'), quality_currency)} "
                f"({shown_percent(summary.get('latestCapitalExpenditureToOperatingCashFlowPercent'))} of operating cash), "
                f"shareholder cash returns {_compact_amount(summary.get('latestShareholderCashReturns'), quality_currency)} "
                f"({shown_percent(summary.get('latestShareholderReturnsToFreeCashFlowPercent'))} of positive FCF), "
                f"FCF after those returns {_compact_amount(summary.get('latestFreeCashFlowAfterShareholderReturns'), quality_currency)}.\n"
                f"- Net common-stock issuance {_compact_amount(summary.get('latestNetCommonStockIssuance'), quality_currency)}; "
                f"net debt issuance {_compact_amount(summary.get('latestNetDebtIssuance'), quality_currency)}; positive FCF in "
                f"{summary.get('positiveFreeCashFlowPeriods') or 0} of {summary.get('freeCashFlowPeriodCount') or 0} returned period(s).\n"
                + "\n".join(annual_lines)
                + sector_caution
                + "\n- Cash conversion is descriptive, not an accounting-quality score. Statements can be restated, missing rows are not zero, and capital allocation is not a standalone investment signal."
            )
        else:
            earnings_quality_section = (
                "\n\nEarnings quality and capital-allocation evidence\n"
                "- Comparable annual income/cash-flow periods available nahi hain; missing conversion, buyback, issuance ya debt-flow evidence invent nahi kiya gaya."
            )
    liquidity_debt_section = ""
    if _requests_liquidity_debt_analysis(lowered):
        liquidity = (company_profile or {}).get("liquidityDebtIntelligence") or {}
        if liquidity.get("status") == "available":
            summary = liquidity.get("summary") or {}
            annual = liquidity.get("annual") or []
            liquidity_currency = liquidity.get("currency") or prediction.get("expectedRange", {}).get("currency")
            shown_ratio = lambda value: "unavailable" if value is None else f"{value}x"
            shown_percent = lambda value: "unavailable" if value is None else f"{value}%"
            annual_lines = [
                f"- {item.get('period')}: liquid funds {_compact_amount(item.get('liquidFunds'), liquidity_currency)} "
                f"({item.get('liquidityBasis')}), total debt {_compact_amount(item.get('totalDebt'), liquidity_currency)}, "
                f"debt after liquid funds {_compact_amount(item.get('debtAfterLiquidFunds'), liquidity_currency)}, "
                f"current ratio {shown_ratio(item.get('currentRatio'))}."
                for item in annual[-4:]
            ]
            mismatch_periods = summary.get("providerNetDebtBasisMismatchPeriods") or []
            mismatch_line = (
                f"\n- Provider net-debt basis differs from FinTrack's total-debt-minus-liquid-funds calculation in {', '.join(mismatch_periods)}; the values are kept separate."
                if mismatch_periods else ""
            )
            sector_caution = (
                "\n- Financial-institution caution: debt, liquidity and interest classifications reflect the business model; industrial-company interest coverage and debt/EBITDA are intentionally withheld."
                if liquidity.get("financialSectorCaution") else ""
            )
            liquidity_debt_section = (
                "\n\nBalance-sheet liquidity and debt-capacity evidence\n"
                f"- Latest reported period {summary.get('latestPeriod')}: liquid funds "
                f"{_compact_amount(summary.get('latestLiquidFunds'), liquidity_currency)} using "
                f"{summary.get('latestLiquidityBasis')}; total debt {_compact_amount(summary.get('latestTotalDebt'), liquidity_currency)}; "
                f"debt after liquid funds {_compact_amount(summary.get('latestDebtAfterLiquidFunds'), liquidity_currency)} "
                f"({summary.get('latestBalancePosition')}).\n"
                f"- Liquidity: current ratio {shown_ratio(summary.get('latestCurrentRatio'))}, working capital "
                f"{_compact_amount(summary.get('latestWorkingCapital'), liquidity_currency)}, liquid-funds-to-debt "
                f"{shown_percent(summary.get('latestLiquidFundsToDebtPercent'))}; liquid-funds trend {summary.get('liquidFundsTrend')}.\n"
                f"- Debt capacity: debt/equity {shown_ratio(summary.get('latestTotalDebtToEquityRatio'))}, debt/assets "
                f"{shown_percent(summary.get('latestTotalDebtToAssetsPercent'))}, interest coverage "
                f"{shown_ratio(summary.get('latestInterestCoverageRatio'))}, debt/EBITDA "
                f"{shown_ratio(summary.get('latestDebtToEbitdaRatio'))}; total-debt trend {summary.get('totalDebtTrend')}.\n"
                + "\n".join(annual_lines)
                + mismatch_line
                + sector_caution
                + "\n- This is descriptive balance-sheet evidence, not a credit rating or synthetic health score. Statements can be restated, missing rows are not zero, and debt capacity also depends on maturities, covenants and cash-flow stability."
            )
        else:
            liquidity_debt_section = (
                "\n\nBalance-sheet liquidity and debt-capacity evidence\n"
                "- Provider ne comparable annual balance-sheet rows return nahi kiye; missing liquidity, leverage ya coverage ratios invent nahi kiye gaye."
            )
    profitability_returns_section = ""
    if _requests_profitability_return_analysis(lowered):
        returns = (company_profile or {}).get("profitabilityReturnsIntelligence") or {}
        if returns.get("status") == "available":
            summary = returns.get("summary") or {}
            annual = returns.get("annual") or []
            shown_percent = lambda value: "unavailable" if value is None else f"{value}%"
            shown_ratio = lambda value: "unavailable" if value is None else f"{value}x"
            annual_lines = [
                f"- {item.get('period')}: gross/operating/net margins "
                f"{shown_percent(item.get('grossMarginPercent'))}/{shown_percent(item.get('operatingMarginPercent'))}/"
                f"{shown_percent(item.get('netMarginPercent'))}; ROA {shown_percent(item.get('returnOnAssetsPercent'))}, "
                f"ROE {shown_percent(item.get('returnOnEquityPercent'))}, ROIC "
                f"{shown_percent(item.get('returnOnInvestedCapitalPercent'))}, asset turnover "
                f"{shown_ratio(item.get('assetTurnoverRatio'))}."
                for item in annual[-4:]
            ]
            sector_caution = (
                "\n- Financial-institution caution: ROA and ROE remain descriptive, but industrial ROIC is intentionally withheld because debt and cash are operating inputs."
                if returns.get("financialSectorCaution") else
                "\n- ROIC is an approximation using provider-derived tax rate and average debt plus equity minus disclosed liquid funds; it is not company-reported ROIC."
            )
            profitability_returns_section = (
                "\n\nProfitability, returns and capital-efficiency evidence\n"
                f"- Latest reported period {summary.get('latestPeriod')}: gross margin "
                f"{shown_percent(summary.get('latestGrossMarginPercent'))}, operating margin "
                f"{shown_percent(summary.get('latestOperatingMarginPercent'))}, net margin "
                f"{shown_percent(summary.get('latestNetMarginPercent'))}.\n"
                f"- Average-balance returns: ROA {shown_percent(summary.get('latestReturnOnAssetsPercent'))}, "
                f"ROE {shown_percent(summary.get('latestReturnOnEquityPercent'))}, industrial ROIC "
                f"{shown_percent(summary.get('latestReturnOnInvestedCapitalPercent'))}.\n"
                f"- Efficiency bridge: asset turnover {shown_ratio(summary.get('latestAssetTurnoverRatio'))}, "
                f"equity multiplier {shown_ratio(summary.get('latestEquityMultiplierRatio'))}, effective tax rate "
                f"{shown_percent(summary.get('latestEffectiveTaxRatePercent'))}; operating-margin trend "
                f"{summary.get('operatingMarginTrend')}.\n"
                + "\n".join(annual_lines)
                + sector_caution
                + "\n- ROA, ROE and ROIC use average beginning and ending balances. These are descriptive accounting ratios, not a profitability score, moat rating or investment recommendation; statements can be restated and cross-company accounting policies can differ."
            )
        else:
            profitability_returns_section = (
                "\n\nProfitability, returns and capital-efficiency evidence\n"
                "- Provider ne aligned annual income-statement aur balance-sheet rows return nahi kiye; missing margins, ROA, ROE ya ROIC invent nahi kiye gaye."
            )
    return (
        f"{prediction['name']} ke liye model ka current scenario {prediction['outlook']} hai, lekin ise guaranteed "
        "direction ya trading call nahi samajhna chahiye.\n\n"
        "Verified figures\n"
        + "\n".join(evidence_lines)
        + historical_section
        + "\n\nRelevant market factors\n"
        + ("\n".join(factor_lines) if factor_lines else "- Requested live factor data abhi available nahi hai.")
        + breadth_line
        + risk_section
        + catalyst_section
        + news_section
        + financial_trend_section
        + ownership_section
        + estimate_revision_section
        + dividend_action_section
        + earnings_quality_section
        + liquidity_debt_section
        + profitability_returns_section
        + "\n\nCalculation aur scenario\n"
        + f"- Current price se lower range tak downside: {brief['currentPrice']} - "
        + f"{prediction['expectedRange']['low']} = {brief['expectedDownsidePoints']} points "
        + f"({brief['expectedDownsidePercent']}%).\n"
        + f"- Current price se upper range tak upside: {prediction['expectedRange']['high']} - "
        + f"{brief['currentPrice']} = {brief['expectedUpsidePoints']} points "
        + f"(+{brief['expectedUpsidePercent']}%).\n"
        + f"- Probability neutral 50% se sirf {brief['distanceFromNeutralPoints']} points door hai. "
        + f"News tone {news['sentimentLabel']} hai.\n\n"
        + "Assumptions aur confidence\n"
        + f"- {reliability} Balanced accuracy {model['balancedAccuracy']}%, "
        + f"{model['walkForwardFolds']} time-ordered folds, quality {model.get('quality', 'unknown')}.\n"
        + "- Range historical volatility aur available factors par based hai; breaking news, gaps aur provider delay "
        + "actual outcome badal sakte hain.\n\n"
        + "Final assessment\n"
        + f"Base case {prediction['outlook']} hai. Downside/neutral/upside tino scenario possible hain; "
        + "FinTrack isse research estimate ke roop me dikhata hai, personalized buy/sell advice ke roop me nahi."
        + document_section
    )


def _verified_document_answer(
    symbol: str,
    question: str,
    document_matches: List[Dict[str, Any]],
) -> str:
    """Return citation-first evidence when a document question is asked offline."""
    if not document_matches:
        return (
            f"{symbol} ke indexed documents me is question ka retrievable evidence available nahi hai. "
            "Main annual report ya filing ka answer invent nahi kar raha hoon.\n\n"
            "Evidence boundary\n"
            "Current market prices, ML predictions aur company-document statements alag evidence types hain. "
            "Document index ready hone ke baad isi question ko dobara poochha ja sakta hai.\n\n"
            "Final assessment\n"
            "Verified document evidence ke bina koi filing-based conclusion nahi diya gaya."
        )
    lines = []
    for match in document_matches[:4]:
        lines.append(
            f"- [{match['citation']} p.{match['page']}] {match['snippet']} "
            f"(Source: {match['title']})"
        )
    return (
        "Neeche ka answer sirf retrieved company-document evidence dikhata hai; missing details infer nahi ki gayi hain.\n\n"
        "Indexed evidence\n"
        + "\n".join(lines)
        + "\n\nEvidence boundary\n"
        + "Ye excerpts current stock price ya ML outlook nahi hain. Har statement ke saath document page citation diya gaya hai.\n\n"
        + "Final assessment\n"
        + f"Question: {question}\nRetrieved evidence ko cited source pages ke context me verify karein; ye investment advice nahi hai."
    )


def _llm_grounding_issue(
    answer: str,
    message: str,
    prediction: Dict[str, Any],
    factor_payload: Dict[str, Any],
    historical: Optional[Dict[str, Any]] = None,
    document_matches: Optional[List[Dict[str, Any]]] = None,
    document_requested: bool = False,
    company_profile: Optional[Dict[str, Any]] = None,
    news_payload: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    normalized_answer = answer.lower()
    lowered = message.lower()
    # A short answer can be the correct response when the user only asks what
    # one visible metric means. Reject only effectively empty/non-explanatory
    # provider output; the metric-specific checks below still enforce evidence.
    if len(answer.strip()) < 80:
        return "answer too short to explain the requested evidence"
    factor_keywords = {
        "gold": "GC=F", "crude": "CL=F", "oil": "CL=F", "rupee": "INR=X",
        "dollar": "INR=X", "yield": "^TNX", "vix": "^VIX", "bitcoin": "BTC-USD",
    }
    factors_by_symbol = {item["symbol"]: item for item in factor_payload.get("factors", [])}
    for keyword, factor_symbol in factor_keywords.items():
        if keyword not in lowered:
            continue
        factor = factors_by_symbol.get(factor_symbol)
        if not factor or factor.get("changePercent") is None:
            continue
        expected_number = f"{abs(float(factor['changePercent'])):.2f}".rstrip("0").rstrip(".")
        if expected_number not in normalized_answer:
            return f"missing live {keyword} move"
    if float(prediction["model"]["balancedAccuracy"]) < 53:
        weak_markers = ["weak", "no reliable", "reliable nahi", "kamzor", "below 53", "less than 53", "53 se kam"]
        if not any(marker in normalized_answer for marker in weak_markers):
            return "missing weak-model warning"
    risk_requested = _requests_risk_analysis(lowered)
    asset_risk = (prediction.get("riskBenchmark") or {}).get("asset") or {}
    if risk_requested:
        risk_payload = prediction.get("riskBenchmark") or {}
        comparison = risk_payload.get("comparison") or {}
        benchmark = risk_payload.get("benchmark") or {}
        required_metrics = []
        if any(term in lowered for term in ("risk", "volatility")) and asset_risk.get("annualizedVolatilityPercent") is not None:
            required_metrics.append(("historical volatility", asset_risk["annualizedVolatilityPercent"]))
        if "beta" in lowered and comparison.get("beta") is not None:
            required_metrics.append(("beta", comparison["beta"]))
        if "drawdown" in lowered and asset_risk.get("maxDrawdownPercent") is not None:
            required_metrics.append(("drawdown", asset_risk["maxDrawdownPercent"]))
        if ("value at risk" in lowered or "historical var" in lowered or re.search(r"\bvar\b", lowered)) and asset_risk.get("historicalVar95Percent") is not None:
            required_metrics.append(("historical VaR", asset_risk["historicalVar95Percent"]))
        if "tracking error" in lowered and comparison.get("trackingErrorPercent") is not None:
            required_metrics.append(("tracking error", comparison["trackingErrorPercent"]))
        relative_comparison_requested = any(term in lowered for term in (
            "broad market", "market comparison", "behaved versus",
            "relative return", "outperform", "underperform",
        ))
        if relative_comparison_requested and comparison.get("relativeReturnPoints") is not None:
            required_metrics.append(("relative return", comparison["relativeReturnPoints"]))
        for label, value in required_metrics:
            expected_value = f"{abs(float(value)):.2f}".rstrip("0").rstrip(".")
            if expected_value not in normalized_answer:
                return f"missing requested {label} evidence"
        benchmark_name = str(benchmark.get("name") or "").lower()
        benchmark_identity_requested = "benchmark" in lowered or relative_comparison_requested
        if benchmark_identity_requested and benchmark_name and benchmark_name not in normalized_answer:
            return "missing requested benchmark identity"
    if historical:
        session_date = date.fromisoformat(historical["sessionDate"])
        readable_date = f"{session_date.day} {session_date.strftime('%B %Y')}"
        accepted_date_markers = {historical["sessionDate"].lower(), readable_date.lower()}
        if not any(marker in normalized_answer for marker in accepted_date_markers):
            return "missing requested historical session"
    if _requests_catalyst_analysis(lowered):
        catalysts = (company_profile or {}).get("catalysts") or {}
        consensus = catalysts.get("analystConsensus") or {}
        if ("analyst" in lowered or "target" in lowered or "consensus" in lowered) and consensus.get("targetMean") is not None:
            expected_target = f"{abs(float(consensus['targetMean'])):.2f}".rstrip("0").rstrip(".")
            if expected_target not in normalized_answer:
                return "missing requested analyst target evidence"
        if "earnings" in lowered:
            earnings_event = next(
                (item for item in catalysts.get("events") or [] if item.get("type") == "earnings"),
                None,
            )
            if earnings_event:
                event_date = date.fromisoformat(earnings_event["date"])
                markers = {
                    earnings_event["date"].lower(),
                    f"{event_date.day} {event_date.strftime('%B %Y')}".lower(),
                }
                if not any(marker in normalized_answer for marker in markers):
                    return "missing requested earnings date evidence"
    if _requests_news_analysis(lowered):
        intelligence = (news_payload or {}).get("intelligence") or {}
        if intelligence.get("status") == "available":
            sentiment_label = str(intelligence.get("sentimentLabel") or "").lower()
            accepted_tone = {
                sentiment_label,
                sentiment_label.replace("mixed/neutral", "mixed"),
                sentiment_label.replace("mixed/neutral", "neutral"),
            }
            if sentiment_label and not any(tone and tone in normalized_answer for tone in accepted_tone):
                return "missing requested headline sentiment evidence"
            if "theme" in lowered and intelligence.get("themes"):
                expected_theme = str(intelligence["themes"][0].get("theme") or "").lower()
                if expected_theme and expected_theme not in normalized_answer:
                    return "missing requested headline theme evidence"
    if _requests_financial_trend_analysis(lowered):
        trends = (company_profile or {}).get("financialTrends") or {}
        summary = trends.get("summary") or {}
        if trends.get("status") == "available":
            latest_period = str(summary.get("latestAnnualPeriod") or "").lower()
            if latest_period and latest_period not in normalized_answer:
                return "missing latest financial statement period"
            if ("revenue" in lowered or "cagr" in lowered) and summary.get("revenueTrend"):
                expected_trend = str(summary["revenueTrend"]).lower()
                if expected_trend not in normalized_answer:
                    return "missing requested revenue trend evidence"
            financial_boundary_markers = (
                "not an accounting audit", "not a financial audit", "not estimated", "not estimates",
                "provider statement", "provider-reported", "can be restated", "may be restated",
                "fiscal periods differ",
            )
            if not any(marker in normalized_answer for marker in financial_boundary_markers):
                return "missing financial statement evidence boundary"
    if _requests_ownership_analysis(lowered):
        ownership = (company_profile or {}).get("ownershipIntelligence") or {}
        if ownership.get("status") == "available":
            major = ownership.get("majorOwnership") or {}
            if any(term in lowered for term in ("ownership", "shareholding", "institutional")) and major.get("institutionsPercentHeld") is not None:
                expected_percent = f"{abs(float(major['institutionsPercentHeld'])):.2f}".rstrip("0").rstrip(".")
                if expected_percent not in normalized_answer:
                    return "missing requested institutional ownership evidence"
            insider = ownership.get("insiderSummary") or {}
            if "insider" in lowered and insider.get("netActivity"):
                expected_activity = str(insider["netActivity"]).lower()
                if expected_activity not in normalized_answer:
                    return "missing requested insider net activity evidence"
            ownership_boundary_markers = (
                "not a standalone", "not standalone", "delayed", "reporting delay",
                "needs context", "need context", "not investment advice",
            )
            if not any(marker in normalized_answer for marker in ownership_boundary_markers):
                return "missing ownership evidence boundary"
    if _requests_estimate_revision_analysis(lowered):
        estimates = (company_profile or {}).get("analystEstimateIntelligence") or {}
        summary = estimates.get("summary") or {}
        if estimates.get("status") == "available":
            if any(term in lowered for term in ("eps", "earnings estimate", "analyst estimate", "earnings outlook")) and summary.get("currentQuarterEpsAverage") is not None:
                expected_eps = f"{abs(float(summary['currentQuarterEpsAverage'])):.4f}".rstrip("0").rstrip(".")
                if expected_eps not in normalized_answer:
                    return "missing requested current-quarter EPS estimate"
            if "revenue" in lowered and summary.get("currentQuarterRevenueGrowthPercent") is not None:
                expected_growth = f"{abs(float(summary['currentQuarterRevenueGrowthPercent'])):.2f}".rstrip("0").rstrip(".")
                if expected_growth not in normalized_answer:
                    return "missing requested revenue estimate growth"
            if "revision" in lowered and summary.get("currentQuarterRevisionSignal") not in (None, "unavailable"):
                expected_signal = str(summary["currentQuarterRevisionSignal"]).lower()
                if expected_signal not in normalized_answer:
                    return "missing requested estimate revision direction"
            if "trend" in lowered and summary.get("periodsWithBasisMismatch"):
                if not any(marker in normalized_answer for marker in ("basis", "not comparable", "incompatible")):
                    return "missing EPS trend basis mismatch warning"
            estimate_boundary_markers = (
                "third-party analyst", "external analyst", "not company guidance",
                "not fintrack ml", "can change", "changing estimate", "changing third-party",
            )
            if not any(marker in normalized_answer for marker in estimate_boundary_markers):
                return "missing analyst-estimate evidence boundary"
    if _requests_dividend_action_analysis(lowered):
        actions = (company_profile or {}).get("corporateActionIntelligence") or {}
        summary = actions.get("summary") or {}
        action_snapshot = actions.get("snapshot") or {}
        if actions.get("status") == "available":
            if any(term in lowered for term in ("dividend history", "dividend growth", "trailing dividend", "distribution history")) and summary.get("trailing12MonthTotalPerShare") is not None:
                expected_total = f"{abs(float(summary['trailing12MonthTotalPerShare'])):.6f}".rstrip("0").rstrip(".")
                if expected_total not in normalized_answer:
                    return "missing requested trailing dividend evidence"
            if "dividend yield" in lowered and action_snapshot.get("currentYieldPercent") is not None:
                expected_yield = f"{abs(float(action_snapshot['currentYieldPercent'])):.4f}".rstrip("0").rstrip(".")
                if expected_yield not in normalized_answer:
                    return "missing requested dividend yield evidence"
            if "payout ratio" in lowered and action_snapshot.get("payoutRatioPercent") is not None:
                expected_payout = f"{abs(float(action_snapshot['payoutRatioPercent'])):.2f}".rstrip("0").rstrip(".")
                if expected_payout not in normalized_answer:
                    return "missing requested payout ratio evidence"
            if "split" in lowered and summary.get("latestSplitRatio"):
                if str(summary["latestSplitRatio"]).lower() not in normalized_answer:
                    return "missing requested stock-split evidence"
            boundary_markers = (
                "historical distributions are not guaranteed", "historical dividend is not guaranteed",
                "current calendar-year totals are partial", "current year is partial", "partial calendar year",
                "missing data is not zero", "missing data ko zero", "split does not create economic value",
                "split does not create value",
            )
            if not any(marker in normalized_answer for marker in boundary_markers):
                return "missing dividend/corporate-action evidence boundary"
    if _requests_earnings_quality_analysis(lowered):
        quality = (company_profile or {}).get("earningsQualityIntelligence") or {}
        summary = quality.get("summary") or {}
        if quality.get("status") == "available":
            if any(term in lowered for term in ("earnings quality", "cash conversion", "profit to cash", "operating cash conversion")) and summary.get("latestOperatingCashConversionPercent") is not None:
                expected_conversion = f"{abs(float(summary['latestOperatingCashConversionPercent'])):.2f}".rstrip("0").rstrip(".")
                if expected_conversion not in normalized_answer:
                    return "missing requested operating-cash conversion evidence"
            if any(term in lowered for term in ("fcf conversion", "free cash flow conversion")) and summary.get("latestFreeCashFlowConversionPercent") is not None:
                expected_conversion = f"{abs(float(summary['latestFreeCashFlowConversionPercent'])):.2f}".rstrip("0").rstrip(".")
                if expected_conversion not in normalized_answer:
                    return "missing requested free-cash-flow conversion evidence"
            if any(term in lowered for term in ("capital allocation", "buyback", "share repurchase", "shareholder return")) and summary.get("latestShareholderCashReturns") is not None:
                expected_returns = _compact_amount(summary["latestShareholderCashReturns"], quality.get("currency")).lower()
                if expected_returns not in normalized_answer:
                    return "missing requested shareholder cash-return evidence"
            if quality.get("financialSectorCaution") and not any(marker in normalized_answer for marker in ("financial institution", "financial-sector", "bank cash", "not directly comparable", "business model")):
                return "missing financial-sector cash-flow caution"
            quality_boundary_markers = (
                "not an accounting-quality score", "not an accounting quality score",
                "descriptive", "statements can be restated", "may be restated",
                "missing rows are not zero", "missing data is not zero",
                "not a standalone investment signal", "not a standalone signal",
            )
            if not any(marker in normalized_answer for marker in quality_boundary_markers):
                return "missing earnings-quality evidence boundary"
    if _requests_liquidity_debt_analysis(lowered):
        liquidity = (company_profile or {}).get("liquidityDebtIntelligence") or {}
        summary = liquidity.get("summary") or {}
        if liquidity.get("status") == "available":
            if any(term in lowered for term in ("liquidity", "cash position", "cash balance")) and summary.get("latestLiquidFunds") is not None:
                expected_liquidity = _compact_amount(summary["latestLiquidFunds"], liquidity.get("currency")).lower()
                if expected_liquidity not in normalized_answer:
                    return "missing requested liquid-funds evidence"
            if "net debt" in lowered and summary.get("latestDebtAfterLiquidFunds") is not None:
                expected_net_debt = _compact_amount(summary["latestDebtAfterLiquidFunds"], liquidity.get("currency")).lower()
                if expected_net_debt not in normalized_answer:
                    return "missing requested debt-after-liquid-funds evidence"
            if "current ratio" in lowered and summary.get("latestCurrentRatio") is not None:
                expected_ratio = f"{abs(float(summary['latestCurrentRatio'])):.3f}".rstrip("0").rstrip(".")
                if expected_ratio not in normalized_answer:
                    return "missing requested current-ratio evidence"
            if "interest coverage" in lowered and summary.get("latestInterestCoverageRatio") is not None:
                expected_ratio = f"{abs(float(summary['latestInterestCoverageRatio'])):.3f}".rstrip("0").rstrip(".")
                if expected_ratio not in normalized_answer:
                    return "missing requested interest-coverage evidence"
            if any(term in lowered for term in ("debt trend", "leverage trend")) and summary.get("totalDebtTrend"):
                if str(summary["totalDebtTrend"]).lower() not in normalized_answer:
                    return "missing requested total-debt trend"
            if summary.get("providerNetDebtBasisMismatchPeriods") and not any(marker in normalized_answer for marker in ("different basis", "basis differs", "basis mismatch", "kept separate", "provider net debt")):
                return "missing provider net-debt basis warning"
            if liquidity.get("financialSectorCaution") and not any(marker in normalized_answer for marker in ("financial institution", "financial-sector", "bank", "business model", "intentionally withheld")):
                return "missing financial-sector liquidity caution"
            liquidity_boundary_markers = (
                "not a credit rating", "not credit rating", "not a synthetic health score",
                "not a health score", "statements can be restated", "may be restated",
                "missing rows are not zero", "missing data is not zero", "maturities", "covenants",
            )
            if not any(marker in normalized_answer for marker in liquidity_boundary_markers):
                return "missing liquidity/debt evidence boundary"
    if _requests_profitability_return_analysis(lowered):
        returns = (company_profile or {}).get("profitabilityReturnsIntelligence") or {}
        summary = returns.get("summary") or {}
        if returns.get("status") == "available":
            if re.search(r"\broe\b|return on equity", lowered) and summary.get("latestReturnOnEquityPercent") is not None:
                expected_roe = f"{abs(float(summary['latestReturnOnEquityPercent'])):.2f}".rstrip("0").rstrip(".")
                if expected_roe not in normalized_answer:
                    return "missing requested return-on-equity evidence"
            if re.search(r"\broa\b|return on assets", lowered) and summary.get("latestReturnOnAssetsPercent") is not None:
                expected_roa = f"{abs(float(summary['latestReturnOnAssetsPercent'])):.2f}".rstrip("0").rstrip(".")
                if expected_roa not in normalized_answer:
                    return "missing requested return-on-assets evidence"
            if re.search(r"\broic\b|return on invested capital", lowered) and summary.get("latestReturnOnInvestedCapitalPercent") is not None:
                expected_roic = f"{abs(float(summary['latestReturnOnInvestedCapitalPercent'])):.2f}".rstrip("0").rstrip(".")
                if expected_roic not in normalized_answer:
                    return "missing requested return-on-invested-capital evidence"
            if "gross margin" in lowered and summary.get("latestGrossMarginPercent") is not None:
                expected_margin = f"{abs(float(summary['latestGrossMarginPercent'])):.2f}".rstrip("0").rstrip(".")
                if expected_margin not in normalized_answer:
                    return "missing requested gross-margin evidence"
            if returns.get("financialSectorCaution") and not any(marker in normalized_answer for marker in ("financial institution", "financial-sector", "bank", "intentionally withheld", "operating inputs")):
                return "missing financial-sector profitability caution"
            return_boundary_markers = (
                "average beginning and ending", "average beginning/ending", "average balance",
                "not a profitability score", "not profitability score", "not a moat rating",
                "statements can be restated", "may be restated", "accounting policies",
            )
            if not any(marker in normalized_answer for marker in return_boundary_markers):
                return "missing profitability/returns evidence boundary"
    if document_requested and not document_matches:
        return "no indexed document evidence available"
    if document_matches:
        allowed_citations = {
            f"[{item['citation']} p.{item['page']}]".lower()
            for item in document_matches
        }
        if not any(citation in normalized_answer for citation in allowed_citations):
            return "missing indexed document citation"
    return None


@router.get("/overview")
def get_global_market_overview(refresh: bool = False):
    if refresh:
        _cache.pop("global-overview", None)
    return global_overview()


@router.get("/currencies")
def get_inr_currency_rates(refresh: bool = False):
    return inr_currency_rates(refresh)


@router.get("/analysis")
def get_market_analysis(symbol: str = "^NSEI", refresh: bool = False):
    try:
        if refresh:
            clear_market_cache()
        return market_prediction(symbol)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Market data provider is unavailable: {error}") from error


@router.get("/predictions")
def get_prediction_audit(symbol: str = "^NSEI", limit: int = 12):
    """Expose the model's session-by-session prediction audit without invoking Gemini."""
    try:
        return prediction_audit(symbol, max(1, min(limit, 30)))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/news")
def get_market_news(symbol: str = "^NSEI", limit: int = 8):
    try:
        return market_news(symbol, max(1, min(limit, 12)))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/factors")
def get_macro_factors(refresh: bool = False):
    if refresh:
        clear_market_cache()
    return macro_factors()


@router.get("/breadth")
def get_market_breadth(refresh: bool = False):
    if refresh:
        clear_market_cache()
    return market_breadth()


@router.get("/company")
def get_company_research(symbol: str = "RELIANCE.NS", refresh: bool = False):
    try:
        if refresh:
            clear_market_cache()
        return company_research(symbol)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Company research data is unavailable: {error}") from error


@router.get("/peer-comparison")
def get_sector_peer_comparison(symbol: str = "RELIANCE.NS", refresh: bool = False):
    try:
        normalized = _sanitize_symbol(symbol)
        if refresh:
            _cache.pop(f"sector-peers:{normalized}", None)
        return sector_peer_intelligence(normalized)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/news-feed")
def get_news_feed(limit: int = 12, refresh: bool = False):
    if refresh:
        # A headline refresh must not evict quote, currency or analytics caches.
        clear_market_cache_prefix("news:")
    return market_news_feed(limit)


@router.post("/agent")
async def market_agent(request: FastApiRequest):
    try:
        body = await request.body()
        if not body:
            raise ValueError(
                f"Empty request body (content-length={request.headers.get('content-length')}, "
                f"content-type={request.headers.get('content-type')})."
            )
        raw_payload = json.loads(body.decode("utf-8"))
        if not isinstance(raw_payload, dict):
            raise ValueError("JSON request body must be an object.")
        payload = MarketAgentRequest(
            message=raw_payload.get("message", ""),
            symbol=raw_payload.get("symbol") or None,
            recent_messages=raw_payload.get("recent_messages") or raw_payload.get("recentMessages") or [],
        )
    except Exception as error:
        raise HTTPException(status_code=422, detail=f"Invalid market agent request: {error}") from error

    symbol = _infer_symbol(payload.message, payload.symbol)
    lowered = payload.message.lower()
    requested_date = _extract_requested_date(payload.message)
    plan = build_agent_plan(
        payload.message,
        symbol,
        requested_date,
        is_index=symbol in GLOBAL_INDICES or symbol in MACRO_FACTORS,
    )
    tools = [step["tool"] for step in plan["steps"]]
    outcomes: Dict[str, Dict[str, Any]] = {}
    context: Dict[str, Any] = {}

    context["snapshot"] = market_snapshot(symbol)
    outcomes["market_snapshot"] = {"status": "completed", "evidenceCount": 1}
    context["prediction"] = market_prediction(symbol)
    outcomes["technical_prediction"] = {
        "status": "completed",
        "evidenceCount": len(context["prediction"].get("history") or []),
    }
    if "market_news" in tools:
        context["news"] = market_news(symbol, 6)
        outcomes["market_news"] = {
            "status": "completed",
            "evidenceCount": len(context["news"].get("articles") or []),
        }
    if "macro_market_factors" in tools:
        context["macroFactors"] = macro_factors()
        outcomes["macro_market_factors"] = {
            "status": "completed",
            "evidenceCount": len(context["macroFactors"].get("factors") or []),
        }
    if "historical_market_session" in tools and requested_date:
        context["historicalSession"] = _historical_session(symbol, requested_date)
        outcomes["historical_market_session"] = {"status": "completed", "evidenceCount": 1}
    if "company_fundamentals" in tools:
        context["company"] = company_research(symbol)
        outcomes["company_fundamentals"] = {"status": "completed", "evidenceCount": 1}
    if "sector_peer_comparison" in tools:
        context["sectorPeers"] = sector_peer_intelligence(symbol)
        peer_count = len(context["sectorPeers"].get("peers") or [])
        outcomes["sector_peer_comparison"] = {
            "status": "completed" if peer_count else context["sectorPeers"].get("status", "unavailable"),
            "evidenceCount": peer_count,
            **({"message": context["sectorPeers"].get("message")} if not peer_count else {}),
        }
    if "market_breadth" in tools:
        context["breadth"] = market_breadth()
        outcomes["market_breadth"] = {
            "status": "completed",
            "evidenceCount": int(context["breadth"].get("coverageCount") or 0),
        }
    if "global_market_overview" in tools:
        context["globalOverview"] = global_overview()
        outcomes["global_market_overview"] = {
            "status": "completed",
            "evidenceCount": len(context["globalOverview"].get("markets") or []),
        }
    if "company_document_rag" in tools:
        try:
            # Runtime import avoids a module cycle: document_rag reuses this
            # module's provider adapter for optional grounded generation.
            from document_rag import retrieve_chunks
            context["documentEvidence"] = retrieve_chunks(symbol, payload.message, 5)
            document_count = len(context["documentEvidence"].get("matches") or [])
            outcomes["company_document_rag"] = {
                "status": "completed" if document_count else "no_evidence",
                "evidenceCount": document_count,
                **({"message": "No retrievable indexed company evidence was found; no document claim was invented."}
                   if not document_count else {}),
            }
        except (RuntimeError, ValueError) as error:
            logger.warning("Agent document retrieval failed for %s: %s", symbol, error)
            context["documentEvidence"] = {"matches": [], "provider": None}
            outcomes["company_document_rag"] = {
                "status": "unavailable",
                "evidenceCount": 0,
                "message": "Indexed document retrieval is temporarily unavailable.",
            }

    prediction = context["prediction"]
    analysis_brief = _build_analysis_brief(context["snapshot"], prediction)
    model_context: Dict[str, Any] = {
        "outlook": prediction["outlook"],
        "probabilityUp": prediction["probabilityUp"],
        "range": prediction["expectedRange"],
        "testAccuracy": prediction["model"]["backtestAccuracy"],
        "balancedAccuracy": prediction["model"]["balancedAccuracy"],
        "rocAuc": prediction["model"]["rocAuc"],
        "walkForwardFolds": prediction["model"]["walkForwardFolds"],
        "selectedClassifier": prediction["model"]["type"],
        "quality": prediction["model"]["quality"],
        "newsTone": prediction["newsFactor"]["sentimentLabel"],
        "macroSignal": prediction["macroFactor"]["signal"],
    }
    if any(word in lowered for word in ["rsi", "technical", "model", "outlook", "prediction", "forecast"]):
        model_context["rsi14"] = prediction["technicalIndicators"]["rsi14"]

    llm_context: Dict[str, Any] = {
        "asset": {
            "symbol": symbol,
            "name": prediction["name"],
            "price": context["snapshot"].get("price"),
            "changePct": context["snapshot"].get("changePercent"),
            "asOf": context["snapshot"].get("dataAsOf"),
        },
        "model": model_context,
        "drivers": [
            [item["factor"], item["changePercent"], item["scoreContribution"], item["reason"]]
            for item in prediction["macroFactor"]["factors"]
        ],
        "derivedCalculations": analysis_brief,
    }
    if _requests_risk_analysis(lowered):
        llm_context["historicalRiskAndBenchmark"] = prediction.get("riskBenchmark")
    if "historicalSession" in context:
        llm_context["historicalSession"] = context["historicalSession"]
    if "news" in context:
        llm_context["headlineEvidence"] = {
            "summary": context["news"].get("intelligence"),
            "articles": [
                {
                    "title": item["title"][:160],
                    "publisher": item.get("publisher"),
                    "publishedAt": item.get("publishedAt"),
                    "sentimentLabel": item.get("sentimentLabel"),
                    "themes": item.get("themes"),
                }
                for item in context["news"]["articles"][:6]
            ],
        }
    if "company" in context:
        financial_trends = context["company"].get("financialTrends") or {}
        ownership = context["company"].get("ownershipIntelligence") or {}
        analyst_estimates = context["company"].get("analystEstimateIntelligence") or {}
        corporate_actions = context["company"].get("corporateActionIntelligence") or {}
        earnings_quality = context["company"].get("earningsQualityIntelligence") or {}
        liquidity_debt = context["company"].get("liquidityDebtIntelligence") or {}
        profitability_returns = context["company"].get("profitabilityReturnsIntelligence") or {}
        llm_context["company"] = {
            "sector": context["company"]["sector"],
            "industry": context["company"]["industry"],
            "performance": context["company"]["performance"],
            "fundamentals": context["company"]["fundamentals"],
            "catalysts": context["company"].get("catalysts"),
            "financialStatementTrends": {
                "status": financial_trends.get("status"),
                "summary": financial_trends.get("summary"),
                "annual": [
                    {key: item.get(key) for key in (
                        "period", "revenue", "revenueYoYPercent", "netIncome", "netIncomeYoYPercent",
                        "operatingMarginPercent", "freeCashFlow", "freeCashFlowYoYPercent",
                        "totalDebt", "debtYoYPercent", "debtToEquityRatio",
                    )}
                    for item in financial_trends.get("annual") or []
                ],
                "quarterly": [
                    {key: item.get(key) for key in (
                        "period", "revenue", "revenueQoQPercent", "netIncome",
                        "netIncomeQoQPercent", "operatingMarginPercent", "previousQuarterComparable",
                    )}
                    for item in financial_trends.get("quarterly") or []
                ],
                "method": financial_trends.get("method"),
            },
            "ownershipAndInsiderActivity": {
                "status": ownership.get("status"),
                "coverageLevel": ownership.get("coverageLevel"),
                "coverage": ownership.get("coverage"),
                "majorOwnership": ownership.get("majorOwnership"),
                "concentration": ownership.get("concentration"),
                "insiderSummary": ownership.get("insiderSummary"),
                "latestInsiderTransactionDate": ownership.get("latestInsiderTransactionDate"),
                "topInstitutions": (ownership.get("institutionalHolders") or [])[:5],
                "topMutualFunds": (ownership.get("mutualFundHolders") or [])[:5],
                "recentInsiderTransactions": (ownership.get("recentInsiderTransactions") or [])[:6],
                "method": ownership.get("method"),
                "disclaimer": ownership.get("disclaimer"),
            },
            **({
                "analystEstimateRevisions": {
                    "status": analyst_estimates.get("status"),
                    "coverageLevel": analyst_estimates.get("coverageLevel"),
                    "coverage": analyst_estimates.get("coverage"),
                    "summary": analyst_estimates.get("summary"),
                    "periods": analyst_estimates.get("periods"),
                    "method": analyst_estimates.get("method"),
                    "disclaimer": analyst_estimates.get("disclaimer"),
                },
            } if "analyst_estimate_revision_analysis" in plan["intents"] else {}),
            **({
                "dividendAndCorporateActions": {
                    "status": corporate_actions.get("status"),
                    "coverageLevel": corporate_actions.get("coverageLevel"),
                    "currency": corporate_actions.get("currency"),
                    "snapshot": corporate_actions.get("snapshot"),
                    "summary": corporate_actions.get("summary"),
                    "annualDividends": corporate_actions.get("annualDividends"),
                    "recentDividends": corporate_actions.get("recentDividends"),
                    "recentSplits": corporate_actions.get("recentSplits"),
                    "recentCapitalGains": corporate_actions.get("recentCapitalGains"),
                    "upcomingEvents": corporate_actions.get("upcomingEvents"),
                    "method": corporate_actions.get("method"),
                    "disclaimer": corporate_actions.get("disclaimer"),
                },
            } if "dividend_and_corporate_action_analysis" in plan["intents"] else {}),
            **({
                "earningsQualityAndCapitalAllocation": {
                    "status": earnings_quality.get("status"),
                    "coverageLevel": earnings_quality.get("coverageLevel"),
                    "currency": earnings_quality.get("currency"),
                    "sector": earnings_quality.get("sector"),
                    "financialSectorCaution": earnings_quality.get("financialSectorCaution"),
                    "summary": earnings_quality.get("summary"),
                    "annual": earnings_quality.get("annual"),
                    "method": earnings_quality.get("method"),
                    "disclaimer": earnings_quality.get("disclaimer"),
                },
            } if "earnings_quality_and_capital_allocation_analysis" in plan["intents"] else {}),
            **({
                "liquidityAndDebtCapacity": {
                    "status": liquidity_debt.get("status"),
                    "coverageLevel": liquidity_debt.get("coverageLevel"),
                    "coverage": liquidity_debt.get("coverage"),
                    "currency": liquidity_debt.get("currency"),
                    "sector": liquidity_debt.get("sector"),
                    "financialSectorCaution": liquidity_debt.get("financialSectorCaution"),
                    "summary": liquidity_debt.get("summary"),
                    "annual": liquidity_debt.get("annual"),
                    "method": liquidity_debt.get("method"),
                    "disclaimer": liquidity_debt.get("disclaimer"),
                },
            } if "liquidity_and_debt_capacity_analysis" in plan["intents"] else {}),
            **({
                "profitabilityReturnsAndEfficiency": {
                    "status": profitability_returns.get("status"),
                    "coverageLevel": profitability_returns.get("coverageLevel"),
                    "coverage": profitability_returns.get("coverage"),
                    "currency": profitability_returns.get("currency"),
                    "sector": profitability_returns.get("sector"),
                    "financialSectorCaution": profitability_returns.get("financialSectorCaution"),
                    "summary": profitability_returns.get("summary"),
                    "annual": profitability_returns.get("annual"),
                    "method": profitability_returns.get("method"),
                    "disclaimer": profitability_returns.get("disclaimer"),
                },
            } if "profitability_returns_and_efficiency_analysis" in plan["intents"] else {}),
        }
    if context.get("sectorPeers", {}).get("status") == "available":
        peer_context = context["sectorPeers"]
        llm_context["sectorPeerComparison"] = {
            "sector": peer_context["sector"],
            "region": peer_context["region"],
            "selected": peer_context["selected"],
            "peerMedians": peer_context["peerMedians"],
            "comparison": peer_context["comparison"],
            "peers": peer_context["peers"],
            "method": peer_context["method"],
        }
    if "breadth" in context:
        llm_context["breadth"] = {
            "advances": context["breadth"]["advances"],
            "declines": context["breadth"]["declines"],
            "gainers": [[item["name"], item["changePercent"]] for item in context["breadth"]["topGainers"][:3]],
            "losers": [[item["name"], item["changePercent"]] for item in context["breadth"]["topLosers"][:3]],
        }
    if "globalOverview" in context:
        llm_context["global"] = [
            [item["name"], item.get("changePercent")]
            for item in context["globalOverview"]["markets"] if item.get("status") == "available"
        ]
    document_matches = (context.get("documentEvidence") or {}).get("matches") or []
    document_requested = "company_document_rag" in tools
    if document_requested:
        llm_context["indexedDocumentEvidence"] = [
            {
                "citation": f"[{item['citation']} p.{item['page']}]",
                "title": item["title"],
                "reportingPeriod": item.get("reportingPeriod"),
                "sourceUrl": item.get("sourceUrl"),
                "evidence": item["text"][:900],
            }
            for item in document_matches
        ]
        llm_context["documentEvidenceAvailable"] = bool(document_matches)

    system_prompt = (
        "You are FinTrack's evidence-grounded market research analyst. Use only the supplied tool results; never "
        "invent prices, dates, news or calculations. Match the user's Hindi, Hinglish or English. Keep the answer "
        "under 140 words unless the user explicitly asks for detail. If the user asks what a displayed metric means, "
        "first explain what it measures, then interpret the supplied value, then give one important limitation. Do not "
        "repeat unrelated dashboard figures. Start directly with the answer and never print "
        "a 'Seedha jawab' heading. Use only the relevant compact sections from: Verified figures, Calculation, "
        "Scenario/estimate, Assumptions and confidence, Final assessment. Do not repeat a figure in multiple sections. Show arithmetic explicitly using the "
        "derived calculations. For a requested historical date, clearly say whether it is the exact session or "
        "nearest trading session and use its OHLC/change; do not answer it with today's data. Distinguish verified "
        "facts from model estimates. Explain downside, neutral and upside cases instead of pretending one outcome "
        "is certain. Never guarantee direction, profit or return and never issue personalized buy/sell instructions. "
        "When indexedDocumentEvidence is supplied, every document claim must use its exact [S# p.#] citation token. "
        "If documentEvidenceAvailable is false, say that indexed evidence is unavailable and do not infer a filing answer. "
        "When sectorPeerComparison is supplied, describe only above/below/in-line evidence and never turn a peer median into a buy/sell verdict. "
        "Company catalyst dates can change; label analyst consensus and targets as external opinions separate from FinTrack ML. "
        "When headlineEvidence is supplied, call it title-keyword evidence, report source breadth and dates, and do not imply that headlines prove an event or understand full article context. "
        "When financialStatementTrends is supplied, distinguish annual from quarterly periods, use the supplied growth and margin calculations, and do not estimate missing statement rows. "
        "When ownershipAndInsiderActivity is supplied, distinguish provider-reported total ownership from the sum of only returned top-holder rows. State missing holder-table coverage, reporting delays, and that insider activity needs context and is not a standalone trading signal. "
        "When analystEstimateRevisions is supplied, separate changing third-party analyst estimates from company guidance and FinTrack ML. Report the forecast period, ranges, analyst counts and up/down revision breadth; flag any supplied EPS trend basis mismatch instead of merging incompatible series. "
        "When dividendAndCorporateActions is supplied, distinguish history-derived per-share distributions from provider yield/payout snapshots. Mark the current calendar year partial, never treat missing payments as zero, and state that historical distributions are not guaranteed and splits do not create economic value by themselves. "
        "When earningsQualityAndCapitalAllocation is supplied, use only aligned reported periods, call cash-conversion ratios descriptive rather than a quality score, and keep dividends, repurchases, stock issuance and debt flows separate. State that statements can be restated and missing rows are not zero. For a supplied financial-sector caution, explain why bank/financial cash-flow and debt classifications are not directly comparable with industrial companies. "
        "When liquidityAndDebtCapacity is supplied, identify the disclosed liquid-funds basis, keep provider net debt separate from total debt minus liquid funds, and report any supplied basis mismatch. Treat all ratios as descriptive rather than a credit rating or health score. For a supplied financial-sector caution, do not invent industrial interest-coverage or debt/EBITDA ratios. "
        "When profitabilityReturnsAndEfficiency is supplied, report margins separately from average-balance ROA/ROE and any approximate industrial ROIC. Explain the average beginning/ending balance method, do not present ratios as a score or moat rating, and do not invent industrial ROIC for a supplied financial-sector caution. "
        "changePct is daily price change, not trading volume. RSI above 70 is overbought, below 30 is oversold. "
        "If balancedAccuracy is below 53, explicitly state that the model has no reliable directional edge. "
        "Keep the response readable and normally between 60 and 140 words."
    )
    recent = []
    for item in payload.recent_messages[-6:]:
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            continue
        content = item.get("content", "")
        recent.append({"role": item["role"], "content": str(content)[:600]})
    messages = [
        {"role": "system", "content": system_prompt},
        *recent,
        {
            "role": "user",
            "content": f"Question: {payload.message}\nEvidence: {json.dumps(llm_context, default=str)[:8500]}",
        },
    ]
    llm_used = True
    llm_status = "connected"
    llm_answer_accepted = True
    grounding_issue = None
    llm_failure = None
    llm_provider = os.getenv("LLM_PROVIDER", "").strip().lower() or "deterministic"
    document_only = document_requested and not any(intent in plan["intents"] for intent in (
        "model_and_technical_analysis", "historical_date_analysis", "news_analysis",
        "macro_analysis", "market_breadth_analysis", "global_market_comparison",
        "financial_statement_trend_analysis", "company_catalyst_analysis", "sector_peer_analysis",
        "ownership_and_insider_analysis",
        "analyst_estimate_revision_analysis",
        "dividend_and_corporate_action_analysis",
        "earnings_quality_and_capital_allocation_analysis",
        "liquidity_and_debt_capacity_analysis",
        "profitability_returns_and_efficiency_analysis",
    ))

    def verified_fallback() -> str:
        if document_only:
            return _verified_document_answer(symbol, payload.message, document_matches)
        return _verified_tool_answer(
            payload.message,
            context["snapshot"],
            prediction,
            tools,
            context.get("macroFactors") or {"factors": []},
            context.get("breadth"),
            context.get("historicalSession"),
            document_matches,
            document_requested,
            context.get("company"),
            context.get("news"),
        )

    try:
        try:
            answer, llm_provider = _provider_chat(messages)
        except RuntimeError as first_error:
            first_failure = _llm_failure_code(first_error)
            if first_failure not in {"provider_timeout", "provider_unavailable", "provider_error"}:
                raise
            # One immediate retry absorbs transient Gemini/network failures.
            # Authentication, quota, invalid-request and model errors are not
            # retried, preventing duplicate paid calls for permanent failures.
            logger.warning("Transient market LLM failure (%s); retrying once", first_failure)
            answer, llm_provider = _provider_chat(messages)
        if not answer:
            raise RuntimeError("The configured LLM returned an empty answer.")
        grounding_issue = _llm_grounding_issue(
            answer,
            payload.message,
            prediction,
            context.get("macroFactors") or {"factors": []},
            context.get("historicalSession"),
            document_matches,
            document_requested,
            context.get("company"),
            context.get("news"),
        )
        if grounding_issue:
            llm_answer_accepted = False
            llm_status = "grounding_fallback"
            answer = verified_fallback()
    except RuntimeError as error:
        logger.warning("Configured market LLM unavailable; returning verified tool answer: %s", error)
        llm_used = False
        llm_status = "offline"
        llm_answer_accepted = False
        llm_failure = _llm_failure_code(error)
        answer = verified_fallback()

    citations = [{key: match.get(key) for key in (
        "citation", "documentId", "title", "reportingPeriod", "sourceUrl", "page", "score", "snippet"
    )} for match in document_matches]
    execution_trace = tool_trace(plan, outcomes)
    evidence_sources = []
    for item in execution_trace:
        evidence_sources.append({
            "id": f"E{len(evidence_sources) + 1}",
            "tool": item["tool"],
            "label": item["label"],
            "evidenceType": item["evidenceType"],
            "source": item["source"],
            "status": item["status"],
            "evidenceCount": item["evidenceCount"],
        })
    for citation in citations:
        evidence_sources.append({
            "id": citation["citation"],
            "tool": "company_document_rag",
            "label": f"{citation['title']} - page {citation['page']}",
            "evidenceType": "cited_document_chunk",
            "source": citation.get("sourceUrl") or "FinTrack trusted document index",
            "status": "retrieved",
            "evidenceCount": 1,
        })

    return {
        "answer": answer,
        "symbol": symbol,
        "llmUsed": llm_used,
        "llmProvider": llm_provider,
        "llmStatus": llm_status,
        "llmFailure": llm_failure,
        "llmAnswerAccepted": llm_answer_accepted,
        "groundingIssue": grounding_issue,
        "agentPlan": plan,
        "toolsUsed": tools,
        "toolTrace": execution_trace,
        "evidenceSources": evidence_sources,
        "citations": citations,
        "usedLiveContext": True,
        "suggestedQuestions": [
            f"Why is {symbol} outlook {context['prediction']['outlook'].lower()}?",
            f"Show recent news factors for {symbol}",
            "Compare major global indices",
        ],
        "disclaimer": context["prediction"]["disclaimer"],
    }
