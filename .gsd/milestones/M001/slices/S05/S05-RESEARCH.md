# S05 Research — Internal PDF ingestion and Zvec proof

## Summary
- Existing Zvec path (`scripts/zvec_index_run.py`) is cleanup-manifest/wiki oriented and currently **cannot satisfy** S05 contracts (raw/internal PDF-first ingest, page-number citation, quarantine reasons).
- Existing MCP query server (`mcp_servers/smu_zvec_mcp.py`) returns `title/url/path/text/score` only, so S05 needs either schema extension (preferred) or side lookup to expose **page citations** in query output.
- `requirements-pdf.txt` currently points at MarkItDown but milestone context and local environment indicate `pypdf` is available and better aligned for page-preserving extraction proof.
- Highest-risk first proof: establish deterministic PDF intake classifier + page-preserving chunk contract before wiring Zvec indexing/query.

## Active requirements this slice owns/supports
From preloaded requirements/context, S05 is directly responsible for:
- **R009** internal/operator PDFs are first-class source inputs.
- **R010** PDF chunks preserve page-number citations.
- **R011** unsupported/bad PDFs are quarantined visibly with explicit reasons.
And supports:
- **R001** raw-source truth (PDFs as source truth, not cleanup derivative).
- **R004** durable run logs.
- **R012/R015** simple configurable limits/options.

Constraint implications:
- Page metadata must be stored in the chunk record itself (not inferred post hoc from whole-document conversion).
- Quarantine must be an explicit artifact contract (JSON/JSONL rows with reason codes), not just stderr/log text.

## Implementation landscape (current code)

### 1) `scripts/zvec_index_run.py` (existing)
Purpose today:
- Loads docs from `cleanup_manifest.json` + `wiki/*.md`.
- Splits by character windows, embeds via Ollama, writes Zvec docs with fields: `text,title,url,path`.

Gaps for S05:
- No PDF intake.
- No page-number fields.
- No quarantine pipeline.
- Hardcoded collection name/schema for SMU wiki text flow.

Useful reusable pieces:
- Ollama embedding compatibility (`/api/embeddings` then `/api/embed` fallback).
- Batch upsert pattern and simple index manifest write.

### 2) `mcp_servers/smu_zvec_mcp.py` (existing)
Purpose today:
- Opens local Zvec collection, embeds query, returns semantic hits.

Gaps for S05:
- Tool returns no page numbers/citation metadata.
- SMU naming/path defaults imply scope narrowing; S05 needs neutral PDF proof contract.

Reusable:
- Query execution pattern and compatibility open fallback (`open` vs `create_and_open`).

### 3) `requirements-pdf.txt`
- Suggests MarkItDown dependency; milestone context says MarkItDown does not guarantee page-level provenance contract needed for S05.
- `pypdf` path is more deterministic for `page_number` retention and quarantine heuristics (encrypted/malformed/low-text).

## Recommended design for S05

### A. Separate PDF proof pipeline from cleanup/wiki pipeline
Create a dedicated PDF ingestion/index proof module/script rather than mutating cleanup-centric behavior in place.

Suggested artifact contracts (under run/slice output):
- `pdf_sources.jsonl` — one row per submitted PDF source (id, path/url, status).
- `pdf_chunks.jsonl` — one row per chunk with:
  - `pdf_source_id`
  - `page_number` (1-based)
  - `chunk_id`
  - `text`
  - optional offsets (`char_start`,`char_end`) and checksum.
- `pdf_quarantine.jsonl` — one row per quarantined PDF with:
  - `pdf_source_id`, `reason`, `detail`, `observed_at`.
- `pdf_zvec_manifest.json` — db path, embedding model, inserted docs/chunks, timestamp.
- `pdf_query_proof.json` — query input and hits including `page_number`.

### B. Quarantine reason taxonomy (align to milestone acceptance)
Implement explicit reasons:
- `ocr_required` (scanned/image-only or no extractable text above threshold)
- `encrypted`
- `malformed`
- `too_large`
- `low_text`

Recommended precedence to keep deterministic outcomes:
1. file existence/readability/malformed
2. encrypted
3. size cap (`too_large`)
4. extract text + density checks (`ocr_required` vs `low_text`)

