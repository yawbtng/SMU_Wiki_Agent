---
id: S06
parent: M001
milestone: M001
provides:
  - Single V1 config + deterministic M001 proof command that validates S03–S05 contracts and emits actionable pass/fail evidence.
requires:
  - slice: S01
    provides: Run artifact and source lifecycle conventions consumed by proof checks.
  - slice: S03
    provides: Stale packet contract validated by check ID S03_STALE_PACKET.
  - slice: S04
    provides: Maintenance artifact chain validated by check ID S04_MAINTENANCE_ARTIFACTS.
  - slice: S05
    provides: PDF/Zvec artifact and quarantine contracts validated by check ID S05_PDF_CONTRACTS.
affects:
  []
key_files:
  - src/scrape_planner/config_v1.py
  - configs/m001_v1.json
  - tests/test_m001_config_v1.py
  - src/scrape_planner/proof_m001.py
  - scripts/m001_proof.py
  - tests/test_m001_proof_command.py
  - README.md
key_decisions:
  - Use one typed V1 config contract as the single control plane for maintenance/retrieval/PDF/Zvec options.
  - Emit both machine-readable JSON and human-readable markdown reports from proof validation with deterministic check IDs.
  - Fail fast with non-zero exit codes on contract violations to make proof command automation-safe.
patterns_established:
  - Contract-first cross-slice validation via stable check IDs and explicit reasons.
  - Artifact-driven proofing with deterministic fixture-based tests before live runs.
  - Single-entrypoint milestone proof command that composes prior-slice contracts.
observability_surfaces:
  - proof_result.json per-check status/reason/timestamp output
  - proof_report.md human-readable proof report
  - CLI exit code semantics for health/failure signaling
drill_down_paths:
  - .gsd/milestones/M001/slices/S06/tasks/T01-SUMMARY.md
  - .gsd/milestones/M001/slices/S06/tasks/T02-SUMMARY.md
  - .gsd/milestones/M001/slices/S06/tasks/T03-SUMMARY.md
duration: ""
verification_result: passed
completed_at: 2026-05-15T21:34:34.225Z
blocker_discovered: false
---

# S06: Simple V1 configuration and proof command

**Shipped a single V1 config contract plus a deterministic M001 proof CLI that validates S03–S05 cross-slice artifacts and emits machine/human pass-fail outputs.**

## What Happened

Implemented a typed V1 config loader/validator (`src/scrape_planner/config_v1.py`) and canonical operator-editable defaults (`configs/m001_v1.json`) so maintenance options, retrieval bounds, PDF limits, and Zvec settings are controlled from one place with strict required-field and boundedness checks. Added the composed proof validator/CLI path (`src/scrape_planner/proof_m001.py`, `scripts/m001_proof.py`) that validates key cross-slice contracts: S03 stale packet reason contract, S04 maintenance artifact chain, and S05 PDF chunk page-number/quarantine reason contracts. The command writes deterministic `proof_result.json` and `proof_report.md` and exits non-zero on contract failure to localize regressions. Finalized operator usage in README and ensured real CLI invocation behavior is covered in tests and fixture-backed smoke execution.

## Verification

Executed all slice-plan verification commands via gsd_exec and all passed: (1) `python3 -m unittest tests.test_m001_config_v1 -v` (config schema/default/bounds tests pass), (2) `python3 -m unittest tests.test_m001_proof_command -v` (proof command pass/fail semantics, check IDs/reasons, report generation pass), and (3) `python3 scripts/m001_proof.py --config configs/m001_v1.json --run-root tests/fixtures/m001_proof/pass/run_root --output-dir tests/fixtures/m001_proof/tmp_output` (real proof run succeeds and generates deterministic JSON/Markdown outputs).

## Requirements Advanced

- R012 — Centralized V1 configuration now controls maintenance/retrieval/PDF/Zvec options with validation/defaults.
- R015 — Added deterministic milestone proof command with machine/human outputs and non-zero failure semantics.

## Requirements Validated

- R012 — Verified via `python3 -m unittest tests.test_m001_config_v1 -v` covering required fields/defaults/bounded checks.
- R015 — Verified via `python3 -m unittest tests.test_m001_proof_command -v` and real CLI run over pass fixture generating proof_result.json/proof_report.md with pass verdict and expected check IDs.

## New Requirements Surfaced

None.

## Requirements Invalidated or Re-scoped

- none — No requirement invalidation or re-scope identified in S06.

## Operational Readiness

None.

## Deviations

None.

## Known Limitations

Proof behavior is validated against fixture contracts and deterministic artifact layouts; it does not by itself prove production-scale latency or completeness of upstream artifact generation beyond specified contracts.

## Follow-ups

Run the same proof CLI against a representative non-fixture run root as a post-milestone hardening check.

## Files Created/Modified

- `src/scrape_planner/config_v1.py` — Typed V1 config schema, loader, defaults, and validation/bounds enforcement.
- `configs/m001_v1.json` — Canonical operator-editable M001 V1 config values.
- `tests/test_m001_config_v1.py` — Unit tests for config parsing, defaults, and contract/bounds failures.
- `src/scrape_planner/proof_m001.py` — Cross-slice contract validator for S03/S04/S05 with deterministic check outputs.
- `scripts/m001_proof.py` — Proof CLI entrypoint writing JSON/Markdown reports and exit semantics.
- `tests/test_m001_proof_command.py` — Integration-style CLI tests for pass/fail behaviors and output artifacts.
- `README.md` — Operator usage docs for running M001 proof command.
