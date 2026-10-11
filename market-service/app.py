from contextlib import asynccontextmanager
import time
import os
from request_budget import RequestBudget

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from company_catalog import router as company_catalog_router
from document_rag import router as document_rag_router
from market_intelligence import router as market_router
from model_monitoring import router as model_monitoring_router
from runtime_health import initialize_runtime, liveness_report, readiness_report
from runtime_metrics import record_request
from research_backtest import router as research_backtest_router
from event_impact import router as event_impact_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_runtime()
    yield


app = FastAPI(
    title="FinTrack Market Intelligence API",
    version="1.1.0",
    description="Public market quotes, INR currency rates, transparent analytics and a grounded research agent.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-Id"],
    expose_headers=["X-Response-Time-Ms", "Retry-After", "X-FinTrack-Fetched-At"],
)

expensive_budget = RequestBudget(int(os.getenv("EXPENSIVE_REQUESTS_PER_MINUTE", "30")),
                                 int(os.getenv("EXPENSIVE_REQUESTS_CONCURRENT", "2")))


@app.middleware("http")
async def expensive_request_limit(request, call_next):
    expensive = request.method != "OPTIONS" and (
        request.url.path in {"/market/analysis", "/market/predictions", "/market/compare", "/market/agent",
                             "/market/backtest", "/market/event-impact"}
        or (request.method == "POST" and "document" in request.url.path)
    )
    if expensive and not expensive_budget.acquire():
        return JSONResponse({"detail": "Research capacity reached. Please retry after 60 seconds."},
                            status_code=429, headers={"Retry-After": "60", "Access-Control-Allow-Origin": "*"})
    try:
        return await call_next(request)
    finally:
        if expensive:
            expensive_budget.release()


@app.middleware("http")
async def aggregate_request_metrics(request, call_next):
    started = time.monotonic()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed_ms = round((time.monotonic() - started) * 1000, 2)
        record_request(request.url.path, status_code, elapsed_ms)
        if "response" in locals():
            response.headers["X-Response-Time-Ms"] = str(elapsed_ms)

app.include_router(market_router)
app.include_router(company_catalog_router)
app.include_router(model_monitoring_router)
app.include_router(document_rag_router)
app.include_router(research_backtest_router)
app.include_router(event_impact_router)


@app.get("/")
def root():
    return {
        "service": "FinTrack Market Intelligence API",
        "status": "online",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return liveness_report()


@app.get("/health/live")
def health_live():
    return liveness_report()


@app.get("/health/ready")
def health_ready():
    report = readiness_report()
    return JSONResponse(report, status_code=200 if report["status"] == "ready" else 503)
