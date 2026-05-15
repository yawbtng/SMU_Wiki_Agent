---
estimated_steps: 55
estimated_files: 5
skills_used: []
---

# T02: Persist stale artifacts and emit maintenance job packet from run context

---
estimated_steps: 9
estimated_files: 5
skills_used:
  - observability
  - verify-before-complete
---

# T02: Persist stale artifacts and emit maintenance job packet from run context

**Slice:** S03 — Stale dependency tracking and tracer job contract
**Milestone:** M001

## Description

Wire the evaluator into run persistence so S03 produces inspectable artifacts: stale snapshot JSON, append-only stale transition JSONL events, and a tracer maintenance packet directory contract suitable for S04 execution. Packet payload must reference bounded retrieval evidence IDs/paths instead of embedding raw corpus content.

## Failure Modes

| Dependency | On error | On timeout | On malformed response |
|------------|----------|-----------|----------------------|
| `src/scrape_planner/run_persistence.py` atomic/append writers | Propagate write failure with contextual artifact path in raised error and emit failure event where possible | N/A (local filesystem I/O) | Reject malformed event payload before append and fail task-level operation |
| Retrieval evidence references from `src/scrape_planner/raw_retrieval.py` | Emit packet with empty evidence list plus explicit `evidence_status` marker for caller visibility | N/A | Validate required evidence reference keys and fail packet build when missing |

## Load Profile

- **Shared resources**: filesystem writes under run directory
- **Per-operation cost**: constant-count JSON writes + JSONL appends per stale run, proportional to stale transition count
- **10x breakpoint**: event file growth; ensure append-only semantics and parseability under larger stale batches

## Negative Tests

- **Malformed inputs**: packet request missing `page_id` or `run_id` fails with structured error
- **Error paths**: unwritable run directory raises and does not leave partial packet manifest without metadata
- **Boundary conditions**: zero stale pages creates no packet directory but still writes empty/explicit stale snapshot

## Steps

1. Extend run persistence or add a dedicated tracer maintenance persistence helper to write `stale_dependencies.json`, append `stale_dependencies.jsonl`, and create packet directory structure.
2. Define packet file contract (metadata, page targets, evidence references, execution instructions, expected outputs) aligned to agent/skill handoff needs.
3. Implement integration entrypoint used by tests/CLI-facing flow to call evaluator then persistence writers in order.
4. Add integration test using fixture run root that asserts artifact existence, JSON/JSONL parseability, stale reason correctness, and packet contract fields.
5. Add a lightweight proof/verification script or test assertion that surfaces emitted packet path and stale counts for operator diagnostics.

## Must-Haves

- [ ] Append-only stale transition log remains valid JSONL across repeated writes.
- [ ] Packet contract includes target page IDs and bounded evidence references (IDs/paths), not embedded full raw file contents.

## Verification

- `PYTHONPATH=src uv run pytest -q tests/test_tracer_job_packet_integration.py`
- `PYTHONPATH=src uv run pytest -q tests/test_tracer_stale_dependencies.py`

## Verify Rules

- Use a real executable check, not prose.
- If the check needs file-content assertions, write a `node:test` file and run it with `node --test` or a package test script.
- Do not use inline `node -e` assertions for verification.

## Observability Impact

- Signals added/changed: `stale_dependencies.json`, `stale_dependencies.jsonl`, and packet manifest metadata with timestamps/run IDs.
- How a future agent inspects this: inspect run directory artifacts and packet directory contents from integration-test fixtures.
- Failure state exposed: artifact-write and packet-build failures include stage + path context for localization.

## Inputs

- `src/scrape_planner/tracer_dependencies.py` — evaluator and contract definitions from T01.
- `src/scrape_planner/run_persistence.py` — atomic JSON and JSONL append helpers from S01.
- `src/scrape_planner/raw_retrieval.py` — evidence reference shape consumed by packet contract.
- `tests/test_raw_retrieval_integration.py` — integration test style for bounded evidence handling.

## Expected Output

- `src/scrape_planner/run_persistence.py` — stale artifact + packet persistence wiring.
- `src/scrape_planner/tracer_dependencies.py` — orchestration helpers for packet emission from stale set.
- `tests/test_tracer_job_packet_integration.py` — integration coverage for run artifact and packet contract.
- `scripts/tracer_stale_proof.py` — optional proof command or diagnostics script for S03 artifact emission.

## Inputs

- `src/scrape_planner/tracer_dependencies.py`
- `src/scrape_planner/run_persistence.py`
- `src/scrape_planner/raw_retrieval.py`
- `tests/test_raw_retrieval_integration.py`

## Expected Output

- `src/scrape_planner/run_persistence.py`
- `src/scrape_planner/tracer_dependencies.py`
- `tests/test_tracer_job_packet_integration.py`
- `scripts/tracer_stale_proof.py`

## Verification

PYTHONPATH=src uv run pytest -q tests/test_tracer_job_packet_integration.py

## Observability Impact

Introduces durable stale transition artifacts and packet manifests for failure diagnosis and downstream executor traceability.
