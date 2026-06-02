## Why

A seven-area parallel code review of the unified `ultra-fast-rag` repository (React/FastAPI operator UI, wiki Pi pipeline, scrape/sources, index/MCP, infra/runtime, tests, security) found **2 critical**, **10 high**, and **23+ medium** defects. The repo is mid-migration: Streamlit, flat import shims, and legacy Docker coexist with the new subpackage layout and `./start.sh` stack.

Operators cannot reliably build wikis (missing Pi skill, reports stuck at `running`, grace-window relaunch blocks), the React app triggers surprise embedding rebuilds from SSE polling, scrape timelines are empty on disk, student URL policy is not enforced end-to-end, and the local API assumes a trust boundary that breaks if bound beyond loopback.

This change hardens the operator platform so daily workflows are observable, idempotent, policy-consistent, and safe-by-default — without re-architecting retrieval or reintroducing Streamlit.

## What Changes

### Wiki build lifecycle (Critical / High)
- Vendor or repoint the missing `.pi/skills/llm-wiki-v2` compile skill; fail fast with a clear operator message when absent.
- Default wiki launch to Pi compile when available; make lint-only / Python-only an explicit operator setting.
- Finalize `wiki-build-latest.json` on tmux/shell exit (`complete`/`failed`, timestamps, metrics).
- Exclude post-exit grace windows from concurrent-build guards; reconcile dead-session reports to terminal status.
- Wire `lint_wiki` into ingestion pipeline; populate real page/metric fields from compile/lint output.
- Add atomic concurrent-build lock; optional smoke query on rebuild.

### Webapp operator reliability (High / Medium)
- Remove embedding auto-queue from SSE and passive overview reads; require explicit operator action or a debounced scheduler.
- Add stale embedding lock recovery (PID + TTL) and force-unlock operator path.
- Persist scrape events to disk so `/runs` timelines match operator reality.
- SSE: disconnect-aware loops, lighter payloads, frontend error parsing and wiki action wiring.
- Harden `start.sh`/`stop.sh`: optional tmux kill, command-line port verification, env file validation.

### Scrape & source policy (High / Medium)
- Apply `classify_url_for_student_wiki` at discovery, scrape selection, and manual ingest.
- Scrape worker: periodic failure flush, `try/finally` terminal status, crash-safe manifests.
- Registry: file lock or single-writer queue for merge; log/surface corrupt JSONL lines; quarantine duplicate checksums in-batch.

### Index & MCP safety (Medium)
- Reset or per-query embedding degradation; raise default Ollama embed timeout; align with zvec build timeout.
- Serialize index reads during writes or snapshot artifacts atomically for query.
- Re-gate `answer_question` confidence after ingest retry; fix web-search budget race with atomic increment.
- Document BM25-per-query and O(n) vector scan as known perf debt; add build-time BM25 cache as follow-on if needed.

### Local security & trust boundary (High / Medium)
- Redact secrets on `GET /api/app-state`; allowlist writable settings keys.
- Route discovery/sitemap/scrape fetch through SSRF-safe fetch (`ingest_safety` or shared module).
- Quote MCP tmux commands with `shlex` like wiki launcher.
- Document localhost-only default; warn when `HOST` ≠ loopback; tighten CORS validation.
- Update Docker compose for FastAPI path or mark Streamlit stack deprecated; pin deps or add lockfile.

### Runtime, data & tests (Medium / Low)
- Data root: require artifact signal beyond empty `sites/` dir; document sibling tie-break.
- Wire `append_run_event` from scrape runner; fix `background_runner` fd leak.
- Migrate tests: React-critical API routes, wiki launcher, tmux lifecycle, retire Streamlit AST UI tests.
- Add vitest for frontend viewModel + critical hooks.

## Capabilities

### New Capabilities

- `wiki-build-lifecycle`: Pi compile, tmux finalize, concurrent build, ingestion lint parity.
- `webapp-operator-reliability`: SSE, embeddings, runs timeline, frontend error handling, ops scripts.
- `scrape-source-policy`: URL policy enforcement, scrape durability, registry integrity.
- `index-query-safety`: embedding degradation, query/build concurrency, MCP answer gating.
- `local-security-trust`: secrets, SSRF, shell quoting, CORS/host documentation.
- `runtime-data-persistence`: scrape events, data root, Redis fallback visibility.
- `react-test-migration`: webapp route tests, launcher tests, Streamlit test retirement.

### Modified Capabilities

- `llm-wiki-builder` (existing stepper spec): finalize reports, Pi skill presence, runtime defaults.
- `stepper-workflow` (if present): running → terminal status reconciliation.

## Impact

- **Code:** `wiki/`, `webapp/api.py`, `frontend/src/main.tsx`, `scrape/`, `sources/`, `wiki/llm_wiki_index.py`, `wiki/self_improving.py`, `infra/tmux_*`, `runtime/run_persistence.py`, `core/data_root.py`, `start.sh`/`stop.sh`, `.pi/skills/`.
- **Data:** `wiki/reports/wiki-build-*.json`, `indexes/.embedding-job.lock`, `events.jsonl`, `app_state.json` shape (redacted GET).
- **Tests:** new modules in `tests/test_webapp_api.py`, `tests/test_wiki_launcher.py`, `tests/test_scrape_durability.py`, retire ~12 Streamlit AST tests; add `frontend` vitest.
- **Non-goals:** Full auth/OAuth for operator API; replacing BM25 with external search engine; deleting Streamlit `app.py` in this change (deprecate only).

## Success Criteria

- `./start.sh` + wiki build from React produces terminal report with nonzero metrics when Pi compile succeeds.
- SSE connected for 5 minutes does not auto-launch embedding rebuilds.
- `GET /api/sites/{id}/runs` shows events after a scrape completes.
- Discover + scrape reject donor/news URLs per policy on `www.smu.edu` fixtures.
- `GET /api/app-state` never returns raw API key values.
- `openspec validate code-review-hardening --strict` passes.
