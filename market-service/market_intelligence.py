import json
import logging
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
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
    "volatility",
)

CATALYST_QUERY_TERMS = (
    "earnings date", "earnings calendar", "next earnings", "analyst", "price target",
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
    return (
        "Seedha jawab\n"
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
            "Seedha jawab\n"
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
        "Seedha jawab\n"
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
    if len(answer.strip()) < 220:
        return "answer too short for a complete analysis"
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
    if risk_requested and asset_risk.get("annualizedVolatilityPercent") is not None:
        expected_volatility = f"{abs(float(asset_risk['annualizedVolatilityPercent'])):.2f}".rstrip("0").rstrip(".")
        if expected_volatility not in normalized_answer:
            return "missing historical risk evidence"
        risk_payload = prediction.get("riskBenchmark") or {}
        comparison = risk_payload.get("comparison") or {}
        benchmark = risk_payload.get("benchmark") or {}
        required_metrics = []
        if "beta" in lowered and comparison.get("beta") is not None:
            required_metrics.append(("beta", comparison["beta"]))
        if "drawdown" in lowered and asset_risk.get("maxDrawdownPercent") is not None:
            required_metrics.append(("drawdown", asset_risk["maxDrawdownPercent"]))
        if ("value at risk" in lowered or "historical var" in lowered or re.search(r"\bvar\b", lowered)) and asset_risk.get("historicalVar95Percent") is not None:
            required_metrics.append(("historical VaR", asset_risk["historicalVar95Percent"]))
        if "tracking error" in lowered and comparison.get("trackingErrorPercent") is not None:
            required_metrics.append(("tracking error", comparison["trackingErrorPercent"]))
        for label, value in required_metrics:
            expected_value = f"{abs(float(value)):.2f}".rstrip("0").rstrip(".")
            if expected_value not in normalized_answer:
                return f"missing requested {label} evidence"
        benchmark_name = str(benchmark.get("name") or "").lower()
        if "benchmark" in lowered and benchmark_name and benchmark_name not in normalized_answer:
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
        "invent prices, dates, news or calculations. Match the user's Hindi, Hinglish or English. Give a useful, "
        "detailed answer with these compact sections when relevant: Seedha jawab, Verified figures, Calculation, "
        "Scenario/estimate, Assumptions and confidence, Final assessment. Show arithmetic explicitly using the "
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
        "changePct is daily price change, not trading volume. RSI above 70 is overbought, below 30 is oversold. "
        "If balancedAccuracy is below 53, explicitly state that the model has no reliable directional edge. "
        "Keep the response readable and normally within about 550 words."
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
