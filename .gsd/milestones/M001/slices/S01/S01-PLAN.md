# S01: Source ledger and run log foundation

**Goal:** Establish a raw-first source monitoring foundation that diffs current source observations against prior ledger state and writes durable run artifacts (`run.json`, `events.jsonl`, `source_diff.jsonl`, `source_ledger.jsonl`, `build_report.md`) with lifecycle statuses for downstream slices.
**Demo:** Given fixture source records, the system writes a run directory with run.json, events.jsonl, source_diff.jsonl, and a report showing new/changed/unchanged/failed/deleted-candidate sources.

## Must-Haves

- Given fixture source observations and a prior ledger fixture, running the S01 source monitor proof path writes a run directory containing parseable `run.json`, `events.jsonl`, `source_diff.jsonl`, `source_ledger.jsonl`, and `build_report.md`; diff/report counts include `new`, `unchanged`, `changed`, `redirected`, `failed`, and `deleted_candidate`; failed observations preserve prior successful `content_hash`; repeated missing/failure observations cross configured threshold into `deleted_candidate` without deleting ledger rows.

## Proof Level

- This slice proves: contract

## Integration Closure

Introduces a new source-monitor module and fixture proof runner, reusing existing storage primitives for atomic JSON writes and JSONL durability. Produces stable `source_id`/`content_hash` and run-event contracts consumed by S02 retrieval and S03 stale dependency tracking.

## Verification

- Adds source-run lifecycle events (`source_run_started`, per-source observation/classification events, diff/ledger writes, finished/failed) and explicit run-level status/count artifacts so future agents can diagnose partial failures from disk-only artifacts.

## Tasks

- [ ] **T01: Implement source ledger models and lifecycle diff/classification engine** `est:2h`
  ---
  estimated_steps: 8
  estimated_files: 3
  skills_used:
    - tdd
    - verify-before-complete
  ---
  - Files: `src/scrape_planner/source_monitor.py`, `src/scrape_planner/models.py`, `src/scrape_planner/storage.py`
  - Verify: python3 - <<'PY'
from pathlib import Path
compile(Path('src/scrape_planner/source_monitor.py').read_text(encoding='utf-8'), 'src/scrape_planner/source_monitor.py', 'exec')
print('compile ok')
PY

- [ ] **T02: Write run artifacts and fixture proof test for S01 contract** `est:2h`
  ---
  estimated_steps: 9
  estimated_files: 4
  skills_used:
    - python-testing-patterns
    - verify-before-complete
    - write-docs
  ---
  - Files: `src/scrape_planner/source_monitor.py`, `src/scrape_planner/run_persistence.py`, `tests/test_source_monitor.py`, `tests/fixtures/source_monitor/prior_ledger.jsonl`, `tests/fixtures/source_monitor/current_observations.json`
  - Verify: python3 -m pytest tests/test_source_monitor.py -q
python3 - <<'PY'
from pathlib import Path
for p in [
    Path('src/scrape_planner/source_monitor.py'),
    Path('tests/test_source_monitor.py'),
]:
    compile(p.read_text(encoding='utf-8'), str(p), 'exec')
print('compile ok')
PY

## Files Likely Touched

- src/scrape_planner/source_monitor.py
- src/scrape_planner/models.py
- src/scrape_planner/storage.py
- src/scrape_planner/run_persistence.py
- tests/test_source_monitor.py
- tests/fixtures/source_monitor/prior_ledger.jsonl
- tests/fixtures/source_monitor/current_observations.json
