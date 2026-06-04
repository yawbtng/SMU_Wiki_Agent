# UI/Backend Feature Mismatch and Code Quality Audit

Date: 2026-06-04  
Scope: React/FastAPI operator UI, backend route surface, live app/data probes, OpenSpec/spec alignment, and code quality hotspots.  
Mode: Read-only audit plus verification commands; no product source changes.

## Executive verdict

The app is not broken everywhere, but it has a serious "UI promises more than backend guarantees" problem. The codebase currently feels like a migration that got declared finished before the runtime contracts hardened. Tests pass, but they mostly prove happy-path fixtures, not real operator behavior.

Verification performed:

- `./status.sh` — backend/frontend were running and health checks were green.
- `./scripts/verify-webapp.sh` — passed.
- Full test suite — `262 passed`.
- Live API probes against `http://127.0.0.1:8000` — found real failures despite passing tests.
- Lightpanda semantic DOM fetch confirmed the dashboard renders, then browser testing was stopped per instruction.

Current-state refresh on 2026-06-04 around 06:27-06:29 UTC:

- CodeGraph status was healthy: 160 indexed files, 2,583 nodes, 3,527 edges.
- Cursor Agent read-only verification could not run because the local agent exited immediately with `SecItemCopyMatching failed -50`; the refresh used CodeGraph plus narrow live probes instead.
- `./status.sh` still showed backend PID `81218` listening on `127.0.0.1:8000` and frontend PID `81259` listening on `127.0.0.1:5173`.
- `curl -i http://127.0.0.1:8000/api/health` returned `200 OK`.
- `curl -i http://127.0.0.1:8000/api/sites/demo.edu/embeddings/job` still returned `500 Internal Server Error`.
- `curl http://127.0.0.1:8000/api/sites` still reported `demo.edu` as `has_sources: true` with `run_count: 4`.
- `curl 'http://127.0.0.1:8000/api/sites/demo.edu/sources?limit=3'` returned `total: 0`.
- `curl 'http://127.0.0.1:8000/api/sites/www.smu.edu/wiki/pages?limit=1&view=sources'` still returned `total_matching: 1`.
- `curl 'http://127.0.0.1:8000/api/sites/www.smu.edu/wiki/generation'` returned `source_page_count: 2844`.

## Concrete broken or misleading features

### 1. Embeddings tab can break or get stuck

Live failure:

- `GET /api/sites/demo.edu/embeddings/job` returned `500 Internal Server Error`.

Root cause:

- `src/scrape_planner/webapp/embeddings.py:68-72`
- Empty `report_path` becomes `Path("")`, which resolves to the current directory `.`. The code checks `report_path.exists()`, sees the directory exists, then tries to parse it as JSON, raising `IsADirectoryError`.
- Current code still has this path: `embedding_job_status_payload(...)` reads `log_path = Path(str(state.get("log_path") or ""))` and `report_path = Path(str(state.get("report_path") or ""))`, then reads any existing `report_path` without `is_file()` validation.

UI dependency:

- `frontend/src/main.tsx:1903-1907` polls `/api/sites/{site_id}/embeddings/job` for the Embeddings tab.

Additional live issue:

- `data/sites/www.smu.edu/indexes/.embedding-job.lock` contained dead PID `78390`.
- `ps -p 78390` showed no running process.
- Backend still reported the embedding job as `running`, started around `2026-06-04T01:17:36Z`.
- Current-state refresh still found `.embedding-job.lock` containing only `78390`; the file has no timestamp or structured metadata.

Impact:

- Embeddings tab can hard-fail for idle sites.
- A stale lock can make the UI show `Rebuilding...` forever and block/coalesce manual rebuilds.

Recommended fix:

- Treat empty `report_path`/`log_path` as absent.
- Check `is_file()` before reading report JSON.
- Store PID + timestamp in the embedding lock.
- Reap stale locks and terminalize dead jobs to `failed`/`stale`.

### 2. Dashboard lies about workspace readiness

Observed dashboard text for `demo.edu` said:

- `Sources ready`
- `Wiki present`
- `4 artifact runs`

Live API contradicted this:

- `/api/sites/demo.edu/sources?limit=3` returned `total: 0`.
- `/api/sites/demo.edu/runs` listed artifact directories: `indexes`, `raw_sources`, `wiki`, `metrics`.

