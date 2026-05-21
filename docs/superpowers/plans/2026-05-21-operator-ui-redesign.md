# Operator UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the live Streamlit app into a trustworthy operator dashboard for source ingestion, scrape runs, corpus readiness, preview quality, wiki builds, retrieval health, and MCP setup.

**Architecture:** Keep Streamlit and the existing artifact pipeline. Extract focused UI data-model and rendering helpers from `app.py` so the top-level app reads as product sections instead of a long pile of widgets. Preserve existing capabilities while reorganizing navigation around operator decisions: Overview, Sources, Runs, Corpus, Wiki, Retrieval, Settings. Add a preview and corpus-quality layer so the UI can distinguish "we have chunks/vectors" from "the chunks are actually useful for retrieval."

**Tech Stack:** Python 3, Streamlit, pandas, Altair, pytest, existing `src/scrape_planner/*` modules, local JSON/JSONL artifacts under `data/sites/<site_id>/`.

---

## Scope

This plan targets the live checkout served by `http://127.0.0.1:8501`:

- `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`

Do not implement this against `/Users/abhsheno/.codex/worktrees/f98b/ultra-fast-rag` unless the running Streamlit server is intentionally switched to that checkout first.

The live checkout is currently dirty. Do not revert unrelated changes. Work with the current state.

## Current Problems To Fix

- `Workspace` shows `Run State: running`, while `Sources` shows `State: stopped`; the app needs one canonical run truth.
- `Raw Data Sources` leads with all-zero registry metrics, even though PDF extraction has real output: `1,165` pages and `3,752` chunks.
- `Sources` mixes intake, PDF upload, scrape controls, run progress, details, and recent previews.
- `MCP Query` contains `Settings`, which makes the final tab feel like an advanced/debug drawer.
- File paths, tmux session names, JSON snippets, and logs appear too early.
- `Embed + Rerank` has the strongest dashboard feel; its chart/metric pattern should influence Overview, Runs, and Retrieval.
- Browser testing found repeated `Open preview` links that navigated to a preview route showing only Streamlit chrome/`Deploy`, not scraped content.
- Preview navigation can leave the app partially rendered when returning to the root page, so preview routes need explicit smoke coverage.
- `Embedding chunks` previews are not trustworthy enough: chunk samples can look logically incoherent even when extraction and embedding counts exist.
- Retrieval readiness currently risks over-trusting vector existence. The UI must require corpus/chunk quality before presenting retrieval as ready.

## Proposed Navigation

Replace:

```python
WORKFLOW_TABS = [
    "Workspace",
    "Sources",
    "Raw Data Sources",
    "LLM Wiki",
    "Embed + Rerank",
    "MCP Query",
]
```

With:

```python
WORKFLOW_TABS = [
    "Overview",
    "Sources",
    "Runs",
    "Corpus",
    "Wiki",
    "Retrieval",
    "Settings",
]
```

## File Structure

- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/src/scrape_planner/ui_navigation.py`
  - Owns product tab labels.
- Create: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/src/scrape_planner/ui_operator_status.py`
  - Owns canonical status view models and helpers.
- Create: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/src/scrape_planner/ui_operator_components.py`
  - Owns small reusable Streamlit render helpers: status pills, hero status band, metric cards, section headers, detail expanders.
- Create: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/src/scrape_planner/ui_preview_quality.py`
  - Owns preview contracts, preview-route health checks, chunk quality scoring, and content-inspector view models.
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/app.py`
  - Replaces tab bodies with the new operator layout while reusing existing backend functions.
- Modify or create tests:
  - `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_operator_status.py`
  - `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_operator_navigation_ui.py`
  - `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_scrape_tab_ui.py`
  - `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_pdf_sources_ui.py`
  - `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_preview_quality.py`
  - `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_preview_routes.py`
  - `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_stepper_ui.py`

## Task 1: Canonical Operator Status Model

**Files:**
- Create: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/src/scrape_planner/ui_operator_status.py`
- Create: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_operator_status.py`
- Read: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/app.py`
- Read: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/src/scrape_planner/stepper_status.py`

- [ ] **Step 1: Write failing tests for canonical run state**

Create `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_operator_status.py`:

```python
from __future__ import annotations

from src.scrape_planner.ui_operator_status import (
    build_operator_run_status,
    build_operator_source_status,
)


def test_stale_running_status_becomes_paused_when_no_live_runner_exists() -> None:
    status = build_operator_run_status(
        state="running",
        done=18725,
        total=25376,
        running=0,
        failed=1341,
        queued=6651,
        has_live_runner=False,
    )

    assert status.state == "paused"
    assert status.state_label == "Paused"
    assert status.primary_action == "Resume run"
    assert status.attention_level == "warning"
    assert "not actively scraping" in status.message


def test_active_running_status_stays_running_when_live_runner_exists() -> None:
    status = build_operator_run_status(
        state="running",
        done=18725,
        total=25376,
        running=4,
        failed=1341,
        queued=6651,
        has_live_runner=True,
    )

    assert status.state == "running"
    assert status.state_label == "Running"
    assert status.primary_action == "Monitor run"
    assert status.attention_level == "active"


def test_pdf_extraction_counts_promote_real_progress_even_without_registry() -> None:
    status = build_operator_source_status(
        selected_url_count=25379,
        pdf_count=1,
        raw_source_count=0,
        raw_ready_count=0,
        raw_failed_count=0,
        raw_review_count=0,
        pdf_page_count=1165,
        pdf_chunk_count=3752,
    )

    assert status.readiness == "partially prepared"
    assert status.primary_count == 25379
    assert status.pdf_detail == "1 PDF, 1,165 pages, 3,752 chunks"
    assert status.message == "PDF extraction is ready; raw source normalization is still pending."
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_operator_status.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'src.scrape_planner.ui_operator_status'
```

- [ ] **Step 3: Implement minimal status dataclasses and builders**

Create `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/src/scrape_planner/ui_operator_status.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OperatorRunStatus:
    state: str
    state_label: str
    primary_action: str
    attention_level: str
    message: str
    done: int
    total: int
    running: int
    failed: int
    queued: int


