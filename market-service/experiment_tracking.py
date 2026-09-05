"""MLflow experiment tracking for reproducible FinTrack offline model runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse, urlunparse

from data_pipeline import normalize_symbol
from persistence import Database, utc_now


# MLflow's optional Git provenance should not spam training logs when Git is
# installed outside the process PATH (common in Windows desktop environments).
os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")


DEFAULT_MLFLOW_ARTIFACTS = Path(__file__).resolve().parent / "data" / "mlartifacts"
DEFAULT_EXPERIMENT_NAME = "fintrack-market-models"


def _enabled(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _default_mysql_tracking_uri() -> str:
    database_url = Database().url.replace("mysql://", "mysql+pymysql://", 1)
    parsed = urlparse(database_url)
    return urlunparse(parsed._replace(path="/fintrack_mlflow"))


def mlflow_configuration() -> Dict[str, Any]:
    configured_uri = os.getenv("MLFLOW_TRACKING_URI", "").strip()
    tracking_uri = configured_uri or _default_mysql_tracking_uri()
    parsed_scheme = tracking_uri.split(":", 1)[0].lower() if ":" in tracking_uri else "file"
    artifact_root = os.getenv("MLFLOW_ARTIFACT_ROOT", "").strip() or DEFAULT_MLFLOW_ARTIFACTS.resolve().as_uri()
    return {
        "trackingUri": tracking_uri,
        "backend": "mysql" if tracking_uri.startswith(("mysql:", "mysql+pymysql:")) else "file" if parsed_scheme == "file" else "remote",
        "artifactRoot": artifact_root,
        "experimentName": os.getenv("MLFLOW_EXPERIMENT_NAME", DEFAULT_EXPERIMENT_NAME).strip() or DEFAULT_EXPERIMENT_NAME,
        "required": _enabled(os.getenv("MLFLOW_REQUIRED")),
    }


def _mlflow_module():
    try:
        import mlflow
        return mlflow
    except ImportError as error:
        raise RuntimeError("MLflow is not installed. Install market-service/requirements.txt.") from error


def _metric(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _safe_metric_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-/]+", "_", str(value)).strip("_")[:200]


def log_training_experiment(
    *,
    run_id: str,
    symbol: str,
    model_name: str,
    run_status: str,
    dataset_version: str,
    training_period: Dict[str, Any],
    holdout_period: Dict[str, Any],
    holdout_fraction: float,
    holdout_metrics: Dict[str, Any],
    baselines: Dict[str, Dict[str, Any]],
    quality_gate: Dict[str, Any],
    selection: Dict[str, Any],
    validation: Dict[str, Any],
    feature_columns: list[str],
    artifact_path: Path,
    artifact_sha256: str,
    deep_learning_experiment: Optional[Dict[str, Any]] = None,
    deep_artifact_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Log one complete training experiment and return durable public metadata."""
    configuration = mlflow_configuration()
    try:
        mlflow = _mlflow_module()
        mlflow.set_tracking_uri(configuration["trackingUri"])
        client = mlflow.MlflowClient(tracking_uri=configuration["trackingUri"])
        experiment = client.get_experiment_by_name(configuration["experimentName"])
        if experiment is None:
            experiment_id = client.create_experiment(
                configuration["experimentName"],
                artifact_location=(
                    configuration["artifactRoot"]
                    if configuration["backend"] == "file"
                    else None
                ),
            )
        else:
            experiment_id = experiment.experiment_id
        tags = {
            "fintrack.model_run_id": run_id,
            "fintrack.symbol": symbol,
            "fintrack.status": run_status,
            "fintrack.dataset_version": dataset_version,
            "fintrack.quality_gate_passed": str(bool(quality_gate.get("passed"))).lower(),
            "fintrack.validation": "chronological_holdout",
            "fintrack.deep_learning_comparator": str(bool(deep_learning_experiment)).lower(),
        }
        params = {
            "symbol": symbol,
            "selected_model": model_name,
            "selected_model_id": selection.get("id") or "unknown",
            "holdout_fraction": holdout_fraction,
            "training_start": training_period["start"],
            "training_end": training_period["end"],
            "training_rows": training_period["rows"],
            "holdout_start": holdout_period["start"],
            "holdout_end": holdout_period["end"],
            "holdout_rows": holdout_period["rows"],
            "feature_count": len(feature_columns),
            "walk_forward_folds": validation.get("folds") or 0,
            "artifact_sha256": artifact_sha256,
        }
        if deep_learning_experiment:
            early_stopping = deep_learning_experiment.get("earlyStopping") or {}
            architecture = deep_learning_experiment.get("architecture") or {}
            params.update({
                "deep_model": deep_learning_experiment.get("name") or "PyTorch MLP",
                "deep_framework_version": deep_learning_experiment.get("frameworkVersion") or "unknown",
                "deep_seed": deep_learning_experiment.get("seed") or 0,
                "deep_hidden_layers": json.dumps(architecture.get("hiddenLayers") or []),
                "deep_best_epoch": early_stopping.get("bestEpoch") or 0,
                "deep_epochs_trained": early_stopping.get("epochsTrained") or 0,
            })
        metrics: Dict[str, float] = {}
        for name, value in holdout_metrics.items():
            number = _metric(value)
            if number is not None:
                metrics[f"holdout_{_safe_metric_name(name)}"] = number
        for baseline_name, baseline_metrics in baselines.items():
            for metric_name, value in baseline_metrics.items():
                number = _metric(value)
                if number is not None:
                    metrics[f"baseline_{_safe_metric_name(baseline_name)}_{_safe_metric_name(metric_name)}"] = number
        metrics["quality_gate_passed"] = 1.0 if quality_gate.get("passed") else 0.0
        if deep_learning_experiment:
            for split_name in ("validationMetrics", "holdoutMetrics"):
                split_metrics = deep_learning_experiment.get(split_name) or {}
                prefix = "deep_validation" if split_name == "validationMetrics" else "deep_holdout"
                for metric_name, value in split_metrics.items():
                    number = _metric(value)
                    if number is not None:
                        metrics[f"{prefix}_{_safe_metric_name(metric_name)}"] = number

        summary = {
            "modelRunId": run_id,
            "symbol": symbol,
            "model": model_name,
            "status": run_status,
            "datasetVersion": dataset_version,
            "trainingPeriod": training_period,
            "untouchedHoldout": {**holdout_period, **holdout_metrics},
            "baselines": baselines,
            "qualityGate": quality_gate,
            "selection": selection,
            "walkForwardCandidates": validation.get("comparisons") or [],
            "featureColumns": feature_columns,
            "artifactSha256": artifact_sha256,
            "deepLearningExperiment": deep_learning_experiment,
            "loggedAt": utc_now(),
        }
        run_name = f"{symbol}-{model_name}-{run_id[:8]}"
        with mlflow.start_run(run_name=run_name, experiment_id=experiment_id, tags=tags) as active_run:
            mlflow.log_params(params)
            if metrics:
                mlflow.log_metrics(metrics)
            mlflow.log_dict(summary, "training-summary.json")
            mlflow.log_artifact(str(Path(artifact_path).resolve()), artifact_path="model")
            deep_artifact_logged = bool(
                deep_artifact_path and Path(deep_artifact_path).exists()
            )
            if deep_artifact_logged:
                mlflow.log_artifact(
                    str(Path(deep_artifact_path).resolve()),
                    artifact_path="deep-learning",
                )
            info = active_run.info
            return {
                "enabled": True,
                "status": "logged",
                "provider": "MLflow",
                "runId": info.run_id,
                "experimentId": info.experiment_id,
                "experimentName": configuration["experimentName"],
                "backend": configuration["backend"],
                "artifactLogged": True,
                "deepLearningArtifactLogged": deep_artifact_logged,
                "loggedAt": utc_now(),
            }
    except Exception as error:
        if configuration["required"]:
            raise RuntimeError(f"Required MLflow tracking failed: {error}") from error
        return {
            "enabled": False,
            "status": "unavailable",
            "provider": "MLflow",
            "experimentName": configuration["experimentName"],
            "backend": configuration["backend"],
            "artifactLogged": False,
            "deepLearningArtifactLogged": False,
            "message": str(error)[:300],
            "loggedAt": utc_now(),
        }


