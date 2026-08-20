# FinTrack Market Intelligence — interview and viva preparation

## 30-second introduction

“FinTrack Market Intelligence ek public, no-login financial research dashboard hai. User kisi bhi supported company ya index ko search karke price evidence, technical indicators, historical risk, company fundamentals, news, probabilistic next-session ML outlook aur official-report RAG dekh sakta hai. React frontend ke peeche optional Spring Boot public gateway aur Python FastAPI data/ML service hai. Predictions scikit-learn se banti hain; Gemini sirf verified evidence ko simple language mein explain karta hai. PostgreSQL production persistence, MLflow experiments, model registry, drift monitoring aur prediction outcome audit project ko notebook demo ke badle end-to-end ML system banate hain.”

## 2-minute explanation

1. **Problem:** Market data alag-alag pages par hota hai aur prediction websites uncertainty/source/timestamp clear nahi karti. FinTrack evidence, source, timestamp and limitations ek dashboard mein rakhta hai.
2. **Frontend:** React sections—Market Pulse, INR Currency Desk, Market News, Intelligence & MLOps. No login; saved comparison list only browser `localStorage` mein rehti hai.
3. **Java boundary:** Spring Boot WebFlux route validation, correlation ID, timeout/retry, circuit breaker, metrics and parallel multi-symbol orchestration handle karta hai.
4. **Python boundary:** FastAPI yfinance/provider data leta hai; Pandas/NumPy clean/features banate hain; scikit-learn time-aware model evaluate/infer karta hai.
5. **Persistence:** PostgreSQL market bars, runs, predictions/outcomes, drift and RAG documents persist karta hai. SQLite local/demo fallback hai.
6. **ML discipline:** Random shuffle nahi; walk-forward validation plus untouched chronological holdout, naive baselines, balanced accuracy, ROC-AUC and Brier score use hote hain. Weak model auto-promote nahi hota.
7. **AI/RAG:** Official NSE/SEC reports page-aware chunks mein index hote hain. Gemini ko only selected verified tool evidence milta hai. Unsupported answer deterministic fallback se replace hota hai.
8. **Operations:** Readiness, schema version, database durability, API latency/error rate, LLM fallback, model artifact, drift and prediction outcomes visible hain.

## Technology revision map

| Technology | Project mein kaam | Interview revision |
|---|---|---|
| Java 21 | Strongly typed gateway code | records, collections, exceptions, concurrency basics |
| Spring Boot WebFlux | Public API boundary and non-blocking WebClient | controller/service/config, Reactor `Mono`/`Flux`, CORS |
| WebClient | FastAPI calls and bounded parallel comparison | timeout, retry, error mapping, backpressure |
| Micrometer/Actuator | Gateway counters, timers and health | metric tags, health vs readiness |
| Python 3.12 | Data, ML, RAG and operations service | typing, exceptions, context managers, concurrency |
| FastAPI/Pydantic | Validated JSON APIs | routers, request models, middleware, HTTP errors |
| Pandas | OHLCV cleaning, alignment and features | DataFrame/index, rolling window, missing values |
| NumPy | Numeric arrays/statistics | vectorization, percentiles, NaN/finite handling |
| yfinance/provider APIs | Market prices, profile and headline metadata | ticker formats, delays, provider failure |
| scikit-learn | Pipeline and candidate classifiers | scaling, leakage, class metrics, calibration |
| PyTorch | MLP comparison experiment | tensor, layer, loss, optimizer, early stopping |
| MLflow | Experiment/run/artifact tracking | params vs metrics vs artifacts, reproducibility |
| PostgreSQL | Durable bars/runs/predictions/drift/RAG | keys, indexes, transactions, migrations |
| SQLite | Simple local/demo persistence | file DB limitations, write concurrency, redeploy loss |
| React | Section UI, state, dynamic search/comparison | components, hooks, controlled forms, effects |
| Vite | Dev server and optimized production build | environment variables and static assets |
| Playwright | Real desktop/mobile end-to-end tests | locators, route mocking, traces, CI browser install |
| Docker/Compose | Reproducible API/gateway/Postgres/MLflow | images, containers, networks, volumes, healthchecks |
| GitHub Actions/Pages | CI and static frontend deployment | jobs, dependencies, secrets, artifacts |
| Render | API/gateway containers and environment secrets | health check, cold start, managed database choice |
| Gemini | Concise grounded explanation | prompt context, grounding validation, fallback |
| RAG | Official report Q&A with page citations | chunk, retrieve, rank, context, generate, cite |

## Important terms in simple language

