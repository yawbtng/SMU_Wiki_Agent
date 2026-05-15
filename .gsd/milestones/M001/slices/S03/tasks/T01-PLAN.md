---
estimated_steps: 30
estimated_files: 3
skills_used: []
---

# T01: Define tracer dependency + stale/job packet contracts and deterministic stale evaluator

Why
- S03’s main risk is ambiguous contract shape. Locking schema and pure evaluation logic first prevents drift in S04 packet consumers.

Files
- `src/scrape_planner/models.py`
- `src/scrape_planner/state.py`
- `tests/test_stale_dependency_tracking.py`

Do
1. Add typed contract structures for tracer page manifests, reverse dependency map entries, stale records, and maintenance job packet metadata/evidence references.
2. Implement a pure stale-evaluation function that accepts prior/current source hash views and source->page dependencies, and returns affected pages + per-source stale records with deterministic ordering.
3. Enforce raw-source identifiers (`source_id`, hashes) and reason taxonomy (at minimum `source_hash_changed`) aligned to R001/R006.
4. Add unit tests that prove: unchanged hashes => no stale pages; changed hash for one source => only dependent pages marked stale; sources without dependents do not create page staleness.
5. Keep this task I/O-free except fixtures in tests; persistence is handled in T02.

Must-haves
- Pure function output is deterministic and parseable.
- Contract fields required by downstream packet emission are present (page target, source refs, reason, run linkage).

Verification
- `python3 -m pytest tests/test_stale_dependency_tracking.py -q`

Done when
- Contract models and evaluator exist, tests pass, and evaluator output is sufficient for artifact writing and packet generation in T02.

Failure Modes (Q5)
- Dependency: malformed prior/current hash maps. On error: raise typed validation error; no partial stale set.
- Dependency: dependency map missing source IDs. On error: treat as no dependents (not crash), but include explicit empty handling in tests.

Load Profile (Q6)
- Shared resources: none in pure function path.
- Per-operation cost: O(changed_sources + dependency_edges_for_changed_sources).
- 10x breakpoint: large dependency map iteration; ensure set/dict lookups, no full raw file scans.

Negative Tests (Q7)
- Malformed inputs: missing hash fields / wrong type maps raise clear errors.
- Error paths: empty prior map with populated current map does not falsely mark unchanged sources stale.
- Boundary: single source with multiple pages yields all dependent pages exactly once.

## Inputs

- `src/scrape_planner/models.py`
- `src/scrape_planner/state.py`
- `.gsd/milestones/M001/slices/S03/S03-RESEARCH.md`
- `.gsd/REQUIREMENTS.md`

## Expected Output

- `src/scrape_planner/models.py`
- `src/scrape_planner/state.py`
- `tests/test_stale_dependency_tracking.py`

## Verification

python3 -m pytest tests/test_stale_dependency_tracking.py -q

## Observability Impact

Defines normalized stale reason/state fields that T02 will emit into durable events.
