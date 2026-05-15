# S04: Tracer wiki page maintenance proof

**Goal:** Execute one S03 maintenance packet through a deterministic tracer wiki maintenance path that updates/creates one cited page and emits complete downstream-executable artifact chain (manifest, source map, source usage, events, result, handoff) with bounded evidence references.
**Demo:** A pi-agent/skill-style job updates or creates one cited tracer wiki page with manifest, source map, source usage, events, and handoff/result artifacts.

## Must-Haves

- Running a single-packet executor against a fixture S03 packet creates/updates one tracer wiki page markdown with citations tied to source IDs/URLs and bounded evidence handles.
- Executor writes machine-parseable artifacts for this run: `events.jsonl`, `source_usage.jsonl`, `result.json`, page manifest, and source map updates preserving source-hash provenance and stale reason continuity (`source_hash_changed`).
- Output packet/result artifacts remain pi-agent/skill-compatible for downstream resumption (explicit target page, status, artifact pointers, timestamps).
- Tests prove happy path and key negative path (malformed/missing required packet fields) without reading `.gsd/` paths.

## Proof Level

- This slice proves: integration

## Integration Closure

Consumes S03 packet contract outputs and retrieval evidence handles, then closes S03→S04 boundary by materializing a concrete tracer page plus maintenance artifacts that S06 can validate end-to-end.

## Verification

- Adds append-only maintenance lifecycle events and bounded source-usage traces so future agents can inspect started/succeeded/failed transitions and replay context without raw-body payload expansion.

## Tasks

- [ ] **T01: Define S04 packet/result contracts and deterministic artifact writers** `est:1.5h`
  Why: Locking contract semantics first prevents executor drift and ensures R006/R008/R014 are encoded before orchestration.
  - Files: `src/scrape_planner/models.py`, `src/scrape_planner/run_persistence.py`, `src/scrape_planner/tracer_maintenance.py`, `tests/test_tracer_maintenance_proof.py`
  - Verify: python3 -m unittest tests.test_tracer_maintenance_proof.TestTracerMaintenanceContractAndWriters -v

- [ ] **T02: Implement single-packet maintenance executor and end-to-end proof tests** `est:1.5h`
  Why: This is the slice demo path (S03 packet -> tracer page + artifacts) and proves one tracer maintenance loop works in real execution.
  - Files: `src/scrape_planner/tracer_maintenance.py`, `src/scrape_planner/state.py`, `tests/test_tracer_maintenance_proof.py`
  - Verify: python3 -m unittest tests.test_tracer_maintenance_proof.TestTracerMaintenanceExecutorE2E -v

## Files Likely Touched

- src/scrape_planner/models.py
- src/scrape_planner/run_persistence.py
- src/scrape_planner/tracer_maintenance.py
- tests/test_tracer_maintenance_proof.py
- src/scrape_planner/state.py
