## 0. OpenSpec gate

- [ ] 0.1 Run `/interrogate` adversarial review on this change; resolve all "Act on" findings in proposal/design/specs.
- [ ] 0.2 `openspec validate code-review-hardening --strict` passes.

## 1. Wiki build lifecycle (Critical C1–C2, High H1–H2)

- [ ] 1.1 Add `.pi/skills/llm-wiki-v2/` (SKILL.md, schema.md, `scripts/generate_wiki.sh`) or repoint `build_wiki.sh` / `llm_wiki_builder` to in-repo compile; fail fast when missing.
- [ ] 1.2 Remove Streamlit hardcoded `runtime="python"`; use `app/tmux_settings.wiki_builder_runtime`.
- [ ] 1.3 Add `wiki/finalize_build_report.py` and `EXIT` trap in `build_wiki.sh` to write terminal `wiki-build-latest.json`.
- [ ] 1.4 Update `_active_session` to ignore reports with `job_finished_at` or terminal status during grace.
- [ ] 1.5 Add `wiki/reports/.wiki-build.lock` (O_EXCL) around tmux start.
- [ ] 1.6 Call `lint_wiki` from `wiki_ingestion_pipeline`; populate real metrics in `build_wiki` report.
- [ ] 1.7 Reconcile dead tmux: patch report to `failed`/`stale` when session gone and status still `running`.
- [ ] 1.8 Make `--skip-smoke` / smoke query controlled by app setting, not hardcoded in launcher.
- [ ] 1.9 Tests: `tests/test_wiki_launcher.py` — finalize, grace relaunch, lock race, missing Pi skill.

## 2. Webapp operator reliability (High H3–H4, H8, Medium M1–M4)

- [ ] 2.1 Add `auto_rebuild_embeddings` to app state (default false); gate `maybe_auto_queue_embedding_job`.
- [ ] 2.2 Remove auto-queue from SSE path; use digest-only tick or overview cache without side effects.
- [ ] 2.3 Embedding lock: store PID + timestamp; reap stale locks; add `POST .../embeddings/unlock` or equivalent.
- [ ] 2.4 Wire `ScrapeRunner` → `append_run_event` → `{run}/events.jsonl`.
- [ ] 2.5 SSE: check disconnect; break loop on client drop.
- [ ] 2.6 Frontend: try/catch on approval save/draft; parse FastAPI `detail`; wire Wiki build buttons to API.
- [ ] 2.7 Frontend: enable Overview REST query while SSE connecting (`enabled: !!siteId`).
- [ ] 2.8 `stop.sh --kill-tmux`; port listener cmdline check in `start.sh`; status env drift warning.
- [ ] 2.9 Tests: SSE no auto-queue (mock), stale lock reap, runs events round-trip, app-state redaction (with §3).

## 3. Scrape & source policy (High H5–H6, Medium M9–M10)

- [ ] 3.1 Apply `classify_url_for_student_wiki` in `discover_site_urls` before `selected=True`.
- [ ] 3.2 Apply policy in scrape worker pre-fetch filter.
- [ ] 3.3 Apply policy in `manual_url_pipeline` before scrape.
- [ ] 3.4 Add `scrape/safe_fetch.py` (or export from `ingest_safety`); use in discovery, sitemap, scrape HTTP mode.
- [ ] 3.5 Scrape `_execute`: outer try/finally terminal status; periodic `failures.json` flush.
- [ ] 3.6 Registry merge file lock; log corrupt JSONL lines; quarantine in-batch duplicate checksums.
- [ ] 3.7 Tests: `tests/test_scrape_policy.py`, `tests/test_scrape_durability.py`; extend `test_url_policy.py` for discovery integration.

## 4. Index & MCP safety (Medium M11–M16)

- [ ] 4.1 Reset `_DENSE_EMBEDDING_UNAVAILABLE` on successful embed; per-query override option.
- [ ] 4.2 Raise default `OLLAMA_EMBED_TIMEOUT` to ≥30s in `embedding_client.py`.
- [ ] 4.3 Query snapshot: read lock or generation token on manifest during `query_llm_wiki_index`.
- [ ] 4.4 `answer_question` retry_local: return non-ok when confidence still low.
- [ ] 4.5 Atomic web-search budget increment (lock file or temp swap).
- [ ] 4.6 (Optional P2) BM25 cache at index build time — separate task if perf still hot after 4.1–4.5.
- [ ] 4.7 Tests: degradation reset, query-during-build, post-ingest gating, budget race.

