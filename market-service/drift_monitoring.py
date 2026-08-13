"""Persistent feature-drift evidence and guarded retraining recommendations."""

from __future__ import annotations

from datetime import date, datetime, timezone
import math
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

import numpy as np
import pandas as pd

from persistence import Database, utc_now


MINIMUM_DRIFT_OBSERVATIONS = 20
PSI_WATCH_THRESHOLD = 0.10
PSI_HIGH_THRESHOLD = 0.25


def build_feature_baselines(
    training: pd.DataFrame, feature_columns: Iterable[str]
) -> List[Dict[str, Any]]:
    """Create finite, versionable PSI reference bins from training-only rows."""
    baselines: List[Dict[str, Any]] = []
    created_at = utc_now()
    for feature_name in feature_columns:
        values = pd.to_numeric(training[feature_name], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        ).dropna().to_numpy(dtype=float)
        if values.size == 0:
            continue
        quantiles = np.quantile(values, [0.10, 0.25, 0.50, 0.75, 0.90])
        edges = sorted({float(value) for value in quantiles if math.isfinite(float(value))})
        counts, _ = np.histogram(values, bins=[-np.inf, *edges, np.inf])
        proportions = (counts / max(int(counts.sum()), 1)).astype(float)
        baselines.append({
            "featureName": feature_name,
            "sampleCount": int(values.size),
            "mean": float(np.mean(values)),
            "std": float(np.std(values)),
            "binEdges": edges,
            "binProportions": proportions.tolist(),
            "createdAt": created_at,
        })
    return baselines


def _population_stability_index(
    values: List[float], edges: List[float], expected: List[float]
) -> float:
    counts, _ = np.histogram(np.asarray(values, dtype=float), bins=[-np.inf, *edges, np.inf])
    observed = counts / max(int(counts.sum()), 1)
    reference = np.asarray(expected, dtype=float)
    if len(reference) != len(observed):
        raise ValueError("Feature baseline bins do not match their stored proportions.")
    epsilon = 1e-6
    observed = np.clip(observed, epsilon, None)
    reference = np.clip(reference, epsilon, None)
    return float(np.sum((observed - reference) * np.log(observed / reference)))