Evidence:

- Backend marks `has_sources` true if `raw_sources/registry.jsonl` exists, not if ready source rows exist: `src/scrape_planner/webapp/api.py:80-98`.
- Frontend displays that as `Sources ready`: `frontend/src/main.tsx:400-407`.
- Backend run listing treats any site subdirectory except `meta` as a run: `src/scrape_planner/webapp/api.py:441-461`.

Impact:

- Operators are shown false readiness.
- Run history is polluted with non-run artifact directories.

Recommended fix:

- `GET /api/sites` should include real `ready_source_count`, `wiki_page_count`, and `scrape_run_count`.
- Only directories with scrape run status/events/pages should count as runs.
- Frontend should say `No ready sources` when registry exists but has zero ready rows.

### 3. Passive reads can start background work

`GET /api/sites/{site_id}/overview` may auto-queue embedding rebuilds.

Evidence:

- `src/scrape_planner/webapp/api.py:150-158` calls `maybe_auto_queue_embedding_job(...)` during overview payload construction.
- `src/scrape_planner/webapp/embeddings.py:362-389` launches embedding rebuilds when documents changed.
- SSE calls `site_overview_payload(...)`: `src/scrape_planner/webapp/api.py:1059+`.
- Current CodeGraph refresh confirmed `site_overview_payload(...)` still updates `index_status` with `maybe_auto_queue_embedding_job(...)`, and `site_event_stream(...)` still calls `site_overview_payload(...)` inside the SSE loop.

Impact:

- Opening or refreshing the UI can mutate runtime state.
- SSE polling can accidentally launch indexing work.
- Operators cannot reason about what actions are safe.

Recommended fix:

- Make overview/SSE read-only.
- Move auto-rebuild to an explicit scheduler or explicit `POST` action.
- Add an app-state flag like `auto_rebuild_embeddings`, default `false`, if auto behavior is desired.

### 4. Settings has fake or partially wired knobs

Settings exposes many fields that are mostly persisted but not actually connected to runtime behavior.

UI evidence:

- Settings UI: `frontend/src/main.tsx:2390-2546`
- Settings model: `frontend/src/settingsModel.ts:46-88`

Examples:

- `scrape_concurrency` is saved, but frontend has no real scrape launcher.
- `lightpanda_cdp_url` is saved, but the web scrape route does not read app state or pass it into `start_scrape_payload`.
- `use_tavily_for_map` appears unused in current operator UI flow.
- `url_reasoning_openrouter_model` is mostly decorative after URL approval chat became deterministic.
- `zvec_collection` is persisted but does not visibly drive the current UI flow.
- OpenSpec claims URL reasoning, wiki enrichment, wiki Q&A, and embedding model selectors should exist, but Settings currently shows URL reasoning and embedding selectors only.

Backend evidence:

- Route accepts explicit scrape request fields only: `src/scrape_planner/webapp/routes.py:185-194`.
- `start_scrape_payload(...)` accepts `concurrency` and `browser_mode`, but does not read Settings state: `src/scrape_planner/webapp/api.py:501-532`.

Impact:

- Settings page is a junk drawer: it saves values that do not consistently affect behavior.
- Operators will assume controls are real when they are not.

Recommended fix:

- For each Settings field, either wire it into a concrete backend path or remove/hide it.
- Add backend tests proving saved settings affect launched jobs.
- Add a Settings contract doc mapping field -> consumer.

### 5. "LLM agent" approval chat is not an LLM

Frontend says:

- `Asking LLM to draft approved URLs...`
- `LLM agent is thinking...`

Evidence:

- `frontend/src/main.tsx:1039-1074`

Backend behavior:

- `_operator_intent_from_message(...)` uses deterministic keyword parsing: `src/scrape_planner/webapp/approved_urls.py:365-392`.
- `approval_chat_payload(...)` calls that local heuristic and stores it under a variable named `llm`: `src/scrape_planner/webapp/approved_urls.py:403-435`.

This may be intentional per `operator-agent-runtime`, but the UI wording is dishonest.

Impact:

- Operator thinks an LLM/agent reasoned over URLs.
- Backend actually used regex/keyword heuristics.

