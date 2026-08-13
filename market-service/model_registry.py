"""Trusted model approval, artifact loading and persistent prediction audit."""

from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, Optional

import joblib

from persistence import Database, utc_now
from data_operations import data_operations_snapshot
from drift_monitoring import refresh_drift_snapshot, retraining_policy, rolling_prediction_quality


DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"


def _json_object(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        decoded = json.loads(value or "{}")
        return decoded if isinstance(decoded, dict) else {}
    except (TypeError, ValueError):
        return {}


def _trusted_artifact_path(path_value: str, trusted_root: Optional[Path] = None) -> Path:
    root = Path(trusted_root or os.getenv("MODEL_ARTIFACT_DIR") or DEFAULT_ARTIFACT_DIR).resolve()
    path = Path(path_value).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError("Model artifact is outside the trusted FinTrack artifact directory.") from error
    if not path.is_file() or path.suffix != ".joblib":
        raise ValueError("Trusted model artifact does not exist or has an invalid extension.")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=24)
def _load_verified_artifact(path_value: str, expected_sha256: str) -> Dict[str, Any]:
    path = Path(path_value)
    actual_sha256 = _sha256(path)
    if not expected_sha256 or actual_sha256 != expected_sha256:
        raise ValueError("Model artifact checksum does not match its registered training run.")
    artifact = joblib.load(path)
    if not isinstance(artifact, dict) or "estimator" not in artifact:
        raise ValueError("Model artifact payload is invalid.")
    return artifact


