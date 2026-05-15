---
id: T01
parent: S01
milestone: M001
key_files:
  - src/scrape_planner/source_monitor.py
key_decisions:
  - (none)
duration: 
verification_result: passed
completed_at: 2026-05-15T20:35:34.230Z
blocker_discovered: false
---

# T01: Added `src/scrape_planner/source_monitor.py` with deterministic URL/source hashing, JSONL ledger helpers, and lifecycle classification for new/unchanged/changed/redirected/failed/deleted-candidate states.

**Added `src/scrape_planner/source_monitor.py` with deterministic URL/source hashing, JSONL ledger helpers, and lifecycle classification for new/unchanged/changed/redirected/failed/deleted-candidate states.**

## What Happened

Implemented a new pure source-monitor module that defines typed dataclasses for observations, ledger rows, diff rows, and config thresholds; added URL normalization and stable source identity (`src_` + SHA-256 prefix) plus content hashing (`sha256:`). Added JSONL ledger load/serialize helpers with explicit malformed-line errors and deterministic ordering. Implemented prior-vs-current classification logic that emits updated ledger rows, diff rows, and status counts, including conservative threshold-based deleted-candidate transitions for repeated failures/missing observations while never deleting rows. Failed observations preserve prior successful `content_hash`, `last_success_at`, and `last_changed_at` metadata, and missing prior sources are retained and classified with failure/deleted-candidate outcomes. Included inline docstrings describing downstream stability assumptions for IDs/hashes.

## Verification

Re-verified module syntax by compiling `src/scrape_planner/source_monitor.py` via the task’s prescribed Python compile check; command succeeded and printed `compile ok`.

## Verification Evidence

| # | Command | Exit Code | Verdict | Duration |
|---|---------|-----------|---------|----------|
| 1 | `python3 - <<'PY'
from pathlib import Path
compile(Path('src/scrape_planner/source_monitor.py').read_text(encoding='utf-8'), 'src/scrape_planner/source_monitor.py', 'exec')
print('compile ok')
PY` | 0 | ✅ pass | 350ms |

## Deviations

None.

## Known Issues

No dedicated runtime/integration tests were added in this task; end-to-end contract assertions are expected in Task T02 per plan.

## Files Created/Modified

- `src/scrape_planner/source_monitor.py`
