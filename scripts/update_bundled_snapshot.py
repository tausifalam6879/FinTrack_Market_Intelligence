"""Refresh the frontend's packaged startup snapshot from a running market API.

Run this before a release when a newer verified baseline is wanted. The browser
renders this data immediately and then replaces it with the live API response.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "frontend" / "src" / "data" / "bundledMarketSnapshot.json"
API_BASE = os.getenv("MARKET_API_BASE_URL", "http://127.0.0.1:8002").rstrip("/")


def fetch(path: str, **params):
    query = f"?{urlencode(params)}" if params else ""
    with urlopen(f"{API_BASE}{path}{query}", timeout=90) as response:
        return json.load(response)


def main() -> None:
    analysis_symbols = ["^NSEI", "^BSESN", "RELIANCE.NS", "HDFCBANK.NS", "INFY.NS", "AAPL", "MSFT"]
    snapshot = {
        "schemaVersion": 1,
        "packagedAt": datetime.now(timezone.utc).isoformat(),
        "overview": fetch("/market/overview"),
        "currencies": fetch("/market/currencies"),
        "newsFeed": fetch("/market/news-feed", limit=20),
        "analysis": {symbol: fetch("/market/analysis", symbol=symbol) for symbol in analysis_symbols},
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Updated {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
