# Finish E2E UI/MCP Challenges From Browser Smoke

Trusted workspace: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`.

## Goal

Make the app pass the observed end-to-end operator path far enough that a human can use the UI to create a workspace, discover/approve sources, scrape, build/update wiki artifacts, rebuild embeddings, start/use MCP as a connector, and ask questions. Keep the human in the loop: do not claim the overall thread goal is complete until the user confirms.

## Current Evidence

Browser smoke at `http://127.0.0.1:5173/` created a fresh local fixture workspace `127.0.0.1:8766` using a temporary sample site:

- Discovery worked: 5 URLs from 1 sitemap source.
- Bulk approval worked: all 5 URLs saved, including homepage and PDF.
- Scrape backend worked only when invoked manually:
  `POST /api/sites/127.0.0.1:8766/scrape` returned run `20260604T210548Z-e3b4ed`.
- Sources UI then showed 4 ready web sources and a functioning raw-source inspector.
- The approved PDF URL did not appear as extracted document content or raw source content.
- Wiki build launched from UI but stalled after model-selection warnings such as:
  `Warning: No models match pattern "github-copilot/gpt-4o"`.
- Archiving the stalled tmux session stopped the session, but Wiki hero status still said `Running` while the session card said `archived`.
- Embeddings correctly blocked because wiki/index prerequisites were missing, but the button was still clickable and only then showed the block.
- MCP UI said `2 / 6 ready`, but JSON-RPC MCP smoke proved the advertised ready sites were not query-ready:
  - `127.0.0.1:8765` query failed with `embedding_unavailable`, reason `vector_store_unavailable`.
  - `www.smu.edu` query failed with `embedding_unavailable`, reason `index_version_mismatch`.
- Settings shows OpenRouter as configured but exposes the full key in the visible input. Do not log or print real keys in tests or reports.

## Constraints

- Preserve unrelated dirty work. Do not reset, clean, rebase, revert, push, or commit.
- Before editing, run `git status --short` and inspect diffs for files you will touch.
- Use CodeGraph first for structural code questions and affected-test discovery. Use `rg` only for literal strings, configs, markdown, and logs.
- Follow TDD for behavior changes: write focused failing tests first, verify they fail for the expected reason, then implement.
- Keep changes small and directly tied to the observed E2E blockers.
- Do not print or snapshot real API keys. UI should mask persisted secrets while still allowing replace/save.

## Implementation Tasks

### 1. Add A Visible Scrape Start Control

Root cause to confirm: backend exposes `POST /api/sites/{site_id}/scrape`, but the React UI has no operator-visible start action.

Requirements:

- Add a visible UI control in the workspace workflow, preferably Runs and/or Overview, to start scraping approved URLs.
- The action must call `/api/sites/{site_id}/scrape` with current settings-derived concurrency/browser mode and `prefer_approved: true`.
- Show busy, success, and error states.
- After starting, refresh overview, runs, sources, and active run status without a full page reload.
- If there are no approved URLs, disable or explain the action before calling the API.

Tests:

- Frontend/view-model or component test proving the scrape action appears when approved URLs exist and calls the scrape API.
- Backend test only if the endpoint contract needs adjustment.

### 2. Make Approved PDF URLs Non-Silent

Root cause to confirm: approved PDF URL was fetched during scrape but did not become visible in Documents or raw source registry.

Requirements:

- Approved PDF URLs must be represented in the UI after scrape as one of:
  - extracted PDF raw/document sources when parsing succeeds, or
  - a visible failed/quarantined PDF row with a reason when parsing fails.
- The Documents tab must not imply the PDF was ignored.
- The source registry/overview counts should distinguish web-ready, PDF-ready, and PDF-failed/quarantined states if those are separate concepts.

Tests:

- Focused backend test with a tiny valid PDF fixture or mocked PDF extractor proving an approved PDF URL is persisted into PDF source state.
- Focused failure test proving a bad PDF is visible as failed/quarantined rather than silently disappearing.
- Frontend/view-model test if Documents needs new state rendering.

### 3. Make Wiki Build Fail Fast Or Complete With Available Runtime

Root cause to confirm: UI launch spawned the noninteractive Pi build, which stalled after unavailable model warnings and produced no pages/indexes.

Requirements:

