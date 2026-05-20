# Ultra Fast RAG Scrape Planner

Local Streamlit app for this workflow:

1. Discover all URLs from sitemap(s)
2. Use OpenRouter to build `source_exclusion_plan.json`, excluding only spam/login/search/filter/feed/archive/news/event/media URLs
3. Scrape every remaining URL with Scrapling (fallback modes for harder pages)
4. Clean pages sequentially with local Ollama model (one URL at a time)
5. Use the Pi `content-organizer` skill to quarantine useless final-output pages and organize content by school, department, office, service, document, and people/professor profile
6. Retry failed URLs with Tavily Extract when needed
7. Review generated wiki/graph outputs

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
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
- OpenRouter: set `OPENROUTER_API_KEY` for the pre-scrape do-not-parse classifier
- Data root: set `ULTRA_FAST_RAG_DATA_ROOT` if you want artifacts somewhere other than `data/`; Codex/Git worktrees automatically reuse the main checkout's populated `data/` directory when local worktree data is empty.
- Claude CLI: install/login `claude` for optional wiki build helpers
- Ollama: run local server at `http://localhost:11434` for cleanup
- PDF/document wiki ingest: use Python 3.10+ and install `pip install -r requirements-pdf.txt` to install Docling for converting PDFs/documents before graph wiki indexing.

## Data layout

Run artifacts are written under:

`data/sites/<site_slug>/<run_id>/`

Key files:

- `discovered_urls.json`
- `source_exclusion_plan.json`
- `selected_urls.json`
- `scrape_manifest.json`
- `failures.json`
- `raw_html/*.html`
- `markdown/*.md`
- `metadata/*.json`
- `claude_wiki_manifest.json`
- `claude_wiki_prompt.md`
- `sources/pdf_uploads/*`
- `document_ingest/converted_markdown/*.md`
- `document_ingest/manifest.json`
- `document_ingest/report.md`
- `content_organizer/quarantine.json`
- `content_organizer/report.md`
- `wiki/index.md`
- `wiki/graph.json`
- `wiki/subwikis/<topic>/index.md`

## Local Zvec Query MCP

Optional local semantic query path after scrape + clean + wiki build:

1. Install optional dependencies:
   `pip install -r requirements-mcp.txt`
2. Ensure Ollama has the embedding model:
   `ollama pull nomic-embed-text:latest`
3. Build a Zvec index from a run directory:
   `python scripts/zvec_index_run.py data/sites/<site_id>/<run_id> --model nomic-embed-text:latest`
4. Connect an agent to the MCP server:
   `ZVEC_DB_PATH=/absolute/path/to/run/zvec_index OLLAMA_EMBED_MODEL=nomic-embed-text:latest python mcp_servers/smu_zvec_mcp.py`

The MCP exposes `query_smu_wiki` and `zvec_index_info` for Claude, Codex, or any MCP client.

## M001 readiness proof

Run the single proof command to validate M001 cross-slice contracts (S03 stale packet, S04 maintenance artifacts, S05 PDF contracts):

```bash
python3 scripts/m001_proof.py --config configs/m001_v1.json --run-root tests/fixtures/m001_proof/pass/run_root --output-dir tests/fixtures/m001_proof/tmp_output
```

Required inputs:
- `--config`: V1 contract file (example: `configs/m001_v1.json`)
- `--run-root`: run artifact root containing `s03/`, `s04/`, `s05/`
- `--output-dir`: destination for deterministic proof outputs

Output artifacts:
- `<output-dir>/proof_result.json` — machine-readable per-check results with `check_id`, `status`, `reason`, and timestamps
- `<output-dir>/proof_report.md` — operator-readable markdown summary

Exit code semantics:
- `0`: overall pass (all checks pass)
- `1`: overall fail (one or more checks fail; inspect `proof_result.json` for failing `check_id` and `reason`)

## Raw markdown retrieval proof

For fixture-level proof of index-first bounded retrieval behavior:

```bash
PYTHONPATH=src python3 scripts/raw_retrieval_proof.py
PYTHONPATH=src python3 scripts/raw_retrieval_proof.py --help
```

The proof script builds lexical index artifacts under `tests/fixtures/raw_retrieval/index` and runs a bounded query path that must return `status: "ok"` from index artifacts.
