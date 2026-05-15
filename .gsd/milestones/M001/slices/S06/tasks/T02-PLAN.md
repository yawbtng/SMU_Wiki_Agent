---
estimated_steps: 21
estimated_files: 3
skills_used: []
---

# T02: Implement M001 proof command and contract validators with durable reports

Why: S06 demo requires one executable command that proves cross-slice contracts using bounded checks and durable pass/fail outputs.

Files:
- `src/scrape_planner/proof_m001.py`
- `scripts/m001_proof.py`
- `tests/test_m001_proof_command.py`

Do:
1) Implement proof validator module that reads config + run root and evaluates contract checks:
   - S03 stale dependency semantics (`source_hash_changed`) and bounded job packet evidence references.
   - S04 tracer maintenance output artifacts (page/manifest/source-map/source-usage/job-result/handoff contracts).
   - S05 PDF contracts (chunk `page_number` presence, quarantine reason visibility, zvec proof manifest/query fields).
2) Use existing persistence/observability helpers to write deterministic artifacts (e.g., proof_result JSON and markdown report) under a configurable output directory.
3) Add CLI wrapper script `scripts/m001_proof.py` accepting `--config`, `--run-root`, and optional `--output-dir`; return non-zero on any failed check.
4) Add unittest suite with fixture temp dirs covering: full pass path, missing-file failure, malformed-field failure, and exit-code/report behavior.
5) Ensure proof logic does not depend on `.gsd/` and does not use cleanup-manifest-first assumptions (R001).

Failure Modes (Q5): missing expected artifact -> fail check with missing path reason; unreadable/malformed JSON -> fail check with parse reason; oversized evidence list -> fail boundedness check.
Load Profile (Q6): proof reads only targeted contract files and bounded records; at 10x artifact volume it should remain linear in configured limits, not full corpus scans.
Negative Tests (Q7): absent stale reason, missing page_number, empty quarantine reason, malformed packet evidence refs.

Done when:
- CLI produces deterministic JSON + markdown outputs and accurate exit status.
- Tests prove both success and meaningful failure diagnostics.
- Proof command can be used as final S06 milestone readiness gate.

## Inputs

- `src/scrape_planner/config_v1.py`
- `src/scrape_planner/run_persistence.py`
- `src/scrape_planner/observability.py`
- `src/scrape_planner/state.py`
- `tests/test_m001_config_v1.py`

## Expected Output

- `src/scrape_planner/proof_m001.py`
- `scripts/m001_proof.py`
- `tests/test_m001_proof_command.py`

## Verification

python3 -m unittest tests.test_m001_proof_command -v && python3 scripts/m001_proof.py --config configs/m001_v1.json --run-root tests/fixtures/m001_proof/pass_fixture --output-dir tmp/m001-proof-smoke

## Observability Impact

Adds proof-step/check visibility with durable artifacts enabling fast diagnosis of cross-slice contract regressions.