- **OHLCV:** Open, High, Low, Close and Volume—ek trading session ka raw price evidence.
- **Feature:** Model ko diya calculated input, jaise return, moving average difference, RSI or volatility.
- **Target/label:** Model jis outcome ko learn karta hai—FinTrack mein next trading session up/down.
- **Data leakage:** Future information galti se training inputs mein aa jana. Time-ordered splits ise prevent karte hain.
- **Walk-forward validation:** Purane data par train, uske baad ke data par validate; window time ke saath aage badhti hai.
- **Holdout:** Final untouched recent period, model selection ke dauran use nahi hota.
- **Balanced accuracy:** Up and down classes ki recall ka average; unequal class counts mein plain accuracy se fairer.
- **ROC-AUC:** Random positive-negative pair ko correct order dene ki model ability; 0.5 random ke aas-paas.
- **Brier score:** Probability aur actual 0/1 outcome ka mean squared error; lower better.
- **Calibration:** 60% predictions long run mein lagbhag 60% true hoti hain ya nahi.
- **RSI:** Recent gains/losses se momentum measure; >70 overbought and <30 oversold rule of thumb, guarantee nahi.
- **Volatility:** Returns kitne spread hain; direction nahi batati.
- **VaR:** Historical distribution se observed one-day loss threshold; extreme future loss guarantee/cap nahi.
- **Drawdown:** Previous peak se sabse bada observed fall.
- **Beta:** Benchmark move ke relation mein asset sensitivity; causation nahi.
- **RAG:** Pehle relevant document text retrieve, phir LLM supplied evidence se answer banata hai.
- **Embedding/vector search:** Text ko numeric representation banakar meaning-similar chunks retrieve karna.
- **Drift/PSI:** Recent feature distribution training reference se kitni badli.
- **Artifact:** Trained model file plus metadata/checksum.
- **Circuit breaker:** Repeated upstream failure par temporary calls rokta hai, recovery ke baad try karta hai.
- **Correlation ID:** Ek request ko frontend/gateway/backend logs mein trace karne ka non-personal identifier.
- **P95 latency:** 95% measured requests is duration se fast/equal; slow tail ko show karta hai.

## Why both Spring Boot and FastAPI?

Good answer:

“Maine Spring Boot sirf resume keyword ke liye nahi rakha. Java service public boundary concerns own karti hai—allowlisting, validation, CORS, request IDs, resilience, Micrometer and multi-company orchestration. FastAPI Python ecosystem concerns own karta hai—Pandas/NumPy features, scikit-learn/PyTorch, RAG and model artifacts. Agar pura application only FastAPI hota to technically possible tha, but separation independent scaling and clear ownership deta hai. Simple deployment mein UI direct-compatible FastAPI contract use kar sakti hai; full production mode mein same contract Spring gateway se serve hota hai.”

## Why REST API alone is not enough for ML?

REST transport hai; model logic nahi. External price API raw/provider data deta hai. FinTrack ko chronological cleaning, feature engineering, validation, calibrated probabilities, artifact approval, outcome evaluation and drift monitoring karna padta hai. Ye Python ML service ka justified role hai.

## Why no login?

Project public educational research tool hai, personalized portfolio/advice product nahi. Login hataane se personal-data/security scope kam hota hai. Saved research list browser-local hai; server user identity ya personal holdings store nahi karta.

## Database explanation

- `companies` and `market_bars` form the reusable data foundation.
- `model_runs` stores training/holdout/quality evidence, not only a model filename.
- `predictions` stores served probability then later actual direction/correctness.
- `prediction_features` plus `model_feature_baselines` support drift and explanation.
- `document_sources` and `document_chunks` support page-cited RAG.
- Foreign keys and one transaction protect related data.
- `schema_migrations` makes deploy upgrades repeatable.
- PostgreSQL is production choice because multiple service/workflow processes need durable shared storage; SQLite remains a lightweight local/demo option.

## ML pipeline explanation

1. Fetch and validate chronological OHLCV.
2. Build only past/current-session features.
3. Shift next-session direction to create label.
4. Compare Logistic Regression, Random Forest and Histogram Gradient Boosting with time-ordered folds.
5. Compare a PyTorch MLP experimentally.
6. Select by balanced evidence, not training accuracy.
7. Evaluate once on untouched final holdout and compare naive baselines.
8. Log params, metrics, dataset version, artifacts and checksums to MLflow.
9. Approve only through offline trusted CLI quality gate.
10. Serve artifact or clearly labeled runtime fallback.
11. Store prediction, evaluate after future session, monitor rolling quality and drift.

## RAG pipeline explanation

1. Accept symbol only—not arbitrary user URL.
2. Discover official NSE PDF or SEC 10-K; validate official HTTPS host/type/size.
3. Extract text page by page and make overlapping chunks.
4. Store source metadata and chunks.
5. Retrieve top relevant chunks for the question.
6. Give only retrieved text to Gemini/deterministic synthesis.
7. Require exact source/page citations; reject unsupported generated answer.

