## Context

The v1 is implemented in the working tree (uncommitted) and behaves as follows:

- `wiki/llm_wiki_index.py`: `EMBEDDING_PROVIDER="ollama"`, `EMBEDDING_DIMENSIONS=768`, with a deterministic hash fallback (`FALLBACK_EMBEDDING_PROVIDER`) that latches per-build when Ollama is unreachable. `build_llm_wiki_index` rewrites `llm_wiki_documents.jsonl` by `unlink()` + line append (not atomic); `postings`/`manifest` use `_write_json_atomic`. `_document_row_current` reuses a row on matching checksum + `provider == EMBEDDING_PROVIDER` + length, and does not inspect manifest `version` or the actual space used.
- `wiki/confidence.py`: `assess_confidence` reads the first non-zero of `combined, model_rerank, retrieval_vector, bm25, lexical`; defaults `RAG_CONFIDENCE_MIN_SCORE=1.0`, `RAG_CONFIDENCE_MIN_GAP=0.05`. `_has_citation` already excludes wiki-only `source_id`, so the "citation" check is meaningful.
- `wiki/web_search.py`: `web_search` with `MockWebSearchProvider`, `BraveWebSearchProvider`, `TavilyWebSearchProvider`; `provider_from_env` precedence is `RAG_WEB_SEARCH_PROVIDER` then Brave key then Tavily key; returns `web_search_unavailable` when unconfigured.
- `wiki/self_improving.py`: `answer_question` → local query → `assess_confidence` → `LoopGuard` cache → `web_search` → `assess_candidate_source` quality gate (`source_quality` + `_student_policy_rejection`) → `launch_ingest_job` (tmux) → provisional answer cached in the guard. `ingest_url` mirrors it for one URL. `record_rejection` appends to `self_improving_rejections.jsonl`. `LoopGuard` has a TTL and a `clear()` that is never called on job completion. `launch_ingest_job` derives `--site-url` from the web URL's own host (so `apply_manual_urls` same-domain check passes for any external URL), runs with `workdir=Path.cwd()`, and reports `unavailable` when tmux is absent.
- `mcp_servers/llm_wiki_mcp.py`: exposes `answer_question` and `ingest_url` alongside the existing query-only tools.

A four-model interrogation (Opus-4.8, GPT-5.3-codex, GPT-5.5, Composer-2.5) converged on five blocking defects (confidence scale, loop-guard completion, write concurrency, SSRF/poisoning, embedding-space integrity) plus idempotency and cold-start issues. This change fixes those.

## Goals / Non-Goals

**Goals:**

- Make the confidence decision calibratable regardless of reranker availability.
- Guarantee the loop guard clears on real ingest completion and never pins a stale answer after failure.
- Make concurrent ingest/index writes safe per site.
- Make `ingest_url` and the fetch path safe against SSRF and untrusted-content poisoning.
- Prevent mixed-embedding-space indexes from producing meaningless similarity.
- Make re-ingest genuinely cheap and bound run-directory growth.
- Prevent web-search storms on empty/new sites.

**Non-Goals:**

- No synchronous index mutation in the MCP request path.
- No new vector database; reuse current artifacts and the Ollama client.
- No LLM answer synthesis in this change; the provisional "answer" is explicitly snippet-derived and flagged unverified.

## Decisions

### Decision 1: Mode-aware confidence
`assess_confidence` SHALL normalize the score it gates on (e.g., min-max or softmax over the candidate set) or read `model_rerank` directly when rerank is active, and SHALL record which scoring mode produced the decision. Defaults:

| Mode | `RAG_CONFIDENCE_MIN_SCORE_*` default | `RAG_CONFIDENCE_MIN_GAP_*` default |
|------|--------------------------------------|------------------------------------|
| `fused` (reranker off) | `0.4` via `RAG_CONFIDENCE_MIN_SCORE_FUSED` | `0.05` via `RAG_CONFIDENCE_MIN_GAP_FUSED` |
| `reranked` (reranker on) | `0.5` via `RAG_CONFIDENCE_MIN_SCORE_RERANKED` | `0.05` via `RAG_CONFIDENCE_MIN_GAP_RERANKED` |