def calculate_drift_snapshot(
    symbol: str,
    model_run_id: str,
    baselines: List[Dict[str, Any]],
    observations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    by_feature: Dict[str, List[float]] = {}
    prediction_ids = set()
    for row in observations:
        try:
            value = float(row["feature_value"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        prediction_ids.add(str(row["prediction_id"]))
        by_feature.setdefault(str(row["feature_name"]), []).append(value)

    recent_count = len(prediction_ids)
    feature_results = []
    for baseline in baselines:
        feature_name = str(baseline["feature_name"])
        values = by_feature.get(feature_name, [])
        result: Dict[str, Any] = {
            "feature": feature_name,
            "observations": len(values),
            "psi": None,
            "meanShiftStd": None,
            "status": "collecting_data",
        }
        if len(values) >= MINIMUM_DRIFT_OBSERVATIONS:
            edges = list(map(float, _decode_json_list(baseline.get("bin_edges_json"))))
            expected = list(map(float, _decode_json_list(baseline.get("bin_proportions_json"))))
            psi = _population_stability_index(values, edges, expected)
            baseline_std = abs(float(baseline.get("std_value") or 0.0))
            mean_shift = abs(float(np.mean(values)) - float(baseline.get("mean_value") or 0.0))
            status = "drifted" if psi >= PSI_HIGH_THRESHOLD else "watch" if psi >= PSI_WATCH_THRESHOLD else "stable"
            result.update({
                "psi": round(psi, 4),
                "meanShiftStd": round(mean_shift / baseline_std, 3) if baseline_std > 1e-12 else None,
                "status": status,
            })
        feature_results.append(result)

    available = [item for item in feature_results if item["psi"] is not None]
    high_count = sum(item["status"] == "drifted" for item in available)
    watch_count = sum(item["status"] == "watch" for item in available)
    if not baselines:
        status = "baseline_unavailable"
        recommendation = "Create a training-only feature baseline before evaluating drift."
    elif not available:
        status = "collecting_data"
        recommendation = f"Collect at least {MINIMUM_DRIFT_OBSERVATIONS} served observations before judging drift."
    else:
        material_count = max(2, math.ceil(len(available) * 0.30))
        max_psi = max(float(item["psi"]) for item in available)
        if high_count >= material_count or max_psi >= 0.50:
            status = "high"
            recommendation = "Review fresh data and run the offline training pipeline; do not auto-promote a replacement."
        elif high_count + watch_count >= material_count:
            status = "watch"
            recommendation = "Keep serving with closer monitoring while more outcomes accumulate."
        else:
            status = "stable"
            recommendation = "Feature distributions remain within the configured monitoring policy."

    psi_values = [float(item["psi"]) for item in available]
    return {
        "id": str(uuid4()),
        "symbol": symbol,
        "modelRunId": model_run_id,
        "evaluatedAt": utc_now(),
        "recentObservations": recent_count,
        "minimumObservations": MINIMUM_DRIFT_OBSERVATIONS,
        "meanPsi": round(float(np.mean(psi_values)), 4) if psi_values else None,
        "maxPsi": round(max(psi_values), 4) if psi_values else None,
        "status": status,
        "recommendation": recommendation,
        "thresholds": {
            "stableBelow": PSI_WATCH_THRESHOLD,
            "watchFrom": PSI_WATCH_THRESHOLD,
            "highFrom": PSI_HIGH_THRESHOLD,
            "policyNote": "PSI thresholds are configurable project policy, not a universal statistical law.",
        },
        "features": sorted(
            feature_results,
            key=lambda item: item["psi"] if item["psi"] is not None else -1,
            reverse=True,
        ),
    }


def _decode_json_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    import json
    try:
        decoded = json.loads(value)
        return decoded if isinstance(decoded, list) else []
    except (TypeError, ValueError):
        return []


def refresh_drift_snapshot(
    symbol: str, model_run_id: str, database: Optional[Database] = None
) -> Dict[str, Any]:
    repository = database or Database()
    repository.initialize_schema()
    observations = repository.prediction_feature_observations(symbol, model_run_id, 60)
    snapshot = calculate_drift_snapshot(
        symbol,
        model_run_id,
        repository.feature_baselines(model_run_id),
        observations,
    )
    latest_data_date = max(
        (str(row.get("model_data_date") or "") for row in observations),
        default="baseline",
    )
    snapshot["id"] = f"{model_run_id}:{latest_data_date or 'baseline'}"
    repository.save_drift_snapshot(snapshot)
    return snapshot


def rolling_prediction_quality(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    evaluated = [row for row in records if row.get("evaluated_at") is not None]
    windows = []
    for size in (10, 20, 30):
        sample = evaluated[:size]
        correct = sum(bool(row.get("correct")) for row in sample)
        brier_values = []
        for row in sample:
            actual_up = 1.0 if str(row.get("actual_direction")) == "UP" else 0.0
            probability = max(0.0, min(1.0, float(row.get("probability_up") or 0) / 100))
            brier_values.append((probability - actual_up) ** 2)
        windows.append({
            "window": size,
            "evaluated": len(sample),
            "accuracy": round(correct / len(sample) * 100, 1) if sample else None,
            "brierScore": round(float(np.mean(brier_values)), 3) if brier_values else None,
        })
    return {"evaluatedTotal": len(evaluated), "windows": windows}


def retraining_policy(
    approved_run: Optional[Dict[str, Any]],
    quality: Dict[str, Any],
    drift: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    thresholds = {
        "minimumPerformanceOutcomes": 20,
        "watchAccuracyBelowPercent": 50,
        "retrainAccuracyBelowPercent": 45,
        "watchArtifactDataAgeDays": 30,
        "retrainArtifactDataAgeDays": 90,
    }
    if not approved_run:
        return {
            "decision": "offline_training_required",
            "severity": "action",
            "automaticRetraining": False,
            "reasons": ["No approved offline artifact is available for this symbol."],
            "nextStep": "Ingest validated data, train offline, pass the final holdout gate, then approve explicitly.",
            "thresholds": thresholds,
        }

    # The final serving estimator is refit on the complete versioned dataset only
    # after the untouched holdout has been scored, so holdout_end is its data cutoff.
    artifact_data_end = date.fromisoformat(
        str(approved_run.get("holdout_end") or approved_run["training_end"])[:10]
    )
    artifact_data_age_days = max(0, (datetime.now(timezone.utc).date() - artifact_data_end).days)
    evaluated = int(quality.get("evaluatedTotal") or 0)
    window_20 = next((item for item in quality.get("windows", []) if item["window"] == 20), {})
    accuracy = window_20.get("accuracy")
    retrain_reasons: List[str] = []
    watch_reasons: List[str] = []

    if drift and drift.get("status") == "high":
        retrain_reasons.append("Multiple served feature distributions show high drift.")
    elif drift and drift.get("status") == "watch":
        watch_reasons.append("Served feature distributions crossed the watch threshold.")
    if evaluated >= thresholds["minimumPerformanceOutcomes"] and accuracy is not None:
        if accuracy < thresholds["retrainAccuracyBelowPercent"]:
            retrain_reasons.append(f"Rolling 20-outcome accuracy fell to {accuracy}%.")
        elif accuracy < thresholds["watchAccuracyBelowPercent"]:
            watch_reasons.append(f"Rolling 20-outcome accuracy is {accuracy}%.")
    if artifact_data_age_days >= thresholds["retrainArtifactDataAgeDays"]:
        retrain_reasons.append(f"Approved artifact data is {artifact_data_age_days} days old.")
    elif artifact_data_age_days >= thresholds["watchArtifactDataAgeDays"]:
        watch_reasons.append(f"Approved artifact data is {artifact_data_age_days} days old.")

    if retrain_reasons:
        decision, severity = "retrain_recommended", "action"
        reasons = retrain_reasons + watch_reasons
        next_step = "Run a new offline candidate experiment. Keep the current artifact until a replacement passes holdout checks and explicit approval."
    elif watch_reasons:
        decision, severity = "watch", "watch"
        reasons = watch_reasons
        next_step = "Keep serving and review the next monitoring snapshots; no replacement is promoted automatically."
    elif evaluated < thresholds["minimumPerformanceOutcomes"] or not drift or drift.get("status") in {"collecting_data", "baseline_unavailable"}:
        decision, severity = "collecting_evidence", "neutral"
        reasons = ["More evaluated outcomes or served feature observations are required for a reliable decision."]
        next_step = "Continue collecting predictions and next-session outcomes."
    else:
        decision, severity = "keep_serving", "healthy"
        reasons = ["Current performance, feature drift and training age remain inside policy limits."]
        next_step = "Continue normal monitoring."

    return {
        "decision": decision,
        "severity": severity,
        "automaticRetraining": False,
        "reasons": reasons,
        "nextStep": next_step,
        "artifactDataAgeDays": artifact_data_age_days,
        "thresholds": thresholds,
    }
