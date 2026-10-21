# Research answer performance

The agent selects evidence from the actual user question. The interface's section instructions are kept in the generator prompt but do not trigger extra tools merely because they mention a model or a report.

## Request paths

| Question | Evidence fetched |
| --- | --- |
| A fact from an indexed report | Company document passages and page citations |
| Company profile or basic fundamentals | Quote, profile and fundamental fields |
| Ownership or analyst estimate revisions | Profile plus the requested provider section |
| Financial statement trends | Profile plus financial statements |
| Probability, technical indicators or historical risk | Existing model and technical analysis |
| Combined or comprehensive question | The corresponding requested tools |

Report questions do not wait for price history, model loading, experimental training or an unrelated provider profile. Other independent evidence calls overlap in a pool of up to four workers. The synchronous research pipeline runs outside FastAPI's event loop so an agent waiting on a provider does not block unrelated requests.

The full `/market/company` endpoint retains all its sections. Partial company profiles use separate cache keys and cannot replace the full profile cache. Chat follow-ups retain their previous question for routing and document search.

## Retrieval and answer checks

Retrieved matrices and exact query vectors are cached for 120 seconds within each instance, with at most 64 entries and a 32 MiB estimated memory budget. The source manifest is checked on each retrieval. The key includes the database, symbol, embedding provider and report revision, so replacing or removing a report invalidates its cached index. Local TF-IDF fallback uses a sparse matrix and its own vector space.

Gemini embeddings have an 8-second transport timeout by default; override it with `RAG_EMBEDDING_TIMEOUT_MS` if needed. Existing local retrieval remains available after an embedding-provider failure. A document question with no relevant passages returns the evidence-unavailable response without waiting for generation.

Document answers retain page citations. Unknown citation tokens and substantive uncited lines trigger the cited-excerpt fallback. These checks reduce unsupported output but do not establish that every generated statement is semantically correct. The original report and reporting period remain the authority.

Generated document answers are not reused from the agent answer cache, ensuring retrieval checks the latest report manifest. Existing short-lived caching remains for accepted standalone market answers; conversations are excluded. Responses expose `timings.evidenceMs` and `timings.totalMs` for diagnosis, alongside existing request timing headers. A cache hit reports the current lookup duration.

## Verification

Run from `market-service` with the project environment:

```sh
python -m unittest test_agent_latency test_agent_orchestrator test_agent_analysis test_company_fundamentals test_document_rag -q
python -m unittest discover -p 'test_*.py' -q
```

The latency regressions verify overlapping independent calls, event-loop responsiveness, skipped unrelated endpoints, source revision invalidation, company isolation, follow-up retrieval and citation rejection. They use controlled providers; their runtimes are not a measurement of live Cloud Run latency. Real response time still depends on cold starts, database access and upstream data and language-model providers.

This change does not require a frontend rebuild or database migration. Deploy the updated `market-service` image to make the improvements available on the public site.

From an authenticated Cloud Shell checkout, run `bash scripts/deploy_agent_speed_fix.sh`. It builds a revision with no traffic, checks company and report questions for two symbols, and switches traffic only after those checks pass. It repeats the checks on the live URL and restores the previous revision traffic if live verification fails. It retains the existing service configuration and prints measured request durations. The script stops before a deployment if the account cannot describe the existing service.
