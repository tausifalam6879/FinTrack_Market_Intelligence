import json
import logging
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

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
    "beat", "beats", "bullish", "gain", "gains", "growth", "higher", "optimism",
    "positive", "profit", "rally", "record", "recovery", "surge", "up", "upgrade",
}
NEGATIVE_WORDS = {
    "bearish", "concern", "crash", "cut", "decline", "down", "drop", "fear", "fraud",
    "inflation", "loss", "miss", "recession", "risk", "slump", "tariff", "war", "weak",
}

CACHE_TTL_SECONDS = int(os.getenv("MARKET_CACHE_TTL_SECONDS", "120"))
QUOTE_CACHE_TTL_SECONDS = int(os.getenv("MARKET_QUOTE_CACHE_TTL_SECONDS", "15"))
OVERVIEW_CACHE_TTL_SECONDS = int(os.getenv("MARKET_OVERVIEW_CACHE_TTL_SECONDS", "900"))
PREDICTION_CACHE_TTL_SECONDS = int(os.getenv("MARKET_PREDICTION_CACHE_TTL_SECONDS", "900"))
_cache: Dict[str, Dict[str, Any]] = {}
_overview_lock = Lock()
_prediction_audit: Dict[str, List[Dict[str, Any]]] = {}
_prediction_audit_lock = Lock()


class MarketAgentRequest(BaseModel):
    message: str = Field(min_length=2, max_length=1200)
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
    if not re.fullmatch(r"[A-Z0-9.^=\-]{1,20}", normalized):
        raise ValueError("Invalid market symbol.")
    return normalized


