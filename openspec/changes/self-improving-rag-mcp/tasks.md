## 0. Baseline

- [x] 0.1 v1 implemented in tree: dense embedding + hash fallback, `wiki/confidence.py`, `wiki/web_search.py`, `wiki/self_improving.py`, MCP `answer_question`/`ingest_url`, `tests/test_self_improving_rag_mcp.py`.
- [x] 0.2 Four-model interrogation completed; blocking findings recorded in design.md.

## 1. Embedding-space integrity

- [x] 1.1 Record the actual embedding space (real vs hash fallback) on each row in `_document_row`.
- [x] 1.2 Key `_document_row_current` reuse on the recorded space and on `INDEX_VERSION`; force full rebuild on version mismatch.
- [x] 1.3 On a degraded build (any hash fallback), disable the vector leg for that index or force re-embed on next healthy build; keep `embedding_degraded` in the manifest.
- [x] 1.4 Make `_cosine_similarity` refuse cross-space comparison; ensure query-time embedding matches the manifest space or skip the vector leg with a visible flag.
- [ ] 1.5 Rebuild the active site index and confirm vector results are coherent.

## 2. Mode-aware confidence

- [x] 2.1 Normalize the gated score (or read `model_rerank` when rerank is active) so the decision is valid in both reranker modes.
- [x] 2.2 Record the scoring mode in the `ConfidenceDecision` and in query metadata; document defaults per mode in design.md.
- [x] 2.3 Keep the wiki-self-path citation exclusion; add a test asserting it.

## 3. Web search precedence

- [x] 3.1 Confirm/spec provider precedence (`RAG_WEB_SEARCH_PROVIDER` → Brave key → Tavily key) and document it.
- [x] 3.2 Ensure `web_search_unavailable` is returned (never raised) when unconfigured; keep mock provider for tests.

## 4. Network safety + quality gate

- [x] 4.1 Add a trusted-domain policy for external ingestion instead of passing the URL's own host as `--site-url`.
- [x] 4.2 Add SSRF protection: https allowlist, block private/link-local/loopback/metadata IPs (post-DNS and post-redirect), redirect cap, byte cap.
- [x] 4.3 Run the real `source_quality` gate on fetched/extracted markdown (not just the snippet); quarantine on failure.
- [x] 4.4 Add executable student-policy rejection tests (donor, news, staff-bio, advancement, admin, non-student-actionable).

## 5. Concurrency + completion

- [x] 5.1 Add a per-site index write lock; reuse the existing concurrent-build guard in `run_manual_url_pipeline`.
- [x] 5.2 Make `build_llm_wiki_index` write `llm_wiki_documents.jsonl` to a temp file and `os.replace` it.
- [x] 5.3 Have the ingest job write a terminal status file (succeeded/failed + reason + ingested source ids).
- [x] 5.4 Make `answer_question` consult job status: clear `LoopGuard` on success, clear immediately on failure, bound retries per query.
- [x] 5.5 Add a portable background runner fallback when tmux is absent; pin ingest `workdir` to the site root.

## 6. Idempotency, cold-start, audit

- [x] 6.1 Add a pre-fetch short-circuit (canonical URL + content checksum) so unchanged re-ingest skips fetch/build.
- [x] 6.2 Add a retention policy bounding `manual-*` run directories.
- [x] 6.3 Suppress web fallback when the index is missing/below minimum docs; add a per-site web-search budget/rate cap.
- [x] 6.4 Add an append-only accepted-ingest ledger (question → job → url → source ids) and a rollback path that quarantines sources/pages and rebuilds.

## 7. Verification

- [x] 7.1 Tests: confidence decision stable across reranker on/off.
- [x] 7.2 Tests: successful ingest clears the guard; failed ingest clears immediately and surfaces failure; retries bounded.
- [x] 7.3 Tests: concurrent ingests do not corrupt `llm_wiki_documents.jsonl` (atomic swap).
- [x] 7.4 Tests: SSRF/private-IP and untrusted-domain rejection; redirect/byte caps.
- [x] 7.5 Tests: mixed-space prevention (degraded build disables vector leg / refuses cross-space cosine).
- [x] 7.6 Tests: idempotent re-ingest creates no duplicates and short-circuits.
- [x] 7.7 Tests: cold-start suppression and web-search budget.
- [x] 7.8 Run compile/syntax checks, `pytest tests/test_self_improving_rag_mcp.py` and affected modules, and an MCP smoke query before marking complete.
