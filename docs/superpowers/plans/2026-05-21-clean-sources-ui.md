# Clean Sources UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `Sources` tab easy to understand by turning it into a source intake dashboard with clear summary metrics, one next action, and collapsed operational details.

**Architecture:** Keep the existing Streamlit app and backend artifacts intact. Refactor the current `Sources` tab in `app.py` into small render helpers for inventory, adding sources, current scrape run, and details. Add source-status helpers only where needed so tests can verify the UI contract without running Streamlit.

**Tech Stack:** Streamlit, Python, pandas, existing `src.scrape_planner` helpers, pytest source-inspection tests.

---

## Current Problem

The `Sources` tab currently mixes four jobs in one long page:

- Website discovery and manual URL entry.
- PDF upload, extraction metrics, parser details, page markdown previews, chunks, and quarantine.
- Scrape controls, concurrency, pause/resume/cancel, refresh, auto-refresh.
- Live scrape telemetry, current activity, recent pages, failures, and all-page filters.

This makes the tab feel like an implementation console. The user needs an intake page that answers:

1. What sources do I have?
2. What is ready?
3. What should I do next?
4. Where are the details if something goes wrong?

## File Structure

- Modify: `app.py`
  - Add small source UI helper functions above the tab rendering block.
  - Replace the body of `with tabs[1]:` with a concise orchestration flow.
  - Keep all existing scrape/PDF behavior available, but move tables and verbose diagnostics into expanders.

- Modify: `tests/test_stepper_ui.py`
  - Add source-inspection tests that lock in the clean visible labels.
  - Add regression tests that prevent noisy labels from returning to the always-visible surface.

- Optional modify: `src/scrape_planner/ui_navigation.py`
  - Do not change tab names in this plan. The goal is first to clean `Sources`, not rename the whole app.

## Target Visual Shape

```text
Sources

Source Inventory
  Website URLs        25,376 selected
  PDF documents       1 uploaded, 1 extracted
  Prepared sources    0 ready
  Current run         paused

Next Action
  Resume scrape / Start scrape / Prepare sources / Add sources

Add Sources
  Website URLs
    Refresh sitemap URLs
    Paste official links

  Documents
    Upload PDFs

Current Run
  Progress bar
  State, success, failed, remaining, elapsed, ETA
  Resume / Pause / Cancel / Refresh

Details
  Website discovery details
  PDF extraction details
  Current activity
  Recent pages
  Current failures
  All pages and filters
```

## Visual Rules

- Keep only high-signal metrics visible by default.
- Hide file paths, parser names, chunk text, page markdown, and raw tables behind expanders.
- Replace technical labels:
  - `Page MD` -> `Pages extracted`
  - `Chunks` -> `Search chunks`
  - `Quarantine` -> `Needs review`
  - `PDF Sources` -> `PDF documents`
  - `Run Health` -> `Current run`
- Keep controls close to the thing they control:
  - URL discovery controls stay under `Website URLs`.
  - PDF upload/re-extract controls stay under `Documents`.
  - Pause/resume/cancel controls stay under `Current run`.
- Show one plain next-action message near the top.

---

### Task 1: Lock The Desired Sources UI Contract In Tests

**Files:**
- Modify: `tests/test_stepper_ui.py`
- Read: `app.py`

- [ ] **Step 1: Add the failing test for clean source sections**

Add this test near the existing UI source-inspection tests:

```python
def test_sources_tab_presents_clean_intake_sections() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")
    sources_tab = source[source.index("with tabs[1]:") : source.index("with tabs[2]:")]

    assert 'st.subheader("Sources")' in sources_tab
    assert '"Source Inventory"' in sources_tab
    assert '"Next Action"' in sources_tab
    assert '"Add Sources"' in sources_tab
    assert '"Website URLs"' in sources_tab
    assert '"Documents"' in sources_tab
    assert '"Current Run"' in sources_tab
    assert '"Details"' in sources_tab
```

- [ ] **Step 2: Add the failing test for removing noisy always-visible labels**

Add this test in the same file:

```python
def test_sources_tab_hides_technical_pdf_and_scrape_details_by_default() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")
    sources_tab = source[source.index("with tabs[1]:") : source.index("with tabs[2]:")]

    assert '"Page MD"' not in sources_tab
    assert '"Chunks"' not in sources_tab
    assert '"Quarantine"' not in sources_tab
    assert 'st.subheader("Current Activity")' not in sources_tab
    assert 'st.subheader("Recently Scraped")' not in sources_tab
    assert 'st.subheader("Current Failures")' not in sources_tab
    assert 'with st.expander("PDF extraction details"' in sources_tab
    assert 'with st.expander("Scrape activity details"' in sources_tab
```

