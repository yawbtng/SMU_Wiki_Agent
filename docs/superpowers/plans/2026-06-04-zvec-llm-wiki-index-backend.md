# Zvec LLM Wiki Index Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make zvec the dense vector storage and query backend for `llm_wiki_index`, while preserving the existing BM25/postings lexical sidecar and MCP evidence contract.

**Architecture:** `build_llm_wiki_index()` remains the single wiki/raw index build entrypoint, but it must persist OpenRouter 1536-dimensional vectors into a site-scoped zvec collection instead of treating JSONL as the vector store. `query_wiki`/`query_mcp_wiki_index()` must use zvec dense retrieval plus BM25 lexical retrieval, then keep the existing evidence formatting, citation/routing annotations, confidence metadata, and explicit `embedding_unavailable` failure contract.

**Tech Stack:** Python 3.14, FastAPI MCP server, OpenRouter embeddings via `src/scrape_planner/index/embedding_client.py`, zvec from `requirements-mcp.txt`, BM25/postings in `src/scrape_planner/wiki/llm_wiki_index.py`, pytest, `py_compile`, CodeGraph sync/status.

---

## Trust Boundary

- Trusted workspace: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`
- Do not inspect or trust any other directory, including `/Users/abhsheno` and sibling worktrees.
- The current worktree has unrelated dirty files. Before editing any file, run `git status --short` and inspect diffs for the exact files you will touch. Do not revert or overwrite unrelated work.

## Required End State

- `build_llm_wiki_index()` writes the canonical document metadata and lexical postings under `data/sites/<site_id>/indexes/` as today, but dense vectors are stored in a zvec collection.
- The zvec collection is site-scoped, for example under `indexes/zvec_llm_wiki` or another deterministic path recorded in `llm_wiki_manifest.json`.
- Dense vectors are OpenRouter vectors with `embedding_space: "dense-openrouter"` and `vector_dimensions: 1536` by default.
- Stored zvec document fields include at least: `id`, `corpus`, `source_kind`, `source_id`, `source_ids`, `path`, `title`, `checksum`, and `text`.
- `query_mcp_wiki_index()` uses zvec dense retrieval plus BM25 fusion. It must not use the older `mcp_servers/smu_zvec_mcp.py` Ollama-specific path as the new backend.
- `search_source_index()` either uses the same zvec adapter for raw dense retrieval or remains lexical-only by explicit design, but must not claim vector readiness when zvec/dense OpenRouter is unavailable.
- `index_info()` reports zvec readiness, zvec path, query modes, embedding space, and vector dimensions. Old/hash/missing-space manifests must not look production-ready.
- The existing fail-fast behavior remains: if OpenRouter query embeddings or the zvec collection are unavailable for vector mode, return `embedding_unavailable` with actionable metadata instead of silently serving degraded vectors.

## OpenSpec Gate

### Task 1: Create And Validate OpenSpec Change

**Files:**
- Create: `openspec/changes/zvec-llm-wiki-index-backend/proposal.md`
- Create: `openspec/changes/zvec-llm-wiki-index-backend/design.md`
- Create: `openspec/changes/zvec-llm-wiki-index-backend/tasks.md`
- Create: `openspec/changes/zvec-llm-wiki-index-backend/specs/index-query-safety/spec.md`
- Create or update only if OpenSpec requires it: `.openspec.yaml` under the change folder

- [ ] **Step 1: Scaffold or create the OpenSpec change**

Run:

```bash
openspec new change zvec-llm-wiki-index-backend
```

If `openspec new change` is unavailable, create the files manually following the existing `openspec/changes/*` structure.

- [ ] **Step 2: Specify the behavioral contract**

The spec must include scenarios for:

- Building an index stores OpenRouter dense vectors in a site-scoped zvec collection.
- The manifest exposes zvec path, zvec readiness, embedding provider/model/dimensions/space, and query modes.
- `query_wiki` retrieves via zvec dense search plus BM25 lexical fusion.
- Missing zvec collection, stale hash manifests, missing OpenRouter key, or query embedding failure return explicit `embedding_unavailable`/not-ready metadata.
- Legacy SMU-only Ollama zvec MCP does not become the production backend.

- [ ] **Step 3: Validate OpenSpec**

Run:

```bash
openspec validate zvec-llm-wiki-index-backend --strict
openspec status --change zvec-llm-wiki-index-backend
```

Expected: strict validation passes and the change is complete enough to implement.

## Implementation Tasks

### Task 2: Add A Site-Scoped Zvec Store Adapter

**Files:**
- Create or modify: `src/scrape_planner/index/zvec_store.py`
- Modify as needed: `src/scrape_planner/index/__init__.py`
- Test: `tests/test_zvec_store.py`

- [ ] **Step 1: Write failing adapter tests**

Use a fake zvec module/collection so unit tests do not require native zvec. Cover:

- deterministic site-scoped collection path creation
- schema fields and embedding vector dimension
- upsert/replace behavior for document rows
- query result formatting back to indexed document rows with scores
- graceful unavailable result/error when zvec import/open fails

Run:

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_zvec_store.py -q
```

Expected: tests fail before implementation.

- [ ] **Step 2: Implement the adapter**

Implement a small boundary API, not zvec calls scattered through `llm_wiki_index.py`. Suggested functions/classes:

- `zvec_collection_path(site_root: Path) -> Path`
- `build_zvec_schema(zvec, *, dimensions: int) -> Any`
- `replace_zvec_documents(site_root: Path, rows: list[dict[str, Any]], *, dimensions: int, zvec_module: Any | None = None) -> dict[str, Any]`
- `query_zvec_documents(site_root: Path, vector: list[float], *, top_k: int, zvec_module: Any | None = None) -> dict[str, Any]`

The adapter must store the required metadata fields and return enough data for rerank/evidence formatting without rereading unrelated files.

- [ ] **Step 3: Verify adapter**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m py_compile src/scrape_planner/index/zvec_store.py tests/test_zvec_store.py
PYTHONPATH=. .venv/bin/pytest tests/test_zvec_store.py tests/test_zvec_mcp.py tests/test_zvec_index.py -q
```

Expected: all pass.

### Task 3: Make `build_llm_wiki_index()` Persist Dense Vectors In Zvec

**Files:**
- Modify: `src/scrape_planner/wiki/llm_wiki_index.py`
- Test: `tests/test_llm_wiki_index.py`

- [ ] **Step 1: Write failing index-build tests**

Add tests using fake zvec injection or monkeypatching around the new adapter. Cover:

- OpenRouter dense rows are written to zvec and JSONL rows do not need to act as the vector store.
- Manifest includes `embedding_space: "dense-openrouter"`, `vector_dimensions: 1536`, `zvec.path`, `zvec.ready`, and query modes.
- Reusing unchanged document metadata does not silently preserve old hash/vector-space rows.
- A zvec write failure makes the build fail explicitly or marks the index not vector-query-ready; do not report production-ready vector mode.

Run a narrow failing test command such as:

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_llm_wiki_index.py::test_build_llm_wiki_index_writes_dense_vectors_to_zvec -q
```

Expected: fails before implementation.

- [ ] **Step 2: Implement build integration**

Inside `build_llm_wiki_index()` / `_build_llm_wiki_index_locked()`:

- Keep writing `llm_wiki_documents.jsonl` as canonical chunk metadata and `llm_wiki_postings.json` as the lexical sidecar.
- Generate/reuse OpenRouter dense embeddings through the existing embedding client.
- Persist dense vector rows through `zvec_store.replace_zvec_documents()`.
- Record zvec metadata in the manifest/report/status.
- Treat old `deterministic-hash-embedding`, 64-dimensional vectors, missing `embedding_space`, or failed zvec writes as not dense-ready.

- [ ] **Step 3: Verify build integration**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m py_compile src/scrape_planner/wiki/llm_wiki_index.py tests/test_llm_wiki_index.py
PYTHONPATH=. .venv/bin/pytest tests/test_llm_wiki_index.py -q
```

Expected: all pass.

### Task 4: Query With Zvec Dense Retrieval Plus BM25 Fusion

**Files:**
- Modify: `src/scrape_planner/wiki/llm_wiki_index.py`
- Test: `tests/test_llm_wiki_index.py`
- Test: `tests/test_llm_wiki_mcp.py`
- Test: `tests/test_self_improving_rag_mcp.py`

- [ ] **Step 1: Write failing query tests**

Cover:

- `query_mcp_wiki_index()` asks zvec for dense candidates and fuses them with `wiki_bm25`.
- Factual questions still lead with BM25 where appropriate, but dense zvec candidates participate in ranking.
- Query embedding failure returns `status: embedding_unavailable`.
- Missing/unopenable zvec collection returns `status: embedding_unavailable` or not-ready metadata, not an empty successful result.
- `search_source_index()` reports source-only semantics correctly under the new backend.

Run narrow failing tests first.

- [ ] **Step 2: Implement query integration**

Refactor the current vector retrieval path so `_vector_retrieval()` uses the zvec adapter rather than scanning vectors from JSONL rows. Preserve:

- `rerank_candidates()` output fields
- `ranking_reasons`
- BM25 annotations
- citation/routing boosts
- confidence metadata
- explicit fail-fast behavior

Avoid importing or depending on `mcp_servers/smu_zvec_mcp.py` from production wiki code.

- [ ] **Step 3: Verify query integration**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m py_compile src/scrape_planner/wiki/llm_wiki_index.py mcp_servers/llm_wiki_mcp.py tests/test_llm_wiki_index.py tests/test_llm_wiki_mcp.py tests/test_self_improving_rag_mcp.py
PYTHONPATH=. .venv/bin/pytest tests/test_llm_wiki_index.py tests/test_llm_wiki_mcp.py tests/test_self_improving_rag_mcp.py -q
```

Expected: all pass.

### Task 5: Expose Honest Readiness In MCP And UI API

**Files:**
- Modify: `src/scrape_planner/wiki/llm_wiki_index.py`
- Modify as needed: `mcp_servers/llm_wiki_mcp.py`
- Modify as needed: `src/scrape_planner/webapp/embeddings.py`
- Modify as needed: `src/scrape_planner/webapp/api.py`
- Tests: `tests/test_llm_wiki_mcp.py`, `tests/test_webapp_api.py`, `tests/test_embedding_job_api.py`

- [ ] **Step 1: Add failing readiness tests**

Cover:

- `index_info()` exposes `query_modes_available` including lexical/page lookup and vector only when zvec/dense readiness is true.
- Old v1/hash/missing-space manifests are not reported as vector-ready.
- Embedding job status does not crash on missing/invalid report paths and surfaces the last zvec/build error.

- [ ] **Step 2: Implement readiness fields and validation**

Expose fields useful to agents and operators:

- `query_modes_available`
- `zvec_ready`
- `zvec_path`
- `embedding_space`
- `embedding_dimensions`
- `embedding_provider`
- `embedding_model`
- `index_version`
- actionable error/message on stale hash/legacy manifests

- [ ] **Step 3: Verify readiness**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m py_compile src/scrape_planner/wiki/llm_wiki_index.py mcp_servers/llm_wiki_mcp.py src/scrape_planner/webapp/embeddings.py src/scrape_planner/webapp/api.py
PYTHONPATH=. .venv/bin/pytest tests/test_llm_wiki_mcp.py tests/test_webapp_api.py tests/test_embedding_job_api.py -q
```

Expected: all pass.

## Runtime Verification

### Task 6: Prove The Real SMU Path Works

**Files/Data:**
- Runtime data: `data/sites/www.smu.edu/`
- Do not modify or delete data except by running the intended index rebuild path.

- [ ] **Step 1: Load environment explicitly for runtime checks**

Use the repo-supported startup path or explicitly source `.env` for one-off commands. Do not print secret values.

- [ ] **Step 2: Rebuild SMU embeddings/index**

Run the repo-supported rebuild path. If using the CLI directly:

```bash
set -a; . ./.env; set +a; PYTHONPATH=. .venv/bin/python -m src.scrape_planner.wiki.llm_wiki_index --site-root data/sites/www.smu.edu
```

Expected: manifest reports dense OpenRouter, 1536 dimensions, zvec ready, and no hash fallback.

- [ ] **Step 3: Query through the MCP function**

Run:

```bash
set -a; . ./.env; set +a; PYTHONPATH=. .venv/bin/python -c 'import json; from pathlib import Path; import mcp_servers.llm_wiki_mcp as s; s.SITE_ROOT=Path("data/sites/www.smu.edu").resolve(); print(json.dumps(s.query_wiki("who is the president?", max_results=3), indent=2)[:6000])'
```

Expected: `ok: true`, vector/zvec metadata present, and evidence includes the relevant president page or an explicit non-success status that points to the remaining data/content issue rather than embedding storage.

- [ ] **Step 4: Check running app/MCP logs if the running service is affected**

If the webapp or MCP service is running, use the app's status/log path or tmux capture to confirm no new exceptions after the rebuild/query.

## Final Verification

- [ ] Run CodeGraph sync/status after source/config/test/doc edits:

```bash
codegraph sync
codegraph status
```

If the CLI is unavailable, use the configured CodeGraph MCP path or report the exact blocker.

- [ ] Run all targeted checks:

```bash
PYTHONPATH=. .venv/bin/python -m py_compile src/scrape_planner/index/zvec_store.py src/scrape_planner/wiki/llm_wiki_index.py mcp_servers/llm_wiki_mcp.py
PYTHONPATH=. .venv/bin/pytest tests/test_zvec_store.py tests/test_zvec_index.py tests/test_zvec_mcp.py tests/test_llm_wiki_index.py tests/test_llm_wiki_mcp.py tests/test_self_improving_rag_mcp.py tests/test_embedding_job_api.py -q
```

- [ ] If frontend/API readiness fields changed, also run the repo webapp gate:

```bash
bash scripts/verify-webapp.sh
```

- [ ] Run `git status --short` and report only the files changed for this plan plus any unrelated pre-existing dirty work left untouched.
