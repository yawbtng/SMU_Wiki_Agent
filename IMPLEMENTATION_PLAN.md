# Ralph Implementation Plan — 2026-05-28

Planning-mode artifact only. Do **not** treat any item below as implemented. This plan follows `.specify/memory/constitution.md`: specs are worked in numeric priority order unless an explicit product-direction conflict must be resolved first; no commits/pushes are allowed by default.

## Current State

All tracked specs are incomplete:

| Priority | Spec | Status | Primary Theme |
| --- | --- | --- | --- |
| 000 | `specs/000-automated-wiki-ingest-build-update.md` | TODO | End-to-end Ingest → Clean → Standardize → Lint → Build Wiki → Build Index → Verify |
| 001 | `specs/001-build-smu-llm-wiki.md` | TODO | Rebuild and verify SMU wiki/index artifacts |
| 002 | `specs/002-wire-wiki-ui-pi-sdk.md` | TODO | Normal wiki UI launches observable Pi SDK runtime |
| 003 | `specs/003-semantic-student-wiki-organization.md` | TODO | Concept-first student wiki organization and retrieval proof |
| 004 | `specs/004-agent-navigable-wiki-map.md` | TODO | Agent-traversable markdown graph, links, backlinks, manifest, MCP hints |
| 005 | `specs/005-wiki-ralph-orchestrator-ui.md` | TODO | Tmux/Ralph wiki agent launch/status UI |

Important product-direction update from this session: a new migration worktree exists at:

```text
/Users/abhsheno/Desktop/Projects/ultra-fast-rag-webapp
branch: migrate-fastapi-react
```

That worktree contains a first FastAPI + React/Vite shell with live SSE status endpoints. Existing specs still reference Streamlit heavily, so Ralph should first reconcile whether future UI acceptance criteria target the new webapp or legacy Streamlit.

## High-Signal Codebase Findings

Reusable backend/domain modules:

- `src/scrape_planner/app/artifact_contracts.py` — app/status contracts.
- `src/scrape_planner/app/repositories.py` — app state, artifact, and status read models.
- `src/scrape_planner/runtime/run_persistence.py` or legacy `src/scrape_planner/run_persistence.py` — run status/events/pages persistence.
- `src/scrape_planner/runtime/state.py` or legacy `src/scrape_planner/state.py` — live run-state store.
- `src/scrape_planner/wiki/stepper_status.py` or legacy `src/scrape_planner/stepper_status.py` — raw/wiki/index/MCP status summaries.
- `src/scrape_planner/wiki/wiki_ingestion_pipeline.py` — canonical end-to-end pipeline orchestrator to extend, not duplicate.
- `src/scrape_planner/wiki/llm_wiki_builder.py` — current wiki builder, semantic page generation, launcher boundary.
- `src/scrape_planner/wiki/llm_wiki_index.py` — wiki/source indexing and query behavior.
- `mcp_servers/llm_wiki_mcp.py` — MCP query/open-page surface for agent traversal.
- `src/scrape_planner/infra/tmux_runner.py` or legacy `src/scrape_planner/tmux_runner.py` — process launch boundary.

Known risks:

1. **Spec/UI drift:** specs 000/002/005 mention Streamlit and Pi SDK, while current product direction is FastAPI/React with responsive realtime updates.
2. **Runtime mismatch:** current wiki/Ralph orchestration can show stale `running` status when tmux has exited; status readers need process-aware reconciliation.
3. **Large working tree:** many pre-existing modifications/deletions/untracked package moves exist. Ralph must avoid broad rewrites and protect existing user changes.
4. **Semantic quality gap:** generated source pages exist, but completion requires concept-first, citation-backed, query-verified semantic/navigation pages.
5. **Agent loop prompt issue:** prior `wiki-ralph-www-smu-edu` run repeatedly asked for confirmation instead of executing; unattended orchestrator prompts must be non-interactive.

## Priority 0 — Reconcile Target UI Architecture Before More Streamlit Work

### Task 0.1 — Add/update specs for FastAPI/React replacement ✅ (branch `feat/fastapi-react-ui-reconciliation`)

**Decision:** UI acceptance criteria target the new worktree (`ultra-fast-rag-webapp`) instead of Streamlit.

