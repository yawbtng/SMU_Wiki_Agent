## 1. OpenSpec

- [ ] 1.1 Validate this change with `openspec validate zvec-llm-wiki-index-backend --strict`.
- [ ] 1.2 Confirm `openspec status --change zvec-llm-wiki-index-backend` reports the change as proposed and complete enough to implement.

## 2. Zvec store adapter

- [ ] 2.1 Add `src/scrape_planner/index/zvec_store.py` with site-scoped collection path, schema creation, replace/upsert, query, and result normalization helpers.
- [ ] 2.2 Add `tests/test_zvec_store.py` using fake zvec modules/collections so adapter behavior is tested without native zvec.
- [ ] 2.3 Verify adapter syntax and tests with `py_compile`, `tests/test_zvec_store.py`, `tests/test_zvec_mcp.py`, and `tests/test_zvec_index.py`.

## 3. Build integration

- [ ] 3.1 Update `build_llm_wiki_index()` to persist OpenRouter dense vectors to zvec and keep JSONL/postings as metadata and lexical sidecars.
- [ ] 3.2 Record zvec path, readiness, vector count, embedding space, provider/model, dimensions, and query modes in manifest/report/status.
- [ ] 3.3 Add tests proving dense vectors are stored through zvec and old hash/missing-space rows are not treated as vector-ready.

## 4. Query integration

- [ ] 4.1 Refactor the dense vector retrieval leg in `llm_wiki_index` to query zvec instead of scanning JSONL vectors.
- [ ] 4.2 Preserve BM25-first factual routing, fusion, evidence formatting, citation/routing boosts, confidence metadata, and explicit `embedding_unavailable` failures.
- [ ] 4.3 Add tests for zvec dense candidate fusion, query embedding failure, missing zvec collection, and source-only search semantics.

## 5. Readiness and runtime proof

- [ ] 5.1 Update `index_info()` and affected MCP/webapp status surfaces to expose honest zvec/vector readiness and query modes.
- [ ] 5.2 Rebuild the real SMU index with `.env` loaded and verify the manifest reports dense OpenRouter 1536-dimensional zvec readiness.
- [ ] 5.3 Query `who is the president?` through the MCP function and confirm the result is either relevant cited evidence or an explicit non-success state that points to content quality rather than embedding storage.

## 6. Final verification

- [ ] 6.1 Run `codegraph sync` and `codegraph status` after source/config/test/doc edits.
- [ ] 6.2 Run targeted Python compile and pytest commands listed in `docs/superpowers/plans/2026-06-04-zvec-llm-wiki-index-backend.md`.
- [ ] 6.3 Run `bash scripts/verify-webapp.sh` if frontend or API readiness output changes.
- [ ] 6.4 Report changed files and leave unrelated pre-existing dirty work untouched.
