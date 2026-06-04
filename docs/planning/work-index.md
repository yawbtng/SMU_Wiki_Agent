# Wiki Work Index

This file is the human-readable checkpoint for wiki build and quality work.

## UI Stack Decision (2026-05-28)

**Primary operator UI:** FastAPI + React/Vite in this repo (`frontend/`, `src/scrape_planner/webapp/`). See `specs/006-fastapi-react-realtime-app.md`.

**Legacy reference:** Streamlit was removed; see `docs/migration/streamlit-to-fastapi-react-audit.md` for parity notes only.

Future UI acceptance criteria for spec 002 target the webapp, not Streamlit.

## Stop Rule

Work should stop when every active spec in `specs/` has `## Status: COMPLETE` or `## Status: SUPERSEDED` and the latest verification pass is recorded in `docs/planning/work-index.md`, `docs/planning/history.md`, and `docs/planning/completion_log/`.

When no incomplete specs remain, output:

```xml
<promise>ALL_DONE</promise>
```

## Current Queue

| Priority | Spec | Status | Purpose |
| --- | --- | --- | --- |
| 006 | `specs/006-fastapi-react-realtime-app.md` | TODO | FastAPI REST + SSE + React shell replaces Streamlit for normal operation |
| 000 | `specs/000-automated-wiki-ingest-build-update.md` | TODO | Automate Ingest → Clean → Standardize → Lint → Build Wiki → Build Index → Verify |
| 001 | `specs/001-build-smu-llm-wiki.md` | TODO | Build and verify the SMU LLM Wiki |
| 002 | `specs/002-wire-wiki-ui-pi-sdk.md` | TODO | Wire Build/Update Wiki controls and LLM Wiki v2 activity to webapp realtime runtime |
| 003 | `specs/003-semantic-student-wiki-organization.md` | TODO | Concept-first, citation-backed semantic wiki organization with retrieval proof |
| 004 | `specs/004-agent-navigable-wiki-map.md` | TODO | Agent-traversable markdown graph, links, backlinks, manifest, MCP hints |
| 005 | `specs/005-wiki-ralph-orchestrator-ui.md` | SUPERSEDED | Removed Ralph loop strategy; use spec 002 LLM Wiki v2 compile path |

**Build order note:** Complete spec 006 baseline before deepening Streamlit UI work. Spec 001 is a lower-risk verification gate before spec 000 end-to-end pipeline work.

## Completion Ledger

| Date | Spec | Result | Verification | Notes |
| --- | --- | --- | --- | --- |
| _pending_ | _pending_ | _pending_ | _pending_ | _pending_ |

## Update Rules

After each completed spec, update the ledger:

1. Change that spec to `## Status: COMPLETE`.
2. Add a one-line entry to `docs/planning/history.md`.
3. Add a detailed timestamped note in `docs/planning/completion_log/`.
4. Update `docs/planning/work-index.md` queue/status table and completion ledger.
5. Continue to the next incomplete spec, or output `<promise>ALL_DONE</promise>` if no incomplete specs remain.
