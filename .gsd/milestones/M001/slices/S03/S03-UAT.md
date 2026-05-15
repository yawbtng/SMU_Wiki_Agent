# S03: S03 — UAT

**Milestone:** M001
**Written:** 2026-05-15T20:46:23.439Z

# S03: S03 — UAT

**Milestone:** M001
**Written:** 2026-05-15

## UAT Type

- UAT mode: artifact-driven
- Why this mode is sufficient: S03’s deliverable is deterministic contract + persisted artifacts (stale transitions and maintenance packets), so correctness is proven by reproducible test fixtures and run outputs rather than interactive runtime UX.

## Preconditions

- Repository is at the S03 implementation state.
- Python environment is available via `uv`.
- Fixture test data for tracer dependencies and packet integration is present under `tests/`.

## Smoke Test

Run:

1. `PYTHONPATH=src uv run pytest -q tests/test_tracer_stale_dependencies.py`
2. Confirm suite passes and reports deterministic stale transition behavior.

## Test Cases

### 1. Source hash change marks dependent tracer page stale

1. Prepare prior/current source-hash views where one source hash changes.
2. Provide source-to-page dependency map including one dependent tracer page.
3. Execute stale evaluator via test harness.
4. **Expected:** Dependent page is marked stale with reason `source_hash_changed`; transition ordering and fields are deterministic and parseable.

### 2. Run context emits maintenance packet with bounded evidence references

1. Execute integration path that persists stale artifacts during run handling.
2. Inspect emitted packet directory and manifest through integration assertions.
3. **Expected:** Packet exists, references bounded retrieval evidence paths (not oversized inline payload), and links to stale transition context required by downstream tracer maintenance execution.

## Edge Cases

### Malformed dependency contract input

1. Provide malformed dependency schema in evaluator/integration tests.
2. **Expected:** Contract validation error is surfaced explicitly; no silent success path.

## Failure Signals

- Any failure in `tests/test_tracer_stale_dependencies.py` or `tests/test_tracer_job_packet_integration.py`.
- Missing stale transition artifacts or missing packet manifest fields in integration assertions.
- Non-deterministic ordering of transitions/targets across repeated runs.

## Not Proven By This UAT

- Live execution of downstream tracer wiki page mutation (covered in S04).
- Production-scale performance/throughput characteristics under very large dependency maps.

## Notes for Tester

Focus on artifact integrity and determinism: this slice is a contract-and-persistence layer. If tests fail, inspect stale transition serialization and packet manifest assembly first, because those are the authoritative outputs consumed by S04.
