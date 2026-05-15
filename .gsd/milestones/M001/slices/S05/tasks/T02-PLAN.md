---
estimated_steps: 24
estimated_files: 4
skills_used: []
---

# T02: Wire PDF chunks into Zvec and produce citation-bearing query proof artifacts

Why: Complete the end-to-end S05 proof by indexing page-attributed PDF chunks into Zvec and verifying retrieval returns citation metadata directly.

Files:
- `scripts/zvec_pdf_proof.py`
- `src/scrape_planner/pdf_zvec.py`
- `mcp_servers/smu_zvec_mcp.py`
- `tests/test_pdf_zvec_proof.py`

Do:
1. Add a dedicated PDF Zvec indexing path (separate from cleanup/wiki flow) that creates/opens a PDF collection schema including `text`, `page_number`, `pdf_source_id`, source path/url, and chunk ordering metadata.
2. Reuse existing Ollama embedding fallback behavior (`/api/embeddings` then `/api/embed`) for compatibility.
3. Build a proof command/script that runs ingest + chunk + index + query flow and writes `pdf_zvec_manifest.json` plus `pdf_query_proof.json` (query input, hit list, citation fields).
4. Extend query output shape (proof path and/or MCP server path) so hits include page citation fields directly; avoid post-hoc side joins.
5. Add integration tests that assert proof artifacts exist and include citation metadata, with graceful skip/fail-fast messaging when optional runtime deps (zvec/ollama) are unavailable.

Must-haves:
- Query hit contract includes `page_number`, `pdf_source_id`, and source path/url.
- Proof artifacts are deterministic and machine-parseable JSON/JSONL.
- Legacy cleanup/wiki indexing path remains unaffected.

Threat Surface (Q3):
- Untrusted PDF metadata/text must be treated as data-only and never executed.
- Paths used for local PDFs must stay constrained to configured source roots.

Load Profile (Q6):
- 10x pages increases embedding calls and upsert volume; batch sizing and chunk limits must bound runtime/memory.

Negative Tests (Q7):
- Query on empty/fully quarantined ingest set returns explicit no-hit proof shape.
- Malformed chunk metadata rejected before upsert.

## Inputs

- `src/scrape_planner/pdf_ingest.py`
- `src/scrape_planner/pdf_contracts.py`
- `scripts/zvec_index_run.py`
- `mcp_servers/smu_zvec_mcp.py`
- `tests/fixtures`

## Expected Output

- `scripts/zvec_pdf_proof.py`
- `src/scrape_planner/pdf_zvec.py`
- `mcp_servers/smu_zvec_mcp.py`
- `tests/test_pdf_zvec_proof.py`

## Verification

python3 -m pytest tests/test_pdf_zvec_proof.py -q

## Observability Impact

Adds query/manifests that make indexing coverage and citation-bearing retrieval auditable for future maintenance and S06 proof orchestration.
