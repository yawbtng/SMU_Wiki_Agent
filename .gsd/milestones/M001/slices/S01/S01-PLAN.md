# S01: S01

**Goal:** Establish a raw-first source monitoring foundation that diffs current source observations against prior ledger state and writes durable run artifacts (`run.json`, `events.jsonl`, `source_diff.jsonl`, `source_ledger.jsonl`, `build_report.md`) with lifecycle statuses for downstream slices.
**Demo:** Given fixture source records, the system writes a run directory with run.json, events.jsonl, source_diff.jsonl, and a report showing new/changed/unchanged/failed/deleted-candidate sources.

## Must-Haves

- Complete the planned slice outcomes.

## Verification

- Run the task and slice verification checks for this slice.

## Tasks

- [x] **T01: Added `src/scrape_planner/source_monitor.py` with deterministic URL/source hashing, JSONL ledger helpers, and lifecycle classification for new/unchanged/changed/redirected/failed/deleted-candidate states.**
  - Files: `src/scrape_planner/source_monitor.py`, `src/scrape_planner/models.py`, `src/scrape_planner/storage.py`
  - Verify: python3 - <<'PY'

- [x] **T02: Write run artifacts and fixture proof test for S01 contract**
  - Files: `src/scrape_planner/source_monitor.py`, `src/scrape_planner/run_persistence.py`, `tests/test_source_monitor.py`, `tests/fixtures/source_monitor/prior_ledger.jsonl`, `tests/fixtures/source_monitor/current_observations.json`
  - Verify: python3 -m pytest tests/test_source_monitor.py -q

## Files Likely Touched

- src/scrape_planner/source_monitor.py
- src/scrape_planner/models.py
- src/scrape_planner/storage.py
- src/scrape_planner/run_persistence.py
- tests/test_source_monitor.py
- tests/fixtures/source_monitor/prior_ledger.jsonl
- tests/fixtures/source_monitor/current_observations.json