Rationale: `combined` is `lexical + 1.5*vector + boosts` (often ≫1) with rerank off, but `_maybe_openrouter_rerank` overwrites `combined` with a ~0–1 score with rerank on; one threshold cannot serve both.

### Decision 2: Completion-driven loop guard
`launch_ingest_job` SHALL cause a terminal status file (`succeeded`/`failed` + reason + ingested source ids) to be written when the detached pipeline finishes. `answer_question` SHALL consult that status: clear the guard on success; on failure clear immediately and surface the failure (subject to a bounded per-query retry count) rather than returning the cached provisional for the full TTL. The guard remains a TTL backstop only.

### Decision 3: Per-site write serialization + atomic docs swap
All index mutation SHALL hold a per-site lock; `run_manual_url_pipeline`'s index build SHALL reuse the existing concurrent-build guard. `build_llm_wiki_index` SHALL write `llm_wiki_documents.jsonl` to a temp file and `os.replace` it, so readers never observe a truncated file and two writers cannot interleave.

### Decision 4: Network safety + trusted-domain policy
`ingest_url` and the fetch path SHALL enforce: `https` scheme allowlist; rejection of private/link-local/loopback and cloud-metadata IPs after DNS resolution and after each redirect; a redirect cap; and a response-byte cap. External ingestion SHALL be governed by an explicit trusted-domain policy (config), not by silently passing the URL's own host as the site domain. The real `source_quality` gate SHALL run on the **fetched, extracted markdown** (not just the snippet); failures are quarantined, not written.

### Decision 5: Embedding-space integrity
Each indexed row SHALL record the embedding space actually used (real vs hash fallback). `_document_row_current` SHALL key reuse on that space and on `INDEX_VERSION`. A degraded build (any hash fallback) SHALL either disable the vector leg for that index or force a full re-embed once the backend recovers; `_cosine_similarity` SHALL refuse to compare vectors from different spaces. Query-time embedding SHALL match the stored space declared in the manifest, or the vector leg SHALL be skipped with a visible flag.

### Decision 6: Honest idempotency + retention
The spec guarantee SHALL be "no duplicate sources/pages," not "no-op." A pre-fetch short-circuit (canonicalized URL + known content checksum) SHALL skip fetch/build when nothing changed. A retention policy SHALL bound accumulation of `manual-*` run directories.

### Decision 7: Cold-start guard
When no usable index exists for a site (or it is below a minimum document count), `answer_question` SHALL NOT trigger web fallback; it SHALL return a clear "index not ready" status. A per-site web-search budget/rate cap SHALL bound fallback frequency even after bootstrap.

### Decision 8: Auditability
Accepted auto-ingests SHALL be recorded in an append-only ledger (mirroring the existing rejection ledger) mapping question → job → ingested source ids, with a rollback path that quarantines those sources/pages and rebuilds.

## Risks / Trade-offs

- Score normalization can shift behavior of existing tests. Mitigation: add labeled boundary tests and document defaults per mode.
- Per-site locking can serialize throughput. Mitigation: coalesce duplicate in-flight ingests; locking is per site, not global.
- Trusted-domain policy may reject useful sources. Mitigation: make the allowlist explicit and configurable; log rejections.
- Disabling the vector leg on degraded builds reduces recall offline. Mitigation: visible flag; BM25 still serves; auto-recover on next healthy rebuild.

## Migration Plan

1. Land embedding-space bookkeeping + version-aware reuse; rebuild the active site's index.
2. Make `assess_confidence` mode-aware; document defaults; update existing tests.
3. Add the ingest completion status file + completion-driven guard clearing with bounded retries.
4. Add per-site lock + atomic docs swap.
5. Add SSRF/domain policy + post-fetch quality gate + portable runner fallback + `workdir=site_root`.
6. Add idempotency short-circuit, run-dir retention, cold-start guard, and the accepted-ingest ledger + rollback.
7. Extend `tests/test_self_improving_rag_mcp.py` across every boundary; run compile + pytest + an MCP smoke query before completion.
