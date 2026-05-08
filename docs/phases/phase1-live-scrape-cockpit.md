# Phase 1: Live Scrape Cockpit

## Goal

Make the Scrape Run tab stop looking dead after `Start Run`. Within one refresh cycle it must show run state, queue state, current activity, and recent logs even before the first page finishes.

## Primary Ownership

- `app.py`
- Optional new UI helper module if you split carefully: `src/scrape_planner/ui_scrape_dashboard.py`

## Do Not Own

- Worker concurrency internals
- Retry implementation
- Cleanup/editor workflow
- LLM scoring workflow

## Current Problem

The app starts a long scrape and mostly shows a green success toast. The detailed widgets only appear after `status`, `pages`, or `events` already contain data. For a 2,383 URL run, this creates a scary blank gap.

## Required UX

The Scrape Run tab should become a cockpit with these sections visible at all times:

1. Command bar
2. Run health header
3. Queue/activity table
4. Live event timeline
5. Inspector preview placeholder

If no run exists, show a clear ready state with selected URL count and start controls. If a run just started but no pages are finished, show queued/running state instead of empty space.

## Implementation Details

### Command Bar

Add a compact top command bar with:

- `Start Run`
- `Cancel Run`
- `Refresh`
- `Auto-refresh` checkbox
- Selected URL count
- Active run id

After starting a run:

- Set `run_id`
- Save app state
- Start runner
- Immediately call `st.rerun()` after showing or setting enough state so the dashboard repaints.

Important: avoid relying on a toast as the only feedback.

### Run Health Header

Always render metrics from best available state:

- Total
- Queued
- Running
- Success
- Failed
- Cancelled/skipped if available
- Pages/min
- ETA
- Elapsed

If state is missing, derive from selected URLs and show `pending initialization`.

### Queue/Activity Table

Show a table even when no completed page exists.

Data priority:

1. Live page state from durable/live state if available
2. Existing `store.get_pages(...)`
3. Selected URLs mapped to rows with `status = queued`

Columns:

- status
- url
- worker_id if present
- fetch_mode
- http_status
- failure_reason
- attempt
- duration_sec
- updated_at

Default sort:

1. running first
2. failed second
3. latest updated next
4. queued last

Filters:

- Status
- URL contains
- Slow threshold
- Show latest activity only

### Event Timeline

Replace raw event dataframe as the default view. A dataframe can remain behind an expander called `Raw events`.

Timeline rows should show:

- timestamp
- event
- status
- url
- fetch mode
- concise error/failure reason

Use `st.container(border=True)` rows or a compact dataframe with curated columns. The default must be readable.

### Empty/Loading States

Add meaningful states:

- `No run yet`
- `Run initializing`
- `Waiting for first page`
- `No events yet`
- `No pages match filters`

Do not leave large blank sections.

## Acceptance Criteria

- Starting a 2,000+ URL run does not leave a mostly blank screen.
- Scrape tab immediately shows total, queued, current state, and selected URL count.
- A newly started run shows queued rows before first page completion.
- Recent events are visible as readable timeline entries.
- Auto-refresh updates the cockpit without manual refresh while running.
- Existing `Page Inspector`, `Cleanup`, `Settings`, and `Metrics` tabs still import and render.

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

1. Start a small scrape of 5-10 URLs.
2. Confirm the cockpit fills immediately.
3. Confirm the queue table appears before first success.
4. Confirm event timeline updates while running.

## Merge Notes

This phase will likely touch the same Scrape tab as Phase 2 and Phase 5. If running in parallel, prefer extracting display helpers into uniquely named functions and keep worker contracts unchanged.

