"""Validated OHLCV ingestion pipeline for arbitrary public market symbols."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

import numpy as np
import pandas as pd
import yfinance as yf

from persistence import Database, utc_now


SYMBOL_PATTERN = re.compile(r"[A-Z0-9.^=&\-]{1,20}")
REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


def normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if not SYMBOL_PATTERN.fullmatch(normalized):
        raise ValueError(f"Invalid market symbol: {symbol!r}")
    return normalized


def validate_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    """Return clean, chronological OHLCV rows and reject impossible prices."""
    if frame is None or frame.empty:
        raise ValueError("Market provider returned no OHLCV rows.")
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {', '.join(missing)}")

    clean = frame.copy()
    clean = clean[~clean.index.duplicated(keep="last")].sort_index()
    for column in (*REQUIRED_COLUMNS, "Adj Close"):
        if column in clean:
            clean[column] = pd.to_numeric(clean[column], errors="coerce")

    clean = clean.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    finite = np.isfinite(clean[["Open", "High", "Low", "Close", "Volume"]]).all(axis=1)
    positive_prices = (clean[["Open", "High", "Low", "Close"]] > 0).all(axis=1)
    valid_volume = clean["Volume"] >= 0
    valid_range = (
        (clean["High"] >= clean[["Open", "Close", "Low"]].max(axis=1))
        & (clean["Low"] <= clean[["Open", "Close", "High"]].min(axis=1))
    )
    clean = clean.loc[finite & positive_prices & valid_volume & valid_range]
    if clean.empty:
        raise ValueError("No valid OHLCV rows remained after validation.")
    return clean


def bars_from_frame(symbol: str, frame: pd.DataFrame, source: str = "Yahoo Finance") -> List[Dict[str, Any]]:
    normalized = normalize_symbol(symbol)
    clean = validate_ohlcv(frame)
    ingested_at = utc_now()
    bars = []
    for index, row in clean.iterrows():
        timestamp = pd.Timestamp(index)
        adjusted = row.get("Adj Close")
        bars.append({
            "symbol": normalized,
            "session_date": timestamp.date().isoformat(),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "adjusted_close": float(adjusted) if adjusted is not None and pd.notna(adjusted) else None,
            "volume": float(row["Volume"]),
            "source": source,
            "ingested_at": ingested_at,
        })
    return bars


def dataset_version(bars: Iterable[Dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    ordered = sorted(bars, key=lambda row: (row["symbol"], row["session_date"]))
    for row in ordered:
        digest.update(
            f"{row['symbol']}|{row['session_date']}|{row['open']:.8f}|{row['high']:.8f}|"
            f"{row['low']:.8f}|{row['close']:.8f}|{row['volume']:.4f}\n".encode("utf-8")
        )
    return digest.hexdigest()[:16]


def ingest_symbols(
    symbols: Iterable[str],
    period: str = "2y",
    database: Optional[Database] = None,
) -> Dict[str, Any]:
    normalized_symbols = list(dict.fromkeys(normalize_symbol(symbol) for symbol in symbols))
    if not normalized_symbols:
        raise ValueError("Provide at least one symbol or a symbols file.")

    repository = database or Database()
    repository.initialize_schema()
    run_id = str(uuid4())
    started_at = utc_now()
    repository.create_ingestion_run({
        "id": run_id,
        "started_at": started_at,
        "status": "running",
        "period": period,
        "symbols_requested": len(normalized_symbols),
    })

    errors: List[Dict[str, str]] = []
    all_bars: List[Dict[str, Any]] = []
    symbol_results = []
    for symbol in normalized_symbols:
        try:
            ticker = yf.Ticker(symbol)
            raw_frame = ticker.history(period=period, interval="1d", auto_adjust=False)
            bars = bars_from_frame(symbol, raw_frame)
            repository.upsert_company({
                "symbol": symbol,
                "name": symbol,
                "source": "Yahoo Finance",
                "metadata": {"period": period},
            })
            written = repository.upsert_market_bars(bars)
            all_bars.extend(bars)
            symbol_results.append({
                "symbol": symbol,
                "status": "stored",
                "rows": written,
                "firstSession": bars[0]["session_date"],
                "lastSession": bars[-1]["session_date"],
            })
        except Exception as error:
            errors.append({"symbol": symbol, "error": str(error)})
            symbol_results.append({"symbol": symbol, "status": "failed", "rows": 0})

    version = dataset_version(all_bars) if all_bars else None
    status = "completed" if not errors else "partial" if all_bars else "failed"
    repository.complete_ingestion_run(
        run_id,
        completed_at=utc_now(),
        status=status,
        bars_written=len(all_bars),
        dataset_version=version,
        errors=errors,
    )
    return {
        "runId": run_id,
        "status": status,
        "backend": repository.backend,
        "database": repository.location,
        "period": period,
        "symbolsRequested": len(normalized_symbols),
        "barsWritten": len(all_bars),
        "datasetVersion": version,
        "results": symbol_results,
        "errors": errors,
        "startedAt": started_at,
        "completedAt": datetime.now(timezone.utc).isoformat(),
    }


def _read_symbols(values: Iterable[str], symbols_file: Optional[str]) -> List[str]:
    symbols: List[str] = []
    for value in values:
        symbols.extend(item for item in value.split(",") if item.strip())
    if symbols_file:
        path = Path(symbols_file)
        symbols.extend(
            line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    return symbols


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest validated daily OHLCV data into FinTrack storage.")
    parser.add_argument("--symbols", nargs="*", default=[], help="Ticker list; comma-separated values are accepted.")
    parser.add_argument("--symbols-file", help="Text file containing one ticker per line.")
    parser.add_argument("--period", default="2y", help="Yahoo Finance history period, for example 1y, 2y or 5y.")
    parser.add_argument("--database-url", help="PostgreSQL URL or sqlite:///path override.")
    arguments = parser.parse_args()
    symbols = _read_symbols(arguments.symbols, arguments.symbols_file)
    result = ingest_symbols(symbols, period=arguments.period, database=Database(arguments.database_url))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
