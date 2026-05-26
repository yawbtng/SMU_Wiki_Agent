# One URL Knowledge Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-action path that takes a manually entered URL, scrapes it, normalizes it into `raw_sources`, incrementally compiles the Markdown wiki, and rebuilds the local query/vector index.

**Architecture:** Add a focused service module under `src/scrape_planner/` that writes the same run artifacts as the existing scrape worker, then calls the existing normalizer, wiki builder, and index builder. Expose the path in the Sources tab without replacing the current batch scrape controls.

**Tech Stack:** Python, Streamlit, existing `extract_content`, `normalize_scraped_markdown`, `build_wiki`, `build_llm_wiki_index`, pytest.

---

### Task 1: Pipeline Service

**Files:**
- Create: `src/scrape_planner/manual_url_pipeline.py`
- Test: `tests/test_manual_url_pipeline.py`

- [x] Write tests for a fake HTML response that creates scrape artifacts, raw registry rows, wiki files, and a ready index.
- [x] Write a test that off-domain URLs are rejected when a workspace site URL is provided.
- [x] Implement `run_manual_url_pipeline(site_root, site_url, url, fetcher=None, now=None)`.
- [x] Run `pytest tests/test_manual_url_pipeline.py -q`.

### Task 2: Sources UI Hook

**Files:**
- Modify: `app.py`
- Test: `tests/test_pdf_sources_ui.py`

- [x] Add a compact “Add One URL To Knowledge Base” input and button in the Sources tab.
- [x] Call `run_manual_url_pipeline(...)` and show run, raw-source, wiki, and index outcomes.
- [x] Add source-level UI assertions for the new control.
- [x] Run `pytest tests/test_pdf_sources_ui.py -q`.

### Task 3: Verification

**Files:**
- Compile: `app.py`, `src/scrape_planner/manual_url_pipeline.py`
- Test: focused manual URL, source UI, raw normalization, wiki builder, and index tests.

- [x] Run Python compile checks.
- [x] Run focused pytest.
- [x] Smoke the running Streamlit app and confirm no new exceptions.
