---
estimated_steps: 43
estimated_files: 3
skills_used: []
---

# T01: Implement source ledger models and lifecycle diff/classification engine

---
estimated_steps: 8
estimated_files: 3
skills_used:
  - tdd
  - verify-before-complete
---
# T01: Implement source ledger models and lifecycle diff/classification engine

**Slice:** S01 — Source ledger and run log foundation
**Milestone:** M001

## Description

Create a new source-monitor module with deterministic source identity, URL normalization/canonical handling, content hashing, and prior-vs-current lifecycle classification. This task establishes the core contract for `new`, `unchanged`, `changed`, `redirected`, `failed`, and `deleted_candidate`, including conservative deletion-candidate behavior and preservation of prior successful hashes on failed checks.

## Failure Modes

| Dependency | On error | On timeout | On malformed response |
|------------|----------|-----------|----------------------|
| Prior ledger JSONL read | Treat as empty ledger only when file missing; otherwise raise explicit parse error | N/A (local file) | Raise explicit validation/parsing error and fail fast in pure loader |
| Source observation payload | Classify source as `failed` with error detail and preserve prior stable fields | Classify as `failed` with timeout reason | Classify as `failed` if required fields absent or invalid |

## Negative Tests

- **Malformed inputs**: observation missing `url`; invalid timestamp; unsupported status/error combination.
- **Error paths**: failed observation with prior successful ledger row keeps prior `content_hash` and increments failure counters.
- **Boundary conditions**: missing/failure counter exactly at threshold transitions to `deleted_candidate`; below threshold remains `failed`.

## Steps

1. Add a new module `src/scrape_planner/source_monitor.py` with typed dataclasses or TypedDicts for observation input, ledger row, diff row, and run counts/status helpers.
2. Implement URL canonicalization + stable source ID generation (`src_` + deterministic hash from canonical/normalized URL) and content hash helper (`sha256:` prefix).
3. Implement ledger load/serialize helpers for JSONL rows and deterministic merge/update behavior for seen sources.
4. Implement classification logic that compares previous ledger state and current observation to produce lifecycle statuses and updated ledger rows.
5. Implement conservative deletion-candidate threshold handling using configurable counters (`delete_candidate_after_failures` and/or missing threshold), without deleting rows.
6. Ensure failed observations preserve prior successful `content_hash`/`last_success_at` while updating failure metadata.
7. Expose pure entrypoints returning: updated ledger rows, diff rows, and status counts needed by run/report writers.
8. Add inline docstrings/comments for downstream S02/S03 assumptions about stable IDs/hashes.

## Must-Haves

- [ ] Classification returns all required statuses with deterministic rules.
- [ ] Failed source handling preserves prior successful hash and does not remove ledger rows.
- [ ] Deletion candidate threshold behavior is configurable and conservative.

## Verification

- `python3 - <<'PY'\nfrom pathlib import Path\ncompile(Path('src/scrape_planner/source_monitor.py').read_text(encoding='utf-8'), 'src/scrape_planner/source_monitor.py', 'exec')\nprint('compile ok')\nPY`
- Task T02 integration tests exercise and assert the classification contract end-to-end.

## Inputs

- `.gsd/milestones/M001/slices/S01/S01-RESEARCH.md` — contract expectations and lifecycle semantics.
- `src/scrape_planner/models.py` — existing model style and naming conventions.
- `src/scrape_planner/storage.py` — atomic write conventions to align with downstream writers.

## Expected Output

- `src/scrape_planner/source_monitor.py` — source ledger types, hashing, identity, and lifecycle diff engine.

## Inputs

- `.gsd/milestones/M001/slices/S01/S01-RESEARCH.md`
- `src/scrape_planner/models.py`
- `src/scrape_planner/storage.py`

## Expected Output

- `src/scrape_planner/source_monitor.py`

## Verification

python3 - <<'PY'
from pathlib import Path
compile(Path('src/scrape_planner/source_monitor.py').read_text(encoding='utf-8'), 'src/scrape_planner/source_monitor.py', 'exec')
print('compile ok')
PY

## Observability Impact

Defines machine-readable diff/status objects that subsequent artifact writers log to run diagnostics.
