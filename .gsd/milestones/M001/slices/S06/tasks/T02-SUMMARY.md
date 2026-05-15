---
id: T02
parent: S06
milestone: M001
key_files:
  - src/scrape_planner/proof_m001.py
  - scripts/m001_proof.py
  - tests/test_m001_proof_command.py
  - tests/fixtures/m001_proof/pass/run_root/s03/stale_packet.json
  - tests/fixtures/m001_proof/pass/run_root/s04/maintenance/job-001/page.md
  - tests/fixtures/m001_proof/pass/run_root/s04/maintenance/job-001/manifest.json
  - tests/fixtures/m001_proof/pass/run_root/s04/maintenance/job-001/source_map.json
  - tests/fixtures/m001_proof/pass/run_root/s04/maintenance/job-001/source_usage.json
  - tests/fixtures/m001_proof/pass/run_root/s04/maintenance/job-001/events.jsonl
  - tests/fixtures/m001_proof/pass/run_root/s04/maintenance/job-001/result.json
  - tests/fixtures/m001_proof/pass/run_root/s04/maintenance/job-001/handoff.md
  - tests/fixtures/m001_proof/pass/run_root/s05/pdf_chunks.jsonl
  - tests/fixtures/m001_proof/pass/run_root/s05/pdf_quarantine.jsonl
  - tests/fixtures/m001_proof/fail_missing/run_root/s03/stale_packet.json
  - tests/fixtures/m001_proof/fail_malformed/run_root/s05/pdf_chunks.jsonl
  - tests/fixtures/m001_proof/fail_malformed/run_root/s05/pdf_quarantine.jsonl
key_decisions: []
duration: 
verification_result: passed
completed_at: 2026-05-15T21:28:46.717Z
blocker_discovered: false
---

# T02: Added an M001 proof validator module and CLI that emits deterministic per-check JSON/Markdown reports with non-zero exit on cross-slice contract failures.

**Added an M001 proof validator module and CLI that emits deterministic per-check JSON/Markdown reports with non-zero exit on cross-slice contract failures.**

## What Happened

Implemented `src/scrape_planner/proof_m001.py` with explicit S03/S04/S05 check functions and a deterministic result model (`check_id`, `status`, `reason`, `details`, `timestamp`) plus overall verdict aggregation. Added CLI entrypoint `scripts/m001_proof.py` supporting `--config`, `--run-root`, and `--output-dir`, writing `proof_result.json` and `proof_report.md`, and returning exit code 1 on any failing check. Added integration-style command tests in `tests/test_m001_proof_command.py` covering: passing fixture success with both outputs, missing maintenance artifact failure, and malformed PDF chunk failure (`missing_page_number`). Created git-tracked fixtures under `tests/fixtures/m001_proof/` for pass and negative scenarios outside `.gsd/`. Fixed CLI import-path behavior by prepending `src/` so direct script execution works in tests and local runs.

## Verification

Ran `python3 -m unittest tests.test_m001_proof_command -v`; all 3 tests passed, validating pass/fail behavior, targeted check IDs/reasons, report file generation, and non-zero exit on failures.

## Verification Evidence

| # | Command | Exit Code | Verdict | Duration |
|---|---------|-----------|---------|----------|
| 1 | `python3 -m unittest tests.test_m001_proof_command -v` | 0 | ✅ pass | 135ms |

## Deviations

None.

## Known Issues

None.

## Files Created/Modified

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
- `tests/fixtures/m001_proof/fail_malformed/run_root/s05/pdf_quarantine.jsonl`