Completed on branch `feat/fastapi-react-ui-reconciliation`:

- Added `specs/006-fastapi-react-realtime-app.md`
- Updated `docs/planning/work-index.md` and `docs/planning/implementation-plan.md`
- Amended specs 002/005 to target FastAPI/React webapp; Streamlit is parity reference only

Acceptance:
- Work index clearly states which UI stack Ralph should build against.
- Future tasks do not ask agents to add major new Streamlit UI unless explicitly for compatibility.

### Task 0.2 — Stabilize new webapp baseline

Files/worktree:
- `/Users/abhsheno/Desktop/Projects/ultra-fast-rag-webapp/src/scrape_planner/webapp/api.py`
- `/Users/abhsheno/Desktop/Projects/ultra-fast-rag-webapp/frontend/`
- `/Users/abhsheno/Desktop/Projects/ultra-fast-rag-webapp/docs/migration/streamlit-to-fastapi-react-audit.md`

Actions:
- Add API tests for `/api/health`, `/api/sites`, `/api/sites/{site}/overview`, `/api/sites/{site}/wiki/agent`, and SSE framing.
- Add frontend smoke/build check to the standard verification flow.
- Document dev startup commands and `SCRAPE_PLANNER_DATA_ROOT` usage.

Verification:
```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag-webapp
PYTHONPATH=. SCRAPE_PLANNER_DATA_ROOT=/Users/abhsheno/Desktop/Projects/ultra-fast-rag/data .venv/bin/python -m py_compile src/scrape_planner/webapp/api.py
cd frontend && npm run build
```

## Priority 1 — Fix Status Truth and Job Orchestration Contracts

### Task 1.1 — Make running status process-aware

Files:
- `src/scrape_planner/wiki/stepper_status.py`
- `src/scrape_planner/app/repositories.py`
- new or existing webapp status reader
- tests for stale tmux sessions

Actions:
- If report/status says `running`, verify the recorded tmux session/process exists.
- Surface `stale_running` or convert display state to `stale`/`exited` with a clear warning.
- Do not silently show a job as running after tmux exits.

Acceptance:
- Stale `wiki-agent-run-latest.json` from `wiki-ralph-www-smu-edu` is detected without manual tmux inspection.

### Task 1.2 — Make orchestrator prompts non-interactive

Files:
- `.pi/skills/wiki-ralph-orchestrator/SKILL.md`
- `scripts/wiki-ralph-orchestrator.sh`
- `scripts/ralph-loop-pi.sh`
- `docs/planning/prompt-build.md`

Actions:
- Remove confirmation-seeking language from unattended prompts.
- Ensure launched agents proceed immediately against the target spec/site/status directory.
- Require structured status/event writes on every iteration.

Acceptance:
- A one-iteration dry/status run produces action/status events instead of “say run it” responses.

## Priority 2 — Complete Spec 001 as the First Concrete Verification Gate

Spec 001 is lower risk than spec 000 and gives a known-good data baseline for later semantic/UI work.

Actions:
- Run the non-interactive wiki rebuild for `data/sites/www.smu.edu` without touching raw sources.
- Verify `wiki/index.md`, `wiki/log.md`, `wiki/review_queue.md`, `wiki/reports/wiki-build-latest.json`, `indexes/llm_wiki_manifest.json`, and `indexes/llm_wiki_documents.jsonl`.
- Run smoke query: `What graduate catalog programs are available?`
- Record completion only if raw sources are unchanged and verification passes.

Verification:
```bash
python -m py_compile src/scrape_planner/wiki/llm_wiki_builder.py src/scrape_planner/wiki/llm_wiki_index.py
.pi/skills/llm-wiki-noninteractive/scripts/build_wiki.sh \
  --site-root data/sites/www.smu.edu \
  --mode rebuild \
  --query "What graduate catalog programs are available?"
```

## Priority 3 — Spec 000 End-to-End Ingest Pipeline Contract

Actions:
- Extend `run_wiki_ingestion_pipeline(...)` as the authoritative orchestrator for stage keys: `ingest`, `clean`, `standardize`, `lint`, `build_wiki`, `build_index`, `verify`.
- Add a single latest report such as `wiki/reports/wiki-ingest-latest.json` with per-stage statuses, counts, timestamps, errors, artifact paths, runtime, and event log paths.
- Stop dependent stages after failures.
- Prevent duplicate concurrent launches for the same site.
- Add reusable cleanup/standardization/lint helpers instead of embedding rules in UI code.