def _infer_symbol(message: str, supplied_symbol: Optional[str]) -> str:
    lowered = message.lower()
    for alias, symbol in SYMBOL_ALIASES.items():
        if alias in lowered:
            return symbol
    if supplied_symbol:
        return _sanitize_symbol(supplied_symbol)
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
    raw_score = sum(word in POSITIVE_WORDS for word in words) - sum(word in NEGATIVE_WORDS for word in words)
    sentiment = max(-1.0, min(1.0, raw_score / 3))
    return {
        "title": title,
        "publisher": provider.get("displayName") or item.get("publisher") or "Unknown",
        "url": item.get("link") or click_url.get("url") or canonical_url.get("url"),
        "publishedAt": published,
        "sentiment": _round(sentiment, 3),
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
    sentiment = float(np.mean([item["sentiment"] for item in articles])) if articles else 0.0
    result = {
        "symbol": symbol,
        "articles": articles,
        "sentimentScore": _round(sentiment, 3),
        "sentimentLabel": "positive" if sentiment > 0.15 else "negative" if sentiment < -0.15 else "mixed/neutral",
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

    close = frame["Close"].astype(float)
    fifty_two_week_low = _round(frame["Low"].min()) if "Low" in frame else None
    fifty_two_week_high = _round(frame["High"].max()) if "High" in frame else None
    result = {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName") or snapshot["name"],
        "sector": info.get("sector") or "Not available",
        "industry": info.get("industry") or "Not available",
        "country": info.get("country") or snapshot.get("region") or "Not available",
        "website": info.get("website"),
        "summary": info.get("longBusinessSummary"),
        "quote": snapshot,
        "performance": {
            "oneDay": snapshot.get("changePercent"),
            "oneMonth": _period_return(close, 22),
            "threeMonths": _period_return(close, 66),
            "sixMonths": _period_return(close, 132),
            "oneYear": _period_return(close, 252),
        },
        "range": {
            "fiftyTwoWeekLow": _round(info.get("fiftyTwoWeekLow")) or fifty_two_week_low,
            "fiftyTwoWeekHigh": _round(info.get("fiftyTwoWeekHigh")) or fifty_two_week_high,
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
        "history": [
            {"date": index.strftime("%Y-%m-%d"), "close": _round(row["Close"])}
            for index, row in frame.tail(120).iterrows()
        ],
        "news": market_news(symbol, 6)["articles"],
        "dataAsOf": snapshot["dataAsOf"],
        "source": "Yahoo Finance via yfinance",
        "missingDataNotice": "Some fundamentals may be unavailable for indices, commodities or unsupported listings.",
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

    validation = _walk_forward_model_comparison(dataset, feature_columns)
    selected = validation["selected"]
    model = _candidate_models()[selected["id"]]["estimator"]
    model.fit(dataset[feature_columns], dataset["target"])
    raw_technical_probability = float(model.predict_proba(latest_features[feature_columns])[0][1])
    balanced_accuracy = float(selected["balancedAccuracy"])
    auc = float(selected["rocAuc"] if selected["rocAuc"] is not None else 0.50)
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
    comparisons = [
        {
            "id": item["id"],
            "name": item["name"],
            "selected": item["id"] == selected["id"],
            "folds": item["folds"],
            "testRows": item["testRows"],
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
        "model": {
            "type": selected["name"],
            "selection": "Best of three classifiers by walk-forward validation score.",
            "trainingRows": len(dataset),
            "testRows": selected["testRows"],
            "walkForwardFolds": selected["folds"],
            "backtestAccuracy": _round(selected["accuracy"] * 100, 1),
            "balancedAccuracy": _round(balanced_accuracy * 100, 1),
            "precision": _round(selected["precision"] * 100, 1),
            "recall": _round(selected["recall"] * 100, 1),
            "f1": _round(selected["f1"] * 100, 1),
            "rocAuc": _round(selected["rocAuc"] * 100, 1) if selected["rocAuc"] is not None else None,
            "brierScore": _round(selected["brierScore"], 3),
            "naiveAccuracy": _round(baseline_accuracy * 100, 1),
            "quality": quality,
            "rawTechnicalProbabilityUp": _round(raw_technical_probability * 100, 1),
            "reliabilityWeight": _round(reliability_weight, 2),
            "confidenceThresholds": {"bullish": 58, "bearish": 42},
            "calibration": "Out-of-sample skill controls shrinkage toward 50%; low-confidence results remain NEUTRAL.",
            "validation": "Expanding-window TimeSeriesSplit with a one-session gap; no random shuffle.",
            "modelsCompared": comparisons,
            "featureImportance": importance,
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
    payload["predictionAudit"] = _record_prediction(payload, payload["modelDataDate"])
    return _cache_put(cache_key, payload)


def _ollama_chat(messages: List[Dict[str, str]]) -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("LLM_MODEL", "llama3.2:3b")
    timeout = max(5, int(os.getenv("LLM_TIMEOUT_MS", "60000")) // 1000)
    body = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": "10m",
        "options": {"temperature": 0.1, "num_predict": 160},
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
    timeout = max(5, int(os.getenv("LLM_TIMEOUT_MS", "15000")) // 1000)
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
        # dashboard response length here.
        "generationConfig": {"maxOutputTokens": 320},
    }).encode("utf-8")
    last_model_error: Optional[HTTPError] = None
    for model in _gemini_model_candidates(configured_model):
        request = UrlRequest(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
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
        "max_tokens": 320,
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
    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    if provider in {"", "ollama", "local"}:
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
    prediction: Dict[str, Any],
    tools: List[str],
    factor_payload: Dict[str, Any],
    breadth: Optional[Dict[str, Any]] = None,
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

    breadth_line = ""
    if breadth:
        breadth_line = (
            f"\n- Watchlist breadth: {breadth['advances']} advances, {breadth['declines']} declines, "
            f"{breadth['unchanged']} unchanged ({breadth['coverageCount']} covered)."
        )
    return (
        "Verified current evidence:\n"
        + "\n".join(factor_lines)
        + breadth_line
        + f"\n- {prediction['name']} model: {prediction['outlook']}, probability-up {prediction['probabilityUp']}%, "
        + f"range {prediction['expectedRange']['low']} to {prediction['expectedRange']['high']} "
        + f"{prediction['expectedRange']['currency']}; news {news['sentimentLabel']}."
        + f"\n- Walk-forward balanced accuracy {model['balancedAccuracy']}% across "
        + f"{model['walkForwardFolds']} time-ordered folds; ROC AUC {model.get('rocAuc')}% "
        + f"({model.get('quality', 'unknown')}). "
        + ("Is model me reliable directional edge nahi hai. " if float(model["balancedAccuracy"]) < 53 else "Uncertainty abhi bhi high hai. ")
        + "Guaranteed return ya buy/sell advice nahi hai."
    )


def _llm_grounding_issue(answer: str, message: str, prediction: Dict[str, Any], factor_payload: Dict[str, Any]) -> Optional[str]:
    normalized_answer = answer.lower()
    lowered = message.lower()
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
    tools = ["market_snapshot", "technical_prediction", "market_news", "macro_market_factors"]
    context: Dict[str, Any] = {
        "snapshot": market_snapshot(symbol),
        "prediction": market_prediction(symbol),
        "news": market_news(symbol, 6),
        "macroFactors": macro_factors(),
    }
    if symbol not in GLOBAL_INDICES and symbol not in MACRO_FACTORS:
        tools.append("company_fundamentals")
        context["company"] = company_research(symbol)
    if any(word in lowered for word in ["gainer", "loser", "breadth", "advance", "decline", "active"]):
        tools.append("market_breadth")
        context["breadth"] = market_breadth()
    if any(word in lowered for word in ["world", "global", "markets", "indices"]):
        tools.append("global_market_overview")
        context["globalOverview"] = global_overview()

    prediction = context["prediction"]
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
    }
    if any(word in lowered for word in ["news", "headline", "war", "ai", "factor", "gold", "oil", "crude", "rupee"]):
        llm_context["headlines"] = [item["title"][:100] for item in context["news"]["articles"][:3]]
    if "company" in context:
        llm_context["company"] = {
            "sector": context["company"]["sector"],
            "industry": context["company"]["industry"],
            "performance": context["company"]["performance"],
            "fundamentals": context["company"]["fundamentals"],
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

    system_prompt = (
        "You are FinTrack Market Agent, a cautious market intelligence assistant. "
        "Use only the supplied tool results. Explain factors, uncertainty, model backtest and data timestamp. "
        "Never invent prices or news. Never guarantee direction, profit or return. Do not issue personalized "
        "buy/sell instructions. changePct means the asset's daily price change, never buying or selling volume. "
        "RSI belongs only to the analyzed asset: above 70 is overbought, below 30 is oversold, otherwise neutral. "
        "If testAccuracy is below 53, explicitly say the model has no reliable directional edge. "
        "Answer in the user's Hindi, Hinglish or English style using at most four short bullets and finish the answer."
    )
    recent = []
    for item in payload.recent_messages[-2:]:
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            continue
        content = item.get("content", "")
        recent.append({"role": item["role"], "content": str(content)[:180]})
    messages = [
        {"role": "system", "content": system_prompt},
        *recent,
        {
            "role": "user",
            "content": f"Question: {payload.message}\nEvidence: {json.dumps(llm_context, default=str)[:1900]}",
        },
    ]
    llm_used = True
    llm_status = "connected"
    llm_answer_accepted = True
    grounding_issue = None
    llm_failure = None
    llm_provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower() or "ollama"
    try:
        answer, llm_provider = _provider_chat(messages)
        if not answer:
            raise RuntimeError("The configured LLM returned an empty answer.")
        grounding_issue = _llm_grounding_issue(answer, payload.message, prediction, context["macroFactors"])
        if grounding_issue:
            llm_answer_accepted = False
            llm_status = "grounding_fallback"
            answer = _verified_tool_answer(
                payload.message,
                prediction,
                tools,
                context["macroFactors"],
                context.get("breadth"),
            )
    except RuntimeError as error:
        logger.warning("Configured market LLM unavailable; returning verified tool answer: %s", error)
        llm_used = False
        llm_status = "offline"
        llm_answer_accepted = False
        llm_failure = _llm_failure_code(error)
        answer = _verified_tool_answer(
            payload.message,
            prediction,
            tools,
            context["macroFactors"],
            context.get("breadth"),
        )

    return {
        "answer": answer,
        "symbol": symbol,
        "llmUsed": llm_used,
        "llmProvider": llm_provider,
        "llmStatus": llm_status,
        "llmFailure": llm_failure,
        "llmAnswerAccepted": llm_answer_accepted,
        "groundingIssue": grounding_issue,
        "toolsUsed": tools,
        "toolTrace": [
            {"step": index + 1, "tool": tool, "status": "completed"}
            for index, tool in enumerate(tools)
        ],
        "usedLiveContext": True,
        "suggestedQuestions": [
            f"Why is {symbol} outlook {context['prediction']['outlook'].lower()}?",
            f"Show recent news factors for {symbol}",
            "Compare major global indices",
        ],
        "disclaimer": context["prediction"]["disclaimer"],
    }
