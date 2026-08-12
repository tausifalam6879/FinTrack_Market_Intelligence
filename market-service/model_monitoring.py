"""Read-only public model provenance and prediction-monitoring endpoints."""

from fastapi import APIRouter, HTTPException, Query

from data_pipeline import normalize_symbol
from experiment_tracking import experiment_comparison
from model_registry import monitoring_snapshot


router = APIRouter(prefix="/market", tags=["Model Monitoring"])


@router.get("/model-status")
def get_model_status(symbol: str = Query(default="^NSEI", min_length=1, max_length=20)):
    try:
        return monitoring_snapshot(normalize_symbol(symbol))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Model monitoring is unavailable: {error}") from error


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