@dataclass(frozen=True)
class OperatorSourceStatus:
    readiness: str
    primary_count: int
    pdf_detail: str
    message: str
    selected_url_count: int
    pdf_count: int
    raw_source_count: int
    raw_ready_count: int
    raw_failed_count: int
    raw_review_count: int
    pdf_page_count: int
    pdf_chunk_count: int


def _label(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").strip().title()


def build_operator_run_status(
    *,
    state: str,
    done: int,
    total: int,
    running: int,
    failed: int,
    queued: int,
    has_live_runner: bool,
) -> OperatorRunStatus:
    normalized = (state or "none").strip().lower()
    if normalized in {"running", "pausing", "initializing"} and not has_live_runner:
        return OperatorRunStatus(
            state="paused",
            state_label="Paused",
            primary_action="Resume run",
            attention_level="warning",
            message="This run is not actively scraping. Resume it to continue from saved progress.",
            done=done,
            total=total,
            running=0,
            failed=failed,
            queued=queued,
        )
    if normalized == "running":
        return OperatorRunStatus(
            state="running",
            state_label="Running",
            primary_action="Monitor run",
            attention_level="active",
            message="Scrape is actively processing queued sources.",
            done=done,
            total=total,
            running=running,
            failed=failed,
            queued=queued,
        )
    if normalized in {"completed", "complete"}:
        return OperatorRunStatus(
            state="completed",
            state_label="Completed",
            primary_action="Review results",
            attention_level="ready",
            message="Scrape finished. Review failures and prepare corpus sources.",
            done=done,
            total=total,
            running=0,
            failed=failed,
            queued=queued,
        )
    return OperatorRunStatus(
        state=normalized,
        state_label=_label(normalized),
        primary_action="Start run" if total else "Add sources",
        attention_level="neutral",
        message="Run is ready to start." if total else "Add sources before starting a run.",
        done=done,
        total=total,
        running=running,
        failed=failed,
        queued=queued,
    )


def build_operator_source_status(
    *,
    selected_url_count: int,
    pdf_count: int,
    raw_source_count: int,
    raw_ready_count: int,
    raw_failed_count: int,
    raw_review_count: int,
    pdf_page_count: int,
    pdf_chunk_count: int,
) -> OperatorSourceStatus:
    pdf_detail = f"{pdf_count:,} PDF, {pdf_page_count:,} pages, {pdf_chunk_count:,} chunks"
    if pdf_count != 1:
        pdf_detail = f"{pdf_count:,} PDFs, {pdf_page_count:,} pages, {pdf_chunk_count:,} chunks"
    readiness = "ready" if raw_ready_count > 0 and raw_failed_count == 0 and raw_review_count == 0 else "not ready"
    message = "Normalize scraped pages, PDFs, or tabular files to prepare the corpus."
    if raw_source_count == 0 and pdf_page_count > 0:
        readiness = "partially prepared"
        message = "PDF extraction is ready; raw source normalization is still pending."
    elif raw_failed_count or raw_review_count:
        readiness = "needs review"
        message = "Some sources need review before wiki and retrieval work."
    elif readiness == "ready":
        message = "Prepared sources are ready for wiki and retrieval work."

    return OperatorSourceStatus(
        readiness=readiness,
        primary_count=selected_url_count,
        pdf_detail=pdf_detail,
        message=message,
        selected_url_count=selected_url_count,
        pdf_count=pdf_count,
        raw_source_count=raw_source_count,
        raw_ready_count=raw_ready_count,
        raw_failed_count=raw_failed_count,
        raw_review_count=raw_review_count,
        pdf_page_count=pdf_page_count,
        pdf_chunk_count=pdf_chunk_count,
    )
```

- [ ] **Step 4: Run tests**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_operator_status.py -v
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit**

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git add src/scrape_planner/ui_operator_status.py tests/test_operator_status.py
git commit -m "feat: add canonical operator status model"
```

## Task 2: Navigation And Page Ownership

**Files:**
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/src/scrape_planner/ui_navigation.py`
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/app.py`
- Create: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_operator_navigation_ui.py`

- [ ] **Step 1: Write failing navigation tests**

Create `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_operator_navigation_ui.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "app.py"
NAV_SOURCE = ROOT / "src" / "scrape_planner" / "ui_navigation.py"


def test_operator_navigation_uses_decision_oriented_tabs() -> None:
    source = NAV_SOURCE.read_text(encoding="utf-8")

    expected = [
        '"Overview"',
        '"Sources"',
        '"Runs"',
        '"Corpus"',
        '"Wiki"',
        '"Retrieval"',
        '"Settings"',
    ]
    for label in expected:
        assert label in source

    removed = ['"Workspace"', '"Raw Data Sources"', '"LLM Wiki"', '"Embed + Rerank"', '"MCP Query"']
    for label in removed:
        assert label not in source


def test_settings_is_not_rendered_inside_mcp_query_tab() -> None:
    app = APP_SOURCE.read_text(encoding="utf-8")

    assert 'st.subheader("Settings")' in app
    assert 'with tabs[6]:' in app
    mcp_start = app.find('st.subheader("MCP Query")')
    settings_start = app.find('st.subheader("Settings")')
    assert mcp_start == -1 or settings_start < mcp_start or 'with tabs[6]:' in app[settings_start - 200:settings_start]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_operator_navigation_ui.py -v
```

Expected: FAIL because old labels still exist.

- [ ] **Step 3: Update navigation labels**

Modify `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/src/scrape_planner/ui_navigation.py`:

```python
from __future__ import annotations

WORKFLOW_TABS = [
    "Overview",
    "Sources",
    "Runs",
    "Corpus",
    "Wiki",
    "Retrieval",
    "Settings",
]
```

- [ ] **Step 4: Create tab placeholders in app.py**

In `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/app.py`, preserve the existing content but move each major body under the new index:

```python
tabs = st.tabs(WORKFLOW_TABS)

with tabs[0]:
    st.subheader("Overview")
    # Existing Workspace content moves here.

with tabs[1]:
    st.subheader("Sources")
    # Source intake and PDF upload remain here.

with tabs[2]:
    st.subheader("Runs")
    # Current Run controls and scrape activity move here.

with tabs[3]:
    st.subheader("Corpus")
    # Existing Raw Data Sources content moves here.

with tabs[4]:
    st.subheader("Wiki")
    # Existing LLM Wiki content moves here.

with tabs[5]:
    st.subheader("Retrieval")
    # Existing Embed + Rerank, metrics, MCP readiness move here.

with tabs[6]:
    st.subheader("Settings")
    # Existing Settings content moves here.
```

Do not remove backend calls during this task. Only move top-level ownership.

- [ ] **Step 5: Run navigation tests**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_operator_navigation_ui.py tests/test_workspace_navigation_ui.py -v
```

Expected:

```text
passed
```

- [ ] **Step 6: Commit**

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git add src/scrape_planner/ui_navigation.py app.py tests/test_operator_navigation_ui.py
git commit -m "feat: reorganize operator navigation"
```

## Task 3: Reusable Streamlit Operator Components

**Files:**
- Create: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/src/scrape_planner/ui_operator_components.py`
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/app.py`
- Create: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_operator_components.py`

- [ ] **Step 1: Write source-level tests for component contracts**

Create `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_operator_components.py`:

```python
from pathlib import Path


COMPONENTS = Path(__file__).resolve().parents[1] / "src" / "scrape_planner" / "ui_operator_components.py"


def test_operator_components_define_dashboard_helpers() -> None:
    source = COMPONENTS.read_text(encoding="utf-8")

    assert "def render_status_band(" in source
    assert "def render_metric_strip(" in source
    assert "def render_operator_details(" in source
    assert "def status_badge_html(" in source
    assert "border-radius: 8px" in source
    assert "Operator Details" in source
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_operator_components.py -v
```

Expected: FAIL because the file does not exist.

- [ ] **Step 3: Add reusable rendering helpers**

Create `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/src/scrape_planner/ui_operator_components.py`:

```python
from __future__ import annotations

from collections.abc import Iterable, Mapping
from html import escape
from typing import Any

import streamlit as st


_STATUS_COLORS = {
    "active": ("#0f766e", "#ecfdf5"),
    "ready": ("#166534", "#f0fdf4"),
    "warning": ("#92400e", "#fffbeb"),
    "danger": ("#991b1b", "#fef2f2"),
    "neutral": ("#475569", "#f8fafc"),
}


def status_badge_html(label: str, tone: str = "neutral") -> str:
    fg, bg = _STATUS_COLORS.get(tone, _STATUS_COLORS["neutral"])
    return (
        '<span style="'
        "display:inline-flex;align-items:center;gap:6px;"
        "border-radius: 8px;"
        "padding:4px 9px;"
        f"color:{fg};background:{bg};"
        "font-size:0.82rem;font-weight:650;"
        f'">{escape(label)}</span>'
    )


def render_status_band(*, title: str, subtitle: str, status_label: str, tone: str, action_label: str | None = None) -> None:
    st.markdown(
        f"""
        <div style="border:1px solid #d8dee8;border-radius: 8px;padding:18px 20px;margin:8px 0 18px 0;background:#ffffff;">
          <div style="display:flex;justify-content:space-between;gap:16px;align-items:flex-start;">
            <div>
              <div style="font-size:1.05rem;font-weight:750;color:#0f172a;">{escape(title)}</div>
              <div style="font-size:0.9rem;color:#475569;margin-top:4px;">{escape(subtitle)}</div>
            </div>
            <div>{status_badge_html(status_label, tone)}</div>
          </div>
          {f'<div style="margin-top:12px;font-weight:650;color:#0f172a;">Next: {escape(action_label)}</div>' if action_label else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_strip(metrics: Iterable[Mapping[str, Any]]) -> None:
    rows = list(metrics)
    if not rows:
        return
    cols = st.columns(len(rows))
    for col, metric in zip(cols, rows):
        col.metric(str(metric["label"]), str(metric["value"]), delta=metric.get("delta"))


def render_operator_details(label: str, body: Mapping[str, Any] | str, *, expanded: bool = False) -> None:
    with st.expander(label or "Operator Details", expanded=expanded):
        if isinstance(body, str):
            st.code(body, language="text")
        else:
            st.json(dict(body))
```

- [ ] **Step 4: Run component tests**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_operator_components.py -v
```

Expected:

```text
1 passed
```

- [ ] **Step 5: Commit**

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git add src/scrape_planner/ui_operator_components.py tests/test_operator_components.py
git commit -m "feat: add operator UI components"
```

## Task 4: Overview Command Center

**Files:**
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/app.py`
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_stepper_ui.py`
- Modify or create: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_operator_navigation_ui.py`

- [ ] **Step 1: Add tests for Overview content**

Append to `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_operator_navigation_ui.py`:

```python
def test_overview_is_command_center_not_file_path_dump() -> None:
    app = APP_SOURCE.read_text(encoding="utf-8")
    start = app.index("with tabs[0]:")
    end = app.index("with tabs[1]:", start)
    overview = app[start:end]

    assert 'st.subheader("Overview")' in overview
    assert "render_status_band" in overview
    assert "build_operator_run_status" in overview
    assert "build_operator_source_status" in overview
    assert "Attention Needed" in overview
    assert "Registry path:" not in overview
    assert "tmux session:" not in overview
    assert "Server command" not in overview
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_operator_navigation_ui.py -v
```

Expected: FAIL until Overview uses the new helpers.

- [ ] **Step 3: Import helpers in app.py**

Add near existing imports:

```python
from src.scrape_planner.ui_operator_components import (
    render_metric_strip,
    render_operator_details,
    render_status_band,
)
from src.scrape_planner.ui_operator_status import (
    build_operator_run_status,
    build_operator_source_status,
)
```

- [ ] **Step 4: Replace Workspace body with Overview status bands**

Inside `with tabs[0]:`, use this structure:

```python
st.subheader("Overview")
render_status_band(
    title=f"{active_ws.get('name', 'Workspace')} operations",
    subtitle=f"{active_ws.get('url') or st.session_state.get('site_url') or 'No site URL'}",
    status_label=operator_run.state_label,
    tone=operator_run.attention_level,
    action_label=operator_run.primary_action,
)

render_metric_strip(
    [
        {"label": "Run Progress", "value": f"{operator_run.done:,}/{operator_run.total:,}"},
        {"label": "Running", "value": f"{operator_run.running:,}"},
        {"label": "Failures", "value": f"{operator_run.failed:,}"},
        {"label": "Queued", "value": f"{operator_run.queued:,}"},
    ]
)

render_status_band(
    title="Source readiness",
    subtitle=operator_sources.message,
    status_label=operator_sources.readiness.title(),
    tone="ready" if operator_sources.readiness == "ready" else "warning",
    action_label="Normalize corpus" if operator_sources.readiness != "ready" else "Build wiki",
)

render_metric_strip(
    [
        {"label": "Selected URLs", "value": f"{operator_sources.selected_url_count:,}"},
        {"label": "PDF Extraction", "value": operator_sources.pdf_detail},
        {"label": "Raw Sources", "value": f"{operator_sources.raw_source_count:,}"},
        {"label": "Needs Review", "value": f"{operator_sources.raw_review_count:,}"},
    ]
)
```

Use existing local variables from the current Workspace block to populate `operator_run` and `operator_sources`. Use `runner.has_live_run(site_id, run_id)` for `has_live_runner`.

- [ ] **Step 5: Keep attention table compact**

Keep the existing `Attention Needed` expander, but restrict rows to source title, kind, status, and reason. Do not show raw paths on Overview.

- [ ] **Step 6: Run focused tests**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_operator_status.py tests/test_operator_components.py tests/test_operator_navigation_ui.py -v
```

Expected:

```text
passed
```

- [ ] **Step 7: Commit**

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git add app.py tests/test_operator_navigation_ui.py
git commit -m "feat: add operator overview dashboard"
```

## Task 5: Split Sources And Runs

**Files:**
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/app.py`
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_scrape_tab_ui.py`
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_pdf_sources_ui.py`

- [ ] **Step 1: Update tests for separated page ownership**

Modify `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_scrape_tab_ui.py` so `_scrape_tab_source()` extracts `with tabs[2]:` to `with tabs[3]:`:

```python
def _scrape_tab_source() -> str:
    source = APP_SOURCE.read_text(encoding="utf-8")
    start = source.index("with tabs[2]:")
    end = source.index("with tabs[3]:", start)
    return source[start:end]
```

Append:

```python
def test_runs_tab_owns_run_controls_and_sources_does_not() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")
    sources_start = source.index("with tabs[1]:")
    sources_end = source.index("with tabs[2]:", sources_start)
    sources_tab = source[sources_start:sources_end]
    runs_tab = _scrape_tab_source()

    assert 'st.subheader("Runs")' in runs_tab
    assert "Start New Scrape" in runs_tab
    assert "Resume" in runs_tab
    assert "Pause" in runs_tab
    assert "Cancel" in runs_tab
    assert "Start New Scrape" not in sources_tab
    assert "Pause" not in sources_tab
    assert "Cancel" not in sources_tab
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_scrape_tab_ui.py tests/test_pdf_sources_ui.py -v
```

Expected: FAIL until run controls move.

- [ ] **Step 3: Keep Sources focused on intake**

In `with tabs[1]:`, keep:

```python
st.subheader("Sources")
```

Sources should include:

- `Source Inventory`
- Website URL metrics
- PDF document metrics
- source freshness summary when available
- `Refresh Sitemap URLs`
- manual URL paste/add
- `Upload PDFs`
- `Extract / Re-extract PDFs`
- a compact “Prepared sources” card

Sources should not include:

- `Start New Scrape`
- `Resume`
- `Pause`
- `Cancel`
- run progress bar
- recent scraped page previews

- [ ] **Step 4: Move run controls into Runs**

Create `with tabs[2]:` content:

```python
st.subheader("Runs")
render_status_band(
    title="Scrape run",
    subtitle=operator_run.message,
    status_label=operator_run.state_label,
    tone=operator_run.attention_level,
    action_label=operator_run.primary_action,
)
```

Then move existing current run controls here:

- `Start New Scrape`
- `Resume`
- `Pause`
- `Cancel`
- `Refresh`
- `Auto-refresh every 1s`
- progress bar
- state/success/failed/remaining/ETA metrics
- discovery details expander
- scrape activity details expander
- recently scraped previews

- [ ] **Step 5: Rename stale warning**

Replace old copy:

```python
This run is not actively scraping right now. Click Resume to continue from the saved disk state.
```

With:

```python
This run is paused in the UI. Resume it to continue from saved progress.
```

This keeps the status honest without sounding broken.

- [ ] **Step 6: Run focused tests**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_scrape_tab_ui.py tests/test_pdf_sources_ui.py tests/test_operator_status.py -v
```

Expected:

```text
passed
```

- [ ] **Step 7: Commit**

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git add app.py tests/test_scrape_tab_ui.py tests/test_pdf_sources_ui.py
git commit -m "feat: split source intake from run operations"
```

## Task 6: Corpus Page That Shows Real Prepared Data

**Files:**
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/app.py`
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_pdf_sources_ui.py`
- Create: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_preview_quality.py`

- [ ] **Step 1: Add corpus tests**

Append to `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_pdf_sources_ui.py`:

```python
def test_corpus_tab_promotes_pdf_extraction_progress() -> None:
    source = APP_PATH.read_text(encoding="utf-8")
    start = source.index("with tabs[3]:")
    end = source.index("with tabs[4]:", start)
    corpus = source[start:end]

    assert 'st.subheader("Corpus")' in corpus
    assert "PDF extraction" in corpus
    assert "Pages extracted" in corpus
    assert "Search chunks" in corpus
    assert "Chunk quality" in corpus
    assert "Content Inspector" in corpus
    assert "Registry path:" in corpus
    assert "Operator Details" in corpus
    assert "Raw Data Sources" not in corpus
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_pdf_sources_ui.py -v
```

Expected: FAIL until the tab is renamed and reorganized.

- [ ] **Step 3: Rename Raw Data Sources to Corpus**

Change:

```python
st.subheader("Raw Data Sources")
```

To:

```python
st.subheader("Corpus")
```

- [ ] **Step 4: Promote PDF extraction data**

At the top of Corpus, render PDF extraction metrics before registry metrics:

```python
render_metric_strip(
    [
        {"label": "PDF Pages", "value": f"{len(page_rows):,}"},
        {"label": "Search Chunks", "value": f"{len(chunk_rows):,}"},
        {"label": "PDF Review", "value": f"{len(quarantine_rows):,}"},
        {"label": "Raw Sources", "value": f"{len(raw_status['rows']):,}"},
        {"label": "Raw Ready", "value": f"{int(counts_by_status.get('ready', 0)):,}"},
    ]
)
```

- [ ] **Step 5: Move file paths into Operator Details**

Replace visible path captions:

```python
st.caption(f"Registry path: `{layout.registry_path}`")
```

With:

```python
render_operator_details(
    "Operator Details",
    {
        "registry_path": str(layout.registry_path),
        "latest_report_path": str(latest_report_path or ""),
    },
)
```

- [ ] **Step 6: Keep preview controls but reduce first-screen clutter**

Keep:

- `Page-by-page markdown`
- `Embedding chunks`
- `PDF review queue`
- PDF/web source cards

Make the default expanded behavior:

```python
with st.expander("PDF extraction", expanded=bool(page_rows)):
```

Use `expanded=False` for `Embedding chunks` and `PDF review queue` unless there are review rows.

- [ ] **Step 7: Add chunk quality tests**

Create `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_preview_quality.py`:

```python
from __future__ import annotations

from src.scrape_planner.ui_preview_quality import (
    build_chunk_quality_summary,
    classify_chunk_sample,
)


def test_short_headingless_chunk_is_flagged_as_low_quality() -> None:
    result = classify_chunk_sample(
        text="Apply now",
        source_title="Admissions",
        section_path=[],
        previous_text="",
        next_text="",
    )

    assert result.quality == "poor"
    assert "too_short" in result.flags
    assert "missing_section_context" in result.flags


def test_pdf_header_fragment_is_flagged_as_boilerplate() -> None:
    result = classify_chunk_sample(
        text="Southern Methodist University Undergraduate Catalog 2024-2025 Page 17",
        source_title="Catalog",
        section_path=["Catalog"],
        previous_text="",
        next_text="",
    )

    assert result.quality in {"poor", "needs_review"}
    assert "boilerplate" in result.flags


def test_good_chunk_includes_reason_and_context() -> None:
    result = classify_chunk_sample(
        text=(
            "Students applying to the Cox School of Business must complete the university "
            "application, submit official transcripts, and meet program-specific prerequisites."
        ),
        source_title="Cox Admissions",
        section_path=["Admissions", "Undergraduate Requirements"],
        previous_text="Admission overview",
        next_text="Application deadlines",
    )

    assert result.quality == "good"
    assert result.reason
    assert result.context_label == "Admissions > Undergraduate Requirements"


def test_quality_summary_blocks_ready_state_when_bad_samples_dominate() -> None:
    summary = build_chunk_quality_summary(
        [
            {"text": "Apply now", "source_title": "Admissions", "section_path": []},
            {"text": "Page 17", "source_title": "Catalog", "section_path": ["Catalog"]},
            {
                "text": "Financial aid applications require FAFSA submission and school-specific forms.",
                "source_title": "Financial Aid",
                "section_path": ["Financial Aid"],
            },
        ]
    )

    assert summary.readiness == "needs_review"
    assert summary.poor_count == 2
    assert summary.ready_for_retrieval is False
```

- [ ] **Step 8: Implement preview quality model**

Create `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/src/scrape_planner/ui_preview_quality.py` with small dataclasses and deterministic heuristics. This is not a full embedding rewrite; it is a UI quality gate that makes bad chunks visible.

Required model:

```python
@dataclass(frozen=True)
class ChunkQuality:
    quality: str
    flags: tuple[str, ...]
    reason: str
    context_label: str
    char_count: int


@dataclass(frozen=True)
class ChunkQualitySummary:
    readiness: str
    ready_for_retrieval: bool
    total: int
    good_count: int
    needs_review_count: int
    poor_count: int
    top_flags: tuple[str, ...]
```

Required flags:

- `too_short`
- `missing_section_context`
- `boilerplate`
- `likely_navigation`
- `duplicate_like`
- `table_fragment`
- `split_mid_sentence`

The first implementation may use deterministic text heuristics only. Do not call an LLM or embedding provider from these tests.

- [ ] **Step 9: Replace raw chunk dump with Content Inspector**

In the Corpus page, replace the repeated raw chunk preview pattern with one consistent section:

```python
st.markdown("### Content Inspector")
st.caption("Preview extracted pages and chunks before trusting them for wiki or retrieval.")
```

For each selected chunk sample, show:

- source title
- source URL or PDF page
- section path
- surrounding context
- character or token count
- quality badge
- flags
- reason the chunk is considered good, needs review, or poor

Do not present embedding chunks as a success state by count alone.

- [ ] **Step 10: Add Chunk quality panel**

At the top of Corpus, after PDF extraction metrics, render:

```python
st.markdown("### Chunk quality")
```

Show:

- total sampled chunks
- good chunks
- needs-review chunks
- poor chunks
- top quality flags
- `Ready for retrieval` only when poor chunks are below the threshold and section/source context exists

If chunk quality cannot be computed, show `Unknown` and make the next action `Inspect sample chunks`, not `Embed`.

- [ ] **Step 11: Run tests**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_pdf_sources_ui.py tests/test_operator_components.py tests/test_preview_quality.py -v
```

Expected:

```text
passed
```

- [ ] **Step 12: Commit**

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git add app.py src/scrape_planner/ui_preview_quality.py tests/test_pdf_sources_ui.py tests/test_preview_quality.py
git commit -m "feat: promote corpus and chunk quality readiness"
```

## Task 6A: Preview Route Reliability

**Files:**
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/app.py`
- Modify or create: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_preview_routes.py`
- Read: existing scraped-page preview route handling in `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/app.py`

Browser audit finding: a generated `Open preview` URL for a scraped page loaded a route like `/?view=scraped_page&site_id=...&run_id=...&page_slug=...` but rendered only Streamlit chrome/`Deploy`, not the scraped page. This task makes preview functionality a tested contract.

- [ ] **Step 1: Add preview route contract tests**

Create `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_preview_routes.py`:

```python
from pathlib import Path


APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"


def test_scraped_page_preview_route_has_real_content_contract() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "view" in source
    assert "scraped_page" in source
    assert "page_slug" in source
    assert "Back to" in source or "st.page_link" in source
    assert "Source URL" in source
    assert "Extracted content" in source or "Markdown preview" in source


def test_preview_links_are_not_rendered_as_repetitive_raw_rows() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "Content Inspector" in source
    assert source.count("Open preview") <= 2
    assert "Recently scraped" in source
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_preview_routes.py -v
```

Expected: FAIL until preview routes and repeated preview links are fixed.

- [ ] **Step 3: Make scraped-page preview route explicit**

When query params request `view=scraped_page`, render a dedicated preview page before the normal tab dashboard:

```python
st.subheader("Scraped page preview")
```

Required visible fields:

- page title
- source URL
- scrape status
- run id
- page slug
- extracted markdown or text
- metadata summary
- clear `Back to Runs` or `Back to Corpus` action

If the artifact is missing, render a useful not-found state with the expected path behind `Operator Details`.

- [ ] **Step 4: Collapse repeated preview links into a table or inspector**

In Runs, replace long repeated `Open preview` blocks with a compact table/list:

- title
- status
- source URL
- scraped timestamp
- preview action

The page should not show dozens of identical `Open preview` controls stacked with raw URL pairs.

- [ ] **Step 5: Add PDF/chunk preview contracts**

The same `Content Inspector` pattern must support:

- scraped web page preview
- PDF page markdown preview
- embedding/chunk sample preview
- wiki page preview when wiki artifacts exist

Each preview type must show what source artifact it came from and why it is ready, blocked, or needs review.

- [ ] **Step 6: Browser smoke test previews**

Using the in-app browser at `http://127.0.0.1:8501`, verify:

- a scraped page preview URL renders real content, not only Streamlit chrome/`Deploy`
- the preview page has a visible back action
- returning to `/` restores the dashboard
- Corpus `Content Inspector` shows chunk context and quality flags
- browser console has no new errors

- [ ] **Step 7: Run tests**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_preview_routes.py tests/test_preview_quality.py tests/test_pdf_sources_ui.py -v
```

Expected:

```text
passed
```

- [ ] **Step 8: Commit**

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git add app.py src/scrape_planner/ui_preview_quality.py tests/test_preview_routes.py tests/test_preview_quality.py tests/test_pdf_sources_ui.py
git commit -m "fix: make content previews reliable"
```

## Task 7: Wiki Page Cleanup

**Files:**
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/app.py`
- Create or modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_wiki_ui.py`

- [ ] **Step 1: Write wiki UI tests**

Create `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_wiki_ui.py`:

```python
from pathlib import Path


APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"


def test_wiki_tab_hides_logs_and_paths_by_default() -> None:
    app = APP_SOURCE.read_text(encoding="utf-8")
    start = app.index("with tabs[4]:")
    end = app.index("with tabs[5]:", start)
    wiki = app[start:end]

    assert 'st.subheader("Wiki")' in wiki
    assert "render_status_band" in wiki
    assert "Live wiki build logs" in wiki
    assert "expanded=False" in wiki
    assert "Operator Details" in wiki
    assert "tmux session:" not in wiki
    assert "Log path:" not in wiki
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_wiki_ui.py -v
```

Expected: FAIL until Wiki is reorganized.

- [ ] **Step 3: Rename and add status band**

Change:

```python
st.subheader("LLM Wiki")
```

To:

```python
st.subheader("Wiki")
```

Add:

```python
wiki_tone = "ready" if _wiki_ready(wiki_status) else "warning"
render_status_band(
    title="Wiki build",
    subtitle="Build grounded pages from prepared corpus sources.",
    status_label=str(wiki_status["job_status"]).replace("-", " ").title(),
    tone=wiki_tone,
    action_label="Build wiki" if raw_sources_ready else "Prepare corpus",
)
```

- [ ] **Step 4: Hide paths and tmux behind Operator Details**

Replace visible captions for tmux/log/index/review queue paths with:

```python
render_operator_details(
    "Operator Details",
    {
        "tmux_session": wiki_status["tmux_session"],
        "log_path": wiki_status["log_path"],
        "index_path": wiki_status["index_path"],
        "review_queue_path": wiki_status["review_queue_path"],
        "latest_report_path": wiki_status.get("latest_report_path") or "",
    },
)
```

- [ ] **Step 5: Collapse logs by default**

Change:

```python
with st.expander("Live wiki build logs", expanded=True):
```

To:

```python
with st.expander("Live wiki build logs", expanded=False):
```

- [ ] **Step 6: Run tests**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_wiki_ui.py tests/test_operator_components.py -v
```

Expected:

```text
passed
```

- [ ] **Step 7: Commit**

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git add app.py tests/test_wiki_ui.py
git commit -m "feat: clean up wiki operations page"
```

## Task 8: Retrieval Page And MCP Readiness

**Files:**
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/app.py`
- Create or modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_retrieval_ui.py`

- [ ] **Step 1: Write retrieval UI tests**

Create `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_retrieval_ui.py`:

```python
from pathlib import Path


APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"


def test_retrieval_tab_combines_metrics_and_mcp_readiness() -> None:
    app = APP_SOURCE.read_text(encoding="utf-8")
    start = app.index("with tabs[5]:")
    end = app.index("with tabs[6]:", start)
    retrieval = app[start:end]

    assert 'st.subheader("Retrieval")' in retrieval
    assert "Scrape Analytics Charts" in retrieval
    assert "Index Health" in retrieval
    assert "Chunk quality" in retrieval
    assert "ready_for_retrieval" in retrieval
    assert "MCP readiness" in retrieval
    assert "Server command" in retrieval
    assert "Operator Details" in retrieval
    assert 'st.subheader("Settings")' not in retrieval
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_retrieval_ui.py -v
```

Expected: FAIL until retrieval and MCP readiness are combined.

- [ ] **Step 3: Rename Embed + Rerank to Retrieval**

Change:

```python
st.subheader("Embed + Rerank")
```

To:

```python
st.subheader("Retrieval")
```

- [ ] **Step 4: Keep metrics and charts**

Preserve the existing `Metrics` block, run selector, run summary, performance metrics, content volume, scrape analytics charts, slowest pages table, and OpenRouter LLM metrics.

- [ ] **Step 5: Add chunk quality gate before index readiness**

Retrieval must not show a simple green/ready state just because embeddings or vector artifacts exist.

Before `Index Health`, render:

```python
st.markdown("### Chunk quality")
```

Use the `ChunkQualitySummary` from `ui_preview_quality.py`.

Rules:

- If `ready_for_retrieval is False`, show Retrieval as `Blocked` or `Needs review`.
- If quality is unknown, show `Unknown` and route the next action to Corpus `Content Inspector`.
- If poor chunks dominate sampled chunks, show the top flags and do not recommend embedding.
- If vectors exist but chunk quality is poor, say `Vectors exist, but source chunks need review before retrieval can be trusted.`

- [ ] **Step 6: Move MCP readiness above settings**

Move the MCP prerequisite/status section from the old `MCP Query` tab into Retrieval after index metrics:

```python
st.markdown("### MCP readiness")
```

Use `render_operator_details("Operator Details", {...})` for:

- server command
- expected server command
- config snippet
- latest MCP report path

- [ ] **Step 7: Run tests**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_retrieval_ui.py tests/test_run_analytics_metrics.py tests/test_llm_wiki_mcp.py tests/test_preview_quality.py -v
```

Expected:

```text
passed
```

- [ ] **Step 8: Commit**

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git add app.py src/scrape_planner/ui_preview_quality.py tests/test_retrieval_ui.py tests/test_preview_quality.py
git commit -m "feat: gate retrieval readiness on chunk quality"
```

## Task 9: Standalone Settings Page

**Files:**
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/app.py`
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_operator_navigation_ui.py`

- [ ] **Step 1: Add settings ownership test**

Append to `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_operator_navigation_ui.py`:

```python
def test_settings_has_own_top_level_tab() -> None:
    app = APP_SOURCE.read_text(encoding="utf-8")
    start = app.index("with tabs[6]:")
    settings = app[start:]

    assert 'st.subheader("Settings")' in settings
    assert "settings_tabs = st.tabs" in settings
    assert "OPENROUTER_API_KEY" in settings
    assert "TAVILY_API_KEY" in settings
    assert "Save All Settings" in settings
```

- [ ] **Step 2: Run test to verify failure if settings still nested**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_operator_navigation_ui.py -v
```

Expected: FAIL if Settings is not its own tab.

- [ ] **Step 3: Move Settings into `with tabs[6]:`**

Move all existing Settings content to:

```python
with tabs[6]:
    st.subheader("Settings")
    st.caption("Configure local providers, models, scraping, retrieval, and research.")
```

Keep the existing settings sub-tabs:

```python
settings_tabs = st.tabs(["Keys", "LLM", "Scraping", "Retrieval", "Research"])
```

Use emoji-free labels if the app direction is sober operator UI.

- [ ] **Step 4: Mask keys by default**

Keep `type="password"` for all API-key fields. Do not show actual key values anywhere outside the input field.

- [ ] **Step 5: Run tests**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_operator_navigation_ui.py -v
```

Expected:

```text
passed
```

- [ ] **Step 6: Commit**

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git add app.py tests/test_operator_navigation_ui.py
git commit -m "feat: make settings a top-level page"
```

## Task 10: Visual Polish Pass

**Files:**
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/app.py`
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/src/scrape_planner/ui_operator_components.py`
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_operator_components.py`

- [ ] **Step 1: Add style guard tests**

Append to `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/test_operator_components.py`:

```python
def test_operator_styles_are_restrained_dashboard_ui() -> None:
    source = COMPONENTS.read_text(encoding="utf-8")

    assert "border-radius: 8px" in source
    assert "font-weight:750" in source or "font-weight: 750" in source
    assert "#0f172a" in source
    assert "gradient" not in source.lower()
    assert "border-radius: 24px" not in source
```

- [ ] **Step 2: Run test to verify failure if needed**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_operator_components.py -v
```

Expected: PASS if Task 3 already introduced the style contract; otherwise FAIL and fix styles.

- [ ] **Step 3: Add compact page-level styles**

If `_apply_compact_ui_styles()` exists in `app.py`, update it with restrained operator-dashboard styling:

```python
st.markdown(
    """
    <style>
      .block-container { padding-top: 2.2rem; max-width: 1180px; }
      [data-testid="stMetric"] {
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 12px 14px;
        background: #ffffff;
      }
      [data-testid="stAlert"] {
        border-radius: 8px;
      }
      div[data-testid="stExpander"] {
        border-radius: 8px;
      }
    </style>
    """,
    unsafe_allow_html=True,
)
```

Avoid:

- dark mode
- purple-heavy gradients
- hero marketing layout
- decorative cards inside cards
- oversized headlines

- [ ] **Step 4: Update copy for operator clarity**

Replace these strings:

```text
LLM Wiki Pipeline
Raw Data Sources
Embed + Rerank
MCP Query
Missing prerequisite
```

With context-specific product labels:

```text
University Knowledge Ops
Corpus
Retrieval
MCP readiness
Blocked
```

Do not remove technical detail; move it behind `Operator Details`.

- [ ] **Step 5: Run tests**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest tests/test_operator_components.py tests/test_operator_navigation_ui.py -v
```

Expected:

```text
passed
```

- [ ] **Step 6: Commit**

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git add app.py src/scrape_planner/ui_operator_components.py tests/test_operator_components.py
git commit -m "style: polish operator dashboard hierarchy"
```

## Task 11: Runtime Verification

**Files:**
- No code changes expected.
- Verify live app at `http://127.0.0.1:8501`.

- [ ] **Step 1: Compile changed code paths**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
python3 - <<'PY'
from pathlib import Path
for path in [
    Path("app.py"),
    Path("src/scrape_planner/ui_navigation.py"),
    Path("src/scrape_planner/ui_operator_status.py"),
    Path("src/scrape_planner/ui_operator_components.py"),
    Path("src/scrape_planner/ui_preview_quality.py"),
]:
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
print("compile ok")
PY
```

Expected:

```text
compile ok
```

- [ ] **Step 2: Run focused tests**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
PYTHONPATH=. python3 -m pytest \
  tests/test_operator_status.py \
  tests/test_operator_components.py \
  tests/test_operator_navigation_ui.py \
  tests/test_workspace_navigation_ui.py \
  tests/test_scrape_tab_ui.py \
  tests/test_pdf_sources_ui.py \
  tests/test_preview_quality.py \
  tests/test_preview_routes.py \
  tests/test_wiki_ui.py \
  tests/test_retrieval_ui.py \
  tests/test_run_analytics_metrics.py \
  -v
```

Expected:

```text
passed
```

- [ ] **Step 3: Restart or reload Streamlit**

If the running server is already serving `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`, reload the browser. If it is stale or wedged, stop and restart:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
python3 -m streamlit run app.py --server.headless true --server.port 8501
```

- [ ] **Step 4: Browser smoke test**

Use the in-app browser at `http://127.0.0.1:8501` and verify:

- Overview shows one canonical run state.
- Sources no longer contains pause/resume/cancel scrape controls.
- Runs owns scrape controls, progress, recent pages, and details.
- Corpus shows PDF extraction progress at the top.
- Corpus shows `Content Inspector` with chunk context, quality badges, and flags.
- Scraped page preview URLs render real content, not only Streamlit chrome/`Deploy`.
- Returning from a preview route to `/` restores the dashboard.
- Wiki hides tmux/log paths behind Operator Details.
- Retrieval shows charts plus MCP readiness.
- Retrieval does not report ready when chunk quality is poor or unknown.
- Settings is a standalone top-level tab.
- No new browser console errors appear during tab navigation.

- [ ] **Step 5: Final commit**

If all checks pass and previous task commits were not made individually:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git add app.py src/scrape_planner/ui_navigation.py src/scrape_planner/ui_operator_status.py src/scrape_planner/ui_operator_components.py src/scrape_planner/ui_preview_quality.py tests
git commit -m "feat: redesign operator dashboard"
```

## Self-Review

- Spec coverage: The plan covers canonical run truth, source maintenance readiness, reliable previews, chunk quality inspection, retrieval readiness gating, cleaner organization, visual hierarchy, advanced detail hiding, navigation, and runtime verification.
- Placeholder scan: No task uses placeholder language. Code steps include concrete code or exact transformation targets.
- Type consistency: `OperatorRunStatus`, `OperatorSourceStatus`, `ChunkQuality`, `ChunkQualitySummary`, `render_status_band`, `render_metric_strip`, and `render_operator_details` are defined before later tasks use them.
- Scope check: This is a UI/product reorganization with light view-model extraction and deterministic preview-quality heuristics. It does not rewrite scraper, PDF extraction, wiki builder, embedding generation, or MCP server internals; it makes poor chunks visible and prevents retrieval from looking ready when the corpus is not trustworthy.
