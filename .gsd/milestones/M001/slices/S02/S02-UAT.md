# S02: Index-first raw retrieval — UAT

**Milestone:** M001
**Written:** 2026-05-15T17:56:32.238Z

# UAT Type
Blocked / recovery-required validation

## Preconditions
1. Auto-mode is running with milestone worktree isolation active for M001.
2. Python environment in the worktree has pytest installed.
3. S02 tasks are re-executed so task summaries are implementation-backed, not blocker placeholders.

## Steps
1. Re-run execute-task for `M001/S02/T01` in auto-mode and confirm `src/scrape_planner/raw_retrieval.py` and related tests are updated in the M001 worktree.
2. Re-run execute-task for `M001/S02/T02` in auto-mode and confirm `scripts/raw_retrieval_proof.py`, integration tests, and README updates are present in the M001 worktree.
3. Run:
   - `python3 -m pytest -q tests/test_raw_retrieval.py`
   - `python3 -m pytest -q tests/test_raw_retrieval_integration.py`
   - `python3 -m pytest -q tests/test_raw_retrieval_integration.py -k "index_first or bounded or read"`
   - `python3 scripts/raw_retrieval_proof.py --help`
4. Execute a fixture retrieval query and verify evidence output includes bounded fields: `source_id`, `url`, `path`, `chunk_id`, `score`, `snippet`, plus bound flags/status.
5. Trigger missing/stale index scenarios and verify explicit status contract is returned.

## Expected Outcomes
1. All verification commands pass.
2. Query path uses prebuilt index artifacts and does not scan all raw markdown files per query.
3. Missing/stale index conditions are explicit and test-covered.
4. Slice artifacts reflect real implementation evidence.

## Edge Cases
- Missing index artifact should return explicit missing-index status, not fallback full scan.
- Stale index should return explicit stale status and required remediation path.
- Empty or low-signal query still returns bounded, schema-valid response.

## Not Proven By This UAT
- 25k-page benchmark performance (deferred requirement scope).
- Downstream stale-dependency and tracer maintenance job flows (S03/S04).