def approve_model(
    run_id: str,
    database: Optional[Database] = None,
    trusted_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Approve a quality-gate candidate after verifying trusted path and checksum."""
    repository = database or Database()
    repository.initialize_schema()
    run = repository.model_run(run_id)
    if not run:
        raise ValueError(f"Unknown model run: {run_id}")
    if run["status"] != "candidate":
        raise ValueError("Only a candidate that passed the offline quality gate can be approved.")

    metrics = _json_object(run.get("metrics_json"))
    quality_gate = _json_object(metrics.get("qualityGate"))
    if quality_gate.get("passed") is not True:
        raise ValueError("Model run did not pass the registered offline quality gate.")
    artifact_path = _trusted_artifact_path(run["artifact_path"], trusted_root)
    expected_sha256 = str(metrics.get("artifactSha256") or "")
    artifact = _load_verified_artifact(str(artifact_path), expected_sha256)
    if artifact.get("modelRunId") != run_id or artifact.get("symbol") != run["symbol"]:
        raise ValueError("Artifact identity does not match the registered model run.")
    if artifact.get("datasetVersion") != run["dataset_version"]:
        raise ValueError("Artifact dataset version does not match the registered model run.")

    repository.approve_model_run(run_id, run["symbol"])
    return {
        "modelRunId": run_id,
        "symbol": run["symbol"],
        "model": run["model_name"],
        "status": "approved",
        "artifactSha256": expected_sha256,
        "datasetVersion": run["dataset_version"],
        "approvedAt": utc_now(),
    }


def approved_model(
    symbol: str,
    database: Optional[Database] = None,
    trusted_root: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    repository = database or Database()
    repository.initialize_schema()
    run = repository.latest_model_run(symbol, "approved")
    if not run:
        return None
    metrics = _json_object(run.get("metrics_json"))
    path = _trusted_artifact_path(run["artifact_path"], trusted_root)
    artifact = _load_verified_artifact(str(path), str(metrics.get("artifactSha256") or ""))
    if artifact.get("modelRunId") != run["id"] or artifact.get("symbol") != symbol:
        raise ValueError("Approved artifact identity is invalid.")
    return {"run": run, "metrics": metrics, "artifact": artifact}


def record_prediction(
    payload: Dict[str, Any],
    database: Optional[Database] = None,
    feature_values: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist one prediction per symbol/data-date/model and score older pending rows."""
    repository = database or Database()
    repository.initialize_schema()
    symbol = str(payload["symbol"])
    model_data_date = str(payload["modelDataDate"])
    reference_close = float(payload["lastClose"])
    repository.evaluate_pending_predictions(symbol, model_data_date, reference_close)
    model_run_id = payload.get("model", {}).get("modelRunId")
    identity = re.sub(r"[^A-Za-z0-9_.-]+", "_", model_run_id or "runtime")
    prediction_id = f"{symbol}:{model_data_date}:{identity}"
    repository.upsert_prediction({
        "id": prediction_id,
        "symbol": symbol,
        "model_run_id": model_run_id,
        "model_data_date": model_data_date,
        "generated_at": payload["generatedAt"],
        "probability_up": float(payload["probabilityUp"]),
        "outlook": payload["outlook"],
        "reference_close": reference_close,
        "expected_low": payload.get("expectedRange", {}).get("low"),
        "expected_high": payload.get("expectedRange", {}).get("high"),
    })
    if model_run_id and feature_values:
        repository.upsert_prediction_features(
            prediction_id,
            symbol,
            str(model_run_id),
            feature_values,
            payload["generatedAt"],
        )
        refresh_drift_snapshot(symbol, str(model_run_id), repository)


def monitoring_snapshot(symbol: str, database: Optional[Database] = None) -> Dict[str, Any]:
    repository = database or Database()
    repository.initialize_schema()
    approved = repository.latest_model_run(symbol, "approved")
    latest = repository.latest_model_run(symbol)
    records = (
        repository.model_prediction_records(symbol, approved["id"], 100)
        if approved else repository.prediction_records(symbol, 100)
    )
    evaluated = [row for row in records if row.get("evaluated_at") is not None]
    correct = [row for row in evaluated if bool(row.get("correct"))]
    quality = rolling_prediction_quality(records)
    drift = repository.latest_drift_snapshot(symbol, approved["id"]) if approved else None
    policy = retraining_policy(approved, quality, drift)
    data_operations = data_operations_snapshot(symbol, repository)

    def public_run(run: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not run:
            return None
        metrics = _json_object(run.get("metrics_json"))
        baselines = _json_object(run.get("baselines_json"))
        quality_gate = _json_object(metrics.get("qualityGate"))
        return {
            "id": run["id"],
            "model": run["model_name"],
            "status": run["status"],
            "datasetVersion": run["dataset_version"],
            "trainingPeriod": {
                "start": run["training_start"], "end": run["training_end"],
                "rows": run["training_rows"],
            },
            "holdout": {
                "start": run["holdout_start"], "end": run["holdout_end"],
                "rows": run["holdout_rows"],
                "balancedAccuracy": round(float(run["balanced_accuracy"]) * 100, 1),
                "rocAuc": round(float(run["roc_auc"]) * 100, 1) if run.get("roc_auc") is not None else None,
                "brierScore": round(float(run["brier_score"]), 3),
            },
            "qualityGate": quality_gate,
            "baselines": baselines,
            "createdAt": str(run["created_at"]),
        }

    public_records = [{
        "id": row["id"],
        "modelDataDate": row["model_data_date"],
        "probabilityUp": row["probability_up"],
        "outlook": row["outlook"],
        "actualDirection": row.get("actual_direction"),
        "correct": None if row.get("correct") is None else bool(row["correct"]),
        "status": "evaluated" if row.get("evaluated_at") else "pending",
    } for row in records[:8]]
    return {
        "symbol": symbol,
        "servingMode": "approved_artifact" if approved else "runtime_fallback",
        "approvedModel": public_run(approved),
        "latestModelRun": public_run(latest),
        "predictionMonitoring": {
            "totalStored": len(records),
            "evaluated": len(evaluated),
            "observedAccuracy": round(len(correct) / len(evaluated) * 100, 1) if evaluated else None,
            "records": public_records,
            "rollingQuality": quality,
        },
        "driftMonitoring": drift or {
            "status": "baseline_unavailable" if approved else "not_applicable",
            "recentObservations": 0,
            "meanPsi": None,
            "maxPsi": None,
            "features": [],
            "recommendation": (
                "The approved legacy artifact has no stored feature baseline yet."
                if approved else "Drift monitoring starts after an offline artifact is approved."
            ),
        },
        "retrainingPolicy": policy,
        "dataOperations": data_operations,
        "storage": {"backend": repository.backend, "persistent": True},
        "generatedAt": utc_now(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Approve a trusted FinTrack model artifact for serving.")
    parser.add_argument("--approve", required=True, help="Candidate model-run ID to approve.")
    parser.add_argument("--database-url", help="PostgreSQL URL or sqlite:///path override.")
    parser.add_argument("--artifact-dir", help="Trusted artifact directory override.")
    arguments = parser.parse_args()
    result = approve_model(
        arguments.approve,
        Database(arguments.database_url),
        Path(arguments.artifact_dir) if arguments.artifact_dir else None,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
