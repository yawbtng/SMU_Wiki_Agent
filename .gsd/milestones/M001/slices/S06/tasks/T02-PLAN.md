---
estimated_steps: 12
estimated_files: 4
skills_used: []
---

# T02: Build M001 proof validator and CLI report command

Why: S06 demo requires one real entrypoint that composes S01–S05 contracts and returns objective pass/fail.

Do:
1. Add `src/scrape_planner/proof_m001.py` implementing check functions for:
   - S03 stale packet artifacts with reason `source_hash_changed` and bounded evidence references.
   - S04 maintenance artifacts (page, manifest, source map, source usage, events, result, handoff).
   - S05 PDF artifacts requiring chunk `page_number` and quarantine reason contract.
2. Implement deterministic result model: check_id, status(pass/fail), reason/details, timestamps, and overall verdict.
3. Add CLI entrypoint `scripts/m001_proof.py` that accepts `--config`, `--run-root`, and `--output-dir`; writes `proof_result.json` and `proof_report.md`; exits non-zero on any failed check.
4. Add integration tests `tests/test_m001_proof_command.py` with fixture-driven pass case and negative cases (missing artifact + malformed field).
5. Ensure tests/fixtures for this slice live outside `.gsd/` (e.g., under `tests/fixtures/m001_proof/`) and do not depend on gitignored planning artifacts.

Done when: running proof command against pass fixture returns success with both report files, and negative fixtures fail with targeted check IDs/reasons and non-zero exit.

Expected executor skills: tdd, verify-before-complete, observability

## Inputs

- `src/scrape_planner/config_v1.py`
- `configs/m001_v1.json`
- `src/scrape_planner/run_persistence.py`
- `src/scrape_planner/tracer_dependencies.py`
- `src/scrape_planner/tracer_maintenance.py`
- `tests/fixtures/source_monitor/prior_ledger.jsonl`

## Expected Output

- `src/scrape_planner/proof_m001.py`
- `scripts/m001_proof.py`
- `tests/test_m001_proof_command.py`
- `tests/fixtures/m001_proof/pass/run_root/s03/stale_packet.json`
- `tests/fixtures/m001_proof/pass/run_root/s04/maintenance/job-001/page.md`
- `tests/fixtures/m001_proof/pass/run_root/s04/maintenance/job-001/manifest.json`
- `tests/fixtures/m001_proof/pass/run_root/s04/maintenance/job-001/source_map.json`
- `tests/fixtures/m001_proof/pass/run_root/s04/maintenance/job-001/source_usage.json`
- `tests/fixtures/m001_proof/pass/run_root/s04/maintenance/job-001/events.jsonl`
- `tests/fixtures/m001_proof/pass/run_root/s04/maintenance/job-001/result.json`
- `tests/fixtures/m001_proof/pass/run_root/s04/maintenance/job-001/handoff.md`
- `tests/fixtures/m001_proof/pass/run_root/s05/pdf_chunks.jsonl`
- `tests/fixtures/m001_proof/pass/run_root/s05/pdf_quarantine.jsonl`
- `tests/fixtures/m001_proof/fail_missing/run_root/s03/stale_packet.json`
- `tests/fixtures/m001_proof/fail_malformed/run_root/s05/pdf_chunks.jsonl`

## Verification

python3 -m unittest tests.test_m001_proof_command -v

## Observability Impact

Proof outputs expose per-check status and failure reasons so downstream agents can localize contract breakage quickly.
