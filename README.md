# FinTrack Market Intelligence

A focused public financial-information dashboard extracted as a new, independent project from the larger FinTrack platform. It opens directly without login and concentrates on:

- latest available company and global-index quotes;
- INR exchange rates and a searchable currency directory;
- timestamped market headlines with theme filters and explicit publisher links;
- sector filtering and company research;
- configurable downside alerts with optional browser notifications and a 15-minute scan interval;
- a draggable sliding section selector for quick market, currency, news and intelligence navigation;
- transparent, experimental market analytics;
- a Gemini-enabled agent grounded in the dashboard's verified market tools.

> Market quotes can be delayed by the upstream exchange/provider. Every screen displays its data timestamp and never presents cached values as live.

The frontend uses a stale-while-revalidate startup flow. A fresh browser renders a packaged, timestamped verified snapshot immediately; an existing browser prefers its last successful response. The live API is requested in the background and replaces the visible values as soon as it responds, so a sleeping backend never leaves the dashboard blank. Use `python scripts/update_bundled_snapshot.py` while the local API is running to refresh the packaged release snapshot.

The downside monitor is deliberately rule-based and fast: it evaluates the verified percentage move against the user's chosen threshold without waiting for Gemini. Browser notifications require explicit permission, work while the site is open, and are deduplicated per quote timestamp. Alerts are risk signals, not automated sell instructions.

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

After Render provides the API URL, set `VITE_MARKET_API_BASE_URL` during the GitHub Pages build. Do not deploy until the local version has been reviewed.

## Scope

This project deliberately excludes authentication, personal expenses, loans, payments, profiles and databases. It can therefore be presented as a smaller MCA/minor-project proposal while the original full FinTrack project remains unchanged.
