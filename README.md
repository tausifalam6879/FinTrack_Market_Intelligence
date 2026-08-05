# FinTrack Market Intelligence

## Live Demo

**Open the deployed application:** [https://tausifalam6879.github.io/FinTrack_Market_Intelligence/](https://tausifalam6879.github.io/FinTrack_Market_Intelligence/)

A focused public financial-information dashboard extracted as a new, independent project from the larger FinTrack platform. It opens directly without login and concentrates on:

- latest available company and global-index quotes;
- INR exchange rates and a searchable currency directory;
- timestamped market headlines with theme filters and explicit publisher links;
- sector filtering and company research;
- configurable downside alerts with optional browser notifications and a 15-minute scan interval;
- a draggable sliding section selector for quick market, currency, news and intelligence navigation;
- transparent, experimental market analytics;
- next-session direction prediction with confidence-based `BULLISH`, `NEUTRAL` and `BEARISH` outcomes;
- walk-forward comparison of Logistic Regression, Random Forest and Histogram Gradient Boosting;
- visible validation metrics, feature importance and a session-by-session prediction audit;
- a Gemini-enabled agent grounded in the dashboard's verified market tools.

> Market quotes can be delayed by the upstream exchange/provider. Every screen displays its data timestamp and never presents cached values as live.

The frontend uses a stale-while-revalidate startup flow. A fresh browser renders a packaged, timestamped verified snapshot immediately; an existing browser prefers its last successful response. The live API is requested in the background and replaces the visible values as soon as it responds, so a sleeping backend never leaves the dashboard blank. Use `python scripts/update_bundled_snapshot.py` while the local API is running to refresh the packaged release snapshot.

The downside monitor is deliberately rule-based and fast: it evaluates the verified percentage move against the user's chosen threshold without waiting for Gemini. Browser notifications require explicit permission, work while the site is open, and are deduplicated per quote timestamp. Alerts are risk signals, not automated sell instructions.

## Predictive ML pipeline

The intelligence screen now contains a genuine predictive experiment rather than using Gemini to invent a forecast. Historical daily OHLCV data is transformed into seven lagged features: 1-session and 5-session returns, price-to-SMA-10 and price-to-SMA-20 ratios, 10-session volatility, volume change and RSI-14. The supervised target is whether the following trading session closes above the current session.

Three scikit-learn classifiers are trained and compared:

- Logistic Regression as the interpretable baseline;
- Random Forest for non-linear interactions;
- Histogram Gradient Boosting for a second non-linear candidate.

Evaluation preserves chronology. An expanding-window `TimeSeriesSplit` with a one-session gap tests each model on future rows without random shuffling or leaking future prices into training. The winner is selected using balanced accuracy, ROC AUC and Brier score. Out-of-sample skill controls probability shrinkage toward 50%; only values above 58% or below 42% create a directional label, while uncertain output remains `NEUTRAL`.

The UI exposes the selected model, candidate comparison, walk-forward folds, balanced accuracy, precision/recall/F1, ROC AUC, Brier score, diagnostic permutation importance and a runtime prediction audit. Gemini receives this verified model result and explains it in plain language; Gemini is not the component that generates the numerical prediction. Ollama is therefore optional and is not required for the predictive pipeline.

This remains an educational next-session probability experiment, not a guaranteed return, target price or buy/sell recommendation. Feature importance describes model dependency and does not prove market causality.

## Project structure

```text
frontend/        React + Vite public website
market-service/  FastAPI market, currency and grounded-agent API
scripts/         Release-snapshot maintenance utility
```

## Run locally

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

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

## Deployment

For a public demo, keep this focused application in its own GitHub repository. Deploy `frontend/` to GitHub Pages and deploy `market-service/` as a separate Render web service using the included `render.yaml`. A new Render account is not required, but the Python API needs its own service because GitHub Pages can host only the static frontend.

The public frontend workflow builds against:

```text
https://fintrack-market-intelligence-api.onrender.com
```

GitHub Pages publishes the frontend from `.github/workflows/deploy-pages.yml`. The bundled verified snapshot renders immediately, then the page replaces it with the newest Render response in the background.

## Scope

This project deliberately excludes authentication, personal expenses, loans, payments, profiles and databases. It can therefore be presented as a smaller MCA/minor-project proposal while the original full FinTrack project remains unchanged.
