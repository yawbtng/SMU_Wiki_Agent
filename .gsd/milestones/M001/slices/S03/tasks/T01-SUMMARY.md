---
id: T01
parent: S03
milestone: M001
key_files:
  - src/scrape_planner/tracer_dependencies.py
  - tests/test_tracer_stale_dependencies.py
  - src/scrape_planner/__init__.py
key_decisions:
  - (none)
duration: 
verification_result: passed
completed_at: 2026-05-15T20:43:37.151Z
blocker_discovered: false
---

# T01: Added deterministic tracer stale-dependency contracts and pure hash-delta evaluator with typed transition/job packet outputs.

**Added deterministic tracer stale-dependency contracts and pure hash-delta evaluator with typed transition/job packet outputs.**

## What Happened

Implemented new module src/scrape_planner/tracer_dependencies.py with explicit contract dataclasses for stale transitions, evaluator errors/results, and maintenance job packets. Added reverse dependency normalization that validates mapping shape and de-duplicates/sorts page ids, plus source-hash entry normalization that reports structured missing-key/content-hash errors instead of crashing. Implemented evaluate_stale_dependencies as a pure deterministic function (sorted source iteration, sorted deduped stale pages) that emits transition records with required fields source_id, old_hash, new_hash, affected_pages, and reason=source_hash_changed. Added packet builder for downstream agent/skill-compatible maintenance job payload shape. Exported evaluator surface in src/scrape_planner/__init__.py. Added focused tests in tests/test_tracer_stale_dependencies.py for unchanged hashes, single-source change, multi-source shared-page dedupe, changed source absent from reverse map, malformed reverse-map rejection, malformed source-hash entries, packet shape, and normalization ordering behavior.

## Verification

Ran the task verification commands successfully: pytest target for stale dependency evaluator tests passed, and module compile check passed. Test results confirm deterministic ordering and required transition reason/value behavior plus malformed schema error surfacing.

## Verification Evidence

| # | Command | Exit Code | Verdict | Duration |
|---|---------|-----------|---------|----------|
| 1 | `PYTHONPATH=src uv run pytest -q tests/test_tracer_stale_dependencies.py` | 0 | ✅ pass | 140ms |
| 2 | `python3 -m compileall src/scrape_planner/tracer_dependencies.py` | 0 | ✅ pass | 58ms |

## Deviations

None.

## Known Issues

None.

## Files Created/Modified

- `src/scrape_planner/tracer_dependencies.py`
- `tests/test_tracer_stale_dependencies.py`
- `src/scrape_planner/__init__.py`
