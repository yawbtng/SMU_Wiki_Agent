## Design

The app stores only OpenRouter model IDs for URL reasoning, wiki enrichment, wiki Q&A, and embeddings. Provider fields are normalized to `openrouter`; legacy Ollama/local fields are dropped from saved app state. The UI uses curated model `<select>` controls and displays per-1M token pricing plus a configurable estimate.

Costs are estimates using static pricing metadata in the frontend. Actual run cost remains sourced from run metrics when available.
