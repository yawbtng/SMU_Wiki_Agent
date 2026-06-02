## Context

The repository consolidated React/FastAPI into `ultra-fast-rag` (`frontend/`, `src/scrape_planner/webapp/`, `./start.sh`) while retaining Streamlit (`app.py`), subpackage layout (`wiki/`, `scrape/`, `infra/`, `runtime/`), and root import shims. A parallel code review identified defects across wiki lifecycle, webapp side effects, scrape policy gaps, index concurrency, security assumptions, and test drift.

Existing OpenSpec changes (`build-llm-wiki-stepper`, `self-improving-rag-mcp`) partially overlap (embedding space, SSRF on ingest, concurrent index writes). This change **extends and completes** operator-facing wiring those changes assumed but did not fully land in the webapp/React path.

## Goals / Non-Goals

**Goals:**

- Wiki builds are **observable**: terminal JSON reports, relaunchable after grace, Pi compile actually runs from UI defaults.
- Webapp is **predictable**: no background embedding storms; runs show real events; secrets not leaked.
- Scrape/discover **honor student URL policy** consistently.
- Local deployment is **safe by default** (loopback, SSRF guards, quoted shell).
- Test suite **tracks React** as primary UI.

**Non-Goals:**

- Multi-user auth, RBAC, or API tokens (document localhost trust boundary only).
- Rewriting `llm_wiki_index.py` (~2059 lines) in one pass.
- Removing Streamlit in this change.
- Moving site data from symlinks (operator migration is manual).

## Decisions

### Decision 1: Wiki finalize via shell trap + Python helper
`build_wiki.sh` SHALL register an `EXIT` trap that invokes a small Python helper (`wiki/finalize_build_report.py` or inline) to patch `wiki-build-latest.json` with terminal status, `job_finished_at`, exit code, and best-effort metric counts from lint/registry.

Rationale: launcher and shell are separate processes; trap is the single choke point regardless of Pi/lint/index failures.

### Decision 2: Active session = running report AND live tmux AND job not finalized
`_active_session` SHALL return None when report has `job_finished_at` or terminal status, even if tmux session still in grace period.

Rationale: grace is for log review, not build mutex.

### Decision 3: Embedding auto-queue is opt-in
`maybe_auto_queue_embedding_job` SHALL NOT run from SSE or overview unless `app_state.auto_rebuild_embeddings === true` (default false).

Rationale: polling must not mutate indexes.

### Decision 4: Scrape events dual-write
`ScrapeRunner` SHALL append each event to `events.jsonl` via `append_run_event` in addition to any Redis/in-memory push.

Rationale: webapp reads disk; Streamlit may still use Redis — unify over time.

### Decision 5: URL policy at discovery write time
`discover_site_urls` SHALL set `selected=False` and `excluded_reason` from `classify_url_for_student_wiki` for each URL before persisting `discovered_urls.json`.

Rationale: downstream scrape/worker already filter on `selected`; one policy gate.

### Decision 6: Shared fetch module
Extract or reuse `ingest_safety.safe_fetch` (or move to `scrape/safe_fetch.py`) for discovery, sitemap recursion, and scrape worker HTTP mode.

Rationale: avoid three divergent HTTP stacks.

### Decision 7: App state secrets
`GET /api/app-state` SHALL redact keys matching `*_api_key`, `*_secret`, `*_token`. `PUT` SHALL accept only allowlisted keys from Settings UI contract.

Rationale: settings pane already scopes writes; prevent accidental exfiltration.

### Decision 8: MCP tmux command quoting
`start_mcp_server_for_site` SHALL build argv list and pass through `shlex.join` before tmux, matching `wiki_launcher._pipeline_command`.

### Decision 9: Test migration phased
Phase A: add webapp route + launcher tests. Phase B: mark Streamlit AST tests `@pytest.mark.legacy_streamlit` skip by default. Phase C: delete after React parity checklist.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Pi skill vendoring increases repo size | submodule or script-only skill; `--skip-pi` for CI |
| Finalize trap masks partial failures | always set `failed` on nonzero exit; attach stderr tail in report |
| URL policy reduces discovered count | show excluded count in discover API; operator override flag |
| Redacted GET breaks clients expecting keys | return `{ "openrouter_api_key": "set" \| "missing" }` metadata |
| Lock files stale | same pattern as embedding lock (PID + TTL) |

## Migration Plan

1. **Wiki lifecycle** — Pi skill, finalize trap, active-session fix, lint in pipeline (blocks operators).
2. **Webapp reliability** — disable SSE auto-embed, scrape events, frontend fixes.
3. **Policy + SSRF** — discovery/scrape/manual paths.
4. **Security** — app-state redaction, MCP quoting.
5. **Index/MCP** — embedding timeout, degradation reset, query snapshot (incremental).
6. **Tests + docs** — new tests, skip legacy Streamlit, update README/AGENTS.

## Dependencies

- Completes gaps relative to `openspec/changes/self-improving-rag-mcp` (SSRF, concurrency) on discover/scrape paths.
- Assumes unified repo layout (`frontend/`, `./start.sh`) from recent consolidation.
