## Why

The current LLM Wiki path proves that source ingestion, wiki generation, indexing, and query can run end to end, but the output is not yet useful enough for a real student-facing institutional assistant.

Recent audit findings show the core problem is not simply missing data. The corpus contains valuable institutional facts, including admissions, tuition, financial aid, programs, faculty, leadership, scholarships, and catalog material. However, those facts are buried inside noisy scraped pages, repeated navigation/footer chrome, redirect stubs, binary/PDF contamination, and broad generated wiki buckets such as `programs.md`.

The wiki builder must move from a source-dump model to a generic routed Markdown knowledge-base model. It should work for any school or university by inferring the institution structure from sources, applying quality gates, normalizing documents, and building profile-aware routing pages before indexing.

## What Changes

- Add source quality gates before wiki generation:
  - quarantine binary/PDF-in-markdown, NUL-byte files, redirect stubs, near-empty pages, and high-boilerplate pages;
  - strip repeated navigation/footer/search chrome from otherwise useful pages;
  - compute durable quality signals and make them visible in reports and the UI.
- Normalize PDFs/documents into the same `raw_sources` pipeline as web pages:
  - preserve page spans, section paths, tables, document metadata, and provenance;
  - do not rely on page-range wiki dumps as the canonical document path.
- Replace broad keyword buckets with a generic institution wiki contract:
  - infer audiences, intents, schools/colleges, departments, programs, offices, people, research, costs, policies, calendars, and source provenance;
  - create canonical Markdown pages where each important fact has one owner;
  - put raw excerpts/source notes outside the student-facing answer surface.
- Create profile-aware routing:
  - route by audience, education level, role, intent, and academic interest before searching;
  - avoid irrelevant academic/deep-program material for users whose profile does not need it.
- Improve query/index behavior:
  - prioritize curated routed wiki pages first;
  - use cited raw/document sources as supporting evidence;
  - fall back to raw sources only when the routed wiki lacks coverage.
- Update the operator UI:
  - show Markdown wiki files and routing pages in a readable UI;
  - show quality reports and quarantined-source reasons without exposing JSON as the primary interface.

## Non-Goals

- Do not hard-code SMU schools, departments, offices, programs, or example URLs into the generic wiki prompt or builder logic.
- Do not make the wiki depend on one institution-specific taxonomy.
- Do not answer directly from noisy raw chunks before routed wiki pages have been considered.
- Do not delete original raw sources; quarantine and report bad inputs while preserving provenance.
- Do not build another graph-first workflow. The primary surface remains Markdown wiki plus routed retrieval.

## Capabilities

### New Capabilities

- `source-quality-gating`: Scores, cleans, and quarantines fetched source documents before wiki generation and indexing.
- `document-source-normalization`: Converts PDFs and other documents into structured raw sources with page/section/table provenance.
- `routed-institution-wiki`: Builds a generic Markdown wiki for any educational institution by inferring institutional structure and student-relevant routes.
- `profile-aware-query-routing`: Routes queries through audience/intent/topic indexes before retrieval.

### Modified Capabilities

- `llm-wiki-builder`: Replace broad source-note buckets with canonical routed Markdown pages and separate source-note artifacts.
- `embedding-reranker-query`: Prefer curated wiki routes and cited sources before raw fallback.
- `stepper-workflow`: Make source quality, wiki routing, and generated Markdown inspection first-class operator surfaces.

## Impact

- Affected source pipeline: raw source registration, cleanup reports, PDF/document ingestion, source quality reports.
- Affected wiki output: `wiki/index.md`, routed Markdown pages, source-note pages, page metadata/frontmatter, build reports.
- Affected retrieval: candidate selection, reranking weights, profile-aware query routing, answer evidence contract.
- Affected UI: Wiki tab, source quality status, generated file browser/preview, query evidence display.
- Affected validation: fixture sites must include noisy HTML, binary/PDF contamination, document tables, student profiles, and answer probes.
