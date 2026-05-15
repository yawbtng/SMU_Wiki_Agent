# S04: S04

**Goal:** Execute one S03 maintenance packet through a deterministic tracer wiki maintenance path that updates/creates one cited page and emits complete downstream-executable artifact chain (manifest, source map, source usage, events, result, handoff) with bounded evidence references.
**Demo:** A pi-agent/skill-style job updates or creates one cited tracer wiki page with manifest, source map, source usage, events, and handoff/result artifacts.

## Must-Haves

- Complete the planned slice outcomes.

## Verification

- Run the task and slice verification checks for this slice.

## Tasks

- [x] **T01: Added S04 tracer-maintenance packet/result contracts with deterministic artifact writers and bounded evidence enforcement.**
  - Files: `src/scrape_planner/models.py`, `src/scrape_planner/run_persistence.py`, `src/scrape_planner/tracer_maintenance.py`, `tests/test_tracer_maintenance_proof.py`
  - Verify: python3 -m unittest tests.test_tracer_maintenance_proof.TestTracerMaintenanceContractAndWriters -v

- [x] **T02: Implement single-packet maintenance executor and end-to-end proof tests**
  - Files: `src/scrape_planner/tracer_maintenance.py`, `src/scrape_planner/state.py`, `tests/test_tracer_maintenance_proof.py`
  - Verify: python3 -m unittest tests.test_tracer_maintenance_proof.TestTracerMaintenanceExecutorE2E -v

## Files Likely Touched

- src/scrape_planner/models.py
- src/scrape_planner/run_persistence.py
- src/scrape_planner/tracer_maintenance.py
- tests/test_tracer_maintenance_proof.py
- src/scrape_planner/state.py
