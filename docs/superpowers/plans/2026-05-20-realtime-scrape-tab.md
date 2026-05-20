# Realtime Scrape Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the cluttered Scrape tab with a realtime-first cockpit, add new-tab rendered markdown previews, and make pause/resume clearly continue the current run.

**Architecture:** Keep worker contracts intact and extract small pure UI helpers into `src/scrape_planner/ui_scrape_realtime.py` so preview URLs, page summaries, and markdown resolution can be unit tested outside Streamlit. `app.py` will use those helpers for a dedicated `view=scraped_page` route and a simplified Scrape tab layout. Resume correctness will be verified at the worker level before changing UI labels.

**Tech Stack:** Python, Streamlit, pandas, pytest, existing `RunStateStore`, `ScrapeRunner`, and run artifacts under `data/sites/<site_id>/<run_id>/`.

---

## File Structure

- Create `src/scrape_planner/ui_scrape_realtime.py`: pure helper functions for URL slugging, preview link generation, preview artifact resolution, run-summary derivation, and compact activity slicing.
- Create `tests/test_ui_scrape_realtime.py`: unit tests for helper behavior without importing Streamlit.
- Modify `app.py`: render scraped-page preview route before normal tab UI, replace the Scrape tab default layout with realtime-first sections, and move the full page table behind an expander.
- Modify `tests/test_scrape_worker.py`: add persisted-state resume coverage so successful pages are not fetched again after process/UI state loss.
- Modify `src/scrape_planner/scrape_worker.py`: only if the new persisted resume test exposes a real bug; keep any change minimal and localized.

Do not commit during execution unless the user explicitly authorizes commits. If commit authorization is given, use the commit commands shown in each task.

---

### Task 1: Add Pure Realtime Scrape UI Helpers

**Files:**
- Create: `src/scrape_planner/ui_scrape_realtime.py`
- Create: `tests/test_ui_scrape_realtime.py`

- [ ] **Step 1: Write failing helper tests**

Create `tests/test_ui_scrape_realtime.py` with this content:

```python
from pathlib import Path

from src.scrape_planner.ui_scrape_realtime import (
    build_scraped_page_preview_href,
    derive_run_summary,
    latest_pages_by_status,
    page_slug,
    resolve_scraped_markdown_preview,
)


def test_page_slug_matches_existing_worker_slug() -> None:
    assert page_slug("https://example.com/path?a=1") == "635d6a6279df"


def test_build_scraped_page_preview_href_uses_query_route() -> None:
    href = build_scraped_page_preview_href(
        site_id="site-a",
        run_id="run-1",
        url="https://example.com/a page",
    )

    assert href.startswith("?view=scraped_page&")
    assert "site_id=site-a" in href
    assert "run_id=run-1" in href
    assert "page_slug=" in href


def test_resolve_scraped_markdown_preview_from_slug_and_metadata(tmp_path: Path) -> None:
    run_root = tmp_path / "sites" / "site-a" / "run-1"
    markdown_dir = run_root / "markdown"
    metadata_dir = run_root / "metadata"
    markdown_dir.mkdir(parents=True)
    metadata_dir.mkdir(parents=True)
    slug = page_slug("https://example.com/a")
    md_path = markdown_dir / f"{slug}.md"
    meta_path = metadata_dir / f"{slug}.json"
    md_path.write_text("# Title\nBody", encoding="utf-8")
    meta_path.write_text(
        '{"url":"https://example.com/a","http_status":200,"fetch_mode":"fetcher","text_length":12}',
        encoding="utf-8",
    )

    preview = resolve_scraped_markdown_preview(run_root, slug)

    assert preview.ready is True
    assert preview.markdown == "# Title\nBody"
    assert preview.url == "https://example.com/a"
    assert preview.http_status == 200
    assert preview.fetch_mode == "fetcher"
    assert preview.text_length == 12


def test_resolve_scraped_markdown_preview_missing_file_is_not_ready(tmp_path: Path) -> None:
    preview = resolve_scraped_markdown_preview(tmp_path / "run", "missing")

    assert preview.ready is False
    assert preview.markdown == ""
    assert preview.message == "Scraped markdown is not ready yet."


def test_derive_run_summary_uses_status_and_pages() -> None:
    summary = derive_run_summary(
        status={"state": "running", "total": 4, "running": 1, "success": 1, "failed": 1},
        pages=[
            {"url": "https://example.com/a", "status": "success"},
            {"url": "https://example.com/b", "status": "failed"},
            {"url": "https://example.com/c", "status": "running"},
        ],
        selected_count=4,
    )

    assert summary.state == "running"
    assert summary.total == 4
    assert summary.success == 1
    assert summary.failed == 1
    assert summary.running == 1
    assert summary.remaining == 2
    assert summary.progress_label == "2 / 4"


def test_latest_pages_by_status_sorts_newest_first() -> None:
    pages = [
        {"url": "https://example.com/old", "status": "success", "finished_at": "2026-01-01T00:00:00+00:00"},
        {"url": "https://example.com/new", "status": "success", "finished_at": "2026-01-02T00:00:00+00:00"},
        {"url": "https://example.com/fail", "status": "failed", "finished_at": "2026-01-03T00:00:00+00:00"},
    ]

    latest = latest_pages_by_status(pages, "success", limit=1)

    assert [row["url"] for row in latest] == ["https://example.com/new"]
```

