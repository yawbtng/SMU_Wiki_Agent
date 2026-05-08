# Phase 4: Pause, Resume, And Durable Runs

## Goal

Make long scrapes survivable. A refresh, process restart, pause, or cancel should not destroy visibility into what happened or force the user to start from scratch.

## Primary Ownership

- `src/scrape_planner/state.py`
- New module: `src/scrape_planner/run_persistence.py`
- `src/scrape_planner/scrape_worker.py`
- Small UI controls in `app.py`

## Do Not Own

- Inspector layout
- Failure retry UI
- Cleanup workflow
- Metrics polish

## Current Problem

Live state mostly lives in Redis or memory. `scrape_manifest.json` is written only after the run completes. During long runs, that is fragile.

## Required Durable Artifacts

Inside each run root:

- `run_status.json`
- `pages.jsonl`
- `events.jsonl`
- `failures.json`
- `scrape_manifest.json`
- `selected_urls.json`

Write incrementally during the run.

## Implementation Details

### Persistence Module

Create `src/scrape_planner/run_persistence.py` with helpers:

```python
def write_run_status(run_root: Path, status: dict[str, Any]) -> None: ...
def read_run_status(run_root: Path) -> dict[str, Any]: ...
def append_run_event(run_root: Path, event: dict[str, Any]) -> None: ...
def read_run_events(run_root: Path, limit: int | None = None) -> list[dict[str, Any]]: ...
def upsert_page_state(run_root: Path, page: dict[str, Any]) -> None: ...
def read_page_states(run_root: Path) -> list[dict[str, Any]]: ...
```

For page state, JSONL append is okay, but reads must collapse by URL to latest state.

### State Store Fallback

When `store.get_status/get_pages/get_events` is empty, UI should load from durable files.

Do this without making UI code messy:

- Either add store methods that accept `run_root`
- Or add a small loader helper consumed by Scrape tab

### Pause

Add pause flag:

- `set_pause(site_id, run_id, value)`
- `get_pause(site_id, run_id)`

Worker behavior:

- Existing running page may finish.
- Workers do not take new URLs while paused.
- State is `paused` while no active workers are running and queue remains.

### Resume

Resume should:

- Read latest page states
- Skip `success`
- Requeue `queued`, `failed` if user chooses retry failed, and `cancelled` if user chooses resume cancelled
- Keep same run id unless user explicitly starts a new retry run

Minimum viable version:

- Resume queued/cancelled unfinished pages from same run.
- Do not automatically retry failed pages unless Phase 5 adds that flow.

### Cancel

Cancel should persist:

- final run status
- cancellation event
- cancelled page states for remaining queued pages

## Acceptance Criteria

- Active run state survives Streamlit refresh.
- If Redis is unavailable, durable files still allow UI to show progress.
- `events.jsonl` grows during the run.
- `pages.jsonl` or equivalent state grows during the run.
- Pause prevents new pages from starting.
- Resume continues unfinished queued/cancelled pages.

## Verification

Run:

```bash
python3 - <<'PY'
from pathlib import Path
for p in [
    Path("src/scrape_planner/state.py"),
    Path("src/scrape_planner/scrape_worker.py"),
    Path("src/scrape_planner/run_persistence.py"),
    Path("app.py"),
]:
    if p.exists():
        compile(p.read_text(encoding="utf-8"), str(p), "exec")
print("ok")
PY
```

Manual test:

1. Start a 20 URL run.
2. Refresh the Streamlit browser.
3. Confirm progress remains visible.
4. Pause, wait, confirm no new pages start.
5. Resume, confirm queue continues.
6. Cancel, confirm queued pages become cancelled.

## Merge Notes

This phase touches worker and state contracts. Coordinate carefully with Phase 3. If Phase 3 lands first, build persistence around its `pages_by_url` model.

