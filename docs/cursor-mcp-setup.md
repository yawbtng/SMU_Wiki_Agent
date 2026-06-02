# Cursor MCP — LLM Wiki (query-only)

Connect Cursor to the local **llm-wiki** indexes for a site (read-only: no scrape, no wiki build).

## Quick install

From the repo root:

```bash
./scripts/install-cursor-mcp.sh
```

Optional:

```bash
LLM_WIKI_SITE_ID=demo.edu ./scripts/install-cursor-mcp.sh
```

Then in Cursor: **Settings → MCP**, enable **`llm-wiki-www.smu.edu`** (or your site id), and **reload the window**.

## Tools exposed

| Tool | Purpose |
|------|---------|
| `index_info` | Index health, counts, last build |
| `query_wiki` | Hybrid wiki + source search |
| `search_sources` | Raw source evidence only |
| `get_wiki_page` | Fetch a wiki page by path, id, or title |
| `answer_question` | Local evidence + optional web fallback |
| `ingest_url` | Queue one URL through the manual pipeline |

## Smoke test (terminal)

```bash
SITE="$(pwd)/data/sites/www.smu.edu"
PY="$(pwd)/.venv/bin/python"
cd "$(pwd)"
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"index_info","arguments":{}}}' \
| PYTHONPATH=. "$PY" -m mcp_servers.llm_wiki_mcp --site-root "$SITE"
```

Expect `"ok": true` and non-zero `wiki_index_count` when embeddings were built.

## Manual config

See `configs/cursor-mcp-llm-wiki.example.json`. Merge into `~/.cursor/mcp.json` under `mcpServers`. Use the repo `.venv` python, set `cwd` to the repo root, and pass `--site-root` to the site directory.

Prerequisites: indexes built (Embeddings tab / `llm_wiki_manifest.json` present). MCP deps: `pip install -r requirements-mcp.txt` if import errors occur.

## Production (pre-built site, query via MCP)

Use this when wiki + indexes are **already built** (on a laptop or build host with Docling and the full operator flow). Production does **not** re-parse PDFs or rebuild the wiki on each question.

### What to ship

Copy or mount at least:

```text
data/sites/<site_id>/wiki/pages/
data/sites/<site_id>/indexes/llm_wiki_documents.jsonl
data/sites/<site_id>/indexes/llm_wiki_postings.json
data/sites/<site_id>/indexes/llm_wiki_manifest.json
```

Original PDFs and `sources/pdf_ingest/` are optional on the query host.

### Setup steps

1. Build indexes once (operator UI **Embeddings** tab or `llm-wiki-noninteractive` Pi skill).
2. Place `data/sites/<site_id>/` on the machine that runs MCP (or sync to your laptop).
3. Run `./scripts/install-cursor-mcp.sh` with `LLM_WIKI_SITE_ID` set; fix paths in `~/.cursor/mcp.json` if directories moved.
4. Set `OPENROUTER_API_KEY` in the MCP `env` block (or shell) for rerank quality.
5. Enable the server in Cursor and reload the window.
6. Prefer `query_wiki`, `search_sources`, and `get_wiki_page` for student Q&A. Avoid `ingest_url` on read-only prod data.

### Read-only prod tools

| Tool | Use in prod |
|------|-------------|
| `index_info` | Health check after deploy |
| `query_wiki` | Primary retrieval |
| `get_wiki_page` | Full page text for citations |
| `search_sources` | Catalog/PDF evidence ids |
| `answer_question` | Optional; may trigger web/ingest if confidence is low |
| `ingest_url` | Operator refresh only |

Docling remains part of the **full app** (`requirements-pdf.txt`) for when you ingest new PDFs on a build machine; it is not required for steady-state MCP query over existing indexes.

See README sections **Local operator vs production** and **Using MCP in production**.
