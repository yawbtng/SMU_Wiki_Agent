## Context

The current app already has workspace creation, discovery/feed URLs, scraping, PDF upload/extraction, and an embedding-oriented path. The product direction is changing from graph-first output toward a persistent LLM Wiki: immutable raw sources are normalized to markdown, an agent builds and maintains a generated wiki, and embeddings/reranking answer user questions from both generated wiki pages and raw evidence.

The user wants this exposed as a stepper, not a loose collection of tabs. Long-running LLM wiki work must run in tmux through Pi/agent skills without interactive prompts. Codex should be able to query the completed local index through a one-click MCP connector.

## Goals / Non-Goals

**Goals:**

- Make the workflow explicit: workspace, sources, raw data, LLM wiki, embedding/reranker, MCP query.
- Preserve every source as immutable normalized markdown plus metadata before LLM synthesis.
- Support multiple source types: web pages, scraped markdown, PDFs, Excel/CSV, and future document formats.
- Generate a persistent wiki with `index.md`, `log.md`, interlinked markdown pages, source citations, and review queues.
- Run the wiki builder as a non-interactive Pi/agent skill in tmux.
- Build embeddings over both raw sources and wiki pages.
- Rerank candidate evidence before answering so the best data source is chosen per query.
- Expose a Codex-compatible MCP server that queries the local indexes and returns ranked evidence.

**Non-Goals:**

- Do not make perfect per-page PDF parser routing the primary product objective.
- Do not require the MCP server to build or mutate indexes.
- Do not allow agent/wiki builder jobs to block on user input.
- Do not delete or rewrite raw sources when regenerating the wiki.
- Do not replace all existing scraping code in this change; adapt current artifacts into the new source database.

## Decisions

### Decision 1: Raw Sources Are The Source Of Truth

All crawled pages, uploaded PDFs, Excel/CSV files, and scraped markdown SHALL be normalized into `raw_sources/` before wiki generation. The generated wiki is derived and can be rebuilt.

Alternatives considered:

- Build wiki directly from crawler/PDF outputs. Rejected because each source type would require special handling in the wiki builder.
- Store only embeddings. Rejected because the user needs inspectable markdown, reproducibility, and citation provenance.

### Decision 2: Use A Registry As The Source Database

Each normalized source SHALL have a row in `raw_sources/registry.jsonl` with stable `source_id`, kind, title, original path/URL, markdown path, checksum, parser, status, and integration state.

The registry enables incremental rebuilds: changed or newly added sources can be detected without rebuilding everything.

### Decision 3: Agent Skills Own Wiki Generation

The LLM Wiki builder SHALL be implemented as a local Pi/agent skill that consumes `raw_sources/registry.jsonl`, writes wiki files, updates `index.md` and `log.md`, and emits reports. It SHALL run non-interactively in tmux.

Alternatives considered:

- Embed wiki generation directly in Streamlit. Rejected because long-running agent work should be observable and recoverable outside the web process.
- Use interactive chat workflow. Rejected because the UI stepper must run unattended.

### Decision 4: Wiki And Raw Indexes Are Separate

The system SHALL build at least two queryable corpora: generated wiki pages and raw source chunks. Querying should prefer the wiki for synthesized answers and raw sources for evidence/citations.

This avoids forcing every answer to rediscover synthesis from raw chunks while still preserving source-grounded evidence.

### Decision 5: Retrieval Must Rerank

Embedding top-k alone is not enough. The retrieval path SHALL collect candidates from wiki and raw indexes, rerank them, and return the selected evidence set with source metadata.

The initial reranker can be hybrid score-based, but the interface must allow future local cross-encoder or LLM rerankers.

### Decision 6: MCP Is Query-Only

The MCP connector SHALL read existing indexes and source/wiki files. It SHALL NOT normalize sources, build the wiki, or mutate index state.

This keeps MCP fast, predictable, and safe for Codex to use during answers.

## Risks / Trade-offs

- Agent wiki generation may produce unsupported claims -> Require source citations per generated page and maintain review queues for uncertain updates.
- Wiki drift from raw sources -> Track source checksums, source IDs, and page evidence references; rerun affected pages incrementally.
- Long-running jobs may fail mid-run -> Run in tmux, write progress logs, and make jobs resumable by registry status.
- Reranking may add latency -> Start with fast hybrid reranking and allow more expensive rerankers only when configured.
- Raw source markdown quality may vary -> Preserve parser metadata and allow re-normalization of failed/low-quality sources without changing source identity.
- MCP config can be brittle across machines -> Generate absolute-path config snippets and expose index health through an `index_info` tool.

## Migration Plan

1. Add the new stepper states without removing existing workspace/discovery/source inputs.
2. Create the raw source database layout and adapters from current scraped markdown, PDF ingest outputs, and uploaded file paths.
3. Add the non-interactive LLM Wiki skill and tmux launcher.
4. Generate wiki output into `data/sites/<site_id>/wiki/`.
5. Build raw and wiki indexes into `data/sites/<site_id>/indexes/`.
6. Add reranked query path and MCP server.
7. Move the UI primary action from “Build Graph” to “Build LLM Wiki” once the new path is runnable.

Rollback is straightforward because raw sources and wiki outputs live in new directories. Existing scrape outputs remain intact.
