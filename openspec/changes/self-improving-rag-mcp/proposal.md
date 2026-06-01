## Why

A first version of the self-improving retrieval MCP is already implemented in the working tree (uncommitted): real dense Ollama embeddings with a hash fallback in `wiki/llm_wiki_index.py`, a confidence gate in `wiki/confidence.py`, a provider-abstracted `wiki/web_search.py` (Tavily + Brave), and an orchestrator `wiki/self_improving.py` exposing `answer_question` / `ingest_url` MCP tools with a quality gate, a `LoopGuard`, and a tmux-launched ingest job.

A four-model adversarial review of that code found correctness, concurrency, and security defects that make the loop unsafe and unreliable in practice. This change hardens the implemented v1 so the self-improvement loop is calibratable, idempotent, concurrency-safe, and not an SSRF/poisoning vector — rather than re-building features that already exist.

## What Changes

- **Confidence calibration:** make the confidence gate aware of the scoring mode. `combined` is an unbounded additive score when the reranker is off but a ~0–1 model score when OpenRouter rerank is on, so a single `RAG_CONFIDENCE_MIN_SCORE` is meaningless. Gate on a normalized score and document mode-specific defaults.
- **Ingest completion signal:** the async ingest job SHALL write a terminal status (success/failure + reason); `LoopGuard` SHALL clear on success and clear immediately on failure, with bounded retries, so a failed ingest no longer pins a stale provisional answer for the full TTL.
- **Concurrency safety:** serialize index writers per site and make the `llm_wiki_documents.jsonl` rewrite atomic, so concurrent `answer_question`/`ingest_url` calls cannot corrupt or truncate the index.
- **Network safety:** add an explicit trusted-domain policy plus SSRF protection (scheme allowlist, block private/link-local/metadata IPs, cap redirects and response bytes) to `ingest_url` and the fetch path; run the real `source_quality` gate on **fetched content**, not just the search snippet; quarantine on failure.
- **Embedding-space integrity:** record the actual embedding space per document, force a full re-embed (or disable the vector leg) when a build is degraded, and refuse cross-space cosine, so a mixed dense/hash index cannot silently produce garbage similarity.
- **Honest idempotency:** reword the guarantee to "no duplicate sources/pages," add a pre-fetch checksum/URL-canonical short-circuit so unchanged re-ingests are cheap, and add a retention policy for accumulating `manual-*` run directories.
- **Cold-start guard:** suppress web fallback (or rate-limit it per site) until an initial index exists, so a new/empty site does not trigger a web-search storm.
- **Portability + auditability:** add a non-tmux background runner fallback, pin the ingest workdir to the site root, and add an append-only ledger of accepted auto-ingests with a rollback path.

## Capabilities

### New Capabilities

- `confidence-gated-retrieval`: Orchestrated `answer_question` flow and a mode-aware, calibrated confidence decision.
- `web-search-backfill`: Provider-abstracted web search (Tavily/Brave) with explicit provider precedence, invoked only on low confidence.
- `self-improving-ingest`: Quality-gated, idempotent, concurrency-safe, SSRF-hardened asynchronous write-back with completion-driven loop guarding and an audit/rollback ledger.

### Modified Capabilities

- `embedding-reranker-query`: Dense+BM25 fusion with embedding-space integrity (per-row space, degraded-build handling, version-aware reuse).

## Impact

- Affected code: `wiki/self_improving.py`, `wiki/confidence.py`, `wiki/llm_wiki_index.py`, `wiki/web_search.py`, `scrape/manual_url_pipeline.py`, `scrape/sitemap_discovery.py` (domain policy), `infra/tmux_runner.py` (or a portable runner), `mcp_servers/llm_wiki_mcp.py`.
- Affected dependencies: Tavily (`TAVILY_API_KEY`) and/or Brave (`BRAVE_SEARCH_API_KEY`), selected via `RAG_WEB_SEARCH_PROVIDER`; Ollama embeddings.
- Affected storage: per-row embedding-space field (index rebuild), ingest job-status files, loop-guard state, rejection + accepted-ingest ledgers, run-dir retention under `data/sites/<site_id>/`.
- Affected tests: extend `tests/test_self_improving_rag_mcp.py` with rerank-mode confidence, completion-driven guard clearing, concurrent-write safety, SSRF/domain rejection, mixed-space prevention, idempotent re-ingest, and cold-start suppression.
- Non-goal: MCP tools never mutate indexes synchronously in the request path; the deterministic wiki build contract is unchanged beyond embedding-space bookkeeping.