def experiment_comparison(
    symbol: str,
    database: Optional[Database] = None,
    limit: int = 8,
) -> Dict[str, Any]:
    normalized = normalize_symbol(symbol)
    repository = database or Database()
    repository.initialize_schema()
    rows = repository.model_runs(normalized, max(1, min(int(limit), 20)))
    runs = []
    for row in rows:
        try:
            metrics = json.loads(row.get("metrics_json") or "{}")
        except (TypeError, ValueError):
            metrics = {}
        try:
            baselines = json.loads(row.get("baselines_json") or "{}")
        except (TypeError, ValueError):
            baselines = {}
        baseline_scores = [
            _metric(item.get("balancedAccuracy"))
            for item in baselines.values() if isinstance(item, dict)
        ]
        baseline_scores = [item for item in baseline_scores if item is not None]
        tracking = metrics.get("experimentTracking") or {
            "enabled": False,
            "status": "legacy-untracked",
            "provider": "MLflow",
        }
        deep = metrics.get("deepLearningExperiment")
        deep_summary = None
        if isinstance(deep, dict):
            deep_validation = deep.get("validationMetrics") or {}
            deep_holdout = deep.get("holdoutMetrics") or {}
            deep_balanced = _metric(deep_holdout.get("balancedAccuracy"))
            classical_balanced = float(row["balanced_accuracy"])
            deep_summary = {
                "model": deep.get("name") or "PyTorch MLP",
                "status": deep.get("status") or "experimental_not_served",
                "framework": deep.get("framework") or "PyTorch",
                "frameworkVersion": deep.get("frameworkVersion"),
                "device": deep.get("device") or "cpu",
                "seed": deep.get("seed"),
                "architecture": deep.get("architecture") or {},
                "earlyStopping": deep.get("earlyStopping") or {},
                "validationBalancedAccuracy": (
                    round(float(deep_validation["balancedAccuracy"]) * 100, 1)
                    if _metric(deep_validation.get("balancedAccuracy")) is not None else None
                ),
                "holdoutBalancedAccuracy": (
                    round(deep_balanced * 100, 1) if deep_balanced is not None else None
                ),
                "holdoutRocAuc": (
                    round(float(deep_holdout["rocAuc"]) * 100, 1)
                    if _metric(deep_holdout.get("rocAuc")) is not None else None
                ),
                "holdoutBrierScore": (
                    round(float(deep_holdout["brierScore"]), 3)
                    if _metric(deep_holdout.get("brierScore")) is not None else None
                ),
                "balancedAccuracyDeltaVsClassical": (
                    round((deep_balanced - classical_balanced) * 100, 1)
                    if deep_balanced is not None else None
                ),
                "artifactSha256": deep.get("artifactSha256"),
                "servingPolicy": deep.get("servingPolicy"),
            }
        runs.append({
            "modelRunId": row["id"],
            "model": row["model_name"],
            "status": row["status"],
            "datasetVersion": row["dataset_version"],
            "trainingRows": row["training_rows"],
            "holdoutRows": row["holdout_rows"],
            "holdoutBalancedAccuracy": round(float(row["balanced_accuracy"]) * 100, 1),
            "holdoutRocAuc": round(float(row["roc_auc"]) * 100, 1) if row.get("roc_auc") is not None else None,
            "holdoutBrierScore": round(float(row["brier_score"]), 3),
            "bestBaselineBalancedAccuracy": round(max(baseline_scores) * 100, 1) if baseline_scores else None,
            "qualityGatePassed": bool((metrics.get("qualityGate") or {}).get("passed")),
            "tracking": tracking,
            "deepLearningExperiment": deep_summary,
            "createdAt": str(row["created_at"]),
        })
    configuration = mlflow_configuration()
    return {
        "symbol": normalized,
        "runs": runs,
        "count": len(runs),
        "trackedCount": sum(1 for run in runs if run["tracking"].get("status") == "logged"),
        "configuration": {
            "provider": "MLflow",
            "backend": configuration["backend"],
            "experimentName": configuration["experimentName"],
            "required": configuration["required"],
        },
        "generatedAt": utc_now(),
    }