## Performance and reliability decisions

- Short-lived server caches reduce provider calls but timestamps/cached mode stay visible.
- Browser cache and bundled snapshot make the page useful during Render cold start.
- Multi-company UI sends one batch request instead of 2–4 browser requests.
- Spring uses maximum four parallel WebClient calls and caches batch results for five minutes.
- FastAPI direct fallback also uses bounded concurrency and returns partial results when possible.
- One retry is limited to read-only/transient failures; mutation/training endpoints are not publicly retryable.
- Timeout plus circuit breaker prevents cascading overload.

## Testing strategy

- Python unit/integration tests cover ML validation, data pipeline, persistence, RAG, monitoring and security.
- Real PostgreSQL service in CI verifies migrations, readiness and SQLite-to-PostgreSQL cutover.
- Spring tests cover validation, circuit breaker and cached parallel comparison.
- Playwright runs desktop and mobile flows: navigation, saved comparison, PDF action, grounded explanation, observability and overflow.
- Docker CI builds both services and checks non-root runtime/readiness.

## Challenges and honest answers

### Provider can be slow or unavailable

Use TTL caches, timeout, one safe retry, partial comparison, browser cache and visible timestamp/mode. Do not present stale data as live.

### Model accuracy is near random

Do not hide it. Shrink weak probabilities toward 50%, label quality, keep neutral thresholds, show baselines and block auto-promotion. Project demonstrates honest ML engineering, not fake guaranteed returns.

### Gemini key/quota/grounding fails

Numerical research remains independent. Deterministic verified tool answer is returned, failure type and fallback rate are visible, secret remains server-side.

### SQLite data disappears on redeploy

Readiness explicitly reports non-durable mode. Production cutover requires PostgreSQL, schema `4/4`, durability guard, verified migration manifest and backup/restore policy.

## Likely interview questions

1. Why did you use balanced accuracy instead of only accuracy?
2. How did you prevent time-series leakage?
3. What is the difference between walk-forward validation and final holdout?
4. Why does weak model probability move toward 50%?
5. How do you evaluate a stored prediction later?
6. What happens when Yahoo/provider or Render is down?
7. Why Spring WebFlux instead of blocking MVC?
8. Why does Spring not perform Pandas/ML work?
9. How are batch comparison partial failures represented?
10. How do retry and circuit breaker differ?
11. What data is cached and how do you disclose staleness?
12. How is the Gemini key protected?
13. How do you ensure a Gemini answer is grounded?
14. Why is RAG better than sending an entire annual report?
15. What is stored in PostgreSQL and why not only CSV files?
16. How do migrations and rollback work?
17. What would you scale first under high traffic?
18. Why is MLflow outside the normal user response path?
19. What is PSI and when would you retrain?
20. What are the project’s current limitations?

## Five-minute demo script

1. Open Market Pulse; point to source timestamp and delayed-data warning.
2. Open Market News; show image, source link and research action.
3. Open Intelligence; search a dynamic company rather than only presets.
4. Explain Probability Up/RSI using `? Explain` and show “Gemini grounded” or honest fallback.
5. Save two companies, open comparison and explain the one-request batch architecture.
6. Open Company Evidence; show fundamentals, benchmark/peer comparison and limitations.
7. Open Reports & RAG; ask a report question and point to source/page citation.
8. Open Model & MLOps; show validation, model candidates, prediction outcomes, drift and API/Gemini telemetry.
9. Use Print/Save PDF.
10. End with: “It is educational probabilistic research, not a guaranteed trading call.”

## Commands to remember

```powershell
# Backend tests
cd market-service
python -m unittest discover -q

# Spring gateway tests
cd gateway-service
.\mvnw.cmd --batch-mode verify

# Frontend build and real browser tests
cd frontend
npm ci
npx playwright install chromium
npm run build
npm run test:e2e

# Full local PostgreSQL architecture
docker compose up --build

# Read-only deployed smoke check
python scripts/production_smoke_test.py
python scripts/production_smoke_test.py --gateway https://fintrack-market-gateway.onrender.com

# After an explicitly approved PostgreSQL deployment
python scripts/production_smoke_test.py --require-postgres
```

## Final positioning

Use this title:

**Applied AI/ML Engineer with strong backend engineering, focused on financial-market intelligence systems.**

Avoid claiming guaranteed prediction accuracy, real-time exchange-grade data, personalized advice, fully durable production storage before PostgreSQL is actually connected, or a live Spring gateway before its deployed health URL passes.
