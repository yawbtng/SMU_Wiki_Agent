# Scrape Internal Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the existing `Scrape` workflow page into focused internal tabs for overview, scraped pages, and failures so the UI stays clean for large scrape runs.

**Architecture:** Keep the top-level workflow as `Setup -> Discover -> Scrape -> Corpus -> Graph`. Inside the existing `Scrape` tab, compute the run status and page dataframe once, then render three Streamlit sub-tabs: `Overview`, `Scraped`, and `Failures`. Reuse the existing URL action dashboard, run-health metrics, retry actions, and dynamic pagination without changing scrape artifacts or worker behavior.

**Tech Stack:** Python 3.9, Streamlit, pandas, pytest.

---

### Task 1: Add Pure Scrape Table Helpers

**Files:**
- Create: `src/scrape_planner/scrape_ui_tables.py`
- Create: `tests/test_scrape_ui_tables.py`

- [ ] **Step 1: Write failing tests for table filtering helpers**

Create `tests/test_scrape_ui_tables.py`:

```python
import pandas as pd

from src.scrape_planner.scrape_ui_tables import filter_page_rows, page_table_columns


def test_filter_page_rows_filters_status_url_and_latest_only() -> None:
    rows = pd.DataFrame(
        [
            {
                "url": "https://www.smu.edu/a",
                "status": "success",
                "duration_sec": 1.0,
                "updated_at": pd.Timestamp("2026-05-21T10:00:00Z"),
                "status_rank": 2,
            },
            {
                "url": "https://www.smu.edu/b",
                "status": "failed",
                "duration_sec": 12.0,
                "updated_at": pd.Timestamp("2026-05-21T11:00:00Z"),
                "status_rank": 1,
            },
            {
                "url": "https://www.smu.edu/c",
                "status": "failed",
                "duration_sec": 2.0,
                "updated_at": pd.Timestamp("2026-05-21T09:00:00Z"),
                "status_rank": 1,
            },
        ]
    )

    result = filter_page_rows(
        rows,
        selected_statuses=["failed"],
        url_query="smu.edu",
        slow_threshold=10,
        latest_only=True,
        latest_limit=1,
    )

    assert result["url"].tolist() == ["https://www.smu.edu/b"]
    assert result["is_slow"].tolist() == [True]


def test_page_table_columns_returns_existing_columns_in_display_order() -> None:
    df = pd.DataFrame(
        [
            {
                "status": "success",
                "url": "https://www.smu.edu/a",
                "worker_id": "worker-1",
                "ignored": "x",
            }
        ]
    )

    assert page_table_columns(df) == ["status", "url", "worker_id"]
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run:

```bash
PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_scrape_ui_tables.py -q
```

Expected: fails with `ModuleNotFoundError: No module named 'src.scrape_planner.scrape_ui_tables'`.

- [ ] **Step 3: Implement the helper module**

Create `src/scrape_planner/scrape_ui_tables.py`:

```python
from __future__ import annotations

import pandas as pd


PAGE_TABLE_COLUMN_ORDER = [
    "status",
    "url",
    "worker_id",
    "fetch_mode",
    "http_status",
    "failure_reason",
    "attempt",
    "duration_sec",
    "is_slow",
    "updated_at_str",
]


def filter_page_rows(
    pages_df: pd.DataFrame,
    *,
    selected_statuses: list[str],
    url_query: str,
    slow_threshold: float,
    latest_only: bool,
    latest_limit: int = 250,
) -> pd.DataFrame:
    visible_df = pages_df.copy()
    if selected_statuses:
        visible_df = visible_df[visible_df["status"].isin(selected_statuses)]
    if url_query.strip():
        visible_df = visible_df[
            visible_df["url"].astype(str).str.contains(url_query.strip(), case=False, na=False)
        ]
    visible_df["is_slow"] = visible_df["duration_sec"] >= float(slow_threshold)
    if latest_only:
        return visible_df.sort_values(
            ["status_rank", "updated_at"],
            ascending=[True, False],
            na_position="last",
        ).head(latest_limit)
    return visible_df.sort_values(
        ["status_rank", "updated_at", "url"],
        ascending=[True, False, True],
        na_position="last",
    )