Recommended fix:

- Rename UI to `URL selection assistant` / `rule-based URL helper`, or route the action through the Pi `site-url-curation` skill.
- Do not use `LLM` labels unless an LLM or Pi agent actually ran.

### 6. Pi operator job APIs exist but UI barely uses them

Backend exposes Pi skills:

- `site-discovery`
- `site-url-curation`
- `llm-wiki-noninteractive`

Evidence:

- `src/scrape_planner/app/operator_skills.py:26-54`
- `src/scrape_planner/webapp/routes.py:42`
- `src/scrape_planner/webapp/routes.py:168-181`

Frontend evidence:

- Frontend calls `/api/sites/{site_id}/approved-urls/chat` directly: `frontend/src/main.tsx:1041`, `1073`, `1117`.
- Frontend does not appear to call `/api/operator/skills`.
- Discovery uses `/api/discover` directly, not a `site-discovery` job.

Impact:

- Architecture says FastAPI should be thin and operator workflows should run through Pi skills, but UI still uses direct synchronous backend paths.
- Job catalog exists as backend plumbing without becoming the UI contract.

Recommended fix:

- Decide: direct FastAPI workflows or Pi jobs.
- If Pi jobs are the desired path, route discovery and URL curation UI through `/api/sites/{id}/jobs`.
- If direct FastAPI is desired, remove the unused promise surface.

### 7. Wiki page totals are wrong

`wiki_pages_payload(...)` slices rows before calculating `total_matching`.

Evidence:

- `src/scrape_planner/webapp/api.py:1005-1019`
- Current CodeGraph refresh confirmed the order is still `rows = rows[:limit]` followed by `"total_matching": len(rows)`.

Live example:

- `GET /api/sites/www.smu.edu/wiki/pages?limit=1&view=sources` reported `total_matching: 1`.
- `GET /api/sites/www.smu.edu/wiki/generation` reported `source_page_count: 2844`.
- Current-state refresh reproduced the same mismatch: `total_matching: 1` from the pages endpoint versus `source_page_count: 2844` from the generation endpoint.

Impact:

- UI page counts are capped counts, not actual totals.
- Operators cannot trust list counts.

Recommended fix:

- Calculate `total_matching = len(rows)` before slicing.
- Return `pages = rows[:limit]` separately.

### 8. App state leaks secrets and accepts arbitrary writes

Evidence:

- `GET /api/app-state` returns raw state: `src/scrape_planner/webapp/routes.py:46-48`.
- `PUT /api/app-state` blindly merges arbitrary payload keys: `src/scrape_planner/webapp/routes.py:50-55`.
- `/api/discover` returns `app_state`: `src/scrape_planner/webapp/api.py:548-590`.
- Current CodeGraph refresh confirmed `GET /api/app-state` still returns `state_repo().load()`, `PUT /api/app-state` still does `current.update(update.payload)`, and `discover_site_payload(...)` still returns `{**summary, "rows_written": len(rows), "app_state": repo.load()}`.

Risk:

- If API keys are set, they can be returned to any client that can hit the API.
- There is no auth layer.
- Docker binds to `0.0.0.0`; CORS is not security.

Impact:

- This is a local-trust-boundary footgun.

Recommended fix:

- Redact `*_api_key` values on all GET responses.
- Remove `app_state` from discovery response.
- Allowlist writable app-state keys.
- Add tests proving secrets never leave the API.

### 9. Scrape workflow is half-present

Backend route exists:

- `src/scrape_planner/webapp/routes.py:185-194`

Frontend does not expose a real start-scrape control. Yet UI text tells users to use the scrape workflow.

Evidence:

- Frontend references scrape workflow text: `frontend/src/main.tsx:1161`.
- Search found no frontend call to `/api/sites/{site_id}/scrape`.
- Current literal search found frontend calls to `/api/discover` and `/api/sites/${siteId}/approved-urls/chat`, but no frontend call to `/api/sites/{site_id}/scrape` or `/api/operator/skills`.

Impact:

- UI tells users to do something they cannot do from the UI.

Recommended fix:

- Add an explicit scrape action, or remove the instruction.
- If scrape is supposed to happen through Pi jobs, reflect that in UI labels and backend routes.

