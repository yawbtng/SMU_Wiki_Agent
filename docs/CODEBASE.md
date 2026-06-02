# Scrape Planner Codebase Map

Product code lives under `src/scrape_planner/`. Subpackages group the Ultra Fast RAG pipeline by domain. Import from subpackage paths (e.g. `scrape_planner.wiki.llm_wiki_index`); root-level shims were removed.

## Package overview

| Subpackage | Purpose |
|------------|---------|
| `core` | Shared models, storage, data paths, site layout |
| `scrape` | Discovery, fetch, HTML extraction, scrape worker |
| `pdf` | PDF contracts and Docling ingest |
| `sources` | Raw source registry, normalization, quality |
| `wiki` | LLM wiki build, hybrid index, ingestion pipeline |
| `graph` | Markdown knowledge graph and URL-path profiling |
| `index` | Embedding / vector indexes |
| `tracer` | Stale-page evaluation and maintenance |
| `runtime` | Run queue, persistence, analytics, observability |
| `ui` | Streamlit view models and operator components |
| `app` | App context, repositories, artifact contracts |
| `infra` | tmux and other process runners |

## Subpackage modules

### `core`

Shared primitives used across the pipeline.

- `models.py` — domain dataclasses and typed payloads
- `storage.py` — JSON/JSONL read/write helpers
- `data_root.py` — repository and site data path resolution
- `site_layout.py` — per-site directory scaffolding
- `wiki_common.py` — shared wiki path and frontmatter helpers

### `scrape`

Web discovery through scraped markdown artifacts.

- `sitemap_discovery.py` — sitemap and seed URL discovery
- `scrape_worker.py` — fetch, render, and markdown extraction worker
- `content_extract.py` — HTML-to-markdown extraction utilities
- `manual_url_pipeline.py` — operator-supplied URL ingest
- `url_approval_review.py` — URL approval workflow helpers
- `failure_classifier.py` — scrape failure categorization
- `scrape_benchmark.py` — scrape throughput benchmarks

### `pdf`

PDF ingest and page-level normalization inputs.

- `pdf_ingest.py` — Docling-based PDF parsing and chunk emission

Root module: `pdf_contracts.py` (contracts only).

### `sources`

Raw source lifecycle before wiki synthesis.

- `source_registry.py` — registry rows, checksums, stable IDs
- `raw_source_normalizer.py` — web/PDF/tabular normalization CLI
- `source_quality.py` — quality gates, cleaning, quarantine rules

### `wiki`

Student wiki build, query index, and operator stepper.

- `llm_wiki_builder.py` — noninteractive wiki page synthesis
- `llm_wiki_index.py` — hybrid BM25/vector index and MCP query paths
- `wiki_ingestion_pipeline.py` — end-to-end wiki refresh orchestration
- `wiki_markdown_ui.py` — Streamlit wiki markdown rendering
- `stepper_status.py` — pipeline step readiness and status probes
- `wiki_graph_artifacts.py` — wiki-linked graph artifact writers
- `confidence.py`, `ingest_safety.py`, `index_lock.py`, `self_improving.py`, `web_search.py` — wiki quality, safety, and enrichment

### `index`

Dense retrieval indexes over registry and wiki corpora.

- `embedding_client.py` — Ollama/OpenRouter embedding clients
- `zvec_index.py` — vector index build and query

### `tracer`

Stale content evaluation (root-level until subpackage extraction).

- `tracer_dependencies.py` — dependency graph for stale transitions
- `tracer_maintenance.py` — maintenance jobs and refresh triggers

Public API re-exported from `scrape_planner.__init__`: `evaluate_stale_dependencies`.

### `runtime`

Run state, persistence, and operator observability.

- `state.py` — run queue and Redis-backed state store
- `run_persistence.py` — run artifact persistence
- `run_analytics.py` — run-level analytics aggregation
- `observability.py` — structured logging and metrics hooks
- `agent_run_metrics.py` — agent run timing and counters

### `webapp`

FastAPI operator API (`webapp/api.py` orchestrates payloads; `routes.py`, `jobs.py`, `approved_urls.py`, `embeddings.py`, `deps.py`, `schemas.py`).

### `app`

Application wiring, artifact contracts, Pi job launcher, navigation.

- `navigation.py` — `WORKFLOW_TABS` for React operator
- `repositories.py` — app state and site artifact repositories
- `artifact_contracts.py` — typed app-state defaults and contracts
- `job_launcher.py`, `operator_skills.py` — Pi skill registry and tmux launch

### `infra`

Long-running job process management.

- `tmux_runner.py` — tmux session launch and attach helpers
- `background_runner.py` — detached background process runner

## Related entrypoints

- `./start.sh` — React (5173) + FastAPI (8000) via tmux
- `mcp_servers/llm_wiki_mcp.py` — MCP server over the hybrid wiki index
- `.pi/skills/` — Pi operator skills (`site-discovery`, `site-url-curation`, `llm-wiki-noninteractive`)
