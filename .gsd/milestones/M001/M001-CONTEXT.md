# M001: Raw Source Monitor, Run Logs, Retrieval, Tracer Maintenance Job, and PDF/Zvec Proof

**Gathered:** 2026-05-15
**Status:** Ready for planning

## Project Description

Build the first useful proof of a raw-first, pi-agent-maintained university wiki system. The system treats raw scraped sources and internal/operator-provided PDFs as truth, tracks changes over time, retrieves bounded evidence, and creates one cited tracer wiki update through an agent/skill-compatible maintenance job.

M001 is intentionally simple: it proves the substrate and one tracer loop without building the full wiki generator, full scheduler daemon, full GSD extension, OCR, or full 25k-page benchmark.

## Why This Milestone

The current codebase already contains scraping, URL scoring, cleanup, graph, run persistence, PDF intake, and Zvec-related pieces, but they are not yet organized around the desired raw-first maintenance architecture. Existing graph code includes hardcoded SMU-specific taxonomy assumptions, and existing Zvec indexing is cleanup-manifest-oriented.

This milestone proves the hard parts that must be true before later LLM classification, topic clustering, full wiki generation, extension commands, and scheduler operations are worth building.

## User-Visible Outcome

### When this milestone is complete, the user can:

- Run a proof workflow against fixture/existing artifacts and see a durable run directory explaining source changes, failures, stale wiki outputs, and generated reports.
- Search raw markdown evidence through an index-first bounded retrieval path.
- Ingest an internal/operator-provided born-digital PDF, chunk it with page numbers, index/query it through Zvec, and see PDF page-number citations in query results.
- See unsupported PDFs quarantined with explicit reasons such as `ocr_required`, encrypted, malformed, too large, or low text.
- Inspect one tracer wiki page maintained through a pi-agent/skill-compatible job packet with manifest, source map, source usage, events, result, and handoff artifacts.

### Entry point / environment

- Entry point: Python proof command/script and fixture tests; later extension commands are deferred.
- Environment: local development environment.
- Live dependencies involved: local filesystem, existing scraped artifacts, internal PDFs, optional mocked/limited HTTP checks, Zvec, embedding provider such as Ollama for PDF proof.

## Completion Class

- Contract complete means: source ledger, run logs, retrieval outputs, manifests, source maps, job packets, and PDF chunk records match documented JSON/JSONL contracts and tests parse them.
- Integration complete means: the proof command or equivalent workflow connects source diffing, run logging, index-first retrieval, stale-page tracking, tracer wiki maintenance artifacts, and PDF/Zvec query proof.
- Operational complete means: failed runs and quarantined PDFs leave durable logs and do not erase prior state; simple configuration controls V1 maintenance/retrieval/PDF limits.

## Final Integrated Acceptance

To call this milestone complete, we must prove:

- A changed source hash in fixture/existing artifacts marks the dependent tracer wiki page stale and produces an inspectable run log.
- A bounded retrieval path returns evidence without scanning every raw markdown file for each query.
- An internal born-digital PDF can be chunked with page numbers, indexed/queryable through Zvec, and returned with source URL/path plus page-number citation.
- Unsupported PDF cases are quarantined visibly and the run continues where appropriate.
- A pi-agent/skill-compatible job packet can produce or update one tracer wiki page and write manifest, source map, events, source usage, result, and handoff artifacts.

## Architectural Decisions

### Raw source truth over cleanup-first architecture

**Decision:** M001 treats raw sources and internal PDFs as source truth. It must not depend on `cleanup_manifest.json` as the controlling source of truth.

**Rationale:** The user wants a raw-first wiki system. Existing cleanup paths can remain optional, but cleanup-first architecture would make future maintenance brittle and obscure source provenance.

**Alternatives Considered:**
- Cleanup-manifest-first flow — rejected because it keeps the old pipeline in control and does not match the raw-first requirement.

### JSON/JSONL file artifacts for M001

**Decision:** M001 uses JSON and JSONL file artifacts for source ledger, source diffs, events, manifests, run reports, stale records, and job packets.

**Rationale:** File artifacts are inspectable, Git-friendly, easy for agents to read, and close to existing `run_persistence` patterns. They are enough for V1 proof.

**Alternatives Considered:**
- SQLite now — deferred because it adds schema/migration complexity before the first useful proof. Revisit if JSONL becomes a scale bottleneck.

### LLM work through agent/skill-compatible job packets

**Decision:** M001 should define the job packet contract for pi-agent/skill maintenance and use it for the tracer wiki page. It should not hide LLM work inside a monolithic backend call.

