---
estimated_steps: 45
estimated_files: 3
skills_used: []
---

# T02: Add fixture-level proof command coverage for index-first bounded retrieval

---
estimated_steps: 6
estimated_files: 3
skills_used:
  - tdd
  - verify-before-complete
  - write-docs
---
# T02: Add fixture-level proof command coverage for index-first bounded retrieval

**Slice:** S02 — Index-first raw retrieval
**Milestone:** M001

## Description
Wire retrieval build/query into an executable fixture-facing path and add regression coverage proving query-time behavior is bounded and index-first. Capture proof assertions in tests that can be reused by S03/S04 integration.

## Failure Modes

| Dependency | On error | On timeout | On malformed response |
|------------|----------|-----------|----------------------|
| Fixture run data location | Fail fast with actionable path error | N/A | Validate schema before query and surface explicit contract failure |
| Retrieval module API | Surface typed exception/status in test harness | N/A | Assert failure status instead of proceeding with partial output |

## Load Profile

- **Shared resources**: fixture raw markdown corpus and generated index artifacts
- **Per-operation cost**: one index build + bounded query execution
- **10x breakpoint**: fixture size growth; test still asserts no O(N) per-query markdown read

## Negative Tests

- **Malformed inputs**: query against non-existent run/index path
- **Error paths**: stale index after source mutation
- **Boundary conditions**: max-results clipping and snippet truncation assertions

## Steps

1. Add a small CLI/script entrypoint (or extend an existing script) to run raw index build then query using configurable bounds.
2. Add integration tests that monkeypatch/spy file reads during query and assert no full markdown corpus scan occurs.
3. Add assertions for evidence shape and bound flags so downstream slices can consume stable metadata fields.
4. Update README or developer docs minimally with command usage for S02 verification.

## Must-Haves

- [ ] Verification proves index-first behavior via query-time read-boundedness check.
- [ ] Verification proves bounded output semantics (result cap + snippet cap) and required evidence metadata.

## Verification

- `python3 -m pytest -q tests/test_raw_retrieval_integration.py -k "index_first or bounded or read"`
- `python3 scripts/raw_retrieval_proof.py --help`

## Inputs

- `src/scrape_planner/raw_retrieval.py` — retrieval API implemented in T01
- `tests/test_raw_retrieval_integration.py` — integration test scaffold from T01
- `README.md` — existing verification/docs conventions

## Expected Output

- `scripts/raw_retrieval_proof.py` — fixture proof command for raw retrieval index/query
- `tests/test_raw_retrieval_integration.py` — expanded read-boundedness and contract assertions
- `README.md` — concise S02 proof command documentation

## Inputs

- `src/scrape_planner/raw_retrieval.py`
- `tests/test_raw_retrieval_integration.py`
- `README.md`

## Expected Output

- `scripts/raw_retrieval_proof.py`
- `tests/test_raw_retrieval_integration.py`
- `README.md`

## Verification

python3 -m pytest -q tests/test_raw_retrieval_integration.py -k "index_first or bounded or read" && python3 scripts/raw_retrieval_proof.py --help

## Observability Impact

Adds explicit proof command and repeatable assertions for retrieval index health and bounded query behavior.
