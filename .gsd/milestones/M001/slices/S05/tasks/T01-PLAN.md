---
estimated_steps: 22
estimated_files: 3
skills_used: []
---

# T01: Implement PDF intake classifier and page-preserving chunk contracts

Why: Establish the core S05 contracts (R009/R010/R011) before vector integration by making PDF acceptance/quarantine deterministic and page-aware.

Files:
- `src/scrape_planner/pdf_ingest.py`
- `src/scrape_planner/pdf_contracts.py`
- `tests/test_pdf_ingest.py`

Do:
1. Add a PDF ingest module that accepts operator-provided PDF inputs and emits source records plus per-page extraction results using `pypdf`.
2. Implement deterministic quarantine classification with explicit precedence and reason taxonomy: `malformed`, `encrypted`, `too_large`, then text-density checks for `ocr_required`/`low_text`.
3. Define and use explicit artifact row contracts for `pdf_sources.jsonl`, `pdf_chunks.jsonl`, and `pdf_quarantine.jsonl`, including `pdf_source_id`, `page_number` (1-based), stable `chunk_id`, and diagnostic detail fields.
4. Implement page-preserving chunking that never drops page attribution; chunk IDs must be deterministic across runs for identical input.
5. Add focused unit tests covering born-digital happy path + quarantine classes (encrypted, malformed, oversized, low-text/image-like).

Must-haves:
- Chunk rows always carry `page_number` and `pdf_source_id`.
- Quarantine rows always carry `reason`, `detail`, and timestamp field.
- Tests use local fixtures and do not depend on `.gsd/` artifacts.

Failure Modes (Q5):
- Corrupt/unreadable bytes -> classified `malformed`, surfaced in quarantine artifact.
- Encrypted PDFs -> classified `encrypted` without partial processing.
- Extraction returns no meaningful text -> classified deterministically as `ocr_required` or `low_text`.

Negative Tests (Q7):
- Empty input list, nonexistent file paths, and mixed valid/invalid batches.
- Boundary thresholds around max-size and min-text limits.

## Inputs

- `requirements-pdf.txt`
- `.gsd/REQUIREMENTS.md`
- `src/scrape_planner`

## Expected Output

- `src/scrape_planner/pdf_ingest.py`
- `src/scrape_planner/pdf_contracts.py`
- `tests/test_pdf_ingest.py`

## Verification

python3 -m pytest tests/test_pdf_ingest.py -q

## Observability Impact

Introduces explicit quarantine and chunk lineage artifacts that expose ingestion failure cause and page-level provenance.
