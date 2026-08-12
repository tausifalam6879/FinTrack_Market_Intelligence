from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from company_catalog import router as company_catalog_router
from document_rag import router as document_rag_router
from market_intelligence import router as market_router
from model_monitoring import router as model_monitoring_router
from runtime_health import initialize_runtime, liveness_report, readiness_report


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
    allow_headers=["Content-Type"],
)

app.include_router(market_router)
app.include_router(company_catalog_router)
app.include_router(model_monitoring_router)
app.include_router(document_rag_router)


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
