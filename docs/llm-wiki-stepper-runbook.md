# LLM Wiki Stepper Runbook

This runbook covers the operator path for taking local source artifacts through raw source normalization, LLM Wiki generation, embedding/reranking, and Codex MCP query setup.

## Directory Layout

For each site, the stepper uses this layout:

- `data/sites/<site_id>/raw_sources/registry.jsonl`
- `data/sites/<site_id>/raw_sources/web/`
- `data/sites/<site_id>/raw_sources/pdf/`
- `data/sites/<site_id>/raw_sources/excel/`
- `data/sites/<site_id>/wiki/`
- `data/sites/<site_id>/indexes/`

Raw sources are the source of truth. Wiki and index files are derived artifacts and can be rebuilt.

## One-Command Ingestion

Use this non-interactive command to run the complete durable path: normalize raw sources, build/update the wiki, rebuild the local index, and optionally run a smoke query.

```bash
python -m src.scrape_planner.wiki_ingestion_pipeline \
  --site-root data/sites/<site_id> \
  --run-root data/sites/<site_id>/<run_id> \
  --kind auto \
  --query "What are the admissions deadlines?"
```

Useful variants:

- `--kind web --run-root ...` for a scrape run.
- `--kind pdf` for previously extracted PDF page markdown under `sources/pdf_pages/` or `sources/pdf_ingest/`.
- `--kind excel --tabular-path /absolute/path/to/source.csv` for tabular sources.
- `--kind all --run-root ... --tabular-path ...` for every source family.
- `--rebuild` for a full derived-wiki rebuild; otherwise the command resumes incrementally.
- `--skip-normalize`, `--skip-wiki`, or `--skip-index` to restart from a later stage.

The command prints a JSON report with normalization counts, registry readiness, wiki build report, index report, and optional query evidence.

## Add New Sources

Use the existing app flows for scraping pages, uploading PDFs, or adding CSV/Excel files. Then normalize into the raw source database.

Web scrape markdown:

```bash
python -m src.scrape_planner.raw_source_normalizer \
  --site-root data/sites/<site_id> \
  --kind web \
  --run-root data/sites/<site_id>/<run_id> \
  --no-input
```

PDF-derived markdown:

```bash
python -m src.scrape_planner.raw_source_normalizer \
  --site-root data/sites/<site_id> \
  --kind pdf \
  --no-input
```

CSV or Excel:

```bash
python -m src.scrape_planner.raw_source_normalizer \
  --site-root data/sites/<site_id> \
  --kind excel \
  --tabular-path /absolute/path/to/source.csv \
  --no-input
```

After normalization, inspect:

- `raw_sources/registry.jsonl`
- `raw_sources/reports/normalization-*.json`
- rows with `status=failed` or `status=needs-review`

## Build Or Rerun The Wiki

Incremental build:

```bash
python -m src.scrape_planner.llm_wiki_builder \
  --site-root data/sites/<site_id> \
  --no-input \
  --resume
```

Full derived-wiki rebuild:

```bash
python -m src.scrape_planner.llm_wiki_builder \
  --site-root data/sites/<site_id> \
  --no-input \
  --rebuild
```

The builder does not prompt. Uncertain or conflicting material goes to `wiki/review_queue.md`.

Check:

- `wiki/index.md`
- `wiki/pages/*.md`
- `wiki/log.md`
- `wiki/reports/wiki-build-latest.json`
- `wiki/review_queue.md`

## Rebuild Indexes And Query

Build or refresh the deterministic raw/wiki index:

```bash
python -m src.scrape_planner.llm_wiki_index \
  --site-root data/sites/<site_id>
```

Run a local reranked query:

```bash
python -m src.scrape_planner.llm_wiki_index \
  --site-root data/sites/<site_id> \
  --query "What are the admissions deadlines?"
```

Check:

- `indexes/llm_wiki_manifest.json`
- `indexes/llm_wiki_documents.jsonl`
- `indexes/reports/embedding-*.json`
- `indexes/embedding_status.json`

## Install The Codex MCP Connector

The MCP server is query-only. It reads existing wiki/index files and does not normalize, build, or mutate artifacts.

Add this server entry to Codex MCP config, replacing `<repo>` and `<site_id>` with absolute paths:

```json
{
  "mcpServers": {
    "llm-wiki-<site_id>": {
      "command": "/absolute/path/to/python",
      "args": [
        "-m",
        "mcp_servers.llm_wiki_mcp",
        "--site-root",
        "/absolute/path/to/<repo>/data/sites/<site_id>"
      ]
    }
  }
}
```

Smoke-test the server with a bounded request/response check:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"index_info","arguments":{}}}' \
| LLM_WIKI_SITE_ROOT=/absolute/path/to/<repo>/data/sites/<site_id> \
  timeout 10s python -m mcp_servers.llm_wiki_mcp --site-root /absolute/path/to/<repo>/data/sites/<site_id>
```

Useful tools exposed to Codex:

- `index_info`
- `query_wiki`
- `search_sources`
- `get_wiki_page`

## Validation

Run the final validation slice:

```bash
python scripts/validate_llm_wiki_stepper.py \
  --output-root data/validation/llm-wiki-stepper \
  --report-path docs/validation/llm-wiki-stepper-validation.json \
  --smu-limit 3
```

The command creates a deterministic fixture site and a bounded SMU proof from existing local SMU scrape artifacts. It does not run live scraping or LLM calls.
