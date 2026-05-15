---
id: S03
parent: M001
milestone: M001
provides:
  - Deterministic source-hash-to-page stale tracking contract.
  - Agent/skill-compatible tracer maintenance job packet directory contract with bounded evidence references.
  - Durable stale transition and packet diagnostics for downstream execution/audit.
requires:
  - slice: S01
    provides: Stable source IDs/hashes and run persistence conventions for stale evaluation references.
  - slice: S02
    provides: Bounded retrieval evidence contract consumed by maintenance packet references.
affects:
  - S04
  - S06
key_files:
  - src/scrape_planner/tracer_dependencies.py
  - src/scrape_planner/run_persistence.py
  - tests/test_tracer_stale_dependencies.py
  - tests/test_tracer_job_packet_integration.py
  - scripts/tracer_stale_proof.py
key_decisions:
  - Use deterministic ordering for source-hash change evaluation and dependent page transitions to guarantee stable artifacts.
  - Emit maintenance packets that reference bounded retrieval evidence paths instead of embedding full evidence payloads.
patterns_established:
  - Contract-first stale dependency evaluation with typed outputs and explicit transition reasons.
  - Run-artifact-first diagnostics for stale transitions and packet emission to support downstream agent debugging.
observability_surfaces:
  - Persisted stale transition artifacts/events in run outputs.
  - Packet-manifest diagnostics that identify what changed, why targets were marked stale, and which packet was emitted.
drill_down_paths:
  - .gsd/milestones/M001/slices/S03/tasks/T01-SUMMARY.md
  - .gsd/milestones/M001/slices/S03/tasks/T02-SUMMARY.md
duration: ""
verification_result: passed
completed_at: 2026-05-15T20:46:23.439Z
blocker_discovered: false
---

# S03: S03

**Shipped deterministic source-hash stale dependency tracking that marks tracer wiki pages stale and emits agent/skill-compatible maintenance job packets with bounded evidence references plus durable run diagnostics.**

## What Happened

S03 delivered the tracer stale-maintenance contract end to end. T01 introduced typed stale-dependency/job-packet contracts and a deterministic hash-delta evaluator that maps changed source hashes to dependent tracer pages with reason `source_hash_changed`, including stable ordering and schema validation behavior. T02 integrated that evaluator into run-context persistence: stale transition snapshots/events are written as durable artifacts, and a maintenance job packet directory is emitted for downstream tracer execution with references to bounded retrieval evidence paths. Integration diagnostics were added so future agents can inspect exactly what changed, why a page was marked stale, and which packet should be executed. During verification, a Python 3.9 compatibility issue and a legacy test signature mismatch were resolved to align with the expanded packet contract.

## Verification

Executed slice-plan verification suites using `gsd_exec`: `PYTHONPATH=src uv run pytest -q tests/test_tracer_stale_dependencies.py tests/test_tracer_job_packet_integration.py` (11 passed). This confirms deterministic stale transition behavior, stale reason/value correctness, contract/schema handling, run-artifact persistence, and maintenance packet emission with bounded evidence references.

## Requirements Advanced

- {{requirementId}} — {{howThisSliceAdvancedIt}}

## Requirements Validated

- {{requirementId}} — {{whatProofNowMakesItValidated}}

## New Requirements Surfaced

None.

## Requirements Invalidated or Re-scoped

- {{requirementIdOr_none}} — {{what changed}}

## Operational Readiness

None.

## Deviations

Updated existing stale-dependency unit test expectations/signature to align with the expanded maintenance packet contract introduced by T02.

## Known Limitations

Does not execute the downstream wiki page update itself; S03 only determines stale pages and emits packetized maintenance work for S04 to execute.

## Follow-ups

Validate end-to-end tracer page creation/update flow in S04 using S03 packet artifacts as the input contract.

## Files Created/Modified

- `src/scrape_planner/tracer_dependencies.py` — Added deterministic stale-dependency evaluator, typed contracts, and maintenance packet contract logic.
- `src/scrape_planner/run_persistence.py` — Integrated stale artifact persistence and maintenance packet emission into run context outputs.
- `tests/test_tracer_stale_dependencies.py` — Added/updated deterministic transition and contract validation coverage.
- `tests/test_tracer_job_packet_integration.py` — Added integration assertions for persisted stale artifacts and packet emission behavior.
- `scripts/tracer_stale_proof.py` — Added/updated proof path for stale tracking and packet contract behavior.
