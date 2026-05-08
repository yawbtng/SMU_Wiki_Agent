# Phase 2: Page Inspector Drawer

## Goal

Make page-by-page preview usable inside the Scrape Run workflow. The user should not need to leave the Scrape tab to inspect what just happened.

## Primary Ownership

- `app.py`
- Optional helper: `src/scrape_planner/page_preview.py`
- Optional helper: `src/scrape_planner/ui_page_inspector.py`

## Do Not Own

- Worker pool/concurrency
- Retry queue
- Cleanup editor
- URL scoring

## Current Problem

The preview is buried and passive. It only shows a selected URL after completed page data exists, and it does not clearly expose raw output, markdown output, metadata, failure reason, or event history together.

## Required UX

Inside the Scrape Run tab, add an inspector area beside or below the queue table.

Default selection:

- If a page is currently running, select that page.
- Else select the most recently updated page.
- Else select the first queued page.

Inspector tabs:

- `Preview`
- `Markdown`
- `Raw HTML`
- `Metadata`
- `Events`
- `Failure`

## Implementation Details

### Selection Model

Use a stable `st.session_state` key:

- `scrape_inspector_url`

When a user selects a row or dropdown URL, persist it.

If selected URL no longer exists in current run, reset to current running/recent URL.

### Preview Tab

Show:

- URL
- status
- fetch mode
- HTTP status
- text length
- link density
- duration
- output artifact paths

If markdown exists, show first 4,000-8,000 chars as rendered markdown or code preview.

If markdown does not exist but raw HTML exists, show a short extracted text preview if possible.

If nothing exists yet, show live status and event trail.

### Markdown Tab

Read `markdown_path` if present and exists.

Controls:

- Preview length selector: 2k / 8k / 20k / full
- Download or show path to artifact

Do not crash if file was deleted or path is stale.

### Raw HTML Tab

Read `raw_html_path` if present and exists.

Controls:

- Preview length selector
- Show size in KB/MB

### Metadata Tab

Read:

- Page row fields
- `metadata_path` JSON if present

Merge them visually without overwriting row values silently.

### Events Tab

Filter current run events by URL and show timeline:

- `page_started`
- `fetch_attempt`
- `fetch_retrying_next_mode`
- `fetch_exception`
- `artifacts_saved`
- `page_done`

### Failure Tab

Show only when failure exists, but keep the tab visible.

Include:

- failure reason
- error text
- HTTP status
- fetch mode
- retry attempts/events
- recommended next action placeholder

## Acceptance Criteria

- During an active run, inspector automatically follows the running page unless user chooses another URL.
- For completed pages, markdown/raw/metadata previews work from artifact paths.
- For failed pages, failure reason and related events are visible in one place.
- Missing files do not crash the UI.
- Existing separate Page Inspector tab can remain, but Scrape Run is usable without it.

## Verification

Run:

```bash
python3 - <<'PY'
from pathlib import Path
for p in [Path("app.py")]:
    compile(p.read_text(encoding="utf-8"), str(p), "exec")
print("ok")
PY
```

Manual test:

1. Open a run with successful and failed pages.
2. Select a successful URL and inspect all tabs.
3. Select a failed URL and verify the failure tab has useful content.
4. Delete or rename one artifact file and verify the UI shows a missing-file state instead of crashing.

## Merge Notes

Coordinate with Phase 1 on shared selection keys and queue table row shape. The inspector should consume page/event data; it should not define new worker behavior.

