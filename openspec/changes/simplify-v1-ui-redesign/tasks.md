# Tasks: Simplify V1 UI Redesign

## 1. Settings Consolidation

- [ ] Move Tavily API key input to Settings only.
- [ ] Ensure OpenRouter key/status is visible only in Settings.
- [ ] Add OpenRouter URL reasoning model setting.
- [ ] Add Ollama base URL setting.
- [ ] Add Ollama embeddings toggle.
- [ ] Add embedding model setting with default `nomic-embed-text:latest`.
- [ ] Add Zvec enabled toggle.
- [ ] Add Zvec index path / collection setting.
- [ ] Remove API key inputs from non-Settings pages.

## 2. Setup Simplification

- [ ] Replace large Setup content with compact workspace status.
- [ ] Show active workspace, site URL, discovered count, selected count, latest run, and next action.
- [ ] Remove duplicate workspace management controls from the normal V1 flow.
- [ ] Keep typography compact.

## 3. Discover Simplification

- [ ] Keep `Refresh Sitemap URLs` as the primary action.
- [ ] Move manual link and PDF addition into a simple source intake area.
- [ ] Show counts by source type and host.
- [ ] Remove raw discovered mega-table from V1.
- [ ] Preserve root-domain/subdomain acceptance.

## 4. Choose URLs V1

- [ ] Make OpenRouter `LLM Choose URLs` the primary action.
- [ ] Read OpenRouter model/key from Settings only.
- [ ] Show selected URL table with score, reason, host, source type.
- [ ] Show excluded/spammy summary without forcing a huge table.
- [ ] Keep threshold and max URLs as the only normal controls.
- [ ] Remove local scoring profile/rules from V1 unless OpenRouter is unavailable.
- [ ] Remove Pi/import scoring from V1 UI.
- [ ] Ensure LLM reasons persist in `selected_urls_llm.json`.
- [ ] Ensure selected rows persist in `discovered_urls.json`.

## 5. University Map

- [ ] Add `Build University Map` action.
- [ ] Use sitemap/manual URLs as base context.
- [ ] Use Tavily search when enabled/configured.
- [ ] Use OpenRouter to classify School -> Department -> Student Office/Service.
- [ ] Save `data/sites/<site_id>/university_map.json`.
- [ ] Render an Obsidian-style categorized graph in Streamlit.
- [ ] Color/group graph nodes by school, department, student office/service, page, and PDF/document.
- [ ] Show URLs under their mapped category.
- [ ] Show supporting table with label, type, URL, confidence, reason.
- [ ] Make node selection show category details when feasible.

## 6. Scrape Cockpit

- [ ] Keep only start/pause/resume/cancel, selected count, concurrency, progress, current URL, success/failure.
- [ ] Show retry failed only after failures exist.
- [ ] Remove page inspector, raw event timeline, full queue table, and failure triage from V1 UI.

## 7. Graph Builder

- [ ] Build graph from successful scraped markdown, not cleaned markdown.
- [ ] Run LLM reasoning over every scraped URL.
- [ ] Write deterministic `wiki/graph.json` and `scraped_url_reasoning.json`.
- [ ] Show included/excluded source counts.
- [ ] Show included URL table by category/group/reason.
- [ ] Keep excluded pages behind a secondary view.
- [ ] Remove cleanup queue/events/reset from V1 UI.

## 8. Review and Outputs

- [ ] Show run summary first.
- [ ] Show scraped source graph and wiki artifacts.
- [ ] Show University Map graph and table when available.
- [ ] Add `Build Wiki` action if artifacts are ready.
- [ ] Add `Build Embeddings` action when graph/wiki content exists.
- [ ] Add Zvec/MCP connection instructions when index exists.
- [ ] Remove dense cost/call/latency analytics and raw traces from V1 UI.

## 9. Embeddings and Zvec

- [ ] Read embedding settings from Settings.
- [ ] Use Ollama `nomic-embed-text:latest` by default.
- [ ] Build Zvec index from graph/wiki markdown.
- [ ] Persist `zvec_index_manifest.json`.
- [ ] Surface index status in Review.
- [ ] Keep MCP server instructions in Review/Settings, not action pages.

## 10. Verification

- [ ] Run `python -m pytest`.
- [ ] Smoke import `python -c "import app"`, or compile-check if Streamlit import side effects block direct import.
- [ ] Start Streamlit at `http://127.0.0.1:8501`.
- [ ] Manually verify Settings has all keys/toggles.
- [ ] Manually verify there are no `Advanced` sections in the V1 UI.
- [ ] Manually verify OpenRouter URL reasoning writes scores/reasons.
- [ ] Manually verify university map renders as an Obsidian-style categorized graph.
- [ ] Manually verify Scrape/Graph/Review normal paths are minimal.
