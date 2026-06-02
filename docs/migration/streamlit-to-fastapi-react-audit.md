# Streamlit to FastAPI/React migration audit

## Decision

Replace the Streamlit shell with a FastAPI API plus React/Vite frontend. Keep Streamlit as a temporary parity reference only.

## Why migrate

Streamlit reruns the whole script and is brittle for this project now that the app must show live scrape runs, wiki-agent/tmux state, JSONL event tails, index progress, and stale-process detection. The replacement must update small UI regions incrementally.

## Reusable code

The following modules are backend/domain code and should be reused directly instead of reimplemented in the frontend:

- `src/scrape_planner/app/artifact_contracts.py` — typed app/workspace/status contracts.
- `src/scrape_planner/app/repositories.py` — app state, site artifacts, run status, raw-source rows, wiki/index/MCP status read models.
- `src/scrape_planner/run_persistence.py` — durable run status/events/pages readers and writers.
- `src/scrape_planner/state.py` — Redis/memory live run-state store for scrape workers.
- `src/scrape_planner/stepper_status.py` — raw-source, wiki, embedding, MCP status summaries.
- `src/scrape_planner/ui_scrape_realtime.py` — pure helpers for scraped markdown preview and run summaries.
- `src/scrape_planner/ui_operator_status.py` — pure operator status aggregation.
- `src/scrape_planner/sitemap_discovery.py`, `scrape_worker.py`, `manual_url_pipeline.py`, `pdf_ingest.py`, `llm_wiki_index.py`, `wiki_ingestion_pipeline.py` — long-running operations to expose as job endpoints.
- `src/scrape_planner/tmux_runner.py` and `scripts/wiki-ralph-orchestrator.sh` — existing process-control boundary for wiki/Ralph jobs.

## Functionality map

Legacy Streamlit tabs from `WORKFLOW_TABS`:

1. Overview — now backed by `GET /api/sites/{site_id}/overview` plus SSE.
2. Sources — now backed by `GET /api/sites/{site_id}/sources`.
3. Runs — now backed by `GET /api/sites/{site_id}/runs` and `GET /api/sites/{site_id}/runs/{run_id}`.
4. Documents — shell placeholder; port markdown/PDF browser next.
5. Wiki — now backed by `GET /api/sites/{site_id}/wiki/agent` and `GET /api/sites/{site_id}/wiki/pages`.
6. Embeddings — included in overview snapshot as `embeddings`.
7. Metrics — shell placeholder; port `run_analytics.py` charts next.
8. Settings — now backed by `GET/PUT /api/app-state`.

## Realtime design

Initial implementation uses Server-Sent Events:

- `GET /api/stream/sites/{site_id}` streams site overview changes every second.
- Payload includes raw source status, wiki status, embedding status, MCP status, and wiki-agent state.
- Backend marks `agent.stale_running = true` when status files say running but the recorded tmux session is missing.

SSE is simpler and more efficient than WebSockets for the current one-way status/event stream. Use WebSockets later only for interactive terminal control or bidirectional agent sessions.

## New files in this worktree

- `src/scrape_planner/webapp/api.py` — FastAPI app and SSE stream.
- `frontend/` — React/Vite/TypeScript UI shell.
- `scripts/run-webapp.sh` — backend dev runner.
- `scripts/verify-webapp.sh` — py_compile + API pytest + frontend build.
- `tests/test_webapp_api.py` — health, sites, overview, wiki/agent, SSE, stale_running.

## Dev startup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export SCRAPE_PLANNER_DATA_ROOT=/path/to/ultra-fast-rag/data   # optional; defaults to ./data
./scripts/run-webapp.sh                                         # API on :8000

cd frontend && npm install && npm run dev                         # UI on :5173, proxies /api
```

Verification:

```bash
SCRAPE_PLANNER_DATA_ROOT=/path/to/ultra-fast-rag/data ./scripts/verify-webapp.sh
```

## Next high-value ports

1. Add action endpoints to start/stop scrape, wiki build, indexing, and wiki agent jobs.
2. Port run event/page tables with virtualized rendering for large runs.
3. Port wiki markdown browser with server-side search and frontmatter extraction.
4. Port metrics charts from `run_analytics.py` to API data endpoints + frontend charting.
5. Add tests around API payloads using temp site fixtures.
