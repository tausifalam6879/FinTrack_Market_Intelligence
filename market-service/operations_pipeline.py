"""Demand-driven scheduled ingestion and monitoring orchestration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from data_pipeline import ingest_symbols, normalize_symbol
from model_registry import monitoring_snapshot
from monitoring_job import monitor_symbols
from persistence import Database, utc_now


def _symbols(values: Iterable[str]) -> list[str]:
    symbols = []
    for value in values:
        symbols.extend(item.strip() for item in str(value).split(",") if item.strip())
    return list(dict.fromkeys(normalize_symbol(item) for item in symbols))


def run_operations(
    database: Optional[Database] = None,
    requested_symbols: Optional[Iterable[str]] = None,
    period: str = "2y",
    max_symbols: int = 100,
) -> Dict[str, Any]:
    repository = database or Database()
    repository.initialize_schema()
    explicit = _symbols(requested_symbols or [])
    universe_source = "manual_selection" if explicit else "demand_driven_database"
    symbols = explicit or repository.operational_symbols(max_symbols)
    if not symbols:
        return {
            "status": "skipped",
            "universeSource": universe_source,
            "symbols": [],
            "message": "No researched symbols exist yet; opening a company will seed the dynamic universe.",
            "automaticTraining": False,
            "automaticApproval": False,
            "completedAt": utc_now(),
        }

    ingestion = ingest_symbols(symbols, period=period, database=repository)
    stored_symbols = [
        item["symbol"] for item in ingestion.get("results", [])
        if item.get("status") == "stored"
    ]
    drift = monitor_symbols(stored_symbols, repository) if stored_symbols else {
        "status": "skipped", "results": [], "errors": []
    }
    decisions = []
    for symbol in stored_symbols:
        snapshot = monitoring_snapshot(symbol, repository)
        decisions.append({
            "symbol": symbol,
            "servingMode": snapshot["servingMode"],
            "dataFreshness": snapshot["dataOperations"]["freshness"],
            "driftStatus": snapshot["driftMonitoring"]["status"],
            "retrainingDecision": snapshot["retrainingPolicy"]["decision"],
        })

    return {
        "status": ingestion["status"],
        "universeSource": universe_source,
        "symbols": symbols,
        "ingestion": ingestion,
        "monitoring": drift,
        "decisions": decisions,
        "automaticTraining": False,
        "automaticApproval": False,
        "policy": (
            "This job refreshes validated data and monitoring evidence only. "
            "Candidate training and model approval remain separate trusted operations."
        ),
        "completedAt": utc_now(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh the demand-driven FinTrack symbol universe and monitoring evidence."
    )
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--symbols-text", default="", help="Optional comma-separated manual universe.")
    parser.add_argument("--period", default="2y")
    parser.add_argument("--max-symbols", type=int, default=100)
    parser.add_argument("--database-url")
    parser.add_argument("--report-file")
    arguments = parser.parse_args()
    result = run_operations(
        Database(arguments.database_url),
        [*arguments.symbols, arguments.symbols_text],
        period=arguments.period,
        max_symbols=arguments.max_symbols,
    )
    rendered = json.dumps(result, indent=2)
    if arguments.report_file:
        Path(arguments.report_file).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
