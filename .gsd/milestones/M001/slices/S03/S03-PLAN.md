# S03: Stale dependency tracking and tracer job contract

**Goal:** Implement deterministic stale dependency tracking from source hash changes to tracer wiki pages and emit an agent/skill-compatible maintenance job packet contract with durable run artifacts.
**Demo:** A changed source hash marks a dependent tracer wiki page stale and creates an agent/skill-compatible maintenance job packet.

## Must-Haves

- Given prior/current source hash views and a source-to-page dependency map, a changed hash marks dependent pages stale with reason `source_hash_changed`, records parseable stale transition events in run artifacts, and writes a maintenance job packet directory that references bounded retrieval evidence paths for downstream tracer execution.

## Proof Level

- This slice proves: integration

## Integration Closure

Consumes stable source IDs/hashes and run persistence conventions from `src/scrape_planner/source_monitor.py` and `src/scrape_planner/run_persistence.py`, plus bounded evidence contracts from `src/scrape_planner/raw_retrieval.py`; introduces composition wiring that turns stale pages into packetized tracer maintenance work for S04 executor flow.

## Verification

- Adds durable stale-evaluation snapshot/event artifacts and packet-manifest diagnostics so future agents can inspect what changed, why pages were marked stale, and which packet was emitted for remediation.

## Tasks

- [x] **T01: Define stale-dependency and tracer job packet contracts with deterministic evaluator** `est:1h`
  ---
  estimated_steps: 8
  estimated_files: 4
  skills_used:
    - design-an-interface
    - tdd
  ---
  - Files: `src/scrape_planner/tracer_dependencies.py`, `tests/test_tracer_stale_dependencies.py`, `src/scrape_planner/__init__.py`, `src/scrape_planner/source_monitor.py`
  - Verify: PYTHONPATH=src uv run pytest -q tests/test_tracer_stale_dependencies.py

- [x] **T02: Persist stale artifacts and emit maintenance job packet from run context** `est:1h 15m`
  ---
  estimated_steps: 9
  estimated_files: 5
  skills_used:
    - observability
    - verify-before-complete
  ---
  - Files: `src/scrape_planner/run_persistence.py`, `src/scrape_planner/tracer_dependencies.py`, `tests/test_tracer_job_packet_integration.py`, `scripts/tracer_stale_proof.py`, `tests/test_raw_retrieval_integration.py`
  - Verify: PYTHONPATH=src uv run pytest -q tests/test_tracer_job_packet_integration.py

## Files Likely Touched

- src/scrape_planner/tracer_dependencies.py
- tests/test_tracer_stale_dependencies.py
- src/scrape_planner/__init__.py
- src/scrape_planner/source_monitor.py
- src/scrape_planner/run_persistence.py
- tests/test_tracer_job_packet_integration.py
- scripts/tracer_stale_proof.py
- tests/test_raw_retrieval_integration.py