- [ ] **Step 3: Run the tests to verify they fail**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_stepper_ui.py::test_sources_tab_presents_clean_intake_sections tests/test_stepper_ui.py::test_sources_tab_hides_technical_pdf_and_scrape_details_by_default -q
```

Expected: both tests fail because the current `Sources` tab still uses the old visible layout.

---

### Task 2: Extract Source Status Helpers In `app.py`

**Files:**
- Modify: `app.py`
- Test: `tests/test_stepper_ui.py`

- [ ] **Step 1: Add small helper functions above `_discovered_json_path`**

Add these helpers near the existing helper functions, before the tab rendering code:

```python
def _selected_url_strings_from_state() -> list[str]:
    selected_rows = st.session_state.get("selected_df", pd.DataFrame())
    if isinstance(selected_rows, pd.DataFrame) and not selected_rows.empty:
        if "selected" in selected_rows.columns:
            selected_url_rows = selected_rows[selected_rows["selected"] == True]  # noqa: E712
        else:
            selected_url_rows = selected_rows
        selected_url_strings = selected_url_rows.get("url", pd.Series(dtype=str)).dropna().astype(str).tolist()
    else:
        selected_url_strings = []
    return [url for url in selected_url_strings if url.strip()]


def _source_next_action(*, selected_url_count: int, pdf_count: int, run_state: str, raw_ready: bool) -> str:
    if run_state in {"paused", "pausing"}:
        return "Resume scrape"
    if run_state in {"running", "initializing"}:
        return "Monitor scrape"
    if selected_url_count > 0 and run_state in {"none", "ready", "completed", "cancelled", "failed"}:
        return "Start scrape"
    if pdf_count > 0 and not raw_ready:
        return "Prepare sources"
    return "Add sources"
```

- [ ] **Step 2: Add a focused helper test through source inspection**

Add this to `tests/test_stepper_ui.py`:

```python
def test_sources_ui_has_next_action_helper() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "def _source_next_action(" in source
    assert 'return "Resume scrape"' in source
    assert 'return "Monitor scrape"' in source
    assert 'return "Start scrape"' in source
    assert 'return "Prepare sources"' in source
    assert 'return "Add sources"' in source
```

- [ ] **Step 3: Run the helper test**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_stepper_ui.py::test_sources_ui_has_next_action_helper -q
```

Expected: pass after adding the helper.

---

### Task 3: Replace The Top Of `Sources` With A Source Inventory

**Files:**
- Modify: `app.py:1337-1372`
- Test: `tests/test_stepper_ui.py`

- [ ] **Step 1: Compute summary values at the start of `with tabs[1]:`**

At the top of the `Sources` tab, keep the existing discovery calculations, then add:

```python
    site_id = st.session_state.get("site_id", "")
    site_root = DATA_ROOT / "sites" / site_id if site_id else None
    pdf_manifest = []
    raw_ready = False
    run_state_label = "none"
    selected_url_strings = _selected_url_strings_from_state()

    if site_root:
        pdf_manifest_path = site_root / "sources" / "pdf_manifest.json"
        pdf_manifest = read_json(pdf_manifest_path, [])
        layout = site_layout(site_root)
        raw_status = _raw_source_status(layout)
        raw_ready = _raw_sources_ready(raw_status)

    if st.session_state.get("run_id") and site_id:
        status, pages, _events = _load_scrape_runtime(site_id, st.session_state["run_id"], max_events=200)
        summary = derive_run_summary(status=status or {}, pages=pages if isinstance(pages, list) else [], selected_count=len(selected_url_strings))
        run_state_label = summary.state
    elif selected_url_strings:
        run_state_label = "ready"
```

- [ ] **Step 2: Render the visible inventory before controls**

Below the calculations, add:

```python
    st.markdown("### Source Inventory")
    i1, i2, i3, i4 = st.columns(4)
    i1.metric("Website URLs", f"{len(selected_url_strings):,} selected")
    i2.metric("PDF documents", f"{len(pdf_manifest):,} uploaded")
    i3.metric("Prepared sources", "ready" if raw_ready else "not ready")
    i4.metric("Current run", run_state_label)

    next_action = _source_next_action(
        selected_url_count=len(selected_url_strings),
        pdf_count=len(pdf_manifest),
        run_state=run_state_label,
        raw_ready=raw_ready,
    )
    st.info(f"Next Action: {next_action}")
```