- If the configured Pi/model runtime cannot run, the wiki job must become `failed` with an operator-visible reason instead of staying `running`.
- Archiving/stopping a session must reconcile the wiki hero/build status away from `Running`.
- If a local deterministic/non-LLM fixture build path already exists for tiny validation, expose only if it matches the product model; otherwise keep the failure explicit.
- Build event stream should summarize build progress/failure instead of flooding the UI with raw agent token/event noise.

Tests:

- Backend/tmux session lifecycle test for archive/failed reconciliation.
- Wiki agent/status test for unavailable model/runtime marking the job failed or stale with a clear reason.
- Frontend/view-model test for hero status after archived/failed job.

### 4. Harden Embedding Prerequisite Guard

Requirements:

- If wiki pages/index prerequisites are missing, the rebuild button should be disabled or clearly non-actionable before click.
- The UI must still show the explicit reason: missing wiki/index prerequisites.
- If the backend receives a rebuild request without prerequisites, it should return a clear blocked payload and not create a misleading active job.

Tests:

- Frontend test for disabled/non-actionable rebuild state.
- Existing backend embedding job tests should cover blocked payload; add one if missing.

### 5. Make MCP Readiness Match Actual Query Readiness

Root cause to confirm: global MCP registry/UI reports ready based on files/counts that are insufficient for the current MCP query contract.

Requirements:

- MCP readiness must use the same health gate as `mcp_servers.llm_wiki_mcp.index_info` / `query_mcp_wiki_index`, including index version and zvec vector-store readiness.
- A site must not be shown as `enabled` / counted as ready if `query_wiki` would return `embedding_unavailable` for index-version or vector-store reasons.
- The MCP UI should show actionable reasons, such as `rebuild index: missing zvec vector store` or `rebuild index: v1 index, expected v2`.
- The JSON-RPC smoke must show `ready_count` only for query-ready sites.

Tests:

- Backend test for `/api/mcp/universities` or status model proving v1/missing-zvec indexes are not counted as MCP-ready.
- MCP server test can remain query-level, but add an API parity test if needed.

### 6. Mask Secrets In Settings

Requirements:

- Persisted OpenRouter/Tavily keys must not be displayed in full.
- UI should show presence/masked value and allow replacing/saving a new key.
- Tests and reports must use fake keys only.

Tests:

- Frontend settings test proving persisted key renders masked/presence state, not the raw secret.
- Save-payload test proving a blank unchanged key does not erase the saved key unless explicitly cleared, if that is the intended UX.

## Verification Commands

Run after implementation:

```bash
PYTHONPATH=. .venv/bin/python -m py_compile \
  src/scrape_planner/webapp/api.py \
  src/scrape_planner/webapp/routes.py \
  src/scrape_planner/webapp/embeddings.py \
  src/scrape_planner/webapp/tmux_sessions.py \
  src/scrape_planner/wiki/llm_wiki_index.py \
  mcp_servers/llm_wiki_mcp.py

PYTHONPATH=. .venv/bin/pytest \
  tests/test_webapp_api.py \
  tests/test_embedding_job_api.py \
  tests/test_tmux_session_lifecycle.py \
  tests/test_llm_wiki_mcp.py \
  tests/test_self_improving_rag_mcp.py \
  tests/test_pdf_ingest.py

cd frontend && npx tsc --noEmit && npm run build
bash scripts/verify-webapp.sh
```

Runtime smoke after tests:

1. Restart the app if source/backend/frontend changed.
2. Use Browser at `http://127.0.0.1:5173/`.
3. Create a fresh local fixture workspace from a live temporary site.
4. Discover, approve all groups, start scrape from the UI, verify ready sources and PDF visibility.
5. Launch wiki build/update and verify it either completes or fails fast with a clear reason.
6. Verify Embeddings cannot start until prerequisites are genuinely ready.
7. Run MCP JSON-RPC initialize + `tools/list` + `list_universities` + `index_info` + `query_wiki`; readiness must match actual queryability.
8. Confirm Settings masks secrets.
9. Confirm no new console errors and no leftover temporary tmux/sample-server processes.

## Human Loop

After verification, report:

- changed files,
- tests/commands and pass/fail,
- Browser screenshots,
- MCP smoke result,
- remaining risks or blockers.

Do not mark the thread goal complete until the user explicitly confirms the goal is achieved.
