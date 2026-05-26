# Wiki-First UI And Metrics Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the confusing graph/corpus-heavy operator flow with a wiki-first workflow that supports late URL discovery, full-screen source/document inspection, embedding-specific controls, cost/request metrics, and end-to-end wiki/index/MCP verification.

**Architecture:** Keep the existing durable pipeline: discovered URLs/PDFs -> scraped/raw sources -> LLM Wiki -> `llm_wiki_index` -> query-only `llm_wiki_mcp`. Move UI sections to match that pipeline, and keep charts derived from existing run and observability artifacts instead of inventing new telemetry stores.

**Tech Stack:** Streamlit, pandas, Altair, existing `src/scrape_planner` helpers, `mcp_servers/llm_wiki_mcp.py`, and `scripts/validate_llm_wiki_stepper.py`.

---

## File Structure

- Modify `src/scrape_planner/ui_navigation.py` to expose the new top-level flow: `Overview`, `Sources`, `Runs`, `Documents`, `Wiki`, `Embeddings`, `Metrics`, `Query`, `Settings`.
- Modify `app.py` to:
  - Keep sitemap refresh additive so later discoveries merge into current selections.
  - Promote the run page table out of the tiny expander and add large table controls.
  - Replace the `Corpus` page with a compact `Documents` page and markdown preview panel.
  - Keep Wiki focused on build status plus latest three to four log lines.
  - Add an `Embeddings` page with index build action and only embedding/index metrics.
  - Add a separate `Metrics` page for scrape, Tavily, Ollama, and OpenRouter usage/cost charts.
  - Replace the graph-heavy retrieval page with a query page backed by `query_llm_wiki_index` and MCP readiness.
- Modify `src/scrape_planner/run_analytics.py` to add provider-agnostic usage summaries and time series.
- Modify tests under `tests/test_*ui.py` and `tests/test_run_analytics_metrics.py` to lock the new screen ownership.

## Task 1: Navigation And Late Discovery

- [ ] Update `WORKFLOW_TABS` to `["Overview", "Sources", "Runs", "Documents", "Wiki", "Embeddings", "Metrics", "Query", "Settings"]`.
- [ ] Change the sitemap refresh path in `app.py` to merge refreshed URLs with existing `st.session_state["discovered"]` and keep already-selected/manual URLs unless the same URL is refreshed.
- [ ] Add explicit UI copy that refreshed sitemap discovery is additive.
- [ ] Add/update a test proving `Refresh Sitemap URLs` merges instead of replacing.

## Task 2: Runs Page Full Table

- [ ] Replace the nested `All pages and filters` expander with a visible `All Pages` section.
- [ ] Add a wide table mode toggle and page-size selector so hundreds of pages can be scanned without a small scroll box.
- [ ] Keep `worker_id` and `fetch_mode` as raw scrape-worker fields only; do not synthesize `recovery` or fake fetch modes.
- [ ] Add/update a test that the runs page exposes `All Pages` directly and does not render it inside an expander.

## Task 3: Documents Page

- [ ] Rename `Corpus` to `Documents`.
- [ ] Show compact rows for raw web/PDF sources with status, kind, title, URL/path, and markdown preview action.
- [ ] Move PDF extraction progress into concise metrics and remove page-by-page markdown/review queue blocks from the main flow.
- [ ] Use a selected-row preview panel/large text area instead of many cards/modals.
- [ ] Add/update tests that documents owns source inspection and does not expose raw normalization JSON by default.

## Task 4: Wiki Page

- [ ] Keep Wiki focused on `Build LLM Wiki`, status counts, and live output.
- [ ] Show only the latest four lines from `wiki/log.md` and tmux pane by default.
- [ ] Move detailed report JSON behind a clearly secondary debug expander.
- [ ] Preserve the existing launch handoff behavior: seed/report, `wiki_build_launch_notice`, and `st.rerun()`.

## Task 5: Embeddings Page

- [ ] Add a top-level `Embeddings` page.
- [ ] Import and use `build_llm_wiki_index` for a build/rebuild action.
- [ ] Show only embedding/index metrics: raw docs, wiki docs, changed docs, skipped docs, term count, embedding provider/model, reranker status, latest report.
- [ ] Remove chunk-quality gates from retrieval; the index embeds wiki plus raw source documents.

## Task 6: Metrics Page

- [ ] Move scrape analytics and LLM/provider cost charts from Retrieval into `Metrics`.
- [ ] Add provider tabs or filters for OpenRouter, Tavily, and Ollama.
- [ ] Derive OpenRouter cost from loaded model pricing when available and already-recorded trace token counts.
- [ ] Use user-entered Tavily per-call and Ollama per-million token settings for estimated costs.
- [ ] Add provider-agnostic charts: requests over time, request counts by provider/model/operation, token usage over time, cost by provider/model/operation.

## Task 7: Query Page

- [ ] Remove deterministic knowledge graph build/search/path UI from the main workflow.
- [ ] Add a question input that calls `query_llm_wiki_index` against the current site root.
- [ ] Show evidence rows with corpus, title, path, score, and excerpt.
- [ ] Keep MCP readiness/config as a compact connection section, not a large JSON-first page.

## Task 8: Verification

- [ ] Run `python -m py_compile app.py src/scrape_planner/ui_navigation.py src/scrape_planner/run_analytics.py src/scrape_planner/llm_wiki_index.py mcp_servers/llm_wiki_mcp.py`.
- [ ] Run focused UI/analytics/index tests.
- [ ] Run `python scripts/validate_llm_wiki_stepper.py --include-smu --smu-limit 3`.
- [ ] Start the Streamlit app and verify logs show no new exceptions after loading the updated workflow.
