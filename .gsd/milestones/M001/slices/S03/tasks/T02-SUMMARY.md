---
id: T02
parent: S03
milestone: M001
key_files:
  - src/scrape_planner/tracer_dependencies.py
  - src/scrape_planner/run_persistence.py
  - tests/test_tracer_job_packet_integration.py
  - tests/test_tracer_stale_dependencies.py
  - scripts/tracer_stale_proof.py
key_decisions:
  - (none)
duration: 
verification_result: mixed
completed_at: 2026-05-15T20:45:48.947Z
blocker_discovered: false
---

# T02: Added run-context stale artifact persistence and tracer maintenance packet emission with bounded evidence references plus integration diagnostics.

**Added run-context stale artifact persistence and tracer maintenance packet emission with bounded evidence references plus integration diagnostics.**

## What Happened

Implemented S03/T02 wiring across stale evaluation and run persistence surfaces. Extended tracer dependency contracts to include run-scoped packet metadata, per-page targets, bounded evidence references (source_id/chunk_id/path only), explicit evidence_status, executor instructions, and expected outputs. Added serialization helpers and strict validation for required packet inputs (run_id, evidence key set). Extended run persistence with persist_stale_artifacts_and_packet() to atomically write stale_dependencies.json snapshots, append transition events to stale_dependencies.jsonl, and conditionally materialize packet manifests under run_root/packets/<run_id>/ only when stale pages exist. Added integration coverage asserting artifact creation, JSON/JSONL parseability, stale reason correctness, packet fields, append-only behavior across repeated writes, and malformed-input failures. Added scripts/tracer_stale_proof.py as a lightweight diagnostics proof command that emits stale counts and packet paths for operator inspection.

## Verification

Executed required verification commands and fixed a Python 3.9 compatibility import issue (datetime.UTC) plus updated legacy test usage of the new packet builder signature. Final verification passed for both slice-required suites.

## Verification Evidence

| # | Command | Exit Code | Verdict | Duration |
|---|---------|-----------|---------|----------|
| 1 | `PYTHONPATH=src uv run pytest -q tests/test_tracer_job_packet_integration.py` | 2 | ❌ fail (initial; ImportError datetime.UTC on Python 3.9) | 176ms |
| 2 | `PYTHONPATH=src uv run pytest -q tests/test_tracer_job_packet_integration.py` | 0 | ✅ pass | 156ms |
| 3 | `PYTHONPATH=src uv run pytest -q tests/test_tracer_stale_dependencies.py` | 1 | ❌ fail (initial; legacy callsite missing new run_id arg) | 147ms |
| 4 | `PYTHONPATH=src uv run pytest -q tests/test_tracer_stale_dependencies.py` | 0 | ✅ pass | 157ms |

## Deviations

Updated existing stale-dependency unit test expectations/signature to align with expanded packet contract; this was required by contract evolution introduced in T02.

## Known Issues

None.

## Files Created/Modified

- `src/scrape_planner/tracer_dependencies.py`
- `src/scrape_planner/run_persistence.py`
- `tests/test_tracer_job_packet_integration.py`
- `tests/test_tracer_stale_dependencies.py`
- `scripts/tracer_stale_proof.py`
