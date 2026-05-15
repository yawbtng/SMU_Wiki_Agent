---
estimated_steps: 52
estimated_files: 4
skills_used: []
---

# T01: Define stale-dependency and tracer job packet contracts with deterministic evaluator

---
estimated_steps: 8
estimated_files: 4
skills_used:
  - design-an-interface
  - tdd
---

# T01: Define stale-dependency and tracer job packet contracts with deterministic evaluator

**Slice:** S03 — Stale dependency tracking and tracer job contract
**Milestone:** M001

## Description

Establish the canonical contract types and pure stale-evaluation logic that map source hash transitions to affected tracer pages before any persistence wiring. This closes the highest-risk ambiguity in S03 by locking schema fields (`source_id`, `old_hash`, `new_hash`, `affected_pages`, `reason`) and the deterministic mapping from reverse dependencies to stale page IDs.

## Failure Modes

| Dependency | On error | On timeout | On malformed response |
|------------|----------|-----------|----------------------|
| `src/scrape_planner/source_monitor.py` hash/state records | Raise validation error with explicit missing-key detail and skip stale output generation | N/A (local pure function) | Reject malformed source hash entries and return structured evaluator error result for caller logging |
| Source-map/reverse-dependency input file consumed by tests | Fail fast in tests with actionable schema mismatch assertion | N/A | Treat non-list page mappings as invalid and assert contract violation |

## Load Profile

- **Shared resources**: none (pure in-memory evaluation)
- **Per-operation cost**: O(S + E) over changed sources S and dependency edges E
- **10x breakpoint**: memory growth from oversized reverse maps; algorithm should remain linear and deterministic

## Negative Tests

- **Malformed inputs**: missing `source_id`, null hash values, reverse map entries with wrong types
- **Error paths**: changed source not present in reverse map should produce zero affected pages without crash
- **Boundary conditions**: empty changed-source set, duplicate page IDs in dependency list, repeated source entries

## Steps

1. Add a new tracer dependency module defining typed contracts for tracer page manifests, reverse dependency maps, stale transition records, and job packet metadata shape.
2. Implement a pure evaluator function that accepts prior/current source hash views plus reverse map and returns stale page IDs and transition records with deterministic ordering.
3. Implement schema normalization helpers that de-duplicate page IDs and validate required keys used by the evaluator.
4. Add focused unit tests covering unchanged hashes, single hash change, multiple sources to same page, and malformed-map rejection.

## Must-Haves

- [ ] Pure evaluator has no filesystem side effects and is deterministic for identical inputs.
- [ ] Transition records include `reason=source_hash_changed` for hash-delta stale marks and preserve source/page linkage.

## Verification

- `PYTHONPATH=src uv run pytest -q tests/test_tracer_stale_dependencies.py`
- `python3 -m compileall src/scrape_planner/tracer_dependencies.py`

## Verify Rules

- Use a real executable check, not prose.
- If the check needs file-content assertions, write a `node:test` file and run it with `node --test` or a package test script.
- Do not use inline `node -e` assertions for verification.

## Observability Impact

- Signals added/changed: structured stale transition record shape that downstream persistence appends to run events.
- How a future agent inspects this: read evaluator outputs through integration artifacts generated in T02.
- Failure state exposed: malformed dependency-map/schema errors become explicit and machine-parseable.

## Inputs

- `src/scrape_planner/source_monitor.py` — source hash/state conventions from S01.
- `src/scrape_planner/raw_retrieval.py` — bounded evidence identifier/path contract used by downstream packet references.
- `tests/test_source_monitor.py` — fixture and contract testing style precedent.

## Expected Output

- `src/scrape_planner/tracer_dependencies.py` — new contract and stale-evaluator module.
- `tests/test_tracer_stale_dependencies.py` — unit tests for evaluator determinism and negative paths.
- `src/scrape_planner/__init__.py` — export new S03 module surface if package-level access is used.

## Inputs

- `src/scrape_planner/source_monitor.py`
- `src/scrape_planner/raw_retrieval.py`
- `tests/test_source_monitor.py`

## Expected Output

- `src/scrape_planner/tracer_dependencies.py`
- `tests/test_tracer_stale_dependencies.py`
- `src/scrape_planner/__init__.py`

## Verification

PYTHONPATH=src uv run pytest -q tests/test_tracer_stale_dependencies.py

## Observability Impact

Defines structured stale transition and contract-validation error surfaces consumed by run artifact logging.
