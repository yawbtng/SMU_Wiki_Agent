# FastAPI + React Realtime App Shell

## Goal

Replace the Streamlit operator shell with a FastAPI backend and React/Vite frontend for normal day-to-day operation. Streamlit (`app.py`) remains a read-only parity reference until feature parity is reached.

## Product Direction

- **Primary UI stack:** FastAPI REST + SSE (initially) + React/Vite in the migration worktree at `ultra-fast-rag-webapp` (`migrate-fastapi-react` branch).
- **Backend/domain code:** Reuse modules under `src/scrape_planner/` in this repository; do not reimplement pipeline logic in the frontend.
- **Streamlit:** Do not add major new Streamlit UI for specs 002, 005, or future operator workflows unless explicitly for compatibility testing.

## Context

- Migration worktree: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag-webapp`
- FastAPI entrypoint: `src/scrape_planner/webapp/api.py`
- Frontend: `frontend/` (React/Vite/TypeScript)
- Dev runner: `scripts/run-webapp.sh`
- Migration audit: `docs/migration/streamlit-to-fastapi-react-audit.md` (in the webapp worktree)
- Data root: `SCRAPE_PLANNER_DATA_ROOT` (defaults to repo `data/`)

Reusable backend read models (this repo):

- `src/scrape_planner/app/repositories.py` — app state, site artifacts, status read models
- `src/scrape_planner/wiki/stepper_status.py` — raw/wiki/index/MCP status summaries
- `src/scrape_planner/runtime/run_persistence.py` — run status/events/pages persistence
- `src/scrape_planner/infra/tmux_runner.py` — process launch boundary

## Requirements

### API baseline

1. Expose health and site discovery endpoints:
   - `GET /api/health`
   - `GET /api/sites`
2. Expose site overview and wiki-agent status:
   - `GET /api/sites/{site_id}/overview`
   - `GET /api/sites/{site_id}/wiki/agent`
3. Stream incremental site status via SSE:
   - `GET /api/stream/sites/{site_id}`
   - Payload includes raw source, wiki, embedding, MCP, and wiki-agent state
4. Mark `agent.stale_running = true` when status files say `running` but the recorded tmux session is missing.

### Frontend baseline

5. React shell renders site list, overview cards, and wiki-agent status panel.
6. SSE subscription updates overview regions without full-page reload.
7. Frontend build (`npm run build`) passes in CI/local verification.

### Action endpoints (follow-on; may span specs 002/005)

8. REST action endpoints for Build Wiki, Update Wiki, start/stop Ralph orchestrator, and status recovery.
9. Job updates stream via SSE initially; reserve WebSockets for bidirectional terminal/agent controls.

### Documentation

10. Document dev startup commands and `SCRAPE_PLANNER_DATA_ROOT` usage in the webapp worktree README or migration docs.

## Acceptance Criteria

- [ ] `docs/planning/work-index.md` lists spec 006 and states FastAPI/React is the primary UI target.
- [ ] Specs 002 and 005 reference spec 006 instead of Streamlit as the primary implementation target.
- [ ] `GET /api/health` returns 200 with a JSON health payload.
- [ ] `GET /api/sites` lists sites under `SCRAPE_PLANNER_DATA_ROOT/sites/`.
- [ ] `GET /api/sites/{site_id}/overview` returns raw/wiki/embedding/MCP status for an existing site.
- [ ] `GET /api/sites/{site_id}/wiki/agent` returns wiki-agent run/tasks/events summary.
- [ ] `GET /api/stream/sites/{site_id}` emits valid SSE frames with site overview snapshots.
- [ ] Stale running wiki-agent status is surfaced when tmux session is absent.
- [ ] API tests cover health, sites, overview, wiki/agent, and SSE framing.
- [ ] `cd frontend && npm run build` succeeds.
- [ ] Dev startup and `SCRAPE_PLANNER_DATA_ROOT` are documented.
- [ ] Syntax check passes: `python -m py_compile src/scrape_planner/webapp/api.py`.

## Suggested Verification

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag-webapp
PYTHONPATH=. SCRAPE_PLANNER_DATA_ROOT=/path/to/ultra-fast-rag/data \
  .venv/bin/python -m py_compile src/scrape_planner/webapp/api.py
PYTHONPATH=. SCRAPE_PLANNER_DATA_ROOT=/path/to/ultra-fast-rag/data \
  .venv/bin/python -m pytest tests/test_webapp_api.py -q
cd frontend && npm run build
```

## Dependencies

- Specs 002 and 005 implement wiki/Pi SDK and Ralph orchestrator UI **in the webapp**, not in Streamlit, once this spec's baseline is stable.
- Spec 001 provides a known-good SMU wiki/index baseline for UI smoke checks.

## Status: TODO

<!-- NR_OF_TRIES: 0 -->
