# Design: Simplify V1 UI Redesign

## Current Shape

The app is a Streamlit workflow with tabs:

- Setup
- Discover
- Choose URLs
- Scrape
- Clean
- Review
- Settings

The backend already has pieces for sitemap discovery, manual URLs, Scrapling scrape, cleanup, Tavily retry, OpenRouter selection, Ollama cleanup, wiki orchestration, Zvec index scaffolding, and MCP query scaffolding.

The redesign should reorganize these capabilities around a simple product story rather than adding new visible controls everywhere. V1 should not use `Advanced` sections. Features that are not necessary for the main workflow should be removed from the visible UI and reintroduced later only when there is a concrete need.

## Target Information Architecture

### Setup

Purpose: show workspace state and next action.

Primary visible content:

- active workspace/site
- active or latest run
- discovered URL count
- selected URL count
- current pipeline status
- next recommended action

Removed from V1:

- workspace deletion
- raw workspace metadata
- duplicate workspace forms when a workspace already exists

### Discover

Purpose: gather candidate sources.

Primary visible content:

- refresh sitemap URLs
- add manual links
- add PDFs
- counts by host/source type

Removed from V1:

- raw discovered URL table
- sitemap diagnostics
- low-level discovery notes

### Choose URLs

Purpose: let the LLM identify useful and spammy URLs.

Primary visible content:

- selected university/source summary
- OpenRouter model label from Settings
- button: `LLM Choose URLs`
- usefulness threshold
- max URLs
- selected URLs table with score and reason
- excluded/spammy summary
- button: `Use These URLs`

Secondary visible content:

- `Build University Map` when Tavily/OpenRouter are configured
- graph/table preview of School -> Department -> Office/Service

Removed from V1:

- generated local scoring profile editor
- imported Pi/legacy scoring JSON
- raw discovered/scored mega-table
- batch size controls
- LLM trace/debug output

### Scrape

Purpose: run and monitor scraping.

Primary visible content:

- selected URL count
- concurrency
- start/pause/resume/cancel
- progress
- current URL
- success/failure counts
- retry failed URLs when failures exist

Removed from V1:

- page inspector
- event timeline
- raw pages table
- deep failure triage
- Tavily fallback controls

### Clean

Purpose: clean scraped markdown into useful wiki/search content.

Primary visible content:

- provider/model label from Settings
- start/resume/cancel
- progress
- cleaned/failed/skipped counts
- latest cleaned outputs

Removed from V1:

- max token controls
- thinking mode
- raw cleanup manifest/events
- Tavily retry
- Claude plan legacy controls

### Review

Purpose: inspect outputs and build final artifacts.

Primary visible content:

- run summary
- selected/scraped/cleaned/skipped/failed
- cleaned output links
- university map graph
- wiki artifact links
- build embeddings button
- query index/MCP instructions

Removed from V1:

- dense analytics tables
- raw traces
- raw manifest viewers

### Settings

Purpose: all configuration lives here.

Primary sections:

- OpenRouter
  - API key status/input
  - URL reasoning model
  - cleanup model
- Tavily
  - API key status/input
  - use for university map research toggle
  - use for failed scrape retry toggle
- Ollama
  - base URL
  - cleanup fallback model
  - embedding toggle
  - embedding model, default `nomic-embed-text:latest`
- Zvec
  - enabled toggle
  - index path
  - collection/index name
- Defaults
  - scrape concurrency
  - cleanup concurrency
  - max selected URLs

No API keys should appear on action pages.

## University Map

### Purpose

Build a structured, Obsidian-like map of the university so URL selection and wiki organization are not just URL ranking. This graph is a primary V1 experience, not a debug visualization.

### Inputs

- sitemap/discovered URLs
- manual URLs
- optional Tavily search snippets
- optional cleaned content when available

### Output Artifact

Path:

`data/sites/<site_id>/university_map.json`

Shape:

```json
{
  "site_url": "...",
  "generated_at": "...",
  "method": "openrouter_with_tavily_and_sitemap",
  "nodes": [
    {
      "id": "school:dedman-college",
      "type": "school",
      "label": "Dedman College of Humanities and Sciences",
      "confidence": 0.92,
      "reason": "Found from official sitemap and Tavily corroboration"
    }
  ],
  "edges": [
    {
      "source": "school:dedman-college",
      "target": "department:biology",
      "relationship": "contains"
    }
  ],
  "sources": [
    {
      "url": "...",
      "title": "...",
      "mapped_to": ["school:...", "department:..."]
    }
  ]
}
```

### Visualization

Use a lightweight graph component that works in Streamlit:

- Prefer a force-directed or hierarchical HTML/JS graph that feels close to Obsidian relationship view.
- Show school nodes as top-level groups.
- Show departments/offices as children.
- Group/categorize URLs under the school, department, or office they belong to.
- Include node colors by category: school, department, office/service, document/PDF, page.
- Clicking a node should show its categorized URLs, confidence, and reason when feasible in V1.

## LLM URL Reasoning

OpenRouter should be the primary V1 selector.

Prompt intent:

- identify student-useful pages
- identify spam/noisy/legacy/archive pages
- classify likely school/department/office when possible
- return scores and reasons
- prefer official canonical pages
- keep PDFs when they look like authoritative catalogs, schedules, policies, or student documents

Local rules remain:

- fallback only when OpenRouter key is missing
- no normal V1 rule editor
- no operator rule tuning unless we later prove it is needed

## Data Flow

1. Discovery writes `discovered_urls.json`.
2. Choose URLs runs OpenRouter and writes `selected_urls_llm.json`.
3. Selected rows are persisted back to `discovered_urls.json` with score/reason/selected fields.
4. Scrape reads selected rows through the existing `selected_df -> DiscoveredURL` path.
5. Clean reads scrape artifacts and writes `cleanup_manifest.json`.
6. Review builds wiki/map/index artifacts from run outputs.
7. Zvec indexing reads cleaned/wiki markdown and writes a local Zvec index.
8. MCP server reads the Zvec index and exposes query tools.

## Error Handling

- If OpenRouter key is missing, show one Settings link/callout and keep local fallback available.
- If Tavily key is missing, build university map from sitemap only and show lower-confidence notice.
- If Ollama embedding model is missing, show command/instruction from Settings and do not block other review actions.
- If Zvec is unavailable for current Python, show environment guidance and do not break Streamlit.

## Migration Notes

- Existing run artifacts should continue to load.
- Existing `selected_urls_llm.json` should remain compatible.
- Existing local scoring profile should stay out of the V1 UI unless OpenRouter is unavailable and the operator explicitly needs a fallback.
- Existing dirty/debug panels should be removed from the V1 UI. Keep backend helpers only when they are still required by the main workflow.

