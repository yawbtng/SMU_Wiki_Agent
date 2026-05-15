# S05: Internal PDF ingestion and Zvec proof

**Goal:** Prove internal/operator PDF ingestion into Zvec with page-number-preserving chunks, citation-bearing query results, and explicit quarantine artifacts for unsupported PDFs.
**Demo:** A born-digital PDF is chunked with page numbers, indexed/queryable through Zvec, and scanned/encrypted/malformed/low-text PDFs are quarantined with reasons.

## Must-Haves

- Running the S05 proof command against fixtures writes `pdf_sources.jsonl`, `pdf_chunks.jsonl`, `pdf_quarantine.jsonl`, `pdf_zvec_manifest.json`, and `pdf_query_proof.json` under a deterministic run output directory.
- Born-digital fixture PDFs produce chunk rows with non-null `page_number` and deterministic `chunk_id` values that are inserted into a dedicated PDF Zvec collection.
- PDF proof query results include citation metadata (`page_number`, `pdf_source_id`, source path/url) directly in returned hits.
- Encrypted, malformed, too-large, and low-text/image-only fixture PDFs are quarantined with explicit reason codes and details (`encrypted`, `malformed`, `too_large`, `ocr_required`/`low_text`).
- Automated tests cover happy path and quarantine paths without reading `.gsd/`, `.planning/`, or `.audits/` directories.

## Proof Level

- This slice proves: integration

## Integration Closure

Consumes S01 run-log contract style and produces S05 PDF artifacts/query contract needed by S06 proof command wiring; after this slice, S06 only needs config + orchestration integration, not new PDF semantics.

## Verification

- Adds durable JSONL/JSON proof artifacts for PDF intake status, chunk lineage, quarantine reasons, and query evidence so future agents can diagnose ingestion and retrieval failures without rerunning end-to-end manually.

## Tasks

- [ ] **T01: Implement PDF intake classifier and page-preserving chunk contracts** `est:1.5h`
  Why: Establish the core S05 contracts (R009/R010/R011) before vector integration by making PDF acceptance/quarantine deterministic and page-aware.
  - Files: `src/scrape_planner/pdf_ingest.py`, `src/scrape_planner/pdf_contracts.py`, `tests/test_pdf_ingest.py`
  - Verify: python3 -m pytest tests/test_pdf_ingest.py -q

- [ ] **T02: Wire PDF chunks into Zvec and produce citation-bearing query proof artifacts** `est:2h`
  Why: Complete the end-to-end S05 proof by indexing page-attributed PDF chunks into Zvec and verifying retrieval returns citation metadata directly.
  - Files: `scripts/zvec_pdf_proof.py`, `src/scrape_planner/pdf_zvec.py`, `mcp_servers/smu_zvec_mcp.py`, `tests/test_pdf_zvec_proof.py`
  - Verify: python3 -m pytest tests/test_pdf_zvec_proof.py -q

## Files Likely Touched

- src/scrape_planner/pdf_ingest.py
- src/scrape_planner/pdf_contracts.py
- tests/test_pdf_ingest.py
- scripts/zvec_pdf_proof.py
- src/scrape_planner/pdf_zvec.py
- mcp_servers/smu_zvec_mcp.py
- tests/test_pdf_zvec_proof.py
