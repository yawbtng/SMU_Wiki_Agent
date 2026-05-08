# Phase 6: Navigation And App Structure

## Goal

Reduce tab soup and split the 1,500+ line `app.py` into smaller surfaces without changing core behavior.

## Primary Ownership

- `app.py`
- New UI modules under `src/scrape_planner/`

## Do Not Own

- Worker concurrency behavior
- Persistence behavior
- Retry semantics
- LLM scoring logic internals

## Current Problem

`app.py` owns almost everything: workspace state, discovery, scoring, scraping, cleanup, Claude plan, settings, observability, and metrics. This makes the UI feel scattered and makes parallel changes painful.

## Target Navigation

Reduce top-level tabs to:

- `Workspace`
- `Discover`
- `Select`
- `Scrape`
- `Cleanup`
- `Metrics`
- `Settings`

Move `Page Inspector` into `Scrape`.

Move `Claude Plan` behind either:

- `Cleanup`
- `Metrics`
- or an expander in `Settings`

Keep the exact destination decision conservative. Do not delete functionality.

## Refactor Shape

Extract render functions:

```python
render_workspace(...)
render_discovery(...)
render_url_selection(...)
render_scrape_run(...)
render_cleanup(...)
render_metrics(...)
render_settings(...)
```

If passing many arguments becomes ugly, create a small context object:

```python
@dataclass
class AppContext:
    store: RunStateStore
    runner: ScrapeRunner
    cleanup_runner: CleanupRunner
    ...
```

Keep session state keys stable unless absolutely necessary.

## UI Cleanup

Remove duplicate concepts:

- `Add Site` and workspace creation overlap
- `Page Inspector` and Scrape preview overlap
- `Settings + Observability` and `Metrics` overlap

Do not remove screens without moving their useful controls somewhere reachable.

## Acceptance Criteria

- Top-level tabs are fewer and map to the actual workflow.
- `app.py` is smaller or at least organized around render functions.
- No major feature disappears.
- Existing saved app state still loads.
- User can still create workspace, discover URLs, select URLs, start scrape, inspect pages, cleanup, and view metrics.

## Verification

Run:

```bash
python3 - <<'PY'
from pathlib import Path
for p in [Path("app.py"), *Path("src/scrape_planner").glob("ui_*.py")]:
    compile(p.read_text(encoding="utf-8"), str(p), "exec")
print("ok")
PY
```

Manual test:

1. Open app.
2. Create/open workspace.
3. Visit each top-level tab.
4. Confirm old actions are still reachable.
5. Confirm Scrape contains page inspection.

## Merge Notes

This phase is high-conflict with all UI phases. Best strategy: land functional phases first, then do this structural cleanup. If it must run in parallel, confine work to extraction with minimal behavior changes.