## 5. Local security & trust (High H7, H9–H10, Medium M20–M23)

- [ ] 5.1 Redact `*_api_key` / secrets on `GET /api/app-state`; allowlist PUT keys.
- [ ] 5.2 Remove full app state from discover response payload.
- [ ] 5.3 SSRF checks on discover entrypoint (block private IPs, http scheme if policy requires https).
- [ ] 5.4 MCP tmux: build command with `shlex.quote` per arg (match wiki_launcher).
- [ ] 5.5 Non-loopback HOST startup warning in `run-webapp.sh`.
- [ ] 5.6 Validate CORS origin list; document in README.
- [ ] 5.7 Update Docker README/compose deprecation note; restrict Redis publish or document dev-only.
- [ ] 5.8 Add `requirements.lock` or pin upper bounds; CI uses lock.
- [ ] 5.9 Tests: SSRF discover rejection, GET redaction, MCP command quoting snapshot.

## 6. Runtime & data persistence (Medium M17–M19, Low L5)

- [ ] 6.1 Confirm `core/data_root._looks_populated_data_root` requires non-empty sites (already partially done — verify webapp shim).
- [ ] 6.2 Document sibling tie-break in README; optional `SCRAPE_PLANNER_DATA_ROOT_STRICT`.
- [ ] 6.3 Log Redis fallback once; expose in `/api/health` metadata.
- [ ] 6.4 `write_page_states` → uuid temp files.
- [ ] 6.5 Fix `background_runner.start_detached` fd leak.
- [ ] 6.6 Tests: empty sites dir fallback, Redis warning flag.

## 7. React test migration (Coverage P0–P2)

- [ ] 7.1 Extend `tests/test_webapp_api.py`: `/runs`, `/sources`, `/wiki/pages`, PUT approved-urls, 404 paths.
- [ ] 7.2 Add vitest to `frontend/package.json`; wire in `scripts/verify-webapp.sh`.
- [ ] 7.3 Mark Streamlit AST tests `@pytest.mark.legacy_streamlit`; skip in default pytest.ini.
- [ ] 7.4 Add `tests/test_tmux_runner.py` with subprocess mocks (tmux missing, session exists).
- [ ] 7.5 Run `scripts/test-resolve-data-root.sh` in CI verify script.
- [ ] 7.6 Document React parity checklist in `docs/migration/streamlit-to-fastapi-react-audit.md`.

## 8. Verification & completion

- [ ] 8.1 `python -m pytest tests/test_webapp_api.py tests/test_wiki_launcher.py tests/test_data_root.py tests/test_url_policy.py -q`
- [ ] 8.2 `./scripts/verify-webapp.sh` green.
- [ ] 8.3 Manual: `./start.sh` → build wiki from React → report reaches `complete` with metrics.
- [ ] 8.4 Manual: SSE connected 5 min → no embedding job spawned (default settings).
- [ ] 8.5 `codegraph sync` after implementation.
- [ ] 8.6 Mark all tasks complete; output `<promise>DONE</promise>` for Ralph if using loop.

## Traceability matrix (code review → tasks)

| Review ID | Summary | Tasks |
|-----------|---------|-------|
| C1 | Missing llm-wiki-v2 | 1.1 |
| C2 | Streamlit skips Pi | 1.2 |
| H1 | Report stuck running | 1.3, 1.7 |
| H2 | Grace blocks relaunch | 1.4 |
| H3 | SSE auto-embed | 2.1, 2.2 |
| H4 | Stale embed lock | 2.3 |
| H5 | URL policy gaps | 3.1–3.3 |
| H6 | Scrape crash recovery | 3.5 |
| H7 | Discover SSRF | 3.4, 5.3 |
| H8 | Events not on disk | 2.4 |
| H9 | Secrets in app_state | 5.1, 5.2 |
| H10 | MCP shell injection | 5.4 |
| M11–M16 | Index/MCP | §4 |
| M17–M19 | Runtime/data | §6 |
| L1 | Streamlit tests stale | 7.3 |
| L6 | No frontend tests | 7.2 |