**Rationale:** The user wants pi agents/skills to keep cleaning, maintaining, ingesting, and updating the wiki over time so data stays relevant. Durable job packets make handoff/resume/debugging possible.

**Alternatives Considered:**
- Direct internal `call_llm()` style backend — rejected because it hides reasoning and weakens maintenance handoff.

### Zvec is PDF proof only in M001

**Decision:** M001 uses Zvec to prove internal PDF ingestion/query/citation behavior, not as the primary retrieval system for all markdown/HTML.

**Rationale:** Current Zvec indexing is cleanup-manifest-oriented and Zvec is not installed locally. M001 should prove PDF-specific behavior before making it central.

**Alternatives Considered:**
- Zvec for all retrieval — deferred because it increases dependency risk and is not needed to prove raw markdown retrieval.

### No hardcoded university taxonomy as core architecture

**Decision:** Existing `UNIT_RULES`-style hardcoded university taxonomy must not be required for the M001 path.

**Rationale:** The user explicitly wants no hardcoded university structure. Later milestones should infer university structure with LLM reasoning over bounded evidence.

**Alternatives Considered:**
- Preserve hardcoded SMU unit rules — rejected for cross-university scalability.

### Simple V1 configuration first

**Decision:** M001 uses a simple configuration file for maintenance, retrieval, PDF, and Zvec options. Full Settings UI is deferred.

**Rationale:** The user wants options and future settings controls, but also wants V1 to be simple and get the most useful work done.

**Alternatives Considered:**
- Build full settings UI now — deferred as nonessential V1 scope.

## Error Handling Strategy

- A single source check/fetch failure is logged as failed and does not delete prior state.
- Repeated missing/404 behavior becomes deleted candidate, not immediate deletion.
- Redirects are recorded in source diffs.
- Changed content hashes mark sources changed and can mark dependent wiki pages stale.
- Scanned/image-only PDFs are quarantined as `ocr_required`; OCR is deferred.
- Encrypted, malformed, too-large, or low-text PDFs are quarantined with explicit reasons.
- Zvec missing/unavailable/embedding failures fail the PDF proof step clearly and write run log details.
- Every run writes `run.json`; phase transitions and failures go to `events.jsonl`.
- Unsupported tracer-page claims fail validation or are omitted/quarantined.
- Failed runs leave enough state for a future agent to debug or resume.

## Risks and Unknowns

- Existing graph code contains useful deterministic graph artifacts but also hardcoded SMU taxonomy assumptions.
- Current Zvec script depends on cleaned markdown via `cleanup_manifest.json`, while M001 needs raw/internal-PDF-oriented behavior.
- `zvec` and `markitdown` are not installed in the current local environment; `pypdf` is installed.
- MarkItDown docs show whole-document conversion but do not prove page-number citation behavior, so PDF proof should preserve page metadata directly.
- Large PDF ingestion behavior is unproven.
- Search must avoid full-corpus scans before scale work begins.
- Exact pi skill execution mechanics are deferred, but M001 must produce compatible job packet artifacts.

## Existing Codebase / Prior Art

- `src/scrape_planner/run_persistence.py` — Existing JSONL event/page persistence patterns that can be reused.
- `src/scrape_planner/markdown_graph.py` — Existing deterministic graph/index work and `knowledge_graph/*` artifacts, but also hardcoded SMU-specific `UNIT_RULES` that should not control the new path.
- `scripts/zvec_index_run.py` — Existing Zvec indexing script, currently cleanup-manifest-oriented and whole-document/chunk loading oriented.
- `mcp_servers/smu_zvec_mcp.py` — Existing Zvec MCP query proof, SMU-specific naming and no PDF page-number-specific contract.
- `requirements-pdf.txt` — Optional PDF dependency file currently listing MarkItDown; current environment has `pypdf` installed and `markitdown` missing.
- `app.py` — Current Streamlit app includes PDF intake/source selection and graph controls, but M001 should not depend on UI redesign.

## Relevant Requirements

- R001 — Raw sources are source truth.
- R002 — V1 stays simple while proving the useful maintenance loop.
- R003 — Source ledger detects lifecycle changes.
- R004 — Every run writes durable logs.
- R005 — Retrieval is index-first and bounded.
- R006 — Wiki pages track source dependencies and staleness.
- R007 — One tracer wiki page proves agent-maintained update flow.
- R008 — LLM maintenance work runs through pi-agent/skill-compatible jobs.
- R009 — Internal/operator PDFs are first-class source inputs.
- R010 — PDF chunks preserve page-number citations.
- R011 — Bad or unsupported PDFs are quarantined visibly.
- R012 — Maintenance behavior has simple configurable options.
- R013 — Architecture avoids hardcoded university taxonomy.
- R014 — System scales toward 25k-page corpora.
- R015 — Material maintenance/configuration choices expose options.

