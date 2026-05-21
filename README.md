# Ultra Fast RAG

Local Streamlit app for building a content-first university knowledge base:

1. Create or open a workspace for a university site.
2. Add website URLs and PDF sources.
3. Scrape selected website URLs into raw markdown artifacts.
4. Normalize web/PDF/tabular artifacts into `raw_sources/`.
5. Build the local LLM Wiki from the normalized source registry.
6. Build/query supporting graph, embedding, rerank, and MCP surfaces.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-pdf.txt
streamlit run app.py
```

## Docker Run

```bash
docker compose up --build -d
```

Then open [http://localhost:8501](http://localhost:8501).
Ollama from host is wired by default as `http://host.docker.internal:11434`.

Optional:

- Redis: set `REDIS_URL` (default `redis://localhost:6379/0`)
- OpenRouter: set `OPENROUTER_API_KEY` for URL reasoning, graph labeling, and Q&A
- Tavily: set `TAVILY_API_KEY` for optional research flows
- Data root: set `ULTRA_FAST_RAG_DATA_ROOT` if you want artifacts somewhere other than `data/`
- PDF ingest: `requirements-pdf.txt` installs Docling, the only supported PDF parser

## Data Layout

Runtime artifacts are written under:

`data/sites/<site_slug>/`

Key workspace and run files:

- `discovered_urls.json`
- `<run_id>/selected_urls.json`
- `<run_id>/scrape_manifest.json`
- `<run_id>/pages.jsonl`
- `<run_id>/raw_html/*.html`
- `<run_id>/markdown/*.md`
- `<run_id>/metadata/*.json`
- `sources/pdf_uploads/*`
- `sources/pdf_pages/<pdf_source_id>/*.md`
- `sources/pdf_ingest/pdf_sources.jsonl`
- `sources/pdf_ingest/pdf_chunks.jsonl`
- `sources/pdf_ingest/pdf_quarantine.jsonl`
- `raw_sources/registry.jsonl`
- `wiki/pages/*.md`
- `wiki/reports/*.json`
- `indexes/*`

`data/` is ignored because it is runtime state and can become very large.

## MCP

The repo currently has two MCP surfaces:

- `mcp_servers/llm_wiki_mcp.py` for the LLM Wiki index/query path.
- `mcp_servers/markdown_graph_mcp.py` for the supporting markdown graph path.

Install the minimal MCP server dependency with:

```bash
pip install -r requirements-markdown-graph-mcp.txt
```