### C. Zvec schema extension for PDF citation
For PDF collection, include fields beyond current text/title/url/path:
- `page_number` (int)
- `pdf_source_id` (string)
- `source_path` or `source_url`
- `chunk_index` (int)

This allows direct citation in query hits without secondary joins.

### D. Keep Ollama embedding fallback behavior
Reuse existing dual endpoint strategy for broader local compatibility.

## Natural seams for planner task decomposition
1. **PDF intake + quarantine classifier**
   - Parse PDF metadata/pages with `pypdf`.
   - Emit source + quarantine artifacts.
2. **Page-preserving chunker contract**
   - Chunk per page while retaining page number and stable chunk IDs.
3. **Zvec PDF indexer**
   - Create/open dedicated PDF collection schema; upsert chunk docs.
4. **PDF semantic query proof + citation output**
   - Query path returns page-numbered results and proof artifact.
5. **Tests + fixtures**
   - Born-digital happy path + each quarantine class.
6. **Config plumbing**
   - PDF size/text thresholds, chunking params, embedding model/db path.

These units are mostly independent after shared contract constants are defined.

## First proof (highest-risk / biggest unblocker)
Build a single deterministic fixture test that ingests one born-digital PDF and asserts:
- At least one chunk row exists with `page_number`.
- Zvec query returns a hit containing the expected `page_number` and source path/id.

Why first:
- Proves core R009/R010 integration quickly.
- De-risks whether current local zvec+ollama+pypdf toolchain can produce citation-bearing hits.

## Verification strategy

### Unit-level
- Quarantine classifier cases:
  - encrypted fixture => `encrypted`
  - malformed bytes => `malformed`
  - oversize fixture => `too_large`
  - no text pages => `ocr_required` or `low_text` per defined thresholds
- Chunker:
  - preserves page_number and stable deterministic IDs.

### Integration-level
- Run PDF proof command on fixtures; assert existence/parse of:
  - `pdf_sources.jsonl`
  - `pdf_chunks.jsonl`
  - `pdf_quarantine.jsonl`
  - `pdf_zvec_manifest.json`
  - `pdf_query_proof.json`
- Assert query proof rows include `page_number` in each hit.

### Commands (planner/executor-ready)
- `python3 -m pytest tests -k "pdf or zvec" -q`
- If a dedicated proof CLI is added: `python3 <proof_command>.py --fixture <...>`

## Files likely to change
- `scripts/zvec_index_run.py` (either refactor/reuse helpers or keep legacy and add new script)
- `mcp_servers/smu_zvec_mcp.py` (if reused for proof output shape; may need page fields)
- `requirements-pdf.txt` (dependency stance clarification)
- New module(s) under `src/scrape_planner/` for:
  - PDF intake/quarantine
  - Page chunking
  - PDF Zvec indexing/query proof
- New tests in `tests/` for PDF/Zvec proof path.

## Risks / watch-outs for planner
- Existing S01 summary is a blocker placeholder; avoid assuming prior slice artifacts are reliable without re-verification.
- Zvec may be unavailable in some dev envs; tests should isolate optional dependency behavior clearly (skip/fail-fast with explicit message).
- MarkItDown whole-doc conversion can lose strict page provenance; avoid making it core for S05 acceptance.
- Keep SMU-specific naming out of core contracts (R013 alignment), even if legacy files retain old names.

## Skill discovery notes
Installed relevant skills already available:
- `observability` (recommended): use for durable failure-state and artifact visibility in ingestion failures.
- `write-docs` (recommended): useful for crisply documenting JSON/JSONL contracts for cross-agent use.
- `decompose-into-slices` (optional): if S05 task granularity needs further thinning.

No additional external skill search was necessary because core stack is Python + existing local Zvec/Ollama integration and relevant local skills already exist.

## Recommendation
Implement S05 as a **new, PDF-specific proof pipeline** with explicit artifacts and page-aware schema, reusing only embedding/query primitives from existing Zvec scripts. This minimizes coupling to cleanup/wiki legacy flow, satisfies citation/quarantine acceptance directly, and keeps S06 integration simple.