Tests:
- cleanup/de-boilerplate fixtures
- standard document structure
- lint rule pass/fail cases
- pipeline success/failure report shape
- duplicate launch behavior

## Priority 4 — Spec 004 Agent-Traversable Wiki Map Before More UI Polish

Actions:
- Define canonical page spec/frontmatter contract.
- Add wikilink parser for `[[Page]]` and `[[Page|Alias]]`.
- Add relationship parser for `## Relationships` typed edges.
- Generate/validate:
  - `wiki/sitemap.md`
  - `wiki/navigation_manifest.json`
  - `wiki/backlinks.json`
  - `wiki/graph_edges.jsonl`
- Update index ranking so semantic/navigation pages outrank raw/source pages for broad questions.
- Update MCP to return `next_pages` and safe open-by-title/path/page-id traversal.

Smoke questions:
1. `I am a new graduate student likely joining Cox; tell me about courses, course fees, and the admission process.`
2. `What graduate catalog programs are available, and where should I go next for school-specific details?`
3. `Show me the navigation path from SMU graduate admissions to Cox MBA costs and curriculum.`

## Priority 5 — Spec 003 Semantic Student Wiki Quality Loop

Actions:
- Replace hardcoded semantic expansion with taxonomy/wiki-plan driven generation.
- Generate school/persona/intent pages with required student-friendly sections.
- Validate citations near claims and related pages.
- Rebuild and query until Cox graduate question retrieves coherent organized pages covering curriculum, fees/costs/aid, and admissions.

Acceptance note:
- Thousands of generated source `.md` files are necessary but not sufficient. Completion requires qualitative retrieval proof.

## Priority 6 — Spec 002 and Spec 005 UI Runtime Wiring

If product direction remains FastAPI/React:

- Implement these specs in the new webapp, not by adding more Streamlit panels.
- Build REST action endpoints for Build Wiki, Update Wiki, start/stop Ralph orchestrator, and status recovery.
- Stream job updates via SSE initially; reserve WebSockets for bidirectional terminal/agent controls.
- Keep Streamlit as read-only parity reference until replaced.

If product direction explicitly reverts to Streamlit:

- Spec 002 must wire Pi SDK runner into the Streamlit Wiki tab.
- Spec 005 must fix tmux/Ralph launcher/status artifacts and checklist rendering.

## Required Verification Matrix

Python syntax:
```bash
python -m py_compile app.py src/scrape_planner/wiki/llm_wiki_builder.py src/scrape_planner/wiki/llm_wiki_index.py src/scrape_planner/wiki/wiki_ingestion_pipeline.py mcp_servers/llm_wiki_mcp.py
```

Core tests:
```bash
pytest -q \
  tests/test_llm_wiki_builder.py \
  tests/test_llm_wiki_index.py \
  tests/test_wiki_ingestion_pipeline.py \
  tests/test_wiki_ui.py \
  tests/test_llm_wiki_mcp.py \
  tests/test_wiki_graph_artifacts.py
```

Node checks where applicable:
```bash
node --check scripts/pi-sdk-wiki-runner.mjs
```

Webapp checks where applicable:
```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag-webapp/frontend
npm run build
```

Runtime smoke:
```bash
.pi/skills/llm-wiki-noninteractive/scripts/build_wiki.sh \
  --site-root data/sites/www.smu.edu \
  --mode resume \
  --query "I am a new graduate student likely joining Cox; tell me about courses, course fees, and the admission process."
```

## Completion Rules for Ralph Build Mode

For each spec completion:

1. Mark the spec `## Status: COMPLETE` only after all acceptance criteria pass.
2. Update `docs/planning/work-index.md` queue and completion ledger.
3. Append a line to `docs/planning/history.md`.
4. Add `docs/planning/completion_log/YYYY-MM-DD--HH-MM-SS--spec-name.md`.
5. Run compile/tests/smoke checks relevant to changed code.
6. Do not commit, push, stage, reset, or rewrite history unless explicitly asked.
