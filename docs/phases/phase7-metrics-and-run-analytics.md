# Phase 7: Metrics And Run Analytics

## Goal

Make Metrics explain the scrape run: progress, speed, failures, slow pages, fetch modes, and output volume.

## Primary Ownership

- `app.py`
- Optional module: `src/scrape_planner/run_analytics.py`
- Optional UI helper: `src/scrape_planner/ui_metrics.py`

## Do Not Own

- Worker queue implementation
- Retry implementation
- App navigation cleanup

## Current Problem

The app has some charts, but they are spread out and do not tell the operator what happened or what needs action.

## Required Metrics

### Run Summary

- Total URLs
- Success
- Failed
- Cancelled/skipped
- Success rate
- Elapsed time
- Pages/min
- Estimated time remaining for active run

### Time Series

- Pages completed over time
- Success/failure over time
- Pages/min over time

### Duration

- Average duration
- P50 duration
- P95 duration
- Slowest pages table

### Failure Analysis

- Failures by reason
- Failures by fetch mode
- Failures by HTTP status
- Top repeated error strings

### Output Volume

- Markdown bytes total
- Raw HTML bytes total
- Text length distribution
- Largest pages table

## Implementation Details

Create analytics helpers that accept plain lists:

```python
def summarize_pages(pages: list[dict]) -> dict[str, Any]: ...
def build_completion_timeseries(pages: list[dict]) -> pd.DataFrame: ...
def summarize_failures(pages: list[dict], failures: list[dict]) -> pd.DataFrame: ...
```

The UI should read from:

1. Durable run files if Phase 4 exists
2. State store pages/events
3. Existing `scrape_manifest.json`

## Visuals

Use Streamlit-native charts or Altair already imported in the app.

Keep charts compact and operational:

- No giant decorative charts
- Tables should be sortable/filterable where useful
- Show empty states when no run data exists

## Acceptance Criteria

- Metrics tab works for active and completed runs.
- Shows failure reasons and slowest pages.
- Shows duration percentiles.
- Shows output size stats.
- Does not crash on missing files or empty run.

## Verification

Run:

```bash
python3 - <<'PY'
from pathlib import Path
for p in [Path("app.py"), Path("src/scrape_planner/run_analytics.py")]:
    if p.exists():
        compile(p.read_text(encoding="utf-8"), str(p), "exec")
print("ok")
PY
```

Manual test:

1. Open completed run.
2. Confirm summary metrics appear.
3. Confirm failure charts appear for failed pages.
4. Confirm slowest/largest page tables appear.
5. Open active run and confirm partial metrics work.

## Merge Notes

This phase should mostly consume data produced by other phases. Avoid mutating worker state from analytics code.

