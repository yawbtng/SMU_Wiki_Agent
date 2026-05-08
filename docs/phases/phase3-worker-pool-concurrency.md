# Phase 3: Worker Pool And Concurrency

## Goal

Replace the single-page scrape loop with a configurable worker pool so large runs can process multiple URLs concurrently while still emitting per-page events and stable page state.

## Primary Ownership

- `src/scrape_planner/scrape_worker.py`
- `src/scrape_planner/models.py`
- Small run-start UI change in `app.py` only for concurrency input

## Do Not Own

- Full Scrape tab redesign
- Inspector UI
- Failure retry UI
- Cleanup workflow

## Current Problem

The worker processes selected URLs sequentially. A 2,383 URL run is therefore slow, hard to cancel, and hard to observe by worker lane.

## Required Behavior

Add configurable concurrency:

- Default: `4`
- UI bounds: `1-16`
- Each worker owns one URL at a time
- Each page row includes `worker_id`
- Page events include `worker_id`

## Implementation Details

### Public Runner API

Update start signature carefully:

```python
def start(self, site_id: str, run_id: str, urls: list[DiscoveredURL], concurrency: int = 4) -> None:
```

Keep default so existing callers still work.

### Queue Model

Use a thread-safe queue:

- Input items: selected `DiscoveredURL`
- Shared page state list/dict protected by a lock
- Shared status protected by a lock

Recommended in-memory shape:

```python
pages_by_url = {
    url: {
        "url": url,
        "status": "queued",
        "worker_id": None,
        "attempt": 0,
        ...
    }
}
```

Initialize all selected pages as `queued` before worker threads start.

### Worker Events

Events must include:

- `worker_id`
- `url`
- `event`
- `status`
- `attempt`
- `fetch_mode`
- `duration_ms` when available

Expected events:

- `page_queued`
- `page_started`
- `fetch_attempt`
- `fetch_retrying_next_mode`
- `fetch_exception`
- `artifacts_saved`
- `page_done`
- `worker_idle`

### Status Counts

Maintain counts from page state:

- queued
- running
- success
- failed
- cancelled
- total

Avoid racey manual increments if possible; derive under lock.

### Cancellation

If cancel flag is set:

- Workers stop taking new URLs
- Already running fetches complete or timeout
- Remaining queued pages become `cancelled`
- Final state becomes `cancelled`

### Fetch Sessions

Be conservative with shared session objects. Create fetch sessions per fetch attempt as current code does unless you prove reuse is safe.

## Acceptance Criteria

- A run with concurrency 4 shows up to 4 pages running.
- Page rows and events include `worker_id`.
- Counts stay consistent: queued + running + success + failed + cancelled = total.
- Cancelling marks remaining queued items as cancelled.
- Existing single-concurrency behavior works with `concurrency=1`.

## Verification

Run:

```bash
python3 - <<'PY'
from pathlib import Path
for p in [Path("src/scrape_planner/scrape_worker.py"), Path("app.py")]:
    compile(p.read_text(encoding="utf-8"), str(p), "exec")
print("ok")
PY
```

Manual test:

1. Start 20 URLs with concurrency 1.
2. Start 20 URLs with concurrency 4.
3. Confirm concurrency 4 completes faster and shows multiple running workers.
4. Cancel mid-run and confirm queued pages become cancelled.

## Merge Notes

This phase creates the core page-state contract consumed by Phase 1, Phase 2, Phase 4, and Phase 5. Keep field names stable and document any additions in this file if changed.

