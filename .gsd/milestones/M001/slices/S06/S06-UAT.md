# S06: Simple V1 configuration and proof command — UAT

**Milestone:** M001
**Written:** 2026-05-15T21:34:34.225Z

# S06: Simple V1 configuration and proof command — UAT

**Milestone:** M001
**Written:** 2026-05-15

## UAT Type

- UAT mode: artifact-driven
- Why this mode is sufficient: S06 is a contract-validation slice whose primary behavior is deterministic inspection of generated artifacts and exit/report semantics.

## Preconditions

- Python 3 is available in the project environment.
- Fixture run root exists at `tests/fixtures/m001_proof/pass/run_root`.
- Config file exists at `configs/m001_v1.json`.

## Smoke Test

Run:
`python3 scripts/m001_proof.py --config configs/m001_v1.json --run-root tests/fixtures/m001_proof/pass/run_root --output-dir tests/fixtures/m001_proof/tmp_output`

Expected quick confirmation:
- Exit code is 0.
- `proof_result.json` and `proof_report.md` are created in the output directory.

## Test Cases

### 1. Passing fixture returns overall pass with expected check IDs

1. Execute the proof command against the passing fixture run root.
2. Open `proof_result.json`.
3. Verify `overall_verdict` is `pass` and checks include IDs `S03_STALE_PACKET`, `S04_MAINTENANCE_ARTIFACTS`, and `S05_PDF_CONTRACTS`.
4. **Expected:** All checks are present, each is pass, and report files exist.

### 2. Contract violation returns non-zero with targeted failure reason

1. Run `python3 -m unittest tests.test_m001_proof_command -v`.
2. Inspect failing-fixture assertions covered by the suite.
3. **Expected:** Failure scenarios return non-zero and include targeted check ID/reason in outputs (not a generic failure).

## Edge Cases

### Missing or malformed required artifacts

1. Use the negative fixture path exercised by `tests.test_m001_proof_command` (missing/invalid contract fields).
2. Execute the proof command under test conditions.
3. **Expected:** Command fails deterministically, identifies the specific failed contract check, and still writes result/report artifacts for diagnosis.

## Failure Signals

- Proof CLI exits non-zero on fixture that should pass.
- `proof_result.json` is missing, malformed, or missing required check IDs.
- `proof_report.md` not generated.
- Check reasons do not localize failure to S03/S04/S05 contract areas.

## Not Proven By This UAT

- Performance/scalability behavior on very large real-world corpora outside fixture bounds.
- Runtime scheduling/orchestration of upstream slice producers; this UAT validates artifact contracts, not live ingestion pipelines.

## Notes for Tester

- Prefer fixture-backed paths for deterministic outcomes.
- Recreate output directory as needed between runs to avoid confusion from stale files.
- Use the JSON output as source-of-truth for automation; markdown is human-readable support.
