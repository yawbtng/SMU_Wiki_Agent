---
estimated_steps: 57
estimated_files: 5
skills_used: []
---

# T02: Write run artifacts and fixture proof test for S01 contract

---
estimated_steps: 9
estimated_files: 4
skills_used:
  - python-testing-patterns
  - verify-before-complete
  - write-docs
---
# T02: Write run artifacts and fixture proof test for S01 contract

**Slice:** S01 — Source ledger and run log foundation
**Milestone:** M001

## Description

Add a file-artifact runner around the T01 diff engine that writes S01-required run outputs and validates them with a fixture-driven integration test. The proof must confirm parseable artifacts, correct status counts, durable event logging, redirected and deleted-candidate handling, and preservation of prior good hashes for failed sources.

## Failure Modes

| Dependency | On error | On timeout | On malformed response |
|------------|----------|-----------|----------------------|
| Run artifact writes | Fail run with `source_run_failed` event and explicit error in `run.json` when possible | N/A (local file) | Fail fast with parseable error event and non-success run status |
| JSONL append operations | Stop run and mark failed; avoid silent data loss | N/A | Emit error event and abort finishing steps |

## Load Profile

- **Shared resources**: local filesystem writes under run root.
- **Per-operation cost**: O(number of sources) diff + JSONL append per source event.
- **10x breakpoint**: larger event/diff files; bounded by local disk I/O, not network.

## Negative Tests

- **Malformed inputs**: fixture observation with explicit `error` and no content should classify as failed and remain parseable in artifacts.
- **Error paths**: prior missing/failure count crossing threshold becomes `deleted_candidate` and appears in both diff and report counts.
- **Boundary conditions**: redirected source with URL change still maps to stable `source_id` and is counted as `redirected`.

## Steps

1. Extend `src/scrape_planner/source_monitor.py` (or companion helpers) with run execution utilities that accept prior ledger + current observations + config and produce all required artifact payloads.
2. Reuse existing atomic JSON patterns from `src/scrape_planner/storage.py` and JSONL append conventions (without relying on private underscored helpers) to write `run.json`, `events.jsonl`, `source_diff.jsonl`, `source_ledger.jsonl`.
3. Add `build_report.md` generator summarizing counts and key failed/deleted-candidate details in human-readable markdown.
4. Ensure run status values follow contract: `completed`, `completed_with_failures`, `failed`.
5. Add fixture data under `tests/fixtures/source_monitor/` for prior ledger and current observations that collectively exercise all required statuses.
6. Add `tests/test_source_monitor.py` integration test that runs the proof path in a temp directory and asserts all artifact files exist and are parseable.
7. In test assertions, verify counts for all statuses, preservation of prior hash on failure, thresholded deleted-candidate behavior, and redirected record fields.
8. Add compile/smoke verification command for environments without pytest and prefer pytest execution when available.
9. Document artifact contract briefly in module docstring/comments for downstream slice consumers.

## Must-Haves

- [ ] Run directory writes all five required artifacts with parseable content.
- [ ] Fixture test covers `new`, `unchanged`, `changed`, `redirected`, `failed`, `deleted_candidate` in one scenario.
- [ ] `run.json` and `build_report.md` reflect consistent counts/status with JSONL diff rows.

## Verification

- `python3 -m pytest tests/test_source_monitor.py -q`
- `python3 - <<'PY'\nfrom pathlib import Path\nfor p in [\n    Path('src/scrape_planner/source_monitor.py'),\n    Path('tests/test_source_monitor.py'),\n]:\n    compile(p.read_text(encoding='utf-8'), str(p), 'exec')\nprint('compile ok')\nPY`

## Observability Impact

- Signals added/changed: source-run lifecycle and per-source classification events in `events.jsonl`; run-level status/count summary in `run.json`.
- How a future agent inspects this: parse `events.jsonl`, `source_diff.jsonl`, and `run.json` inside a run directory.
- Failure state exposed: explicit error reason, failed/deleted-candidate counts, and source-level failure rows.

## Inputs

- `src/scrape_planner/source_monitor.py` — classification engine from T01.
- `src/scrape_planner/storage.py` — atomic JSON write utility.
- `src/scrape_planner/run_persistence.py` — JSONL durability conventions and event shape precedents.
- `.gsd/milestones/M001/slices/S01/S01-RESEARCH.md` — required artifact contracts and fixture expectations.

## Expected Output

- `src/scrape_planner/source_monitor.py` — run artifact writing/report generation entrypoints.
- `tests/test_source_monitor.py` — fixture integration test for S01 artifact contract.
- `tests/fixtures/source_monitor/prior_ledger.jsonl` — prior-ledger fixture for lifecycle diff scenario.
- `tests/fixtures/source_monitor/current_observations.json` — current observation fixture covering all statuses.

## Inputs

- `src/scrape_planner/source_monitor.py`
- `src/scrape_planner/storage.py`
- `src/scrape_planner/run_persistence.py`
- `.gsd/milestones/M001/slices/S01/S01-RESEARCH.md`

## Expected Output

- `src/scrape_planner/source_monitor.py`
- `tests/test_source_monitor.py`
- `tests/fixtures/source_monitor/prior_ledger.jsonl`
- `tests/fixtures/source_monitor/current_observations.json`

## Verification

python3 -m pytest tests/test_source_monitor.py -q
python3 - <<'PY'
from pathlib import Path
for p in [
    Path('src/scrape_planner/source_monitor.py'),
    Path('tests/test_source_monitor.py'),
]:
    compile(p.read_text(encoding='utf-8'), str(p), 'exec')
print('compile ok')
PY

## Observability Impact

Implements durable source-run diagnostics artifacts required for downstream troubleshooting and automation.
