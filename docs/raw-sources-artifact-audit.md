# Raw Sources Artifact Audit

This audit records the current artifacts that can feed `data/sites/<site_id>/raw_sources/` for the `build-llm-wiki-stepper` change.

## Site Workspace Layout

- Workspace state is rooted under `data/sites/<site_id>/`.
- Current run artifacts live under `data/sites/<site_id>/<run_id>/`.
- Source upload artifacts live under `data/sites/<site_id>/sources/`.
- The new raw-source conventions are:
  - `data/sites/<site_id>/raw_sources/registry.jsonl`
  - `data/sites/<site_id>/raw_sources/web/`
  - `data/sites/<site_id>/raw_sources/pdf/`
  - `data/sites/<site_id>/raw_sources/excel/`
  - `data/sites/<site_id>/raw_sources/reports/`
  - `data/sites/<site_id>/wiki/`
  - `data/sites/<site_id>/indexes/`
- Normalized markdown and metadata filenames include the stable source ID and checksum prefix, so a changed source writes a new raw record while the registry keeps one stable row per source ID.

## Discovery Inputs

- `data/sites/<site_id>/discovered_urls.json` is persisted by the workspace/discovery flow.
- `data/sites/<site_id>/<run_id>/selected_urls.json` is written before scrape execution and records the selected source URLs.
- These files are planning inputs. They do not contain normalized markdown, but they identify web/PDF source candidates and can be used as provenance.

## Scrape Inputs

- `data/sites/<site_id>/<run_id>/markdown/*.md` contains scraped markdown for successful HTML pages.
- `data/sites/<site_id>/<run_id>/metadata/*.json` contains crawl metadata such as URL, HTTP status, content type, text length, link density, fetch mode, worker, and attempt.
- `data/sites/<site_id>/<run_id>/raw_html/*.html` contains raw fetched HTML.
- `data/sites/<site_id>/<run_id>/scrape_manifest.json` is the main adapter input for web raw sources. Success rows contain URL, status, markdown path, metadata path, and fetch metadata.
- `data/sites/<site_id>/<run_id>/pages.jsonl` is the durable scrape page-state log and can recover page rows if runtime state is unavailable.
- `data/sites/<site_id>/<run_id>/failures.json` records failed page fetches and can feed failed raw-source diagnostics later.

## PDF Inputs

- Uploaded PDFs are recorded in `data/sites/<site_id>/sources/pdf_manifest.json`.
- Uploaded PDFs are saved under `data/sites/<site_id>/sources/pdfs/`.
- PDF extraction writes page-level markdown under `data/sites/<site_id>/sources/pdf_pages/<pdf_source_id>/`.
- Each page folder has `pages.json` rows with `pdf_source_id`, `source_path`, `page_number`, `parser`, and `markdown_path`.
- PDF extraction also writes:
  - `data/sites/<site_id>/sources/pdf_ingest/pdf_sources.jsonl`
  - `data/sites/<site_id>/sources/pdf_ingest/pdf_chunks.jsonl`
  - `data/sites/<site_id>/sources/pdf_ingest/pdf_quarantine.jsonl`
- Scraped PDF downloads can also write run-local PDF ingest artifacts under `data/sites/<site_id>/<run_id>/s05/`.
- The first normalization adapter path uses `sources/pdf_pages/*/pages.json` and falls back to `sources/pdf_ingest/pdf_chunks.jsonl` when page markdown is unavailable.

## Graph And Zvec Inputs

- `src/scrape_planner/markdown_graph.py` currently builds graph artifacts from run markdown and scrape manifests under a run root.
- `src/scrape_planner/zvec_index.py` currently loads raw scrape docs from `scrape_manifest.json`, wiki docs from a run-local `wiki/`, and PDF chunk docs from `s05/pdf_chunks.jsonl` or site `sources/pdf_ingest/`.
- `data/sites/<site_id>/<run_id>/zvec_index_manifest.json` records the existing run-local embedding index build.
- These graph and zvec artifacts are downstream or read-only consumers for this slice. The raw-source registry should become their future input contract without mutating existing run artifacts.
