---
estimated_steps: 22
estimated_files: 3
skills_used: []
---

# T02: Implement single-packet maintenance executor and end-to-end proof tests

Why: This is the slice demo path (S03 packet -> tracer page + artifacts) and proves one tracer maintenance loop works in real execution.

Files: `src/scrape_planner/tracer_maintenance.py`, `src/scrape_planner/state.py`, `tests/test_tracer_maintenance_proof.py`

Do:
1. Add an orchestration entrypoint that consumes one packet directory/JSON, validates it, writes start event, materializes page+manifests+source usage, writes success/failure result, and returns structured execution status.
2. Ensure executor updates/creates exactly one target tracer page and records citations/source handles in markdown plus corresponding manifest/source-map linkage for dependency continuity.
3. Wire minimal state touchpoints (if needed) to keep runtime integration clean without broad refactors; keep slice-local and deterministic.
4. Add end-to-end fixture tests that create a temporary packet input and assert output file graph, parseability, citation presence, source_hash provenance continuity, and bounded evidence references.
5. Add negative-path test for malformed packet/missing required fields asserting failure result + failure event visibility.

Threat Surface (Q3):
- Abuse: packet tampering with unexpected fields/path traversal; mitigate by strict schema/path normalization and rejecting unknown/unsafe paths.
- Data exposure: avoid writing raw source bodies to artifacts.
- Input trust: packet input is untrusted; validate all required fields/types.

Requirement Impact (Q4):
- Requirements touched: R006, R007, R008, R014.
- Re-verify: stale provenance continuity and packet resumability contracts.
- Decisions revisited: none expected unless path contract conflicts are discovered.

Failure Modes (Q5): malformed packet -> structured failed `result.json` + failure event; write failure -> partial outputs bounded and error captured.
Load Profile (Q6): single-packet tracer proof only; bounded I/O and append-only logs.
Negative Tests (Q7): missing target page id, oversized evidence payload, invalid source hash mapping.

Verify: `python3 -m unittest tests.test_tracer_maintenance_proof.TestTracerMaintenanceExecutorE2E -v`

Done when: E2E tests pass and prove one packet execution produces the full S04 artifact chain with required contract fields and bounded references.

skills_used: tdd, verify-before-complete, observability

## Inputs

- ``src/scrape_planner/tracer_maintenance.py``
- ``tests/test_tracer_maintenance_proof.py``
- ``src/scrape_planner/state.py``

## Expected Output

- ``src/scrape_planner/tracer_maintenance.py``
- ``tests/test_tracer_maintenance_proof.py``

## Verification

python3 -m unittest tests.test_tracer_maintenance_proof.TestTracerMaintenanceExecutorE2E -v