- [ ] **Step 2: Run helper tests and verify they fail**

Run: `pytest tests/test_ui_scrape_realtime.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'src.scrape_planner.ui_scrape_realtime'`.

- [ ] **Step 3: Add helper implementation**

Create `src/scrape_planner/ui_scrape_realtime.py` with this content:

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode


def page_slug(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def build_scraped_page_preview_href(*, site_id: str, run_id: str, url: str) -> str:
    query = urlencode(
        {
            "view": "scraped_page",
            "site_id": site_id,
            "run_id": run_id,
            "page_slug": page_slug(url),
        }
    )
    return f"?{query}"


@dataclass(frozen=True)
class ScrapedMarkdownPreview:
    ready: bool
    markdown: str
    message: str
    path: Path | None = None
    url: str = ""
    http_status: int | None = None
    fetch_mode: str = ""
    text_length: int | None = None


@dataclass(frozen=True)
class RunSummary:
    state: str
    total: int
    queued: int
    running: int
    success: int
    failed: int
    cancelled: int
    remaining: int
    done: int
    progress_percent: float
    progress_label: str


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def resolve_scraped_markdown_preview(run_root: Path, slug: str) -> ScrapedMarkdownPreview:
    safe_slug = "".join(ch for ch in str(slug or "") if ch.isalnum())[:40]
    if not safe_slug:
        return ScrapedMarkdownPreview(False, "", "Scraped markdown is not ready yet.")

    md_path = run_root / "markdown" / f"{safe_slug}.md"
    meta_path = run_root / "metadata" / f"{safe_slug}.json"
    if not md_path.exists():
        return ScrapedMarkdownPreview(False, "", "Scraped markdown is not ready yet.", path=md_path)

    metadata: dict[str, object] = {}
    if meta_path.exists():
        try:
            parsed = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                metadata = parsed
        except json.JSONDecodeError:
            metadata = {}

    return ScrapedMarkdownPreview(
        ready=True,
        markdown=md_path.read_text(encoding="utf-8", errors="replace"),
        message="",
        path=md_path,
        url=str(metadata.get("url") or ""),
        http_status=_safe_int(metadata.get("http_status"), default=0) or None,
        fetch_mode=str(metadata.get("fetch_mode") or ""),
        text_length=_safe_int(metadata.get("text_length"), default=0) or None,
    )


def derive_run_summary(*, status: dict, pages: list[dict], selected_count: int) -> RunSummary:
    state = str(status.get("state") or "ready")
    total = _safe_int(status.get("total"), default=selected_count)
    if total <= 0:
        total = selected_count

    success = _safe_int(status.get("success"))
    failed = _safe_int(status.get("failed"))
    cancelled = _safe_int(status.get("cancelled"))
    running = _safe_int(status.get("running"))
    queued = _safe_int(status.get("queued"))

    if pages and not any(status.get(key) is not None for key in ["success", "failed", "cancelled", "running", "queued"]):
        counts = {"queued": 0, "running": 0, "success": 0, "failed": 0, "cancelled": 0}
        for page in pages:
            page_status = str(page.get("status") or "queued").lower()
            if page_status in counts:
                counts[page_status] += 1
        success = counts["success"]
        failed = counts["failed"]
        cancelled = counts["cancelled"]
        running = counts["running"]
        queued = counts["queued"]

    done = success + failed + cancelled
    remaining = max(total - done, 0)
    if queued <= 0 and remaining > running:
        queued = max(remaining - running, 0)
    progress_percent = (done / total * 100.0) if total > 0 else 0.0

    return RunSummary(
        state=state,
        total=total,
        queued=queued,
        running=running,
        success=success,
        failed=failed,
        cancelled=cancelled,
        remaining=remaining,
        done=done,
        progress_percent=progress_percent,
        progress_label=f"{done} / {total}",
    )


def latest_pages_by_status(pages: list[dict], status: str, *, limit: int = 10) -> list[dict]:
    wanted = status.lower()
    filtered = [page for page in pages if str(page.get("status") or "").lower() == wanted]
    return sorted(
        filtered,
        key=lambda page: str(page.get("finished_at") or page.get("started_at") or ""),
        reverse=True,
    )[:limit]
```

- [ ] **Step 4: Run helper tests and verify they pass**

Run: `pytest tests/test_ui_scrape_realtime.py -v`

Expected: PASS.

- [ ] **Step 5: Commit if explicitly authorized**

Run only if the user has explicitly authorized commits:

```bash
git add src/scrape_planner/ui_scrape_realtime.py tests/test_ui_scrape_realtime.py
git commit -m "feat: add realtime scrape ui helpers"
```

---

### Task 2: Add Scraped Markdown Preview Route

**Files:**
- Modify: `app.py:56-63`, `app.py:1006-1040`
- Test: `tests/test_ui_scrape_realtime.py`

- [ ] **Step 1: Add preview route test coverage**

Append this test to `tests/test_ui_scrape_realtime.py`:

```python
def test_resolve_scraped_markdown_preview_rejects_path_like_slug(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    preview = resolve_scraped_markdown_preview(run_root, "../../secret")

    assert preview.ready is False
    assert preview.message == "Scraped markdown is not ready yet."
    assert preview.path == run_root / "markdown" / "secret.md"
```

- [ ] **Step 2: Run route helper test and verify it passes or exposes slug sanitizing issue**

Run: `pytest tests/test_ui_scrape_realtime.py::test_resolve_scraped_markdown_preview_rejects_path_like_slug -v`

Expected: PASS. If it fails because the sanitized slug is different, update `resolve_scraped_markdown_preview()` to keep only alphanumeric characters before constructing the path.

- [ ] **Step 3: Import preview helpers in `app.py`**

In `app.py`, add this import near the other `src.scrape_planner` imports:

```python
from src.scrape_planner.ui_scrape_realtime import (
    build_scraped_page_preview_href,
    derive_run_summary,
    latest_pages_by_status,
    page_slug,
    resolve_scraped_markdown_preview,
)
```

- [ ] **Step 4: Add scraped preview renderer in `app.py`**

Add this function after `_render_cleanup_direct_preview()`:

```python
def _render_scraped_page_preview() -> None:
    if str(st.query_params.get("view", "") or "").strip() != "scraped_page":
        return

    site_id = str(st.query_params.get("site_id", "") or "").strip()
    run_id = str(st.query_params.get("run_id", "") or "").strip()
    slug = str(st.query_params.get("page_slug", "") or "").strip()

    st.title("Scraped Page Preview")
    if not site_id or not run_id or not slug:
        st.error("Preview link is missing site, run, or page information.")
        st.stop()

    run_root = _run_root(site_id, run_id)
    preview = resolve_scraped_markdown_preview(run_root, slug)
    if preview.url:
        st.caption(f"Source: {preview.url}")
    st.caption(f"Run: `{run_id}`")

    meta_cols = st.columns(3)
    meta_cols[0].metric("HTTP", preview.http_status if preview.http_status is not None else "n/a")
    meta_cols[1].metric("Fetch Mode", preview.fetch_mode or "n/a")
    meta_cols[2].metric("Text Length", preview.text_length if preview.text_length is not None else "n/a")

    if not preview.ready:
        st.info(preview.message)
        st.stop()

    st.divider()
    st.markdown(preview.markdown)
    st.stop()
```

- [ ] **Step 5: Call scraped preview route before normal app state setup**

Change the startup block from:

```python
st.set_page_config(page_title="Scrapling Scrape Planner", layout="wide")
_apply_compact_ui_styles()
_render_cleanup_direct_preview()
_init_state()
```

to:

```python
st.set_page_config(page_title="Scrapling Scrape Planner", layout="wide")
_apply_compact_ui_styles()
_render_cleanup_direct_preview()
_render_scraped_page_preview()
_init_state()
```

- [ ] **Step 6: Compile `app.py`**

Run: `python3 -m py_compile app.py src/scrape_planner/ui_scrape_realtime.py`

Expected: no output and exit code 0.

- [ ] **Step 7: Run helper tests**

Run: `pytest tests/test_ui_scrape_realtime.py -v`

Expected: PASS.

- [ ] **Step 8: Commit if explicitly authorized**

Run only if the user has explicitly authorized commits:

```bash
git add app.py src/scrape_planner/ui_scrape_realtime.py tests/test_ui_scrape_realtime.py
git commit -m "feat: add scraped markdown preview route"
```

---

### Task 3: Verify Resume Uses Persisted Progress

**Files:**
- Modify: `tests/test_scrape_worker.py`
- Modify only if required: `src/scrape_planner/scrape_worker.py:156-171`, `src/scrape_planner/scrape_worker.py:234-283`

- [ ] **Step 1: Add failing persisted resume test**

Append this test to `tests/test_scrape_worker.py`:

```python
def test_resume_reuses_persisted_success_pages_after_state_loss(monkeypatch, tmp_path: Path):
    runner, state = _make_runner(tmp_path)
    run_root = tmp_path / "sites" / "site-a" / "run-persisted"
    run_root.mkdir(parents=True, exist_ok=True)
    selected = _selected_urls("https://example.com/1", "https://example.com/2", "https://example.com/3")
    (run_root / "selected_urls.json").write_text(
        json.dumps([item.to_dict() for item in selected], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_root / "pages.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"url": "https://example.com/1", "status": "success", "fetch_mode": "fetcher"}),
                json.dumps({"url": "https://example.com/2", "status": "success", "fetch_mode": "fetcher"}),
                json.dumps({"url": "https://example.com/3", "status": "cancelled", "fetch_mode": "fetcher"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    state.set_status(
        "site-a",
        "run-persisted",
        {"state": "paused", "running": 0, "success": 2, "failed": 0, "cancelled": 1, "queued": 0, "total": 3},
    )

    seen: list[str] = []

    def fake_fetch(mode: str, url: str):
        seen.append(url)
        return _FakeResponse()

    monkeypatch.setattr(runner, "_fetch_with_mode", fake_fetch)
    monkeypatch.setattr(
        "src.scrape_planner.scrape_worker.extract_content",
        lambda html: ("text", "# ok", 1000, 0.01),
    )

    resumed = runner.resume("site-a", "run-persisted", concurrency=1)
    assert resumed is True
    time.sleep(0.45)

    pages = state.get_pages("site-a", "run-persisted")
    by_url = {row["url"]: row for row in pages}
    status = state.get_status("site-a", "run-persisted")

    assert seen == ["https://example.com/3"]
    assert by_url["https://example.com/1"]["status"] == "success"
    assert by_url["https://example.com/2"]["status"] == "success"
    assert by_url["https://example.com/3"]["status"] == "success"
    assert status["state"] == "completed"
    assert status["success"] == 3
```

- [ ] **Step 2: Run persisted resume test**

Run: `pytest tests/test_scrape_worker.py::test_resume_reuses_persisted_success_pages_after_state_loss -v`

Expected: PASS if the current worker already handles persisted pages correctly, or FAIL showing successful URLs were re-fetched or counts were rebuilt incorrectly.

- [ ] **Step 3: If the test fails, apply the minimal worker fix**

Only edit `src/scrape_planner/scrape_worker.py` if Step 2 fails. In `_execute()`, keep the existing successful-page skip behavior and ensure only `initial_queue_urls` are enqueued. The relevant code should have this shape:

```python
existing_pages = {
    str(page.get("url") or ""): page
    for page in (self.state.get_pages(site_id, run_id) or read_page_states(run_root))
    if isinstance(page, dict) and page.get("url")
}
initial_queue_urls: list[str] = []
for item in selected_urls:
    existing = existing_pages.get(item.url)
    if existing and str(existing.get("status") or "").lower() == "success":
        pages_by_url[item.url] = existing.copy()
        continue
    if existing and str(existing.get("status") or "").lower() in {"queued", "cancelled", "failed", "running", "paused"}:
        page = existing.copy()
        page["status"] = "queued"
        page["worker_id"] = None
        page["finished_at"] = None
        pages_by_url[item.url] = page
    else:
        pages_by_url[item.url] = PageResult(
            url=item.url,
            status="queued",
            fetch_mode="fetcher",
            worker_id=None,
            attempt=0,
            started_at=None,
            finished_at=None,
        ).to_dict()
    initial_queue_urls.append(item.url)
```

And the queue population must remain:

```python
work_queue: Queue[DiscoveredURL] = Queue()
for item in selected_urls:
    if item.url in initial_queue_urls:
        work_queue.put(item)
```

- [ ] **Step 4: Run scrape worker tests**

Run: `pytest tests/test_scrape_worker.py -v`

Expected: PASS.

- [ ] **Step 5: Commit if explicitly authorized**

Run only if the user has explicitly authorized commits:

```bash
git add tests/test_scrape_worker.py src/scrape_planner/scrape_worker.py
git commit -m "test: cover persisted scrape resume progress"
```

---

### Task 4: Replace Scrape Tab Default View With Realtime Cockpit

**Files:**
- Modify: `app.py:1307-1615`
- Test: `tests/test_ui_scrape_realtime.py`

- [ ] **Step 1: Add link markup helper test**

Append this test to `tests/test_ui_scrape_realtime.py`:

```python
def test_build_scraped_page_preview_href_has_stable_slug() -> None:
    first = build_scraped_page_preview_href(site_id="site-a", run_id="run-1", url="https://example.com/a")
    second = build_scraped_page_preview_href(site_id="site-a", run_id="run-1", url="https://example.com/a")

    assert first == second
    assert page_slug("https://example.com/a") in first
```

- [ ] **Step 2: Run new helper test**

Run: `pytest tests/test_ui_scrape_realtime.py::test_build_scraped_page_preview_href_has_stable_slug -v`

Expected: PASS.

- [ ] **Step 3: Update Scrape command bar labels and actions**

In `app.py` inside `with tabs[3]:`, replace the existing command bar labels with explicit copy:

```python
c1, c2, c3, c4, c5, c6, c7 = st.columns([1.2, 1, 1, 1, 1, 1, 2.2])
concurrency = c5.number_input("Concurrency", min_value=1, max_value=16, value=4, step=1)
if c1.button("Start New Scrape", type="primary"):
    with st.spinner(f"Starting run for {len(selected_url_strings):,} selected URL(s)..."):
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
        st.session_state["run_id"] = run_id
        st.session_state["last_run_by_site"][st.session_state["site_id"]] = run_id
        _save_app_state()
        selected_urls = _rows_to_discovered_urls(st.session_state["selected_df"].to_dict("records"))
        if not selected_urls:
            st.error("No URLs selected. Lower the importance threshold or choose URLs before starting a scrape.")
        else:
            runner.start(st.session_state["site_id"], run_id, selected_urls, concurrency=int(concurrency))
            st.session_state["scrape_status_message"] = "Starting run..."
            st.rerun()
if c2.button("Pause", disabled=not st.session_state["run_id"]):
    runner.pause(st.session_state["site_id"], st.session_state["run_id"])
    st.session_state["scrape_status_message"] = "Pausing after in-flight pages finish..."
    st.rerun()
if c3.button("Resume Current Run", disabled=not st.session_state["run_id"]):
    with st.spinner("Continuing from last saved page state..."):
        resumed = runner.resume(st.session_state["site_id"], st.session_state["run_id"], concurrency=int(concurrency))
        if not resumed:
            runner.unpause(st.session_state["site_id"], st.session_state["run_id"])
        st.session_state["scrape_status_message"] = "Continuing from last saved page state..."
        st.rerun()
if c4.button("Cancel", disabled=not st.session_state["run_id"]):
    runner.cancel(st.session_state["site_id"], st.session_state["run_id"])
    st.session_state["scrape_status_message"] = "Cancel requested..."
    st.rerun()
if c6.button("Refresh", use_container_width=True):
    st.rerun()
autorefresh = c7.checkbox("Auto-refresh every 1s", value=False)
```

- [ ] **Step 4: Add compact live health using helper summary**

After loading `status, pages, events`, derive the summary and render compact metrics:

```python
summary = derive_run_summary(status=status, pages=pages, selected_count=len(selected_url_strings))
status_message = st.session_state.get("scrape_status_message", "")
if status_message and summary.state in {"initializing", "running", "pausing", "paused"}:
    st.info(status_message)

st.subheader("Live Scrape")
progress_value = min(max(summary.progress_percent / 100.0, 0.0), 1.0)
st.progress(progress_value, text=f"{summary.progress_label} pages ({summary.progress_percent:.1f}%)")
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("State", summary.state)
k2.metric("Running", f"{summary.running:,}")
k3.metric("Success", f"{summary.success:,}")
k4.metric("Failed", f"{summary.failed:,}")
k5.metric("Remaining", f"{summary.remaining:,}")
k6.metric("Queued", f"{summary.queued:,}")
```

- [ ] **Step 5: Add active, success, and failure sections**

Below the live health metrics, render compact default sections:

```python
running_pages = latest_pages_by_status(pages, "running", limit=8)
success_pages = latest_pages_by_status(pages, "success", limit=10)
failed_pages = latest_pages_by_status(pages, "failed", limit=10)

st.markdown("**Current Activity**")
if running_pages:
    st.dataframe(
        pd.DataFrame(running_pages)[[c for c in ["worker_id", "url", "fetch_mode", "attempt", "started_at"] if c in running_pages[0]]],
        use_container_width=True,
        hide_index=True,
    )
elif summary.state in {"running", "initializing"}:
    st.info("Preparing queue and waiting for worker activity...")
elif summary.state == "paused":
    st.info("Paused. Resume Current Run will continue unfinished pages.")
else:
    st.info("No active workers right now.")

st.markdown("**Recently Scraped**")
if success_pages:
    for row in success_pages:
        url = str(row.get("url") or "")
        href = build_scraped_page_preview_href(site_id=st.session_state["site_id"], run_id=st.session_state["run_id"], url=url)
        st.markdown(
            f'<a href="{href}" target="_blank">Open preview</a> - {url}',
            unsafe_allow_html=True,
        )
else:
    st.info("No scraped markdown is ready yet.")

st.markdown("**Current Failures**")
if failed_pages:
    st.dataframe(
        pd.DataFrame(failed_pages)[[c for c in ["url", "http_status", "failure_reason", "fetch_mode", "attempt", "finished_at"] if c in failed_pages[0]]],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No failures in the current run.")
```

- [ ] **Step 6: Move existing detailed filters/table into an expander**

Wrap the existing `Running Pages` filters and `_render_paginated_df(...)` block with:

```python
with st.expander("All pages and filters", expanded=False):
    # keep existing status filter, slow threshold, URL contains, latest-only controls,
    # visible_df derivation, and _render_paginated_df call here
```

The code inside the expander must be the existing detailed table logic, not a second new table implementation.

- [ ] **Step 7: Compile app**

Run: `python3 -m py_compile app.py src/scrape_planner/ui_scrape_realtime.py`

Expected: no output and exit code 0.

- [ ] **Step 8: Run helper tests**

Run: `pytest tests/test_ui_scrape_realtime.py -v`

Expected: PASS.

- [ ] **Step 9: Commit if explicitly authorized**

Run only if the user has explicitly authorized commits:

```bash
git add app.py tests/test_ui_scrape_realtime.py
git commit -m "feat: simplify scrape tab realtime cockpit"
```

---

### Task 5: Add Seamless Loading And Paused States

**Files:**
- Modify: `app.py:1307-1615`
- Test: `tests/test_ui_scrape_realtime.py`

- [ ] **Step 1: Add summary loading-state tests**

Append these tests to `tests/test_ui_scrape_realtime.py`:

```python
def test_derive_run_summary_ready_state_from_selected_count() -> None:
    summary = derive_run_summary(status={}, pages=[], selected_count=7)

    assert summary.state == "ready"
    assert summary.total == 7
    assert summary.queued == 7
    assert summary.remaining == 7
    assert summary.progress_label == "0 / 7"


def test_derive_run_summary_paused_state_keeps_remaining_count() -> None:
    summary = derive_run_summary(
        status={"state": "paused", "total": 5, "success": 2, "failed": 0, "cancelled": 0, "running": 0, "queued": 3},
        pages=[],
        selected_count=5,
    )

    assert summary.state == "paused"
    assert summary.remaining == 3
    assert summary.queued == 3
```

- [ ] **Step 2: Run loading-state tests and verify failure if ready queued count is missing**

Run: `pytest tests/test_ui_scrape_realtime.py::test_derive_run_summary_ready_state_from_selected_count tests/test_ui_scrape_realtime.py::test_derive_run_summary_paused_state_keeps_remaining_count -v`

Expected: PASS after `derive_run_summary()` sets queued to selected count when no status exists.

- [ ] **Step 3: Fix summary queued fallback if needed**

If `test_derive_run_summary_ready_state_from_selected_count` fails, update `derive_run_summary()` so this block exists after `remaining` is computed:

```python
if queued <= 0 and remaining > running:
    queued = max(remaining - running, 0)
```

- [ ] **Step 4: Add explicit Streamlit loading copy**

In the Scrape tab, use this state copy after rendering metrics:

```python
if not st.session_state.get("run_id"):
    if selected_url_strings:
        st.info(f"Ready to scrape {len(selected_url_strings):,} selected URL(s).")
    else:
        st.info("No selected URLs yet.")
elif summary.state in {"initializing", "running"} and summary.done == 0:
    with st.spinner("Preparing queue and waiting for first scraped page..."):
        st.info("Workers are starting. The latest scraped pages will appear here automatically.")
elif summary.state == "pausing":
    st.warning("Pausing after in-flight pages finish...")
elif summary.state == "paused":
    st.info(f"Paused with {summary.success:,} complete and {summary.remaining:,} remaining. Resume Current Run will continue unfinished pages.")
elif summary.state == "completed":
    st.success("Scrape run completed.")
```

- [ ] **Step 5: Ensure resume clears stale status message after stable states**

After deriving `summary`, add:

```python
if summary.state in {"completed", "cancelled", "failed"}:
    st.session_state["scrape_status_message"] = ""
```

- [ ] **Step 6: Compile app and run tests**

Run: `python3 -m py_compile app.py src/scrape_planner/ui_scrape_realtime.py`

Expected: no output and exit code 0.

Run: `pytest tests/test_ui_scrape_realtime.py tests/test_scrape_worker.py -v`

Expected: PASS.

- [ ] **Step 7: Commit if explicitly authorized**

Run only if the user has explicitly authorized commits:

```bash
git add app.py src/scrape_planner/ui_scrape_realtime.py tests/test_ui_scrape_realtime.py tests/test_scrape_worker.py
git commit -m "feat: add seamless scrape loading states"
```

---

### Task 6: Final Verification

**Files:**
- Verify: `app.py`
- Verify: `src/scrape_planner/ui_scrape_realtime.py`
- Verify: `src/scrape_planner/scrape_worker.py`
- Verify: `tests/test_ui_scrape_realtime.py`
- Verify: `tests/test_scrape_worker.py`

- [ ] **Step 1: Run focused tests**

Run: `pytest tests/test_ui_scrape_realtime.py tests/test_scrape_worker.py -v`

Expected: PASS.

- [ ] **Step 2: Compile changed Python files**

Run: `python3 -m py_compile app.py src/scrape_planner/ui_scrape_realtime.py src/scrape_planner/scrape_worker.py`

Expected: no output and exit code 0.

- [ ] **Step 3: Manually inspect Streamlit route behavior**

Run: `streamlit run app.py`

Expected: app starts without import errors.

Manual checks:

- Open a workspace and select the Scrape tab.
- Confirm the primary button says `Start New Scrape`.
- Start a small scrape and confirm the default view shows progress, current activity, recent scraped pages, and failures without the full table expanded.
- Pause the run and confirm the paused/pausing copy explains in-flight completion.
- Resume the run and confirm it says it is continuing from saved state.
- Click `Open preview` for a successful page and confirm a new browser page renders markdown.

- [ ] **Step 4: Check git diff**

Run: `git diff -- app.py src/scrape_planner/ui_scrape_realtime.py src/scrape_planner/scrape_worker.py tests/test_ui_scrape_realtime.py tests/test_scrape_worker.py`

Expected: diff only contains realtime scrape UI, preview route, tests, and any minimal resume fix required by tests.

- [ ] **Step 5: Final commit if explicitly authorized**

Run only if the user has explicitly authorized commits and previous task commits were not made:

```bash
git add app.py src/scrape_planner/ui_scrape_realtime.py src/scrape_planner/scrape_worker.py tests/test_ui_scrape_realtime.py tests/test_scrape_worker.py
git commit -m "feat: make scrape tab realtime first"
```

---

## Self-Review

- Spec coverage: The plan covers realtime-first default UI, collapsed full details, new-tab markdown previews, explicit start/resume labeling, resume skip tests, and loading states.
- Placeholder scan: No task uses placeholder language. Each code-changing step includes concrete code or exact target structure.
- Type consistency: Helper names are consistent across tests and app usage: `page_slug`, `build_scraped_page_preview_href`, `resolve_scraped_markdown_preview`, `derive_run_summary`, and `latest_pages_by_status`.
