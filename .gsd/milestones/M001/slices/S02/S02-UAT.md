# S02: S02 — UAT

**Milestone:** M001
**Written:** 2026-05-15T20:41:26.440Z

# S02: S02 — UAT

**Milestone:** M001
**Written:** 2026-05-15

## UAT Type

- UAT mode: artifact-driven
- Why this mode is sufficient: S02’s contract is a deterministic retrieval/indexing API plus CLI proof surface; correctness is demonstrated by reproducible test artifacts and command outputs rather than long-running services.

## Preconditions

- Repository is available at `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`.
- Python dependencies are available through `uv`.
- Test fixtures under `tests/fixtures/raw_retrieval` are present.
- Command environment sets `PYTHONPATH=src`.

## Smoke Test

Run:

`PYTHONPATH=src python3 scripts/raw_retrieval_proof.py --help`

Expected: CLI usage text is printed with options for fixture root and index root, confirming the proof command surface is runnable.

## Test Cases

### 1. Index-first bounded retrieval path

1. Run `PYTHONPATH=src uv run pytest -q tests/test_raw_retrieval_integration.py -k "index_first or bounded or read"`.
2. Observe test run completes.
3. **Expected:** Selected tests pass, demonstrating index-first retrieval behavior and bounded evidence outputs.

### 2. Proof command contract visibility

1. Run `PYTHONPATH=src python3 scripts/raw_retrieval_proof.py --help`.
2. Inspect the printed usage/options.
3. **Expected:** Help output lists command purpose and arguments (`--fixture-root`, `--index-root`) with no import/runtime failures.

## Edge Cases

### Missing or stale index status behavior

1. Execute integration tests that cover status cases (`missing_index`, `stale_index`) as part of retrieval integration checks.
2. **Expected:** Retrieval returns explicit non-success status contracts for missing/stale index conditions and does not perform full raw-file scan fallback.

## Failure Signals

- `ModuleNotFoundError: No module named 'scrape_planner'` when PYTHONPATH is not set.
- `No module named pytest` when using system `python3 -m pytest` without project-managed pytest.
- Integration test failures in `tests/test_raw_retrieval_integration.py` for index-first/bounded behavior.
- Proof script failing to print help or exiting non-zero.

## Not Proven By This UAT

- Production-scale latency/performance characteristics on large, real university corpora.
- Downstream stale dependency graph updates and tracer wiki job packet generation (covered by later slices S03/S04).

## Notes for Tester

Use `PYTHONPATH=src` consistently in this repository. Prefer `uv run pytest` over `python3 -m pytest` in environments where system Python does not include pytest.
