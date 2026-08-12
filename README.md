# FinTrack Market Intelligence

## Live Demo

**Open the deployed application:** [https://tausifalam6879.github.io/FinTrack_Market_Intelligence/](https://tausifalam6879.github.io/FinTrack_Market_Intelligence/)

A focused public financial-information dashboard extracted as a new, independent project from the larger FinTrack platform. It opens directly without login and concentrates on:

- latest available company and global-index quotes;
- dynamic company-name and ticker discovery across Yahoo Finance equities;
- a continuously moving quote rail that pauses on hover, keyboard focus or touch;
- INR exchange rates and a searchable currency directory;
- timestamped market headlines with theme filters and explicit publisher links;
- sector filtering and company research;
- configurable downside alerts with optional browser notifications and a 15-minute scan interval;
- a draggable sliding section selector for quick market, currency, news and intelligence navigation;
- transparent, experimental market analytics;
- next-session direction prediction with confidence-based `BULLISH`, `NEUTRAL` and `BEARISH` outcomes;
- walk-forward comparison of Logistic Regression, Random Forest and Histogram Gradient Boosting;
- a seeded PyTorch MLP comparator with early stopping and separate checkpoint lineage;
- visible validation metrics, feature importance and a session-by-session prediction audit;
- a hybrid agentic research backend grounded in read-only market, ML, historical, company, macro and document-RAG tools;
- company-document RAG with PDF page citations and official-source links.

> Market quotes can be delayed by the upstream exchange/provider. Every screen displays its data timestamp and never presents cached values as live.

The frontend uses a stale-while-revalidate startup flow. A fresh browser renders a packaged, timestamped verified snapshot immediately; an existing browser prefers its last successful response. The live API is requested in the background and replaces the visible values as soon as it responds, so a sleeping backend never leaves the dashboard blank. Use `python scripts/update_bundled_snapshot.py` while the local API is running to refresh the packaged release snapshot.

The downside monitor is deliberately rule-based and fast: it evaluates the verified percentage move against the user's chosen threshold without waiting for Gemini. Browser notifications require explicit permission, work while the site is open, and are deduplicated per quote timestamp. Alerts are risk signals, not automated sell instructions.

Company discovery is intentionally separate from the bounded home-page quote board. The public `GET /market/companies?q=...` endpoint searches equities by company name or ticker, while live price and predictive research are loaded only after the visitor selects a symbol. This keeps the site open and dynamic without issuing thousands of quote requests on every page load. If the discovery provider is unavailable, matching companies from FinTrack's verified board remain searchable.

## Predictive ML pipeline

The intelligence screen now contains a genuine predictive experiment rather than using Gemini to invent a forecast. Historical daily OHLCV data is transformed into seven lagged features: 1-session and 5-session returns, price-to-SMA-10 and price-to-SMA-20 ratios, 10-session volatility, volume change and RSI-14. The supervised target is whether the following trading session closes above the current session.

Three scikit-learn classifiers are trained and compared:

- Logistic Regression as the interpretable baseline;
- Random Forest for non-linear interactions;
- Histogram Gradient Boosting for a second non-linear candidate.

Evaluation preserves chronology. An expanding-window `TimeSeriesSplit` with a one-session gap tests each model on future rows without random shuffling or leaking future prices into training. The winner is selected using balanced accuracy, ROC AUC and Brier score. Out-of-sample skill controls probability shrinkage toward 50%; only values above 58% or below 42% create a directional label, while uncertain output remains `NEUTRAL`.

The repository also contains a production-oriented offline path. `data_pipeline.py` validates and upserts arbitrary symbols into PostgreSQL (or a local SQLite development database). `offline_training.py` reserves a final untouched chronological holdout and purges the boundary row whose next-session target would otherwise overlap that holdout. It compares the selected model with majority, previous-session momentum and SMA-trend baselines, applies a quality gate, records the model run and writes a checksummed joblib artifact. Artifacts remain `candidate` or `rejected` until a separate trusted approval step promotes a qualified candidate.

## PyTorch deep-learning comparator

Every offline run also trains a small CPU PyTorch MLP (`7 -> 32 -> 16 -> 1`) as an explicitly experimental comparator. Its scaler is fitted only on the earliest fit window. A one-session purge gap separates fit from chronological validation, validation loss controls early stopping, the best `state_dict` checkpoint is restored, and the final holdout is used once for evaluation rather than hyperparameter tuning. Python, NumPy and PyTorch use a fixed seed and deterministic algorithms on the same runtime/platform.

The MLP checkpoint, architecture, seed, PyTorch version, early-stopping details, validation metrics and holdout metrics are logged into the same MLflow run as the selected classical candidate. The public experiment panel displays classical-vs-MLP balanced accuracy, ROC AUC, Brier score and the performance delta. This phase deliberately does not auto-promote or live-serve the MLP: a deep model must prove stable out-of-sample value before it can enter the trusted approval path.

Approved serving is controlled by `model_registry.py`, never by a public mutation endpoint. The CLI verifies the quality gate, trusted artifact directory, SHA-256 checksum, symbol, run ID and dataset version before atomically approving one model per symbol. The prediction API uses that artifact when available and otherwise keeps the current runtime experiment as an explicit fallback. Every result is written to the prediction audit database and older pending predictions are evaluated when a later market session arrives. `GET /market/model-status?symbol=...` exposes read-only provenance, holdout metrics and observed outcomes to the public monitoring panel.

## MLflow experiment tracking

Every new `offline_training.py` run is logged to MLflow with its symbol, selected estimator, chronological train/holdout periods, dataset version, feature count, walk-forward folds, untouched holdout metrics, naive-baseline metrics, quality-gate outcome, PyTorch comparator metrics, SHA-256 checksums, training summary, checksummed joblib artifact and MLP checkpoint. The default tracking backend is an ignored local SQLite MLflow database at `market-service/data/mlflow.db` with artifacts under `market-service/data/mlartifacts/`; this avoids MLflow's maintenance-only legacy filesystem tracking store. Set `MLFLOW_TRACKING_URI` and `MLFLOW_ARTIFACT_ROOT` for a shared tracking server/storage and `MLFLOW_EXPERIMENT_NAME` to control grouping. Tracking is failure-tolerant by default and can be made mandatory with `MLFLOW_REQUIRED=true`.

The public dashboard uses `GET /market/experiments?symbol=...` to compare registered training runs without exposing artifact filesystem paths or permitting model mutations. The MLflow UI can be started separately from `market-service` with:

```powershell
mlflow ui --backend-store-uri sqlite:///data/mlflow.db --host 127.0.0.1 --port 5000
```

## Company document RAG

`document_rag.py` ingests trusted local PDFs through a CLI rather than exposing a public upload endpoint. It preserves PDF page numbers, creates overlapping chunks, stores vectors and document metadata, retrieves evidence with cosine similarity and returns source/page citations. The dashboard never invents a document answer when no report is available.

For NSE equities, `official_documents.py` removes the fixed-company limitation. It accepts any valid Yahoo/NSE symbol ending in `.NS`, discovers the latest PDF from NSE Corporate Filings, validates that the download is an HTTPS PDF on the official NSE archive host, enforces a size limit, caches it, and indexes it on demand. The public endpoint accepts only a symbol—not a URL—so arbitrary remote downloads are not possible. Repeated requests reuse the indexed document.

Global exchanges do not share one universal annual-report API. For non-NSE companies and funds, FinTrack therefore creates a clearly labelled `market-profile` RAG source from current Yahoo Finance public evidence (identity, instrument type, exchange, business profile, available valuation/fund fields and observed one-year prices). This lightweight source is indexed automatically when an instrument is selected. It never claims to be an audited annual report, never invents missing fields, and links back to the cited provider page. Indices do not show company-document RAG because an index is not a reporting company.

Plain US tickers can additionally use the latest official SEC Form 10-K. Set `SEC_USER_AGENT` to a descriptive application name plus a monitored contact email as required by SEC fair-access guidance. FinTrack uses the official ticker/CIK directory, the filer submissions API and a validated `sec.gov/Archives/edgar/data/...` primary-document URL. Requests are serialized, rate-limited, size-limited and cached. If SEC throttles or blocks a request, preparation automatically falls back to the cited market-profile source instead of leaving RAG blank.

The default `local-hashing-v1` vectorizer is deterministic and works without an API key. For semantic retrieval, ingestion can use Google's text embedding model `gemini-embedding-001`; query embeddings then use the same provider. LLM answer synthesis is opt-in through `RAG_USE_LLM=true` and is accepted only when it contains citations from the retrieved evidence. Otherwise FinTrack returns the retrieved page excerpts directly.

```powershell
python document_rag.py `
  --symbol RELIANCE.NS `
  --pdf data/source-documents/RIL-Integrated-Annual-Report-2024-25.pdf `
  --title "Reliance Integrated Annual Report 2024-25" `
  --document-type annual-report `
  --reporting-period "FY 2024-25" `
  --source-url "https://www.ril.com/ar2024-25/pdf/RIL-Integrated-Annual-Report-2024-25.pdf"
```

Batch preparation is also dynamic; the symbols are supplied at runtime:

```powershell
python official_documents.py --symbols INFY.NS TCS.NS HDFCBANK.NS ICICIBANK.NS
```

Public read-only routes:

```text
GET  /market/documents?symbol=RELIANCE.NS
GET  /market/documents/discover?symbol=INFY.NS
POST /market/documents/prepare
POST /market/documents/ask
```

The UI exposes the selected model, candidate comparison, walk-forward folds, balanced accuracy, precision/recall/F1, ROC AUC, Brier score, diagnostic permutation importance and a runtime prediction audit. When explicitly configured, Gemini receives verified tool results and explains them in plain language; Gemini is not the component that generates the numerical prediction. With no `LLM_PROVIDER`, the agent immediately uses deterministic evidence synthesis instead of waiting for an unconfigured local service. Gemini and Ollama are therefore optional and are not required for the predictive pipeline.

## Hybrid agentic research flow

The public `/market/agent` route uses a `plan -> execute -> synthesize` workflow. `agent_orchestrator.py` deterministically classifies the question and selects only the required read-only tools: current quote, ML/technical outlook, requested historical session, company fundamentals, indexed document RAG, recent headlines, macro factors, market breadth or global indices. The LLM does not choose tools and no mutation-capable tool is exposed, so prompt text cannot approve a model, upload a document or alter project data.

For annual-report, filing, debt, revenue or citation questions, the agent retrieves existing indexed chunks and requires exact `[S# p.#]` citations in any accepted generated answer. When there is no indexed evidence, the trace reports `no_evidence` and the deterministic fallback refuses to invent a filing claim. The API returns `agentPlan`, `toolTrace`, `evidenceSources` and `citations`; the chat UI exposes these behind an expandable evidence trace so an interviewer or user can audit why each tool ran and what it returned.

This remains an educational next-session probability experiment, not a guaranteed return, target price or buy/sell recommendation. Feature importance describes model dependency and does not prove market causality.

## Project structure

```text
frontend/        React + Vite public website
market-service/  FastAPI API, persistence, data ingestion and offline ML training
scripts/         Release-snapshot maintenance utility
```

## Run locally

### Production-style Docker stack

`compose.yaml` starts three isolated services: the non-root FastAPI runtime, PostgreSQL 17 and an MLflow tracking server. PostgreSQL, API and MLflow ports bind to `127.0.0.1` by default instead of being exposed to the local network. Copy `compose.env.example` to `.env`, replace the development password/contact values, and then run:

```powershell
docker compose up --build
```

The stack exposes:

- dashboard API: `http://127.0.0.1:8002`;
- API readiness: `http://127.0.0.1:8002/health/ready`;
- MLflow UI: `http://127.0.0.1:5000`;
- PostgreSQL: `127.0.0.1:5433` for optional local inspection.

Named Docker volumes persist PostgreSQL rows, API data, model artifacts and MLflow runs. `docker compose down` stops the services without deleting those volumes. Do not use `docker compose down --volumes` unless the local persisted project data should intentionally be removed.

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

## Runtime and training dependency separation

The deployed API image installs only `requirements-runtime.txt`. PyTorch and MLflow are intentionally excluded from the request-serving image because live endpoints load approved artifacts and read experiment metadata rather than training models. `requirements-training.txt` adds the CPU PyTorch and MLflow toolchain for offline training/CI, while `requirements.txt` remains a convenience entry point for the complete development environment. This keeps the production API image smaller and reduces cold-start/memory pressure without removing reproducible training code from the repository.

The runtime container runs as the unprivileged `fintrack` user, writes only to declared data/artifact locations and includes a Docker `HEALTHCHECK` against `/health/ready`.

## Health and readiness

- `GET /health` and `GET /health/live` confirm that the API process is alive. They do not call Yahoo Finance or an LLM.
- `GET /health/ready` performs a minimal database query and returns HTTP `503` when the required persistence layer is unavailable.
- Model artifact storage, optional LLM configuration and external training-toolchain availability are reported separately and do not incorrectly restart the public API during an upstream-provider outage.
- Responses expose environment/version/short commit metadata but never return database URLs, passwords, API keys or local artifact paths.

Render now uses `/health/ready` as its deployment health check.

## Continuous integration

`.github/workflows/ci.yml` runs on pull requests and `main` pushes. It:

1. installs the reproducible Python 3.12 training environment and runs all backend tests;
2. creates the complete schema against a real PostgreSQL 17 service and verifies readiness;
3. installs frontend dependencies from `package-lock.json` and produces a Vite production build;
4. builds the lightweight API Docker image, starts it, checks liveness/readiness and verifies that it runs as the non-root `fintrack` user.

The GitHub Pages deployment workflow uses the current supported major versions of the official checkout/setup actions rather than nonexistent `v7` tags. In repository branch protection, make `backend-tests`, `frontend-build` and `api-container` required checks before merging to `main`.

Open `http://localhost:5173`.

The frontend uses this project's local market service by default. For a deployed API, create `frontend/.env.local` before building:

```env
VITE_MARKET_API_BASE_URL=https://your-market-api.example.com
```

### Market service

```powershell
cd market-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --reload --port 8002
```

Gemini is optional. Without it, the research agent returns a deterministic answer based on the same verified tools.

```env
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.5-flash-lite
GEMINI_API_KEY=your-new-server-side-key
```

Never place API keys in the React app or commit them to Git.

### Persistent market data and offline training

Local development uses an ignored SQLite database. The same repository class switches to PostgreSQL whenever `DATABASE_URL` begins with `postgresql://`.

```powershell
cd market-service

# Any Yahoo Finance symbols may be supplied directly or through --symbols-file.
python data_pipeline.py --symbols "^NSEI" RELIANCE.NS INFY.NS --period 2y

# Train only from persisted, validated bars; no provider call occurs here.
python offline_training.py --symbols "^NSEI" RELIANCE.NS

# Approve only the exact candidate run that passed the quality gate.
python model_registry.py --approve YOUR_MODEL_RUN_ID
```

For PostgreSQL:

```env
DATABASE_URL=postgresql://user:password@host:5432/fintrack
MODEL_ARTIFACT_DIR=artifacts
```

The persistence schema contains public-company metadata, OHLCV bars, ingestion audits, model runs and prediction outcomes. It does not store user accounts or personal financial data.

## Deployment

For a public demo, keep this focused application in its own GitHub repository. Deploy `frontend/` to GitHub Pages and deploy `market-service/` as a separate Render web service using the included `render.yaml`. A new Render account is not required, but the Python API needs its own service because GitHub Pages can host only the static frontend.

The public frontend workflow builds against:

```text
https://fintrack-market-intelligence-api.onrender.com
```

GitHub Pages publishes the frontend from `.github/workflows/deploy-pages.yml`. The bundled verified snapshot renders immediately, then the page replaces it with the newest Render response in the background.

## Scope

This project deliberately excludes authentication, personal expenses, loans, payments and user profiles. Its database is limited to public market datasets, ingestion/model audit records and prediction outcomes; it does not collect personal finance data.
