# Ultra Fast RAG Scrape Planner

Local Streamlit app for this workflow:

1. Discover all URLs from sitemap(s)
2. Use OpenRouter `deepseek/deepseek-v4-flash` to select top student-useful and freshest URLs (prefer 2026/current-year)
3. Scrape selected URLs with Scrapling (fallback modes for harder pages)
4. Clean pages sequentially with local Ollama model (one URL at a time)
5. Edit cleaned markdown in-app
6. Retry failed URLs with Tavily Extract
7. Generate and run Claude wiki build orchestration

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
- OpenRouter: set `OPENROUTER_API_KEY` for URL-selection stage
- Claude CLI: install/login `claude` to enable LLM selection and wiki build
- Ollama: run local server at `http://localhost:11434` for cleanup
- PDF/document wiki ingest: use Python 3.10+ and install `pip install -r requirements-pdf.txt`; the Pi `document-wiki-ingest` skill uses Microsoft MarkItDown to convert PDFs/documents to markdown before graph wiki indexing.

## Data layout

Run artifacts are written under:

`data/sites/<site_slug>/<run_id>/`

Key files:

- `discovered_urls.json`
- `selected_urls.json`
- `selected_urls_llm.json`
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
- `wiki/index.md`
- `wiki/graph.json`
- `wiki/subwikis/<topic>/index.md`
