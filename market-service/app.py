from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from market_intelligence import router as market_router


app = FastAPI(
    title="FinTrack Market Intelligence API",
    version="1.0.0",
    description="Public market quotes, INR currency rates, transparent analytics and a grounded research agent.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(market_router)


@app.get("/")
def root():
    return {
        "service": "FinTrack Market Intelligence API",
        "status": "online",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "fintrack-market-intelligence",
        "authentication": "not-required",
    }

