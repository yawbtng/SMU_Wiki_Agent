# URL Action Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the old Choose URLs table-first workflow with a compact Scrape-stage dashboard focused on core insights and next actions.

**Architecture:** Add a small pure helper module that summarizes discovered URL metadata and scrape manifest rows. Render that helper in `app.py` at the top of `Scrape`, and remove the separate pre-scrape Choose URLs tab.

**Tech Stack:** Python, Streamlit, pandas, pytest.

---

### Task 1: Summarize URL Action Insights

**Files:**
- Create: `src/scrape_planner/url_action_insights.py`
- Create: `tests/test_url_action_insights.py`

- [ ] **Step 1: Write failing tests for dashboard insight data**

Test that the helper reports discovered count, successful markdown count, failed count, thin successful count, failure actions, freshness buckets, and review samples.

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_url_action_insights.py -q`

Expected: fail because `src.scrape_planner.url_action_insights` does not exist.

- [ ] **Step 3: Implement the helper**

Create `build_url_action_dashboard(discovered_rows, manifest_rows, now=None, sample_limit=5)` returning a dictionary with `summary`, `failure_queue`, `freshness`, and `samples`.

- [ ] **Step 4: Run focused tests and confirm they pass**

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_url_action_insights.py -q`

Expected: pass.

### Task 2: Render the Compact Dashboard

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Import the helper**

Import `build_url_action_dashboard` near the other scrape planner imports.

- [ ] **Step 2: Load the latest scrape manifest for the active workspace**

Use the current run when available, otherwise the latest run directory under `data/sites/<site_id>/`.

- [ ] **Step 3: Render core details above the selection table**

Show metrics, recommended action, failure repair queue, freshness summary, and review samples. Put raw URL tables behind an `Advanced: raw URL tables` expander.

- [ ] **Step 4: Verify compile and runtime**

Run: `/usr/bin/python3 -m py_compile app.py src/scrape_planner/url_action_insights.py`

Run: `PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_url_action_insights.py -q`

Reload `http://localhost:8502/` in the in-app browser and confirm the `Scrape` tab shows the compact dashboard without a separate `Choose URLs` tab or new exceptions.
