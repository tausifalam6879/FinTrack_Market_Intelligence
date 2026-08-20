"""Read-only public model provenance and prediction-monitoring endpoints."""

from fastapi import APIRouter, HTTPException, Query

from data_pipeline import normalize_symbol
from data_operations import database_storage_snapshot, data_operations_snapshot
from experiment_tracking import experiment_comparison
from model_registry import monitoring_snapshot
from runtime_health import readiness_report
from runtime_metrics import telemetry_snapshot


router = APIRouter(prefix="/market", tags=["Model Monitoring"])


@router.get("/model-status")
def get_model_status(symbol: str = Query(default="^NSEI", min_length=1, max_length=20)):
    try:
        return monitoring_snapshot(normalize_symbol(symbol))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Model monitoring is unavailable: {error}") from error


@router.get("/model-drift")
def get_model_drift(symbol: str = Query(default="^NSEI", min_length=1, max_length=20)):
    """Expose the latest persisted drift evidence and guarded retraining decision."""
    try:
        snapshot = monitoring_snapshot(normalize_symbol(symbol))
        return {
            "symbol": snapshot["symbol"],
            "driftMonitoring": snapshot["driftMonitoring"],
            "retrainingPolicy": snapshot["retrainingPolicy"],
            "generatedAt": snapshot["generatedAt"],
        }
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Model drift monitoring is unavailable: {error}") from error


@router.get("/data-operations")
def get_data_operations(symbol: str = Query(default="^NSEI", min_length=1, max_length=20)):
    """Expose stored-history freshness without starting ingestion or training."""
    try:
        return data_operations_snapshot(normalize_symbol(symbol))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Data operations status is unavailable: {error}") from error


@router.get("/database-status")
def get_database_status():
    """Expose sanitized schema, durability and backup policy without credentials."""
    try:
        return database_storage_snapshot()
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Database status is unavailable: {error}") from error


@router.get("/operations-status")
def get_operations_status():
    """Expose privacy-safe aggregate API/LLM telemetry plus sanitized dependency readiness."""
    readiness = readiness_report()
    return {
        "status": readiness["status"],
        "telemetry": telemetry_snapshot(),
        "dependencies": readiness["checks"],
        "build": readiness["build"],
        "checkedAt": readiness["checkedAt"],
    }


@router.get("/experiments")
def get_experiments(
    symbol: str = Query(default="^NSEI", min_length=1, max_length=20),
    limit: int = Query(default=8, ge=1, le=20),
):
    try:
        return experiment_comparison(normalize_symbol(symbol), limit=limit)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Experiment comparison is unavailable: {error}") from error
