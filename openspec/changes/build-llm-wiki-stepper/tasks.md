## 1. Workflow And Storage Foundation

- [x] 1.1 Audit current workspace, discovery, PDF upload, scrape, graph, and Zvec index code paths and document the existing artifact inputs that can feed `raw_sources/`.
- [x] 1.2 Add the `raw_sources/`, `wiki/`, and `indexes/` directory conventions under `data/sites/<site_id>/`.
- [x] 1.3 Define source registry row helpers for stable `source_id`, source kind, title, original URL/path, markdown path, metadata path, checksum, parser, status, timestamps, and wiki integration state.
- [x] 1.4 Add read/write/merge helpers for `raw_sources/registry.jsonl` with deterministic updates and no duplicate source IDs.
- [x] 1.5 Add focused tests for registry insert, unchanged source detection, changed checksum detection, and failed source status.

## 2. Raw Source Normalization

- [x] 2.1 Implement web/scraped markdown adapter that registers existing crawl markdown as raw source records.
- [x] 2.2 Implement PDF normalization adapter that writes PDF markdown into `raw_sources/pdf/` and records parser/provenance metadata.
- [x] 2.3 Implement Excel/CSV normalization adapter that writes workbook/sheet/table markdown into `raw_sources/excel/`.
- [x] 2.4 Add normalization reports that summarize ready, unchanged, changed, failed, and needs-review sources.
- [x] 2.5 Add tests for web, PDF, Excel/CSV, failed normalization, and incremental rerun behavior.

## 3. Stepper UI

- [x] 3.1 Replace graph-first workflow language with the stepper states `Workspace`, `Sources`, `Raw Data Sources`, `LLM Wiki`, `Embed + Rerank`, and `MCP Query`.
- [x] 3.2 Add readiness checks that prevent downstream steps when prerequisites are missing.
- [x] 3.3 Add Raw Data Sources status UI with source counts by kind, ready/failed/changed status, registry path, and latest normalization report.
- [x] 3.4 Add LLM Wiki status UI with tmux session name, log path, pages created/updated, integrated sources, review queue count, and latest report.
- [x] 3.5 Add Embed + Rerank status UI with raw/wiki index counts, last build time, reranker readiness, and changed-document counts.
- [x] 3.6 Add MCP Query readiness UI with server command/config snippet and index health.
- [x] 3.7 Add UI tests that assert step order, primary `Build LLM Wiki` action, and prerequisite blocking behavior.

## 4. Non-Interactive Agent Skills

- [x] 4.1 Create a local source normalization skill or command wrapper that can run without prompts and produce registry/report artifacts.
- [x] 4.2 Create `.pi/skills/llm-wiki-builder/SKILL.md` or the repo-equivalent skill entrypoint with no-input operation rules.
- [x] 4.3 Implement the wiki builder launcher that starts a tmux session with site root, registry path, output paths, and no-input flags.
- [x] 4.4 Make the wiki builder read ready/unintegrated registry rows and write `wiki/index.md`, `wiki/log.md`, generated pages, source citations, and a build report.
- [x] 4.5 Make the wiki builder write uncertain or conflicting material to `wiki/review_queue.md` instead of prompting.
- [x] 4.6 Add resume/retry behavior so a failed wiki job can continue from registry/report state.
- [x] 4.7 Add tests or dry-run fixtures proving the skill command is non-interactive and writes expected wiki artifacts.

## 5. Wiki Output Quality

- [x] 5.1 Define wiki page frontmatter and citation conventions for source IDs, source paths, source counts, tags, and updated timestamps.
- [x] 5.2 Add generated wiki index maintenance that lists pages by category with one-line summaries and source counts.
- [x] 5.3 Add chronological wiki log entries for ingest, query-derived page creation, lint, and rebuild events.
- [x] 5.4 Add a wiki lint/report command that identifies orphan pages, missing citations, stale source checksums, contradictions/review items, and missing index entries.
- [x] 5.5 Add fixture-based tests for wiki page citation metadata, index updates, log appends, and review queue creation.

## 6. Embedding And Reranking

- [x] 6.1 Extend the indexing pipeline to ingest raw source chunks with source kind, source ID, path, checksum, and parser metadata.
- [x] 6.2 Extend the indexing pipeline to ingest generated wiki pages with page path, title, tags, source IDs, and checksum metadata.
- [x] 6.3 Add incremental embedding logic that re-embeds only changed raw sources or wiki pages when possible.
- [x] 6.4 Implement candidate retrieval from both wiki and raw source corpora.
- [x] 6.5 Implement a baseline reranker that combines vector score, keyword/BM25-style signals where available, source kind priority, freshness, and citation relationship.
- [x] 6.6 Define a stable reranked evidence schema with query, selected evidence, scores, source IDs, paths, source kind, and ranking reasons.
- [x] 6.7 Add tests for wiki-preferred retrieval, raw-source fallback, changed-document reindexing, and explainable reranker output.

## 7. Codex MCP Connector

- [x] 7.1 Add a query-only MCP server module for the LLM Wiki indexes.
- [x] 7.2 Implement MCP tools for `query_wiki`, `search_sources`, `get_wiki_page`, and `index_info`.
- [x] 7.3 Ensure MCP tools read existing indexes/files only and never normalize sources, build the wiki, or mutate indexes.
- [x] 7.4 Add path-safety checks so `get_wiki_page` and source reads cannot escape the configured site root.
- [x] 7.5 Generate a Codex-compatible MCP config snippet with absolute command and site-root paths.
- [x] 7.6 Add integration tests or command-line smoke tests for MCP startup, index info, query evidence, and missing-index errors.

## 8. End-To-End Validation

- [x] 8.1 Create a small fixture site with one web page, one PDF-derived markdown source, one CSV/Excel source, and expected wiki/index outputs.
- [x] 8.2 Run the full stepper path on the fixture: normalize raw sources, build wiki, embed/index, rerank query, and query via MCP.
- [x] 8.3 Run the full path on the current SMU workspace enough to prove real artifacts are produced without manual prompts.
- [x] 8.4 Document the operator runbook for adding new sources, rerunning incremental wiki builds, rebuilding indexes, and installing the Codex MCP connector.
- [x] 8.5 Update or remove obsolete graph-first copy once the LLM Wiki path is verified.
