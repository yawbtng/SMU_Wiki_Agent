## Why

The current workflow treats “Build Graph” as the next step after scraping, but the product direction has shifted toward a persistent LLM-maintained wiki built from all source material. We need a step-by-step pipeline that normalizes PDFs, Excel/CSV files, web pages, and scraped content into raw markdown sources, then runs a non-interactive agent skill to build a meaningful wiki, embed it, rerank evidence, and expose the result to Codex through MCP.

## What Changes

- Replace the current graph-first workflow concept with a visible stepper:
  `Workspace -> Sources -> Raw Data Sources -> LLM Wiki -> Embed + Rerank -> MCP Query`.
- Add a raw source database that stores immutable normalized markdown and metadata for every source type: web, PDF, Excel/CSV, and scraped pages.
- Add non-interactive Pi/agent skills for wiki building, linting, and indexing so long-running work can run in tmux without asking the user questions.
- Add an LLM Wiki layer that maintains generated markdown pages, `index.md`, `log.md`, source citations, review queues, and update reports.
- Add embedding indexes for raw sources and generated wiki pages.
- Add a reranker that chooses the best wiki/raw evidence per query instead of answering from raw vector top-k alone.
- Add a Codex-compatible MCP connector that queries local embeddings/reranker output with one-click MCP configuration.
- Make “uncertain” cases non-blocking: agent jobs must write review artifacts instead of waiting for interactive input.

## Capabilities

### New Capabilities

- `stepper-workflow`: Defines the user-visible workflow states and transitions from workspace creation through MCP query readiness.
- `raw-source-database`: Defines durable normalized markdown storage, source registry metadata, source checksums, source status, and incremental change detection.
- `llm-wiki-builder`: Defines the non-interactive agent/Pi skill that reads raw sources, builds and maintains the generated wiki, updates `index.md` and `log.md`, and emits review queues.
- `embedding-reranker-query`: Defines raw/wiki embedding indexes, candidate retrieval, reranking, source selection, and answer evidence packaging.
- `codex-mcp-connector`: Defines the local MCP server and Codex MCP configuration surface for querying the generated wiki and raw source indexes.

### Modified Capabilities

- None.

## Impact

- Affected UI: Streamlit workflow tabs/stepper, replacing “Build Graph” as the primary post-source workflow with “LLM Wiki” and index/query readiness states.
- Affected storage: `data/sites/<site_id>/raw_sources/`, `data/sites/<site_id>/wiki/`, `data/sites/<site_id>/indexes/`, and build reports/logs.
- Affected agent tooling: new `.pi/skills/` or equivalent local skill surfaces for source normalization, wiki building, wiki linting, and indexing.
- Affected retrieval: existing vector index behavior must support both raw source chunks and generated wiki pages, with reranking before final evidence selection.
- Affected integration: add an MCP server command/config that Codex can use to query the local site wiki/indexes.