## Code quality assessment

### God files and giant functions

The repo has several files that are too large to reason about safely:

- `frontend/src/main.tsx` — 2715 lines.
- `src/scrape_planner/wiki/llm_wiki_index.py` — 2154 lines.
- `src/scrape_planner/sources/raw_source_normalizer.py` — 1211 lines.
- `src/scrape_planner/webapp/api.py` — 1111 lines.
- `src/scrape_planner/scrape/scrape_worker.py` — 918 lines.

Large functions/classes:

- `ScrapeRunner` class — roughly 820 lines.
- `scrape_worker._execute` — roughly 623 lines.
- `scrape_worker._worker` — roughly 427 lines.
- `register_routes` — roughly 237 lines.

Brutal truth: this is not maintainable. It is migration landfill. The repo has good pieces, but too much behavior is coupled through `dict[str, Any]`, implicit files, tmux state, and frontend `AnyRecord`.

### Tests pass but do not protect real operator states

Commands passed:

- `./scripts/verify-webapp.sh`
- full pytest: `262 passed`

But live data still produced:

- A primary route 500: `/api/sites/demo.edu/embeddings/job`.
- Stale embedding lock dead PID.
- False workspace readiness.
- Incorrect wiki total counts.

This means tests are too fixture-happy and not stateful enough.

Recommended test additions:

- Embedding job status with empty `report_path` and `log_path`.
- Stale lock PID recovery.
- `/api/sites` readiness based on real counts, not file existence.
- `/runs` excludes artifact directories.
- `/wiki/pages` total count before pagination.
- App-state redaction.
- Overview/SSE does not start jobs.

### Spec/process smell: completion theater

Examples:

- `openspec/changes/operator-agent-runtime/tasks.md` marks many tasks done, but UI still bypasses the Pi job model for discovery/curation.
- `openspec/changes/openrouter-only-model-settings/specs/openrouter-only-model-settings/spec.md` says wiki enrichment and wiki Q&A model selectors should exist; current Settings UI does not show those selectors.
- `specs/006-fastapi-react-realtime-app.md` still says `Status: TODO` despite much of the FastAPI/React app existing.
- `docs/planning/work-index.md` still marks major specs TODO.
- `openspec/changes/code-review-hardening/proposal.md` already documents several defects that are still present.

Bluntly: the repo has accepted "checkbox done" in places where product behavior is still incomplete.

## Agent execution goals and completion contract

This section converts the audit into actionable completion goals. An agent must not mark an item complete because it "looks fixed" or because unrelated tests pass. An item is complete only when the code path is changed, regression coverage exists, live/read-only probes prove the behavior, and the evidence is recorded in this document.

### Ground rules for the fixing agent

- Start every work session with `git status --short`; inspect diffs for any file already modified before editing it.
- Keep changes scoped: one logical goal per commit/change set if commits are requested.
- For behavior changes, add or update tests before claiming completion.
- Run `./scripts/verify-webapp.sh` and targeted tests for the changed area before marking any P0/P1 item complete.
- Run `codegraph sync` after source/test/doc changes before further CodeGraph-dependent investigation or final reporting.
- Do not mark a checkbox complete if verification is skipped. Instead add `Blocked:` or `Deferred:` with the reason and next command to run.

### P0 — reliability and safety gates

The audit remediation is not allowed to be called "operator-safe" until every P0 item is complete.

#### P0.1 Embedding job status never 500s for idle/empty state

- [ ] Fix `/api/sites/{site_id}/embeddings/job` so empty `report_path` and `log_path` are treated as absent, not as `.`.
- [ ] Add a regression test for an idle embedding state with blank paths.
- [ ] Prove `GET /api/sites/demo.edu/embeddings/job` returns `200` with `phase: idle` or another non-error state.

Completion evidence to record:

```text
P0.1 completed by: <agent/date/commit-or-diff>
Tests: <commands and pass/fail>
Live probe: <curl/python output summary>
Files changed: <paths>
```

#### P0.2 Stale embedding locks are recovered or surfaced as terminal/stale

