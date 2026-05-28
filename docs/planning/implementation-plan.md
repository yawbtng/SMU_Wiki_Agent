# Ralph Implementation Plan — 2026-05-28

Planning-mode artifact only. Do **not** treat any item below as implemented. Specs are worked in numeric priority order unless an explicit product-direction conflict must be resolved first.

## Current State

All tracked specs are incomplete. **UI target:** FastAPI + React in `ultra-fast-rag-webapp` (spec 006); Streamlit is parity reference only.

| Priority | Spec | Status | Primary Theme |
| --- | --- | --- | --- |
| 006 | `specs/006-fastapi-react-realtime-app.md` | TODO | FastAPI REST + SSE + React shell |
| 000 | `specs/000-automated-wiki-ingest-build-update.md` | TODO | End-to-end Ingest → Clean → Standardize → Lint → Build Wiki → Build Index → Verify |
| 001 | `specs/001-build-smu-llm-wiki.md` | TODO | Rebuild and verify SMU wiki/index artifacts |
| 002 | `specs/002-wire-wiki-ui-pi-sdk.md` | TODO | Wiki UI launches observable Pi SDK runtime (webapp) |
| 003 | `specs/003-semantic-student-wiki-organization.md` | TODO | Concept-first student wiki organization and retrieval proof |
| 004 | `specs/004-agent-navigable-wiki-map.md` | TODO | Agent-traversable markdown graph, links, backlinks, manifest, MCP hints |
| 005 | `specs/005-wiki-ralph-orchestrator-ui.md` | TODO | Tmux/Ralph wiki agent launch/status UI (webapp) |

Migration worktree:

```text
/Users/abhsheno/Desktop/Projects/ultra-fast-rag-webapp
branch: migrate-fastapi-react
```

## Priority 0 — Reconcile Target UI Architecture

### Task 0.1 — Add/update specs for FastAPI/React replacement

- Spec 006 added; specs 002/005 amended to target webapp.
- Work index states FastAPI/React is the primary UI stack.

### Task 0.2 — Stabilize new webapp baseline (webapp worktree)

Files:

- `ultra-fast-rag-webapp/src/scrape_planner/webapp/api.py`
- `ultra-fast-rag-webapp/frontend/`
- `ultra-fast-rag-webapp/docs/migration/streamlit-to-fastapi-react-audit.md`

Actions:

- Add API tests for `/api/health`, `/api/sites`, `/api/sites/{site}/overview`, `/api/sites/{site}/wiki/agent`, and SSE framing.
- Add frontend smoke/build check to the standard verification flow.
- Document dev startup commands and `SCRAPE_PLANNER_DATA_ROOT` usage.

Verification:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag-webapp
PYTHONPATH=. SCRAPE_PLANNER_DATA_ROOT=/path/to/ultra-fast-rag/data .venv/bin/python -m py_compile src/scrape_planner/webapp/api.py
cd frontend && npm run build
```

## Priority 1 — Fix Status Truth and Job Orchestration

### Task 1.1 — Make running status process-aware

- If report/status says `running`, verify tmux session/process exists.
- Surface `stale_running` or convert to `stale`/`exited` with a clear warning.

### Task 1.2 — Make orchestrator prompts non-interactive

- Remove confirmation-seeking language from unattended Ralph/wiki-agent prompts.

## Priority 2 — Complete Spec 001 (Verification Gate)

- Non-interactive wiki rebuild for `data/sites/www.smu.edu` without touching raw sources.
- Verify wiki/index artifacts and smoke query.

## Priority 3 — Spec 000 End-to-End Ingest Pipeline

- Extend `run_wiki_ingestion_pipeline(...)` as authoritative orchestrator.
- Add `wiki/reports/wiki-ingest-latest.json` with per-stage statuses.

## Priority 4 — Spec 004 Agent-Traversable Wiki Map

- Sitemap, navigation manifest, backlinks, graph edges, MCP `next_pages`.

## Priority 5 — Spec 003 Semantic Student Wiki Quality

- Taxonomy/wiki-plan driven generation; retrieval proof for Cox graduate questions.

## Priority 6 — Specs 002 and 005 UI Runtime Wiring (Webapp)

- REST action endpoints for Build Wiki, Update Wiki, Ralph orchestrator start/stop.
- SSE job updates; Streamlit parity reference only.

## Required Verification Matrix

```bash
python -m py_compile app.py src/scrape_planner/wiki/llm_wiki_builder.py src/scrape_planner/wiki/llm_wiki_index.py src/scrape_planner/wiki/wiki_ingestion_pipeline.py mcp_servers/llm_wiki_mcp.py
pytest -q tests/test_llm_wiki_builder.py tests/test_llm_wiki_index.py tests/test_wiki_ingestion_pipeline.py tests/test_wiki_ui.py tests/test_llm_wiki_mcp.py tests/test_wiki_graph_artifacts.py
```

Webapp (worktree):

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag-webapp/frontend && npm run build
```

## Completion Rules

1. Mark spec `## Status: COMPLETE` only after all acceptance criteria pass.
2. Update work index, history, and completion log.
3. Run compile/tests/smoke for changed paths.
4. Do not commit or push unless explicitly asked.