def page_table_columns(df: pd.DataFrame) -> list[str]:
    return [column for column in PAGE_TABLE_COLUMN_ORDER if column in df.columns]
```

- [ ] **Step 4: Run the focused test and confirm it passes**

Run:

```bash
PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_scrape_ui_tables.py -q
```

Expected: `2 passed`.

### Task 2: Refactor Scrape Into Internal Tabs

**Files:**
- Modify: `app.py`
- Test: existing compile and focused pytest checks

- [ ] **Step 1: Import helper functions**

Add near existing imports in `app.py`:

```python
from src.scrape_planner.scrape_ui_tables import filter_page_rows, page_table_columns
```

- [ ] **Step 2: Add internal tabs inside `with tabs[2]`**

After `selected_url_set = set(selected_url_strings)`, create:

```python
scrape_view_tabs = st.tabs(["Overview", "Scraped", "Failures"])
```

Render:

- `Overview`: `_render_url_action_dashboard(...)`, scrape controls, selected URL caption, run health metrics.
- `Scraped`: success/markdown table using only rows where `status == "success"`.
- `Failures`: failure repair queue, retry actions, failed table using only rows where `status == "failed"`.

- [ ] **Step 3: Keep data preparation shared**

Keep the existing run status/page dataframe construction once inside `if st.session_state["run_id"]:` before rendering sub-tab contents. Do not duplicate calls to `_load_scrape_runtime`.

- [ ] **Step 4: Move existing retry controls into `Failures`**

The existing `Quick Retry All Failed` and `Quick Tavily Retry` controls should appear only under `Failures`. Preserve `_start_quick_retry(...)` behavior and `retry_failed_with_tavily(...)` behavior exactly.

- [ ] **Step 5: Move the dynamic table into `Scraped` and `Failures`**

Use `filter_page_rows(...)` and `page_table_columns(...)` for both tables. The scraped table should default `selected_statuses=["success"]`; the failures table should default `selected_statuses=["failed"]`. Keep `Rows visible` dynamic pagination via `_render_paginated_df`.

- [ ] **Step 6: Compile check**

Run:

```bash
/usr/bin/python3 -m py_compile app.py src/scrape_planner/scrape_ui_tables.py
```

Expected: no output and exit code `0`.

- [ ] **Step 7: Focused tests**

Run:

```bash
PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_scrape_ui_tables.py tests/test_table_pagination.py tests/test_url_action_insights.py tests/test_wiki_planner.py tests/test_workspace_state.py -q
```

Expected: all tests pass.

### Task 3: Browser Verification

**Files:**
- No code files unless verification reveals a bug.

- [ ] **Step 1: Restart or reload Streamlit**

Use the active local app at `http://localhost:8502/`. If stale UI persists, restart Streamlit from `/Users/abhsheno/.codex/worktrees/67f9/ultra-fast-rag`.

- [ ] **Step 2: Verify top-level workflow**

Expected top-level tabs:

```text
Setup, Discover, Scrape, Corpus, Graph, Settings
```

There must be no top-level `Choose URLs`.

- [ ] **Step 3: Verify Scrape internal tabs**

Inside `Scrape`, verify internal tabs:

```text
Overview, Scraped, Failures
```

Expected default visible content:

- `Overview` has `Core URL Actions`, run controls, and run health.
- `Scraped` has a success-focused table and dynamic `Rows visible`.
- `Failures` has the failure repair queue, retry buttons, and a failed-pages table.

- [ ] **Step 4: Check for runtime exceptions**

Confirm browser DOM does not contain `Traceback`, `NameError`, or Streamlit exception blocks.

---

## Self-Review

- Spec coverage: covers the requested internal tabs for scraped content and failure actions while preserving the simplified top-level workflow.
- Placeholder scan: no placeholders or deferred decisions remain.
- Type consistency: helper function names and imports match the planned tests and implementation.
