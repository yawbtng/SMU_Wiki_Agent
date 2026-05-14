# Proposal: Simplify V1 UI Redesign

## What

Redesign the Streamlit app into a minimal V1 operator workflow for building a university knowledge base:

1. Configure providers once in Settings.
2. Discover sitemap/manual/PDF sources.
3. Use LLM reasoning to classify and select useful URLs.
4. Scrape selected sources.
5. Clean scraped content.
6. Build a wiki and university structure map.
7. Build embeddings with Ollama `nomic-embed-text:latest`.
8. Store/query vectors through Zvec and MCP.

The UI should remove bloated debug surfaces from the product entirely for V1. Do not add `Advanced` panels as a hiding place for complexity. If a feature is not needed for the core workflow, leave it out until there is a clear reason to add it back.

## Why

The current app has grown into a dense operator/debug console. It contains useful capabilities, but the normal workflow is difficult to understand:

- Choose URLs mixes manual filters, local rules, LLM scoring, profile generation, raw tables, and too many recovery controls.
- Provider settings appear in multiple tabs.
- Scrape, Clean, and Review expose too many internal details by default.
- The app does not yet present a clear "student-useful university knowledge base" product path.
- The user needs control, but not every control should be visible all the time.

The V1 product should feel obvious:

- "What university am I building?"
- "What sources are useful?"
- "Run the pipeline."
- "Review the wiki."
- "Build/query the index."

## Goals

- Make Settings the single home for keys, providers, models, embeddings, and vector DB toggles.
- Keep the existing tab order unless a simpler grouping clearly removes confusion.
- Make each page have one primary action and a small number of secondary actions.
- Use OpenRouter for LLM URL reasoning and university structure classification.
- Use Tavily only for research/enrichment and failed-source recovery when enabled.
- Use Ollama embeddings with `nomic-embed-text:latest` for local vector indexing.
- Use Zvec as the local vector DB target.
- Add an Obsidian-like university map graph that organizes everything into:
  - school name
  - department
  - student office/service
  - source URLs
  - confidence/reasoning
- Remove raw/debug/operator-only surfaces from V1 unless they directly support the current task.

## Non-Goals

- Do not replace Streamlit in this change.
- Do not build a full custom frontend.
- Do not remove existing scrape/clean functionality.
- Do not require Tavily for the core pipeline.
- Do not force Ollama for cleanup; OpenRouter remains the preferred fast cleanup path when configured.
- Do not implement production auth or hosted deployment.

## User Experience Principles

- One obvious next action per screen.
- Settings before action, not action pages full of credentials.
- Readable tables only when they help make a decision.
- Graphs should explain relationships, not decorate the page.
- No `Advanced` panels in V1. Complexity must earn its place as a normal feature later.
- LLM decisions should include human-readable reasons.

## Success Criteria

- A new user can run Setup -> Discover -> Choose URLs -> Scrape -> Clean -> Review without needing hidden/debug controls.
- Choose URLs primarily uses OpenRouter reasoning, with local rules as fallback.
- Settings contains OpenRouter, Tavily, Ollama embedding, and Zvec configuration.
- University Map renders a clear Obsidian-style School -> Department -> Office/Service graph with categorized URLs.
- Clean/Review focuses on run outcomes and generated artifacts.
- Embedding/index actions are visible only after usable cleaned/wiki content exists.
- Raw JSON, queues, terminal details, dense analytics, and legacy scoring controls are not part of the V1 UI.

