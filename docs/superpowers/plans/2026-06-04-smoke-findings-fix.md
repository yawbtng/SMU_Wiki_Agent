# Fix smoke-test findings from 2026-06-04

Trusted workspace: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`.

## Context

An end-to-end Browser smoke test created workspace `127.0.0.1:8765` from a disposable local site and found several live app issues:

1. Approval persistence drops selected URLs. Discovery found 5 URLs, but selecting all groups only persisted the 3 `/pages/*` URLs into `approved_urls.md`; homepage and PDF remained missing even after individual add attempts.
2. Scrape artifacts exist but Overview/Sources stay stale. Scrape run `20260604T065804Z-9d1b57` completed 3/3 pages and wrote markdown/raw/metadata files, but Overview still showed `Ready Sources 0` and Sources showed `Raw source registry (0)`.
3. Document upload UI is ahead of the live backend. Source has `POST /api/sites/{site_id}/documents/upload`, but the running OpenAPI did not expose it and upload returned `405`. Fix the code path and ensure the route is registered in the live app after restart.
4. Embeddings state is inconsistent. Settings showed embeddings enabled with OpenAI model, while Embeddings tab said embeddings disabled and disabled rebuild.
5. MCP query retrieval failed with `embedding_unavailable`, and metadata pointed at sibling `ultra-fast-rag-webapp/data/sites/www.smu.edu` despite the current app data root being this checkout. Preserve fail-fast behavior, but align data-root routing so the current checkout is the source of truth.
6. Metrics are live but scrape/Pi metrics separation should be explicit: smoke scrape appears in Runs but metrics remain zero. Do not fake metrics; clarify UI/state if needed.

## Constraints

- Before editing, run `git status --short` and inspect diffs for files you will touch.
- Preserve unrelated dirty work. Do not revert, reset, rebase, clean, commit, or push.
- Use CodeGraph first for structural code questions when available. Use `rg` for literal strings and route names.
- Follow TDD: add focused failing tests for the reproduced failures before production code changes.
- Keep fixes small and rooted in the observed failures.

## Expected investigation

- Trace approval group commit flow from frontend selected groups to backend `approved_urls` payload and markdown rendering.
- Trace site overview/source registry derivation after a scrape run. Determine whether raw-source normalization is not invoked after scrape, overview ignores scrape runs, or frontend reads the wrong payload.
- Confirm document upload route registration in `src/scrape_planner/webapp/routes.py` and app factory/import path in `src/scrape_planner/webapp/api.py`.
- Trace embedding enabled state from Settings save/read payload into Embeddings tab view model.
- Trace MCP global data-root/site-root selection and remove stale sibling-worktree fallback from active current-checkout behavior, unless tests prove it is still required for migration.

## Implementation requirements

- Approval: selecting all discovered groups must persist all selected URLs, including `/` and `/docs/student-handbook.pdf`, and selected/available counts must match persisted markdown.
- Sources/Overview: after a successful scrape, the latest run's successful markdown pages must appear in Sources and ready-source counts must update in Overview without requiring manual filesystem edits.
- Documents: `/api/sites/{site_id}/documents/upload` must appear in OpenAPI and accept multipart PDF upload; Documents tab should be able to show extracted PDF pages after upload.
- Embeddings: Embeddings tab enabled/disabled state must agree with Settings.
- MCP: global mode should list and query sites from the current app data root. If embeddings are unavailable, keep explicit `embedding_unavailable`; if key/model is configured and reachable, query should return evidence.
- Metrics: keep current zero metrics for non-Pi scrape runs unless the product model says scrape metrics should be recorded; if not recorded, make the distinction clear in UI or tests.

## Verification commands

Run focused red tests first, then after implementation run:

```bash
PYTHONPATH=. .venv/bin/python -m py_compile src/scrape_planner/webapp/routes.py src/scrape_planner/webapp/api.py src/scrape_planner/webapp/approved_urls.py src/scrape_planner/webapp/embeddings.py mcp_servers/llm_wiki_mcp.py
PYTHONPATH=. .venv/bin/pytest tests/test_webapp_api.py tests/test_pdf_ingest.py tests/test_embedding_client.py
bash scripts/verify-webapp.sh
npm run build --prefix frontend
```

Runtime smoke after code changes:

1. Restart the app with the repo's `./stop.sh` then `./start.sh` if needed.
2. Confirm `http://127.0.0.1:8000/openapi.json` includes `/api/sites/{site_id}/documents/upload`.
3. Use Browser at `http://127.0.0.1:5173` to create or reuse a disposable sample workspace, approve homepage/pages/PDF, scrape, upload PDF, and verify Overview/Sources/Documents/Runs/Embeddings/MCP/Metrics.
4. Run an MCP initialize + `list_universities` + `query_wiki` smoke using the current checkout `data` root.

## Report

Return changed files, root causes, tests added, verification output, and any issues that remain because of missing external services such as OpenRouter embedding availability.
