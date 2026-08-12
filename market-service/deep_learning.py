"""Leakage-safe PyTorch comparator for the offline market training pipeline."""

from __future__ import annotations

import hashlib
from pathlib import Path
import random
from typing import Any, Dict, List

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from market_intelligence import _classification_metrics


def _selection_score(metrics: Dict[str, Any]) -> float:
    auc_component = metrics["rocAuc"] if metrics["rocAuc"] is not None else 0.50
    return float(
        metrics["balancedAccuracy"] * 0.55
        + auc_component * 0.30
        + (1 - metrics["brierScore"]) * 0.15
    )


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def train_pytorch_mlp_experiment(
    training: pd.DataFrame,
    holdout: pd.DataFrame,
    feature_columns: List[str],
    artifact_path: Path,
    *,
    seed: int = 42,
    validation_fraction: float = 0.20,
    max_epochs: int = 160,
    patience: int = 18,
    min_delta: float = 1e-4,
) -> Dict[str, Any]:
    """Train a deterministic CPU MLP without using the final holdout for tuning.

    The last part of ``training`` is used for early stopping. One row is purged
    between fit and validation because each row's label depends on the following
    market session. The caller already applies the same purge rule before the
    final holdout.
    """
    try:
        import torch
        from torch import nn
    except ImportError as error:
        raise RuntimeError(
            "PyTorch is not installed. Install market-service/requirements.txt before offline training."
        ) from error

    validation_rows = max(24, int(len(training) * validation_fraction))
    purge_gap_rows = 1
    fit_end = len(training) - validation_rows - purge_gap_rows
    if fit_end < 70:
        raise ValueError("PyTorch experiment needs at least 70 fit rows before validation.")

    fit = training.iloc[:fit_end].copy()
    validation = training.iloc[-validation_rows:].copy()
    if fit["target"].nunique() < 2 or validation.empty or holdout.empty:
        raise ValueError("PyTorch experiment needs two-class fit data and non-empty validation/holdout sets.")

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(1)

    scaler = StandardScaler()
    fit_x = scaler.fit_transform(fit[feature_columns]).astype(np.float32)
    validation_x = scaler.transform(validation[feature_columns]).astype(np.float32)
    holdout_x = scaler.transform(holdout[feature_columns]).astype(np.float32)
    fit_y = fit["target"].astype(np.float32).to_numpy()
    validation_y = validation["target"].astype(np.float32).to_numpy()
    holdout_y = holdout["target"].astype(int).to_numpy()

    class MarketDirectionMlp(nn.Module):
        def __init__(self, feature_count: int):
            super().__init__()
            self.network = nn.Sequential(
                nn.Linear(feature_count, 32),
                nn.ReLU(),
                nn.Dropout(0.10),
                nn.Linear(32, 16),
                nn.ReLU(),
                nn.Linear(16, 1),
            )

        def forward(self, features):
            return self.network(features).squeeze(-1)

    model = MarketDirectionMlp(len(feature_columns))
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.002, weight_decay=0.01)
    positive_count = float(fit_y.sum())
    negative_count = float(len(fit_y) - positive_count)
    positive_weight = negative_count / positive_count if positive_count > 0 else 1.0
    loss_function = nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor([positive_weight], dtype=torch.float32)
    )

    fit_tensor = torch.from_numpy(fit_x)
    fit_target = torch.from_numpy(fit_y)
    validation_tensor = torch.from_numpy(validation_x)
    validation_target = torch.from_numpy(validation_y)
    best_state = None
    best_validation_loss = float("inf")
    best_epoch = 0
    stale_epochs = 0
    epochs_trained = 0

    for epoch in range(1, max_epochs + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        fit_loss = loss_function(model(fit_tensor), fit_target)
        fit_loss.backward()
        optimizer.step()

        model.eval()
        with torch.no_grad():
            validation_loss = float(
                loss_function(model(validation_tensor), validation_target).item()
            )
        epochs_trained = epoch
        if validation_loss < best_validation_loss - min_delta:
            best_validation_loss = validation_loss
            best_epoch = epoch
            best_state = {
                name: value.detach().cpu().clone()
                for name, value in model.state_dict().items()
            }
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= patience:
                break

    if best_state is None:
        raise RuntimeError("PyTorch early stopping did not produce a checkpoint.")
    model.load_state_dict(best_state)
    model.eval()

    def evaluate(features: np.ndarray, targets: np.ndarray) -> Dict[str, Any]:
        with torch.no_grad():
            logits = model(torch.from_numpy(features))
            probabilities = torch.sigmoid(logits).numpy()
        predictions = (probabilities >= 0.50).astype(int)
        metrics = _classification_metrics(targets.astype(int), predictions, probabilities)
        metrics["selectionScore"] = _selection_score(metrics)
        return metrics

    validation_metrics = evaluate(validation_x, validation_y.astype(int))
    holdout_metrics = evaluate(holdout_x, holdout_y)
    artifact_path = Path(artifact_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "schemaVersion": 1,
        "modelName": "PyTorch MLP",
        "stateDict": best_state,
        "featureColumns": feature_columns,
        "architecture": {"hiddenLayers": [32, 16], "dropout": 0.10},
        "scaler": {
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(),
        },
        "seed": seed,
        "bestEpoch": best_epoch,
        "torchVersion": torch.__version__,
        "trustNotice": "Load only checkpoints created by this controlled FinTrack training pipeline.",
    }, artifact_path)

    return {
        "id": "pytorch_mlp",
        "name": "PyTorch MLP",
        "status": "experimental_not_served",
        "framework": "PyTorch",
        "frameworkVersion": torch.__version__,
        "device": "cpu",
        "seed": seed,
        "architecture": {"hiddenLayers": [32, 16], "dropout": 0.10},
        "dataSplit": {
            "fit": {
                "start": str(fit.index[0].date()),
                "end": str(fit.index[-1].date()),
                "rows": len(fit),
            },
            "purgeGapRows": purge_gap_rows,
            "validation": {
                "start": str(validation.index[0].date()),
                "end": str(validation.index[-1].date()),
                "rows": len(validation),
            },
            "untouchedHoldout": {
                "start": str(holdout.index[0].date()),
                "end": str(holdout.index[-1].date()),
                "rows": len(holdout),
            },
        },
        "earlyStopping": {
            "monitor": "validation_loss",
            "maxEpochs": max_epochs,
            "patience": patience,
            "epochsTrained": epochs_trained,
            "bestEpoch": best_epoch,
            "bestValidationLoss": best_validation_loss,
        },
        "validationMetrics": validation_metrics,
        "holdoutMetrics": holdout_metrics,
        "artifactSha256": _checksum(artifact_path),
        "servingPolicy": "Comparator only; it cannot replace an approved classical artifact automatically.",
    }
