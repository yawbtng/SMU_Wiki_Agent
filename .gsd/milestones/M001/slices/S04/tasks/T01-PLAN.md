---
estimated_steps: 14
estimated_files: 4
skills_used: []
---

# T01: Define S04 packet/result contracts and deterministic artifact writers

Why: Locking contract semantics first prevents executor drift and ensures R006/R008/R014 are encoded before orchestration.

Files: `src/scrape_planner/models.py`, `src/scrape_planner/run_persistence.py`, `src/scrape_planner/tracer_maintenance.py`

Do:
1. Add compact dataclasses/validators for S04-consumed packet fields (job id, target page id/path, stale reason, source hashes, bounded evidence references) and produced result fields (status, artifact pointers, timestamps, error details).
2. Implement deterministic writer helpers in `tracer_maintenance.py` for tracer page markdown, `events.jsonl`, `source_usage.jsonl`, `result.json`, plus page-manifest/source-map updates using existing atomic/append helpers in `run_persistence.py`.
3. Enforce bounded evidence policy: source usage records must store ids/paths/snippets metadata only; reject/guard full raw body payload fields.
4. Preserve stale provenance semantics by carrying through `source_hash_changed` reason and source-hash references into manifest/source-map/result artifacts.
5. Keep output paths and JSON schemas stable and explicit so downstream agent/skill execution can resume from artifact pointers.

Must-haves:
- Input validation failures return structured failure result and append failure event.
- Artifact writers are idempotent for re-run on same job id (overwrite JSON, append event trail appropriately).

Verify: `python3 -m unittest tests.test_tracer_maintenance_proof.TestTracerMaintenanceContractAndWriters -v`

Done when: Contract validation and writer-level tests pass for both valid packet and malformed packet cases, and generated artifacts are parseable with required fields present.

skills_used: tdd, verify-before-complete, write-docs

## Inputs

- ``src/scrape_planner/models.py``
- ``src/scrape_planner/run_persistence.py``
- ``src/scrape_planner/observability.py``
- ``tests/test_observability.py``

## Expected Output

- ``src/scrape_planner/tracer_maintenance.py``
- ``tests/test_tracer_maintenance_proof.py``
- ``src/scrape_planner/models.py``

## Verification

python3 -m unittest tests.test_tracer_maintenance_proof.TestTracerMaintenanceContractAndWriters -v