## Scope

### In Scope

- Source ledger and source diff artifacts.
- Durable run logs and human-readable build report.
- Index-first raw markdown retrieval proof.
- Stale dependency tracking for one tracer page.
- Agent/skill-compatible maintenance job packet contract.
- One cited tracer wiki page update/create proof.
- Internal/operator PDF ingestion proof with page-number chunks.
- Zvec PDF query proof.
- PDF quarantine behavior for scanned/encrypted/malformed/too-large/low-text cases.
- Simple V1 config file for maintenance/retrieval/PDF/Zvec limits and options.

### Out of Scope / Non-Goals

- Full multi-page wiki generation.
- Full LLM page classification and topic clustering.
- Full GSD extension commands/hooks.
- Autonomous scheduler daemon.
- OCR implementation.
- Full Settings UI.
- Full 25k-page benchmark.
- Customer/public PDF upload handling.
- Silent destructive wiki deletes or merges.
- Cleanup-manifest-first architecture.
- Complex V1 orchestration framework.

## Technical Constraints

- Use `python3` in commands; no `python` shim is available in the current shell.
- Zvec docs indicate Python 3.10+ requirement; current optional PDF dependency note also mentions Python 3.10+ for MarkItDown.
- Keep outputs bounded for agent context safety.
- Keep file artifacts human-inspectable and machine-parseable.
- No hardcoded university taxonomy required by the M001 proof path.

## Integration Points

- Local filesystem — stores source ledger, run logs, query index, job packets, wiki artifacts, manifests, source maps, and reports.
- Existing scraped artifacts — primary proof input for raw markdown/source records.
- Internal PDFs — operator-provided PDF source inputs.
- Zvec — PDF proof vector index and query.
- Embedding provider such as Ollama — vector embeddings for Zvec PDF proof.
- Pi agents/skills — intended executor for future maintenance jobs; M001 creates compatible job packets.
- Optional mocked/limited HTTP checks — freshness behavior proof without full live scheduler.

## Testing Requirements

Tests should be proof-focused rather than a full 25k benchmark.

Required test classes:

- Unit tests for source ledger diffing, source statuses, stale page detection, manifest/source-map logic, and quarantine reason handling.
- Fixture integration tests for run log creation, failed run persistence, index-first retrieval, source hash change flow, and tracer job artifacts.
- PDF/Zvec proof tests for born-digital PDF extraction/chunking with page numbers, Zvec index/query results, and quarantine of scanned/encrypted/malformed/low-text PDFs.
- Artifact checks that expected JSON/JSONL files parse and outputs remain bounded.
- Proof command verification that runs the M001 fixture workflow end to end.

## Acceptance Criteria

- Source ledger classifies fixture sources as new, unchanged, changed, redirected, failed, and deleted candidate.
- Run directory contains `run.json`, `events.jsonl`, `source_diff.jsonl`, stale/affected records, and `build_report.md`.
- Retrieval uses an index-first path and fixture tests prove it does not read every raw file per query.
- One tracer wiki page exists or is updated from bounded evidence.
- The tracer page has manifest, source hashes, source map entries, and cited claims.
- A changed source hash marks the dependent tracer page stale.
- A maintenance job packet exists with job config, bounded evidence, instructions, output contract, events, source usage, result, and handoff/resume notes.
- Internal/operator PDF ingestion extracts born-digital PDF text, chunks by page, indexes/query through Zvec, and returns page-number citations.
- Scanned/image-only PDFs are quarantined as `ocr_required`.
- Encrypted, malformed, too-large, or low-text PDFs are quarantined with explicit reasons.
- Failed runs leave useful logs and do not erase prior state.
- Simple config exposes maintenance/retrieval/PDF/Zvec options.

## Open Questions

- Which embedding model should be default for PDF/Zvec proof if Ollama is available?
- Should M001 install/use MarkItDown, or rely on `pypdf` for page-preserving PDF proof and defer MarkItDown integration?
- What fixture PDF size is sufficient for “large PDF” proof in local tests without making the repo heavy?
- What exact directory should hold raw-wiki artifacts inside existing run roots versus generated `wiki/` output?
