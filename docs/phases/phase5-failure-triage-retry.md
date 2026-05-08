# Phase 5: Failure Triage And Retry

## Goal

Turn failures from a static list into an actionable workflow: understand, filter, retry, fallback, and export.

## Primary Ownership

- `app.py`
- `src/scrape_planner/tavily_retry.py`
- Optional new module: `src/scrape_planner/retry_runner.py`
- Optional new UI helper: `src/scrape_planner/ui_failure_triage.py`

## Do Not Own

- Core concurrency implementation
- Durable persistence design
- Cleanup/editor workflow

## Current Problem

Failures are written to `failures.json`, but the user has no serious failure command center. Retrying is not integrated into the scrape cockpit.

## Required UX

Add a Failure Triage section in Scrape Run:

- Failure summary cards
- Failure groups by reason
- Failed page table
- Retry controls
- Export controls

## Failure Groups

Group by normalized reason:

- `timeout`
- `blocked`
- `http_error`
- `empty_content`
- `parse_error`
- `network_error`
- `unknown`

Use existing `failure_classifier.py` where possible. Do not invent incompatible names unless you also map old values.

## Retry Actions

Add controls:

- `Retry selected`
- `Retry all failed`
- `Retry by failure type`
- `Retry with Tavily fallback`
- `Export failed URLs`

Minimum viable behavior:

- Create a new retry run id by default, e.g. original id plus `-retry-01`
- Carry selected failed URLs into the retry run
- Preserve source run id in metadata

Better behavior if Phase 4 is available:

- Allow retry inside same run as new attempts
- Append retry events to same durable event log

## Tavily Fallback

Integrate existing `retry_failed_with_tavily` safely:

- Require API key before enabling
- Show estimated call count
- Show estimated cost if configured
- Write fallback result events
- Update page state after fallback succeeds/fails

## Failure Table

Columns:

- selected checkbox if feasible
- url
- failure_reason
- http_status
- fetch_mode
- attempt
- duration
- error
- last_event_ts

Filters:

- failure reason
- HTTP status
- URL contains
- fetch mode

## Exports

Add export/download data for:

- failed URLs TXT
- failed pages CSV
- failures JSON

If Streamlit download buttons are not practical for local use, write files to run root and display paths.

## Acceptance Criteria

- Failed pages are grouped with counts.
- User can retry all failed pages.
- User can retry one failure group.
- User can export failed URLs.
- Tavily fallback is disabled unless API key is present.
- Retry run links back to source run.

## Verification

Run:

```bash
python3 - <<'PY'
from pathlib import Path
for p in [Path("app.py"), Path("src/scrape_planner/tavily_retry.py")]:
    compile(p.read_text(encoding="utf-8"), str(p), "exec")
print("ok")
PY
```

Manual test:

1. Use a run with known failed pages.
2. Verify failure grouping counts.
3. Export failed URLs.
4. Retry a small selected subset.
5. Confirm retry run contains only selected failed URLs.

## Merge Notes

This phase consumes page/failure state from Phase 3 and Phase 4. If those are not merged, implement against existing `failures.json` plus `store.get_pages(...)`, then add durable integration later.