- [ ] Store enough lock metadata to identify stale locks safely, at minimum PID and timestamp.
- [ ] Detect dead PID locks and either reap them or mark the job `stale`/`failed` with an operator-visible reason.
- [ ] Add tests for dead PID lock recovery and active lock preservation.
- [ ] Prove `www.smu.edu` no longer reports an hours-old dead embedding job as `running` when the PID is gone.

Completion evidence to record:

```text
P0.2 completed by: <agent/date/commit-or-diff>
Tests: <commands and pass/fail>
Live probe: <state file/API summary>
Files changed: <paths>
```

#### P0.3 Overview and SSE reads do not launch embedding work

- [ ] Remove `maybe_auto_queue_embedding_job(...)` side effects from passive overview/SSE reads, or gate them behind an explicit disabled-by-default setting.
- [ ] Add a regression test proving `GET /api/sites/{site_id}/overview` does not call/launch `trigger_embedding_rebuild`.
- [ ] Add or update SSE tests to prove connecting to `/api/stream/sites/{site_id}` does not enqueue embedding work.

Completion evidence to record:

```text
P0.3 completed by: <agent/date/commit-or-diff>
Tests: <commands and pass/fail>
Side-effect proof: <mock/assertion summary>
Files changed: <paths>
```

#### P0.4 App-state secrets are redacted and writes are allowlisted

- [ ] Redact `*_api_key` and other secret-like fields from every app-state GET/response payload.
- [ ] Remove raw `app_state` from `/api/discover` responses or return only non-secret fields.
- [ ] Add a write allowlist for `PUT /api/app-state` so arbitrary keys cannot be persisted through the API.
- [ ] Add tests proving secrets are never returned and disallowed keys are rejected or ignored.

Completion evidence to record:

```text
P0.4 completed by: <agent/date/commit-or-diff>
Tests: <commands and pass/fail>
Security probe: <redacted response summary>
Files changed: <paths>
```

#### P0.5 Workspace readiness and run counts reflect reality

- [ ] Change `GET /api/sites` so `has_sources`/source status is based on ready source rows, not mere registry-file existence.
- [ ] Change run listing/counting so artifact directories (`indexes`, `raw_sources`, `wiki`, `metrics`, `sources`) are not counted as scrape runs.
- [ ] Update frontend labels so empty registries are not shown as `Sources ready`.
- [ ] Add tests for an empty registry and artifact-only directories.
- [ ] Prove `demo.edu` no longer shows as sources-ready or as having artifact runs masquerading as scrape runs.

Completion evidence to record:

```text
P0.5 completed by: <agent/date/commit-or-diff>
Tests: <commands and pass/fail>
Live probe/UI model proof: <API response summary>
Files changed: <paths>
```

### P1 — UI/backend truth alignment

P1 is complete when the UI no longer promises workflows or intelligence that the backend does not actually provide.

#### P1.1 Approval chat label matches implementation

- [ ] Choose one product direction: rule-based local helper, or Pi/LLM-backed curation job.
- [ ] If rule-based, remove `LLM` language from frontend copy and backend variable names where practical.
- [ ] If Pi-backed, route the UI through the `site-url-curation` job and show job status instead of pretending the synchronous endpoint is an LLM.
- [ ] Add/adjust tests for the chosen contract.

Completion evidence to record:

```text
P1.1 completed by: <agent/date/commit-or-diff>
Decision: <rule-based|Pi-backed>
Tests: <commands and pass/fail>
Files changed: <paths>
```

#### P1.2 Discovery and URL curation use one coherent execution model

- [ ] Decide whether discovery/curation are synchronous FastAPI operations or operator Pi jobs.
- [ ] If Pi jobs are the model, wire UI discovery/curation controls to `/api/sites/{id}/jobs` and job status endpoints.
- [ ] If synchronous FastAPI remains, remove dead/unused promise surfaces or clearly mark Pi jobs as advanced/manual.
- [ ] Add tests for whichever model is selected.

Completion evidence to record:

```text
P1.2 completed by: <agent/date/commit-or-diff>
Decision: <sync FastAPI|Pi jobs>
Tests: <commands and pass/fail>
Files changed: <paths>
```

#### P1.3 Scrape workflow is either real or no longer referenced

- [ ] Add an explicit UI action that calls `POST /api/sites/{site_id}/scrape`, or remove/replace UI copy that tells users to use a scrape workflow.
- [ ] If adding the action, ensure Settings values that should affect scrape are actually passed to the backend.
- [ ] Add API/frontend tests or a smoke proof for the scrape action path.

