"""Sanitized runtime health and readiness diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict

from persistence import Database


logger = logging.getLogger(__name__)
PROCESS_STARTED_AT = datetime.now(timezone.utc)
PROCESS_STARTED_MONOTONIC = time.monotonic()
DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"


def _environment_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _elapsed_ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 2)


def _build_metadata() -> Dict[str, str]:
    return {
        "version": os.getenv("APP_VERSION", "development"),
        "environment": os.getenv("APP_ENV", "development"),
        "commit": (os.getenv("GIT_COMMIT_SHA") or "unknown")[:12],
    }


def liveness_report() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "fintrack-market-intelligence",
        "authentication": "not-required",
        "startedAt": PROCESS_STARTED_AT.isoformat(),
        "uptimeSeconds": round(time.monotonic() - PROCESS_STARTED_MONOTONIC, 1),
        "build": _build_metadata(),
    }


def initialize_runtime() -> None:
    """Create required schema/directories before the API accepts traffic."""
    Database().initialize_schema()
    artifact_directory = Path(os.getenv("MODEL_ARTIFACT_DIR") or DEFAULT_ARTIFACT_DIR)
    artifact_directory.mkdir(parents=True, exist_ok=True)


def readiness_report() -> Dict[str, Any]:
    checks: Dict[str, Dict[str, Any]] = {}
    database = Database()
    durable_database_required = _environment_flag("REQUIRE_DURABLE_DATABASE")
    started = time.monotonic()
    try:
        database.ping()
        schema = database.schema_status()
        durable_database_ready = database.backend == "postgresql"
        if not schema["upToDate"]:
            database_status = "migration-required"
        elif durable_database_required and not durable_database_ready:
            database_status = "durability-required"
        else:
            database_status = "ready"
        checks["database"] = {
            "status": database_status,
            "required": True,
            "backend": database.backend,
            "latencyMs": _elapsed_ms(started),
            "schemaVersion": schema["currentVersion"],
            "expectedSchemaVersion": schema["expectedVersion"],
            "durableAcrossDeploys": durable_database_ready,
            "durabilityRequired": durable_database_required,
        }
    except Exception as error:
        logger.warning("Required database readiness check failed: %s", type(error).__name__)
        checks["database"] = {
            "status": "unavailable",
            "required": True,
            "backend": database.backend,
            "latencyMs": _elapsed_ms(started),
            "durabilityRequired": durable_database_required,
            "message": "Required database connectivity check failed.",
        }

    artifact_directory = Path(os.getenv("MODEL_ARTIFACT_DIR") or DEFAULT_ARTIFACT_DIR)
    artifact_ready = artifact_directory.is_dir() and os.access(artifact_directory, os.W_OK)
    checks["modelArtifactStorage"] = {
        "status": "ready" if artifact_ready else "unavailable",
        "required": False,
        "writable": artifact_ready,
    }
    configured_provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    checks["languageModel"] = {
        "status": "configured" if configured_provider else "deterministic-fallback",
        "required": False,
        "provider": configured_provider or "none",
    }
    if configured_provider in {"hybrid", "auto"}:
        checks["languageModel"].update({
            "primaryProvider": "gemini",
            "fallbackProvider": "ollama",
            "geminiTimeoutMs": max(1000, int(os.getenv("GEMINI_TIMEOUT_MS", "8000"))),
            "circuitCooldownSeconds": max(1, int(float(os.getenv("GEMINI_CIRCUIT_COOLDOWN_SECONDS", "10")))),
        })
    checks["trainingToolchain"] = {
        "status": "installed" if all(
            importlib.util.find_spec(package) is not None for package in ("torch", "mlflow")
        ) else "external-training-image",
        "required": False,
    }
    required_ready = all(
        check["status"] == "ready"
        for check in checks.values()
        if check.get("required")
    )
    return {
        "status": "ready" if required_ready else "not-ready",
        "service": "fintrack-market-intelligence",
        "authentication": "not-required",
        "checks": checks,
        "build": _build_metadata(),
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
