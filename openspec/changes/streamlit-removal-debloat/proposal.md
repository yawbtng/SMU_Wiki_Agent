## Why

The operator product is React/FastAPI (`./start.sh`). Streamlit (`app.py`, 4,663 lines) and `ui_*` modules (~800 lines) are dead weight: duplicate navigation, duplicate scrape/wiki flows, and AST tests that gate CI on legacy UI structure. The repo also carries ~39 root import shims and duplicated policy/orchestration code. Operators and agents should run through Pi skills + thin runtime, not a second monolith.

## What Changes

### Phase 1 — Remove Streamlit (this change)
- Delete `app.py` and all `ui_*.py` Streamlit modules.
- Move shared constants (`WORKFLOW_TABS`) to `app/navigation.py`.
- Drop `streamlit` / `streamlit-autorefresh` from default requirements.
- Remove or skip Streamlit AST UI tests; keep `tests/test_webapp_api.py` as primary gate.
- Update README: React-only quickstart.

### Phase 2 — Root shim removal
- Delete flat re-export modules under `src/scrape_planner/*.py`.
- Point webapp, scripts, and tests at subpackage paths (`wiki/`, `scrape/`, `runtime/`, `infra/`).

### Phase 3 — API de-bloat
- Split `webapp/api.py` (~1,754 lines) into routes + job launcher + artifact readers.
- Move URL approval LLM and discovery policy into Pi skills.

### Phase 4 — Legacy graph + duplicate orchestrators
- Deprecate `markdown_graph.py` / `graph_profile.py` (~1,430 lines).
- Collapse `wiki_ingestion_pipeline.py` into Pi `build_wiki.sh` path.

## Capabilities

### New Capabilities
- `react-only-operator`: Single UI surface; no Streamlit entrypoints in default install.

### Modified Capabilities
- `stepper-workflow`: Status read models only; no Streamlit stepper UI.

## Impact

- **Removed:** `app.py`, `ui_*.py`, ~12 Streamlit test files, streamlit deps.
- **Kept:** `webapp/`, `frontend/`, Pi skills, scrape worker, index engine, MCP.
- **Non-goals (later changes):** Splitting `llm_wiki_index.py`; full Pi skill migration for discovery.

## Success Criteria

- `./scripts/verify-webapp.sh` passes.
- `pytest` default run excludes legacy Streamlit tests and passes.
- No `import streamlit` in `src/scrape_planner/`.
- README documents React/FastAPI only.