- [ ] **Step 3: Run the source-section tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_stepper_ui.py::test_sources_tab_presents_clean_intake_sections -q
```

Expected: the test may still fail until later tasks add all section labels.

---

### Task 4: Group URL And PDF Inputs Under `Add Sources`

**Files:**
- Modify: `app.py:1351-1534`
- Test: `tests/test_stepper_ui.py`

- [ ] **Step 1: Add the `Add Sources` section**

Replace the loose `Refresh Sitemap URLs`, metrics, `Add URLs`, and `PDF Sources` area with:

```python
    st.markdown("### Add Sources")
    url_panel, doc_panel = st.columns(2)

    with url_panel:
        st.markdown("#### Website URLs")
        if st.button("Refresh Sitemap URLs", disabled=not st.session_state["site_url"], type="primary"):
            result = discover_site_urls(st.session_state["site_url"])
            st.session_state["discovered"] = _to_discovered_rows(result.urls)
            st.session_state["selected_df"] = pd.DataFrame(st.session_state["discovered"])
            persist_discovered(_discovered_json_path(st.session_state["site_id"]), result.urls)
            _save_app_state()
            discovered_rows_for_summary = st.session_state["discovered"]
            st.info("\n".join(result.notes) if result.notes else "Discovery completed.")

        st.session_state["manual_urls"] = st.text_area(
            "Paste official links",
            value=st.session_state["manual_urls"],
            height=110,
            placeholder="https://admissions.example.edu/...\n/registrar/...",
        )
        _save_app_state()
        if st.button("Add URLs", type="secondary"):
            items = apply_manual_urls(st.session_state["site_url"], st.session_state["manual_urls"].splitlines())
            merged = {row.get("url"): row for row in st.session_state.get("discovered", []) if isinstance(row, dict) and row.get("url")}
            accepted = 0
            excluded = 0
            for item in items:
                row = item.to_dict()
                if row.get("excluded_reason"):
                    excluded += 1
                else:
                    accepted += 1
                merged[item.url] = row
            st.session_state["discovered"] = list(merged.values())
            st.session_state["selected_df"] = pd.DataFrame(st.session_state["discovered"])
            write_json(_discovered_json_path(st.session_state["site_id"]), st.session_state["discovered"])
            _save_app_state()
            st.success(f"Accepted {accepted:,} URL(s). Excluded {excluded:,} off-domain URL(s).")
```

- [ ] **Step 2: Move PDF upload into the `Documents` panel**

Inside `with doc_panel:`, keep the existing upload behavior, but change the visible labels:

```python
        st.markdown("#### Documents")
        uploaded_pdfs = st.file_uploader(
            "Upload PDFs",
            type=["pdf"],
            accept_multiple_files=True,
            key="choose_pdf_uploads",
        )
```

Keep `_extract_uploaded_pdfs_to_site_sources(...)` exactly as it currently works.

- [ ] **Step 3: Remove the always-visible PDF table from this area**

Do not render `st.dataframe(pd.DataFrame(display_rows), ...)` directly under `Documents`. That table moves to the details expander in Task 6.

- [ ] **Step 4: Run the source-section tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_stepper_ui.py::test_sources_tab_presents_clean_intake_sections -q
```

Expected: closer to green; remaining failures should be `Current Run` or `Details`.

---

### Task 5: Simplify Current Run Into One Visible Status Block

**Files:**
- Modify: `app.py:1536-1836`
- Test: `tests/test_stepper_ui.py`

- [ ] **Step 1: Rename the run section**

Replace `st.subheader("Live Scrape")` and `st.subheader("Run Health")` with:

```python
        st.markdown("### Current Run")
```

Only render this header once in the scrape section.

- [ ] **Step 2: Keep the controls visible but shorten their layout**

Replace the seven-column row with two rows:

```python
        action_cols = st.columns([1, 1, 1, 1])
        settings_cols = st.columns([1, 1, 2])
```

Use `action_cols` for:

- `Start New Scrape`
- `Resume`
- `Pause`
- `Cancel`

Use `settings_cols` for:

- `Concurrency`
- `Refresh`
- `Auto-refresh`

- [ ] **Step 3: Keep only the progress and key metrics visible**

Visible metrics should be:

```python
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("State", summary.state)
            k2.metric("Success", f"{summary.success:,}")
            k3.metric("Failed", f"{summary.failed:,}")
            k4.metric("Remaining", f"{summary.remaining:,}")
            k5.metric("ETA", eta_label)
```

Move `Running`, `Queued`, current URL, elapsed, current activity, recent scraped, and current failures into the details expander.

- [ ] **Step 4: Run the noisy-label regression test**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_stepper_ui.py::test_sources_tab_hides_technical_pdf_and_scrape_details_by_default -q
```

Expected: may still fail until Task 6 moves the detail sections.

---

### Task 6: Move Operational Tables Into `Details`

**Files:**
- Modify: `app.py:1394-1532` and `app.py:1712-1816`
- Test: `tests/test_stepper_ui.py`

- [ ] **Step 1: Add the `Details` section near the bottom of `Sources`**

After the visible `Current Run` block, add:

```python
    st.markdown("### Details")
