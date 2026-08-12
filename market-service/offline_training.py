"""Offline model training with chronological holdout evaluation and artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

# Some minimal Windows/CI images cannot report physical cores. The estimators
# already use one worker; this keeps joblib from emitting an irrelevant warning.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import joblib
import numpy as np
import pandas as pd
import sklearn

from data_pipeline import dataset_version, normalize_symbol
from deep_learning import train_pytorch_mlp_experiment
from experiment_tracking import log_training_experiment
from market_intelligence import (
    FEATURE_LABELS,
    _candidate_models,
    _classification_metrics,
    _features,
    _walk_forward_model_comparison,
)
from persistence import Database, utc_now


DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"


def _frame_from_rows(symbol: str, rows: List[Dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        raise ValueError(f"No persisted market bars were found for {symbol}. Run data_pipeline.py first.")
    frame = pd.DataFrame(rows).rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "adjusted_close": "Adj Close",
        "volume": "Volume",
    })
    frame.index = pd.to_datetime(frame.pop("session_date"))
    return frame.sort_index()


def _baseline_metrics(train: pd.DataFrame, holdout: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    truth = holdout["target"].astype(int).to_numpy()
    majority_value = int(float(train["target"].mean()) >= 0.5)
    majority_probability = float(train["target"].mean())

    definitions = {
        "training_majority": (
            np.full(len(holdout), majority_value),
            np.full(len(holdout), majority_probability),
        ),
        "previous_session_momentum": (
            (holdout["return_1"] > 0).astype(int).to_numpy(),
            np.where(holdout["return_1"] > 0, 0.60, 0.40),
        ),
        "sma_10_20_trend": (
            (holdout["sma_10_ratio"] < holdout["sma_20_ratio"]).astype(int).to_numpy(),
            np.where(holdout["sma_10_ratio"] < holdout["sma_20_ratio"], 0.60, 0.40),
        ),
    }
    return {
        name: _classification_metrics(truth, predictions, probabilities)
        for name, (predictions, probabilities) in definitions.items()
    }


def _artifact_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def train_symbol(
    symbol: str,
    database: Optional[Database] = None,
    artifact_dir: Optional[Path] = None,
    holdout_fraction: float = 0.15,
) -> Dict[str, Any]:
    normalized = normalize_symbol(symbol)
    repository = database or Database()
    repository.initialize_schema()
    rows = repository.load_market_bars(normalized)
    frame = _frame_from_rows(normalized, rows)
    if len(frame) < 180:
        raise ValueError(f"{normalized} needs at least 180 stored daily bars for offline training.")

    feature_columns = list(FEATURE_LABELS)
    features = _features(frame)
    dataset = features.copy()
    dataset["target"] = (frame["Close"].shift(-1) > frame["Close"]).astype(int)
    dataset = dataset.iloc[:-1].dropna()
    minimum_holdout = 30
    holdout_rows = max(minimum_holdout, int(len(dataset) * holdout_fraction))
    purge_gap_rows = 1
    if len(dataset) - holdout_rows - purge_gap_rows < 100:
        raise ValueError("Not enough chronological training rows remain before the final holdout.")

    # The target on row t uses the close on row t+1. Purging the boundary row
    # prevents the last training label from observing the first holdout close.
    training = dataset.iloc[:-(holdout_rows + purge_gap_rows)].copy()
    holdout = dataset.iloc[-holdout_rows:].copy()
    validation = _walk_forward_model_comparison(training, feature_columns)
    selected = validation["selected"]

    evaluation_model = _candidate_models()[selected["id"]]["estimator"]
    evaluation_model.fit(training[feature_columns], training["target"])
    probabilities = evaluation_model.predict_proba(holdout[feature_columns])[:, 1]
    predictions = (probabilities >= 0.50).astype(int)
    holdout_metrics = _classification_metrics(
        holdout["target"].astype(int).to_numpy(), predictions, probabilities
    )
    baselines = _baseline_metrics(training, holdout)
    best_baseline_balanced_accuracy = max(
        metrics["balancedAccuracy"] for metrics in baselines.values()
    )
    quality_checks = {
        "balancedAccuracyAtLeast52Percent": holdout_metrics["balancedAccuracy"] >= 0.52,
        "rocAucAtLeast52Percent": (
            holdout_metrics["rocAuc"] is not None and holdout_metrics["rocAuc"] >= 0.52
        ),
        "brierScoreAtMost0.255": holdout_metrics["brierScore"] <= 0.255,
        "matchesOrBeatsBestNaiveBaseline": (
            holdout_metrics["balancedAccuracy"] >= best_baseline_balanced_accuracy
        ),
    }
    quality_gate = {
        "passed": all(quality_checks.values()),
        "checks": quality_checks,
        "bestBaselineBalancedAccuracy": best_baseline_balanced_accuracy,
        "policy": "Candidate only; explicit approval is still required before serving.",
    }
    run_status = "candidate" if quality_gate["passed"] else "rejected"

    run_id = str(uuid4())
    target_directory = Path(artifact_dir or os.getenv("MODEL_ARTIFACT_DIR") or DEFAULT_ARTIFACT_DIR)
    target_directory.mkdir(parents=True, exist_ok=True)
    safe_symbol = re.sub(r"[^A-Z0-9]+", "_", normalized).strip("_").lower()
    deep_artifact_path = target_directory / f"{safe_symbol}-{run_id}-pytorch-mlp.pt"
    deep_learning_experiment = train_pytorch_mlp_experiment(
        training,
        holdout,
        feature_columns,
        deep_artifact_path,
    )

    production_model = _candidate_models()[selected["id"]]["estimator"]
    production_model.fit(dataset[feature_columns], dataset["target"])

    version_rows = [{
        "symbol": normalized,
        "session_date": str(index.date()),
        "open": float(frame.loc[index, "Open"]),
        "high": float(frame.loc[index, "High"]),
        "low": float(frame.loc[index, "Low"]),
        "close": float(frame.loc[index, "Close"]),
        "volume": float(frame.loc[index, "Volume"]),
    } for index in frame.index]
    version = dataset_version(version_rows)
    created_at = utc_now()
    artifact_path = target_directory / f"{safe_symbol}-{run_id}.joblib"
    artifact_payload = {
        "estimator": production_model,
        "symbol": normalized,
        "modelRunId": run_id,
        "modelName": selected["name"],
        "featureColumns": feature_columns,
        "datasetVersion": version,
        "trainingDataThrough": str(dataset.index[-1].date()),
        "createdAt": created_at,
        "versions": {"scikitLearn": sklearn.__version__},
        "trustNotice": "Load only artifacts created by this controlled FinTrack training pipeline.",
    }
    joblib.dump(artifact_payload, artifact_path, compress=3)
    artifact_sha256 = _artifact_checksum(artifact_path)

    metrics = {
        **holdout_metrics,
        "selection": selected,
        "walkForwardCandidates": validation["comparisons"],
        "walkForwardFolds": validation["folds"],
        "artifactSha256": artifact_sha256,
        "qualityGate": quality_gate,
        "purgeGapRows": purge_gap_rows,
        "deepLearningExperiment": deep_learning_experiment,
    }
    training_period = {
        "start": str(training.index[0].date()),
        "end": str(training.index[-1].date()),
        "rows": len(training),
    }
    holdout_period = {
        "start": str(holdout.index[0].date()),
        "end": str(holdout.index[-1].date()),
        "rows": len(holdout),
    }
    experiment_tracking = log_training_experiment(
        run_id=run_id,
        symbol=normalized,
        model_name=selected["name"],
        run_status=run_status,
        dataset_version=version,
        training_period=training_period,
        holdout_period=holdout_period,
        holdout_fraction=holdout_fraction,
        holdout_metrics=holdout_metrics,
        baselines=baselines,
        quality_gate=quality_gate,
        selection=selected,
        validation=validation,
        feature_columns=feature_columns,
        artifact_path=artifact_path,
        artifact_sha256=artifact_sha256,
        deep_learning_experiment=deep_learning_experiment,
        deep_artifact_path=deep_artifact_path,
    )
    metrics["experimentTracking"] = experiment_tracking
    run = {
        "id": run_id,
        "symbol": normalized,
        "model_name": selected["name"],
        "artifact_path": str(artifact_path.resolve()),
        "dataset_version": version,
        "training_start": training_period["start"],
        "training_end": training_period["end"],
        "training_rows": len(training),
        "holdout_start": holdout_period["start"],
        "holdout_end": holdout_period["end"],
        "holdout_rows": len(holdout),
        "balanced_accuracy": holdout_metrics["balancedAccuracy"],
        "roc_auc": holdout_metrics["rocAuc"],
        "brier_score": holdout_metrics["brierScore"],
        "metrics": metrics,
        "baselines": baselines,
        "features": feature_columns,
        "status": run_status,
        "created_at": created_at,
    }
    repository.save_model_run(run)
    return {
        "modelRunId": run_id,
        "symbol": normalized,
        "status": run_status,
        "model": selected["name"],
        "datasetVersion": version,
        "artifactPath": str(artifact_path.resolve()),
        "artifactSha256": artifact_sha256,
        "trainingPeriod": {
            "start": run["training_start"], "end": run["training_end"], "rows": len(training),
        },
        "untouchedHoldout": {
            "start": run["holdout_start"], "end": run["holdout_end"], "rows": len(holdout),
            **holdout_metrics,
        },
        "baselines": baselines,
        "qualityGate": quality_gate,
        "walkForwardSelection": selected,
        "purgeGapRows": purge_gap_rows,
        "deepLearningExperiment": deep_learning_experiment,
        "experimentTracking": experiment_tracking,
        "createdAt": created_at,
    }


def train_symbols(
    symbols: Iterable[str],
    database: Optional[Database] = None,
    artifact_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    repository = database or Database()
    results = []
    errors = []
    for symbol in dict.fromkeys(normalize_symbol(item) for item in symbols):
        try:
            results.append(train_symbol(symbol, repository, artifact_dir))
        except Exception as error:
            errors.append({"symbol": symbol, "error": str(error)})
    return {
        "status": "completed" if not errors else "partial" if results else "failed",
        "modelsCreated": len(results),
        "results": results,
        "errors": errors,
        "completedAt": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train versioned FinTrack models from persisted OHLCV data.")
    parser.add_argument("--symbols", nargs="+", required=True, help="One or more stored Yahoo Finance symbols.")
    parser.add_argument("--database-url", help="PostgreSQL URL or sqlite:///path override.")
    parser.add_argument("--artifact-dir", help="Directory for trusted joblib model artifacts.")
    arguments = parser.parse_args()
    result = train_symbols(
        arguments.symbols,
        database=Database(arguments.database_url),
        artifact_dir=Path(arguments.artifact_dir) if arguments.artifact_dir else None,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
