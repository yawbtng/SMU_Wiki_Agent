---
id: T01
parent: S05
milestone: M001
key_files:
  - src/scrape_planner/pdf_contracts.py
  - src/scrape_planner/pdf_ingest.py
  - tests/test_pdf_ingest.py
key_decisions:
  - (none)
duration: 
verification_result: mixed
completed_at: 2026-05-15T20:50:23.858Z
blocker_discovered: false
---

# T01: Implemented deterministic PDF intake classification plus page-preserving chunk contracts with stable chunk IDs and quarantine/source row schemas.

**Implemented deterministic PDF intake classification plus page-preserving chunk contracts with stable chunk IDs and quarantine/source row schemas.**

## What Happened

Added new `src/scrape_planner/pdf_contracts.py` dataclasses for `PdfSourceRow`, `PdfChunkRow`, and `PdfQuarantineRow` so artifact rows always carry required lineage and diagnostics fields (including `pdf_source_id`, `page_number`, `reason`, `detail`, and timestamp fields). Implemented `src/scrape_planner/pdf_ingest.py` with `ingest_pdfs()` and `PdfIngestConfig` to classify PDFs in deterministic precedence order (`malformed` -> `encrypted` -> `too_large` -> text-density checks), preserve page attribution during chunking, and generate deterministic chunk IDs for identical input. Added `tests/test_pdf_ingest.py` covering empty input, nonexistent paths, oversized boundary behavior, malformed bytes, encrypted PDFs, deterministic low-text/ocr-required classification, mixed valid/invalid batches, and happy-path lineage/determinism checks.

## Verification

Ran the required task verification command, but verification could not execute because `pytest` is not installed in the current interpreter (`python3 -m pytest ...` failed with `No module named pytest`).

## Verification Evidence

| # | Command | Exit Code | Verdict | Duration |
|---|---------|-----------|---------|----------|
| 1 | `python3 -m pytest tests/test_pdf_ingest.py -q` | 1 | ❌ fail (pytest missing in environment) | 37ms |

## Deviations

None.

## Known Issues

Environment is missing pytest for python3, so automated test execution is currently blocked until dependency installation.

## Files Created/Modified

- `src/scrape_planner/pdf_contracts.py`
- `src/scrape_planner/pdf_ingest.py`
- `tests/test_pdf_ingest.py`