Completion evidence to record:

```text
P1.3 completed by: <agent/date/commit-or-diff>
Decision: <added scrape action|removed stale copy>
Tests/smoke: <commands and pass/fail>
Files changed: <paths>
```

#### P1.4 Settings fields have real consumers or are hidden

- [ ] Create or update a Settings contract mapping each field to its backend consumer.
- [ ] For each current Settings field, either wire it into runtime behavior or remove/hide it from the operator UI.
- [ ] Add tests proving important saved settings affect launched jobs or generated commands.
- [ ] Specifically resolve `lightpanda_cdp_url`, `scrape_concurrency`, `use_tavily_for_map`, `url_reasoning_openrouter_model`, `zvec_collection`, and missing wiki model selectors.

Completion evidence to record:

```text
P1.4 completed by: <agent/date/commit-or-diff>
Contract updated: <path>
Tests: <commands and pass/fail>
Files changed: <paths>
```

#### P1.5 Wiki page totals are correct before pagination

- [ ] Fix `/api/sites/{site_id}/wiki/pages` so `total_matching` is computed before `limit` slicing.
- [ ] Add a test where matching pages exceed the requested limit.
- [ ] Prove `www.smu.edu` source page totals no longer collapse to the limit value.

Completion evidence to record:

```text
P1.5 completed by: <agent/date/commit-or-diff>
Tests: <commands and pass/fail>
Live probe: <API response summary>
Files changed: <paths>
```

### P2 — maintainability and test hardening

P2 work should not block P0/P1 reliability fixes unless the agent explicitly chooses a refactor as the smallest safe path. Large P2 refactors should get their own OpenSpec/change plan before implementation.

#### P2.1 Frontend module split

- [ ] Split `frontend/src/main.tsx` into tab components, hooks, and API client modules.
- [ ] Keep behavior unchanged except where P0/P1 explicitly requires UI copy or flow changes.
- [ ] Add a real frontend test command or document why build-only remains the temporary gate.

#### P2.2 Backend route/service split

- [ ] Split `src/scrape_planner/webapp/api.py` responsibilities into route, payload/service, and read-model layers.
- [ ] Avoid moving bugs around without adding regression tests.

#### P2.3 Giant pipeline modules get seams

- [ ] Break up `llm_wiki_index.py` and `scrape_worker.py` around testable seams: index build, query, rerank, lock handling, scrape scheduling, fetch, persistence.
- [ ] Preserve public CLI/API behavior unless a separate spec says otherwise.

#### P2.4 Live-data smoke coverage

- [ ] Add a smoke test or script that validates current `data/sites/*` shapes for: embeddings status, run list, wiki page totals, source readiness, and app-state redaction.
- [ ] Ensure the smoke check can run read-only and fails with actionable messages.

Completion evidence for each P2 item:

```text
P2.x completed by: <agent/date/commit-or-diff>
Tests/build: <commands and pass/fail>
Behavior preserved: <proof summary>
Files changed: <paths>
```

## How an agent may mark this audit remediation complete

An agent may mark a checkbox above from `[ ]` to `[x]` only after all bullets under that checkbox's goal are satisfied and its evidence block is filled in. The final audit remediation may be marked complete only when all P0 and P1 goals are checked and a final verification ledger is appended below.

Required final verification ledger:

```text
Final remediation completed by: <agent/date/commit-or-diff>
Completed goals: <P0.1...P1.5>
Verification commands:
- git status --short
- ./scripts/verify-webapp.sh
- <targeted pytest commands>
- <frontend build/test command>
- <live API probes used>
- codegraph sync
Known deferred P2 work: <list or none>
Unrelated pre-existing modified files left untouched: <summary>
```

Do not claim completion if any P0/P1 item is unchecked. Say "P0/P1 remediation incomplete" and list the remaining unchecked goals instead.

## Bottom line

The backend has many useful capabilities, but the UI is overconfident and the runtime state model is fragile. The next work should be reliability and truthfulness, not more features. Right now the operator UI often says "ready/running/LLM" when the backend reality is "empty/stale/heuristic".
