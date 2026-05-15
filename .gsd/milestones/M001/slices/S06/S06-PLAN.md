# S06: Simple V1 configuration and proof command

**Goal:** Define a single V1 config contract and ship one proof command that validates S01–S05 artifact contracts together and reports deterministic pass/fail for M001 readiness.
**Demo:** One simple config file controls maintenance options, retrieval limits, PDF limits, and Zvec settings; a proof command runs the M001 fixture workflow and reports pass/fail.

## Must-Haves

- A single config file controls maintenance options, retrieval limits, PDF limits, and Zvec settings with validation/defaults.
- A proof command validates cross-slice artifacts (S03 stale packet reason, S04 maintenance artifact chain, S05 PDF chunk page numbers + quarantine reasons) and exits non-zero on failures.
- Proof writes machine-readable and human-readable outputs (result JSON + markdown report) without reading `.gsd/` paths.
- Unit/integration tests cover success path and key negative paths (missing artifacts, malformed fields, bounded-limit violations).

## Proof Level

- This slice proves: integration

## Integration Closure

Consumes S01 run artifact conventions, S03 stale packet contracts, S04 maintenance result artifact chain, and S05 PDF/Zvec proof artifacts; introduces one composed entrypoint `scripts/m001_proof.py` wired to config + validators. After this slice, milestone is end-to-end provable via one command.

## Verification

- Adds deterministic per-check proof results with check IDs, status, reasons, and timestamps in JSON/markdown outputs so failures localize to specific cross-slice contracts.

## Tasks

- [x] **T01: Implement V1 config schema and defaults for proof orchestration** `est:45m`
  Why: S06 needs a single operator-editable config contract (R012/R015) before proof wiring can be deterministic.
  - Files: `src/scrape_planner/config_v1.py`, `configs/m001_v1.json`, `tests/test_m001_config_v1.py`
  - Verify: python3 -m unittest tests.test_m001_config_v1 -v

- [ ] **T02: Build M001 proof validator and CLI report command** `est:1h15m`
  Why: S06 demo requires one real entrypoint that composes S01–S05 contracts and returns objective pass/fail.
  - Files: `src/scrape_planner/proof_m001.py`, `scripts/m001_proof.py`, `tests/test_m001_proof_command.py`, `tests/fixtures/m001_proof`
  - Verify: python3 -m unittest tests.test_m001_proof_command -v

- [ ] **T03: Wire end-to-end proof smoke verification and usage docs** `est:30m`
  Why: Final assembly slice must prove real entrypoint execution and operator usability, not only library-level checks.
  - Files: `README.md`, `tests/test_m001_proof_command.py`
  - Verify: python3 scripts/m001_proof.py --config configs/m001_v1.json --run-root tests/fixtures/m001_proof/pass/run_root --output-dir tests/fixtures/m001_proof/tmp_output

## Files Likely Touched

- src/scrape_planner/config_v1.py
- configs/m001_v1.json
- tests/test_m001_config_v1.py
- src/scrape_planner/proof_m001.py
- scripts/m001_proof.py
- tests/test_m001_proof_command.py
- tests/fixtures/m001_proof
- README.md
