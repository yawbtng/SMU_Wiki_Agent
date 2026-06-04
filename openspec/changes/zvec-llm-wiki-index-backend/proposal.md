## Why

The current university wiki MCP path builds OpenRouter dense embeddings in `llm_wiki_index`, but serves them from `llm_wiki_documents.jsonl` as an ad hoc vector store. In practice, the active SMU index can still look ready while carrying old 64-dimensional hash vectors or missing embedding-space metadata, which makes `query_wiki` fail with `embedding_unavailable` or return poor BM25-only evidence.

The repo already contains zvec support, but that path is SMU-specific and query-embeds through Ollama. It is not the production wiki MCP backend. The production path should use zvec as the site-scoped dense vector store while preserving the current BM25/postings sidecar, evidence formatting, and fail-fast retrieval contract.

## What Changes

- Add a small zvec store adapter for site-scoped LLM wiki collections.
- Persist OpenRouter 1536-dimensional dense vectors to zvec during `build_llm_wiki_index`.
- Keep `llm_wiki_documents.jsonl` as canonical document metadata and `llm_wiki_postings.json` as the lexical BM25/postings sidecar.
- Query zvec for dense candidates inside `query_mcp_wiki_index`, then fuse those candidates with BM25 lexical candidates before reranking/evidence formatting.
- Report zvec readiness, zvec path, query modes, embedding space, provider/model, and vector dimensions through `index_info`.
- Treat old hash-vector, missing-space, missing-zvec, or unavailable OpenRouter states as explicit not-ready/`embedding_unavailable` states.

## Impact

- Affected index code: `src/scrape_planner/wiki/llm_wiki_index.py`.
- New index adapter: `src/scrape_planner/index/zvec_store.py`.
- Affected MCP server: `mcp_servers/llm_wiki_mcp.py` readiness surface only, if needed.
- Affected webapp status: `src/scrape_planner/webapp/embeddings.py`, `src/scrape_planner/webapp/api.py`, if readiness/status fields need surfacing.
- Affected tests: zvec adapter tests, LLM wiki index tests, MCP tests, embedding job/API readiness tests.
- Non-goal: do not promote `mcp_servers/smu_zvec_mcp.py` as the production backend; it remains legacy/compatibility unless separately removed.
