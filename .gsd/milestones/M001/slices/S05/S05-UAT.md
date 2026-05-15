# S05: Internal PDF ingestion and Zvec proof — UAT

**Milestone:** M001
**Written:** 2026-05-15T19:03:58.599Z

# UAT — S05 Internal PDF ingestion and Zvec proof

## UAT Type
Integration / contract verification (PDF intake + Zvec retrieval proof)

## Preconditions
1. Project checkout is at Milestone M001 state with S05 implementation present.
2. Fixture PDFs include:
   - born-digital (expected ingest)
   - encrypted
   - malformed/corrupt
   - oversized (beyond configured limit)
   - low-text or image-only sample
3. Zvec backend/adapter used by `scripts/zvec_pdf_proof.py` is reachable in local test mode.
4. Deterministic run output directory is writable.

## Steps
1. Run the S05 proof command against fixtures.
2. Inspect output directory for required artifacts:
   - `pdf_sources.jsonl`
   - `pdf_chunks.jsonl`
   - `pdf_quarantine.jsonl`
   - `pdf_zvec_manifest.json`
   - `pdf_query_proof.json`
3. Verify born-digital source rows are present in `pdf_sources.jsonl` with accepted/ingested status.
4. Verify `pdf_chunks.jsonl` rows contain:
   - non-null `page_number`
   - deterministic `chunk_id`
   - `pdf_source_id` linkage back to source rows.
5. Verify quarantine rows contain expected reason codes and details for unsupported fixtures:
   - `encrypted`
   - `malformed`
   - `too_large`
   - `ocr_required` and/or `low_text`
6. Verify `pdf_zvec_manifest.json` references dedicated PDF collection and chunk insertion counts.
7. Verify `pdf_query_proof.json` query hits include citation metadata:
   - `page_number`
   - `pdf_source_id`
   - source path/url metadata.

## Expected Outcomes
1. All five proof artifacts exist under deterministic run path.
2. Born-digital fixture is chunked/indexed successfully with page-preserving lineage.
3. Unsupported PDFs are not silently dropped; each appears in quarantine with explicit reason.
4. Query proof returns citation-ready results directly from retrieval output.

## Edge Cases
1. Mixed fixture batch (one valid + many invalid) still yields successful run and complete quarantine accounting.
2. Empty/near-empty text PDFs are quarantined as low-text/ocr-required, not ingested.
3. Deterministic chunk IDs remain stable across repeated runs with identical input.

## Not Proven By This UAT
1. OCR extraction quality for scanned PDFs (explicitly deferred in requirements).
2. Production-scale throughput/latency behavior under large corpora.
3. Full M006+ orchestration/UI exposure; this UAT only proves S05 contracts for downstream S06 integration.
