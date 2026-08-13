"""Offline monitoring job for baseline backfill and persisted drift snapshots."""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, Iterable, Optional

import pandas as pd

from data_pipeline import normalize_symbol
from drift_monitoring import build_feature_baselines, refresh_drift_snapshot
from market_intelligence import FEATURE_LABELS, _features
from persistence import Database, utc_now


def _feature_frame(rows: list[Dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        raise ValueError("No persisted market bars are available for baseline backfill.")
    frame = pd.DataFrame(rows).rename(columns={
        "open": "Open", "high": "High", "low": "Low", "close": "Close",
        "adjusted_close": "Adj Close", "volume": "Volume",
    })
    frame.index = pd.to_datetime(frame.pop("session_date"))
    return frame.sort_index()


def monitor_symbol(
    symbol: str, database: Optional[Database] = None, backfill_baseline: bool = True
) -> Dict[str, Any]:
    normalized = normalize_symbol(symbol)
    repository = database or Database()
    repository.initialize_schema()
    approved = repository.latest_model_run(normalized, "approved")
    if not approved:
        return {
            "symbol": normalized,
            "status": "not_applicable",
            "message": "No approved offline artifact is available.",
        }

    existing = repository.feature_baselines(approved["id"])
    baseline_backfilled = False
    if not existing and backfill_baseline:
        rows = repository.load_market_bars(normalized)
        frame = _feature_frame(rows)
        features = _features(frame).dropna()
        training = features.loc[str(approved["training_start"]):str(approved["training_end"])]
        if len(training) < 100:
            raise ValueError(
                f"{normalized} needs at least 100 stored training-period feature rows for baseline backfill."
            )
        baselines = build_feature_baselines(training, list(FEATURE_LABELS))
        repository.replace_feature_baselines(approved["id"], normalized, baselines)
        baseline_backfilled = True

    snapshot = refresh_drift_snapshot(normalized, approved["id"], repository)
    return {
        "symbol": normalized,
        "status": snapshot["status"],
        "modelRunId": approved["id"],
        "baselineBackfilled": baseline_backfilled,
        "recentObservations": snapshot["recentObservations"],
        "meanPsi": snapshot["meanPsi"],
        "maxPsi": snapshot["maxPsi"],
        "recommendation": snapshot["recommendation"],
    }


def monitor_symbols(
    symbols: Iterable[str], database: Optional[Database] = None, backfill_baseline: bool = True
) -> Dict[str, Any]:
    repository = database or Database()
    results = []
    errors = []
    for symbol in dict.fromkeys(normalize_symbol(item) for item in symbols):
        try:
            results.append(monitor_symbol(symbol, repository, backfill_baseline))
        except Exception as error:
            errors.append({"symbol": symbol, "error": str(error)})
    return {
        "status": "completed" if not errors else "partial" if results else "failed",
        "results": results,
        "errors": errors,
        "completedAt": utc_now(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Persist FinTrack drift snapshots without training or promoting a model."
    )
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--database-url", help="PostgreSQL URL or sqlite:///path override.")
    parser.add_argument(
        "--no-baseline-backfill",
        action="store_true",
        help="Do not build missing legacy baselines from stored training-period bars.",
    )
    arguments = parser.parse_args()
    result = monitor_symbols(
        arguments.symbols,
        Database(arguments.database_url),
        backfill_baseline=not arguments.no_baseline_backfill,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