```

- [ ] **Step 2: Move website discovery details into an expander**

Wrap top host counts with:

```python
    with st.expander("Website discovery details", expanded=False):
        d1, d2, d3 = st.columns(3)
        d1.metric("Discovered URLs", f"{len(discovered_rows_for_summary):,}")
        d2.metric("Sitemap sources", f"{source_count:,}")
        d3.metric("Last refreshed", last_refreshed)
        if discovered_rows_for_summary:
            host_counts = pd.Series(
                [urlparse(str(row.get("url") or "")).netloc.lower() for row in discovered_rows_for_summary if isinstance(row, dict)]
            ).value_counts().head(12)
            if not host_counts.empty:
                st.dataframe(host_counts.rename_axis("host").reset_index(name="urls"), use_container_width=True, hide_index=True)
```

- [ ] **Step 3: Move PDF tables into an expander**

Wrap PDF table, page markdown preview, chunks, and quarantine with:

```python
    with st.expander("PDF extraction details", expanded=False):
        p1, p2, p3 = st.columns(3)
        p1.metric("Pages extracted", f"{len(page_rows):,}")
        p2.metric("Search chunks", f"{len(chunk_rows):,}")
        p3.metric("Needs review", f"{len(quarantine_rows):,}")
        # Existing PDF dataframe and nested page/chunk/quarantine expanders stay here.
```

- [ ] **Step 4: Move scrape activity into an expander**

Wrap current activity, recent scraped, current failures, and all pages filters with:

```python
    with st.expander("Scrape activity details", expanded=False):
        # Existing Current Activity, Recently Scraped, Current Failures,
        # and All pages and filters content moves here.
```

Inside this expander, change subheaders to captions:

- `st.subheader("Current Activity")` -> `st.caption("Current activity")`
- `st.subheader("Recently Scraped")` -> `st.caption("Recently scraped")`
- `st.subheader("Current Failures")` -> `st.caption("Current failures")`

- [ ] **Step 5: Run the source UI tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_stepper_ui.py::test_sources_tab_presents_clean_intake_sections tests/test_stepper_ui.py::test_sources_tab_hides_technical_pdf_and_scrape_details_by_default -q
```

Expected: both tests pass.

---

### Task 7: Run Focused Verification

**Files:**
- Verify only

- [ ] **Step 1: Run the stepper UI tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_stepper_ui.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run source-related UI tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_pdf_sources_ui.py tests/test_scrape_tab_ui.py tests/test_discover_tab_ui.py -q
```

Expected: all tests pass. If any test fails because it expects the old label, update the test only when the behavior is unchanged and the label intentionally moved or changed.

- [ ] **Step 3: Search for removed always-visible labels**

Run:

```bash
rg -n 'Page MD|st.subheader\("Current Activity"\)|st.subheader\("Recently Scraped"\)|st.subheader\("Current Failures"\)' app.py
```

Expected: no matches.

---

### Task 8: Browser Smoke Check

**Files:**
- Verify local UI only

- [ ] **Step 1: Start or reuse the Streamlit app**

Run:

```bash
PYTHONPATH=src .venv/bin/streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

Expected: Streamlit serves the app on `http://127.0.0.1:8502`.

- [ ] **Step 2: Open the app and inspect `Sources`**

Open:

```text
http://127.0.0.1:8502
```

Expected visible shape:

- `Source Inventory` appears first.
- `Next Action` appears above source controls.
- `Add Sources` has `Website URLs` and `Documents`.
- `Current Run` has compact progress and controls.
- `Details` contains the noisy tables.
- PDF page markdown/chunks/quarantine are not visible until expanding details.
- Current activity/recent scraped/failures are not visible until expanding details.

- [ ] **Step 3: Capture a screenshot if using Browser tooling**

Use the Browser plugin screenshot after opening the Sources tab.

Expected: one screen should explain the page without scrolling through scrape/PDF internals.

---

## Self-Review

- Spec coverage: The plan covers source inventory, next action, grouped source input, compact scrape run, collapsed PDF/scrape details, tests, and browser verification.
- Placeholder scan: No `TBD`, `TODO`, or undefined future task language remains.
- Scope check: This is intentionally limited to the `Sources` tab visuals. It does not rename the full workflow tabs or alter scrape/PDF/backend behavior.
- Risk: `app.py` is already large and dirty in this workspace. Keep edits scoped to `with tabs[1]:` and helper functions; do not revert unrelated changes.
