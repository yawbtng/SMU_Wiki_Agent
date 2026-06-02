# uops MCP Answer Retrieval — Workflow Analysis

This document traces the end-to-end path from a Cursor agent calling the **uops** (llm-wiki) MCP server through local retrieval, confidence gating, and answer synthesis. It uses the real failure case from **“Who is the director of Computer Science (CS)?”** as the worked example.

**Date:** 2026-06-02  
**Site:** `www.smu.edu` (MCP `LLM_WIKI_SITE_ROOT` → sibling worktree `ultra-fast-rag-webapp/data/sites/www.smu.edu`)  
**Index version:** `llm-wiki-hybrid-v2`  
**Embedding state at time of query:** `embedding_degraded: true`, `embedding_space: hash-fallback`

---

## 1. System overview

The uops MCP server is implemented in `mcp_servers/llm_wiki_mcp.py` and delegates to:

| MCP tool | Python entrypoint | Purpose |
|----------|-------------------|---------|
| `answer_question` | `self_improving.answer_question` | Orchestrated answer: local retrieval → confidence → optional web fallback |
| `query_wiki` | `query_mcp_wiki_index` | Hybrid wiki-first retrieval; returns evidence only |
| `search_sources` | `search_source_index` | Raw-source corpus only; returns evidence only |
| `get_wiki_page` | Direct filesystem read | Exact wiki markdown by path/id/title |
| `ingest_url` | `self_improving.ingest_url` | Queue manual URL ingest |
| `index_info` | `index_info` | Index health and counts |

Cursor agents typically call **`answer_question`** first. When that returns no answer, they may fall back to **`query_wiki`** and **`search_sources`** — adding round-trips and latency.

---

## 2. End-to-end workflow

### 2.1 Agent → MCP

```
Cursor Agent
    │  MCP JSON-RPC: tools/call
    ▼
mcp_servers/llm_wiki_mcp.py  (FastMCP / stdio)
    │
    ├── answer_question(question, max_results=5)
    ├── query_wiki(question, max_results=5)
    └── search_sources(query, max_results=5)
```

### 2.2 `answer_question` internal pipeline

```
answer_question(site_root, question)
│
├─ 1. prepare_retrieval_query(question)          [query_intent.py]
│      • Detect person/leadership queries ("who", "director", "chair")
│      • Expand aliases (e.g. add "lyle school of engineering" for SMU leadership)
│
├─ 2. query_mcp_wiki_index(effective_query)    [llm_wiki_index.py]
│      • Load llm_wiki_documents.jsonl + postings + manifest (every call)
│      • Classify query type: factual vs reasoning ("who" → factual)
│      • mcp_auto strategy:
│          - Wiki BM25 (bm25s) + vector search
│          - Fuse candidates (max 50)
│          - rerank_candidates: lexical + vector + keyword + wiki boost (+1.2)
│          - Optional OpenRouter rerank (if OPENROUTER_API_KEY set)
│      • Return top N evidence snippets + metadata
│
├─ 3. assess_confidence(result, question)        [confidence.py]
│      • Person lookup: try extract_leadership_from_evidence() first
│      • Else: require top_score ≥ 0.4, top-two gap ≥ 0.05, citation present
│
├─ 4a. IF confident → _wiki_answer_response()
│         • _answer_from_evidence() or leadership match
│         • Return { status: "ok", provenance: "wiki", answer, citations }
│
└─ 4b. IF NOT confident → fallback chain
       • record_confidence_gap() → self_improving_gaps.jsonl
       • LoopGuard / pending ingest job check
       • Index readiness check
       • Web search budget check
       • _leadership_fallback() — second chance at regex extraction
       • web_search() — provisional answer + ingest queue
       • Else → empty answer + evidence blob + status
```

### 2.3 `query_wiki` vs `search_sources`

Both share `rerank_candidates`, but differ in **which corpus is retrieved first**:

| Tool | Retrieval scope | Wiki boost | Typical hits for person queries |
|------|-----------------|------------|--------------------------------|
| `query_wiki` | Wiki BM25 + vector fusion (wiki-first) | Yes (+1.2 source_priority) | Curated semantic wiki pages |
| `search_sources` | Raw corpus BM25 only | No wiki synthesis boost | Scraped faculty/program pages |

This split is the main reason the CS director question succeeded only on the third tool call.

### 2.4 Index artifacts (loaded per query)

Under `{site_root}/indexes/`:

- `llm_wiki_documents.jsonl` — all wiki + raw document chunks
- `llm_wiki_postings.json` — inverted index for token lookup
- `llm_wiki_manifest.json` — version, embedding space, degraded flag

No in-process cache today: each MCP call re-reads and parses these files.

---

## 3. Worked example: “Who is the director of Computer Science (CS)?”

### 3.1 What the correct answer is

From SMU Lyle CS faculty pages (raw sources):

- **Jia Zhang, Ph.D.** — Robert H. Dedman Jr. **Chairperson** of the Department of Computer Science
- **Theodore Manikas, Ph.D.** — Associate Chair of Computer Science

SMU uses **Chairperson**, not “Director”, for the department head. The question’s wording (“director”) is reasonable but does not match the official title on the page.

**Source URL:** `https://www.smu.edu/lyle/departments/cs/people/faculty`

### 3.2 Tool call 1 — `answer_question`

**Input:**

```json
{ "question": "Who is the director of Computer Science (CS)?", "max_results": 5 }
```

**Result:**

| Field | Value |
|-------|-------|
| `status` | `web_search_unavailable` |
| `provenance` | `none` |
| `answer` | *(empty)* |
| `metadata.confidence.decision` | `not_confident` |
| `metadata.confidence.top_two_gap` | `0.006082` (below 0.05 threshold) |
| `metadata.embedding_degraded` | `true` |
| `metadata.embedding_space` | `hash-fallback` |

**Top evidence returned (wrong domain):**

1. SMU Admissions Guide
2. Cox School of Business
3. Dedman School of Law
4. Cox Admissions Guide
5. Dedman College Admissions Guide

None of these contain CS department leadership. Wiki-first retrieval ranked generic admissions/school overview pages because BM25 matched broad tokens (`computer` in routing profile, school terms) and wiki synthesis boost (+25 BM25, +1.2 rerank) favored curated wiki pages over raw faculty listings.

**Why confidence failed:**

- `top_score_ok` — passed (normalized top score = 1.0)
- `citation_present` — passed (wiki pages cite source_ids)
- `missing_top_two_gap_ok` — **failed** (gap 0.006 ≪ 0.05; admissions pages tied)
- Leadership extraction — **failed** (regex does not match “Chairperson of”; see §4.2)
- Web fallback — **unavailable**

### 3.3 Tool call 2 — `query_wiki`

**Input:**

```json
{ "question": "director of computer science department SMU", "max_results": 10 }
```

**Result:** Same class of wiki pages (admissions, Cox, Dedman). No synthesized answer. Confirms the retrieval routing problem is in the index/query path, not only in `answer_question`’s synthesis layer.

### 3.4 Tool call 3 — `search_sources` (success)

**Input:**

```json
{ "query": "computer science director department chair", "max_results": 10 }
```

**Result:** Raw corpus hits with the correct information in snippets:

| Rank | Source | Snippet (abbrev.) |
|------|--------|-------------------|
| 1 | `ms-datacenter-systems-eng` | Jia Zhang, Ph.D. … **Chairperson of the Department of Computer Science** |
| 2 | `ms-cybersecurity` | CS faculty listing |
| 3 | `ms-software-engineering` | Jia Zhang … Chairperson … Theodore Manikas … Associate Chair |
| 5 | `people` (`/lyle/departments/cs/people`) | Full faculty carousel text |
| 6 | `faculty` (`/lyle/departments/cs/people/faculty`) | Same |

**Agent had to manually interpret snippets** — `search_sources` returns evidence, not a composed answer.

### 3.5 Call count and cost

| Metric | Actual | Ideal |
|--------|--------|-------|
| MCP tool calls | 3 | 1 |
| Agent reasoning steps | Read ~40KB JSON × 2, then search again | Single cited answer |
| Time to answer | Multiple agent turns | Sub-second local path |
| Answer provenance | Agent synthesis from raw snippets | `answer_question` with `provenance: wiki` |

---

## 4. Where the workflow lacked

### 4.1 Retrieval routing (wiki-first bias)

**Location:** `llm_wiki_index._select_retrieval_candidates()` with `retrieval_strategy="mcp_auto"`

For factual/person queries, the pipeline fuses wiki BM25 ahead of raw sources and applies:

- Semantic wiki BM25 boost (+25.0 base, up to +60 for school slug match) in `_apply_semantic_wiki_bm25_boost`
- Wiki `source_priority` +1.2 in `rerank_candidates`
- Wiki wins ties in sort order

**Gap:** Leadership/faculty facts live primarily in **raw** scraped pages (`raw_sources/web/…`, URLs under `/lyle/departments/cs/people`). Wiki synthesis has not curated a CS department leadership page, so wiki-first routing systematically misses the answer.

### 4.2 Leadership regex too narrow

**Location:** `leadership.py` — `extract_leadership_from_evidence()`

Patterns match:

- `Director of`, `Program Director of`, `Chair of`, `Dean of`, `Head of`

They do **not** match:

- `Chairperson of` (SMU CS uses this title)
- Endowed chair lines like `Robert H. DEDMAN, JR. Chairperson of the Department of Computer Science`
- Messy carousel scrape layout: `Jia Zhang, Ph.D. Robert H. DEDMAN, JR. Chairperson of…`

**Gap:** Even when raw faculty text appears in evidence (or would appear with better routing), `assess_confidence` and `_leadership_fallback` cannot extract an answer.

### 4.3 No curated wiki page for CS leadership

**Location:** Wiki build (`llm_wiki_builder`) + navigation manifest

`get_wiki_page("wiki/pages/schools/dedman-college/computer-science.md")` → `page_not_found`.

CS content exists as thin program pages (`wiki/pages/programs/people-web-*.md`) and raw sources, not as a student-actionable department guide with canonical leadership facts in frontmatter.

**Gap:** Wiki-first retrieval has nothing authoritative to rank for “director/chair of CS”.

### 4.4 Confidence gate misfire on tied wiki pages

**Location:** `confidence.py` — gap threshold 0.05 in fused mode

The query returned five wiki pages with nearly identical combined scores (all ~27.x). Normalized top-two gap was 0.006. The gate rejected a confident decision even though **all top hits were wrong**.

**Gap:** Gap check assumes the top cluster is relevant; for person lookups with wrong wiki ties, it blocks without triggering raw fallback.

### 4.5 Web fallback unavailable

**Location:** `self_improving.answer_question` → `web_search()`

Status `web_search_unavailable` ended the self-improving path. No provisional web answer, no ingest job queued.

**Gap:** When local index is stale or mis-routed, there is no external safety net.

### 4.6 Tool API forces agent multi-hop

**Location:** `mcp_servers/llm_wiki_mcp.py` tool surface

`answer_question` and `search_sources` are separate tools with different corpus behavior. The agent must know to call `search_sources` when `answer_question` returns empty — undocumented in the tool description.

**Gap:** Operational knowledge required; not a single-shot API.

### 4.7 Index / embedding degradation

**Observed metadata:**

```json
{
  "embedding_degraded": true,
  "embedding_space": "hash-fallback",
  "vector_leg_enabled": true
}
```

Vector search runs on hash-fallback embeddings, adding compute without reliable semantic discrimination. Person-name queries especially need dense embeddings or lexical/raw paths.

### 4.8 Per-query index reload

Every MCP call reads full `llm_wiki_documents.jsonl` and rebuilds bm25s wiki scores in-process. No warm cache in the MCP server process.

**Gap:** Latency scales with index size on every question.

### 4.9 Site root split

MCP pointed at `ultra-fast-rag-webapp/data/sites/www.smu.edu` while some raw sources also exist under the main repo `data/sites/www.smu.edu`. `start.sh` resolves across worktrees, but MCP config may not always track the populated root.

**Gap:** Index and sources can diverge depending on which worktree was last built.

---

## 5. Failure diagram (this example)

```
"Who is the director of CS?"
         │
         ▼
  answer_question
         │
         ├─ query expansion: person_lookup=true, academic_interest=computer
         │
         ├─ wiki-first hybrid retrieval
         │     └─► Top 5: admissions / Cox / Dedman wiki pages  ✗
         │
         ├─ leadership regex on evidence
         │     └─► No match ("Chairperson" not in pattern)       ✗
         │
         ├─ confidence: gap 0.006 < 0.05                         ✗
         │
         ├─ leadership_fallback (retry regex)                    ✗
         │
         ├─ web_search                                         ✗ unavailable
         │
         └─► Empty answer + 40KB evidence blob

Agent fallback:
  query_wiki          → same wrong wiki pages                      ✗
  search_sources      → raw faculty pages with Jia Zhang           ✓ (evidence only)
  Agent synthesizes answer manually
```

---

## 6. Scope of improvement (prioritized)

### P0 — One-call answers for person/leadership queries

1. **Extend leadership regex** — Add `Chairperson of`, `Department Chair`, endowed-chair patterns; handle carousel scrape layout.
2. **Person-lookup retrieval branch** — For `is_person_lookup_query()`, search raw corpus first or run parallel raw+wiki with raw tie-break inside `answer_question` (do not require a separate `search_sources` call).
3. **Intent-aware confidence** — Skip gap check when leadership regex matches any candidate; or auto-fallback to raw search when person lookup + low gap + no leadership match.

### P1 — Index and content quality

4. **Wiki leadership pages** — Build department pages with `canonical_facts` / leadership in frontmatter from faculty raw sources.
5. **Rebuild embeddings** — Exit `hash-fallback`; use dense embeddings at index build time.
6. **Single canonical site root** — Align MCP `LLM_WIKI_SITE_ROOT` with `start.sh` resolution.

### P2 — Latency

7. **In-process index cache** — Mtime-keyed cache for documents/postings/manifest in MCP server.
8. **Persisted bm25s index** — Stop rebuilding BM25 on every query.
9. **Compact MCP responses** — Default slim evidence payloads; full metadata opt-in.

### P3 — Resilience

10. **Configure web search fallback** — Enable provider + budget for gaps recorded in `self_improving_gaps.jsonl`.
11. **Unify tool contract** — Document that `answer_question` should subsume raw fallback; deprecate agent reliance on `search_sources` for factual person queries.
12. **Optional OpenRouter rerank** — Disambiguate tied wiki pages when API key present.

---

## 7. Target fast path

```
answer_question("Who is the director of CS?")
  → intent: person_lookup + department=computer-science + school=lyle
  → retrieval: raw faculty pages rank first
  → extract: "Jia Zhang … Chairperson of the Department of Computer Science"
  → confidence: leadership_entity_match
  → answer: "Jia Zhang, Ph.D. is Chairperson of the Department of Computer Science …"
  → citations: [smu.edu/lyle/departments/cs/people/faculty]
  → 1 MCP call, provenance: wiki
```

---

## 8. Key source files

| File | Role |
|------|------|
| `mcp_servers/llm_wiki_mcp.py` | MCP tool definitions |
| `src/scrape_planner/wiki/self_improving.py` | `answer_question` orchestration |
| `src/scrape_planner/wiki/llm_wiki_index.py` | Hybrid retrieval, reranking, `search_source_index` |
| `src/scrape_planner/wiki/query_intent.py` | Query expansion, person lookup detection |
| `src/scrape_planner/wiki/confidence.py` | Confidence gating |
| `src/scrape_planner/wiki/leadership.py` | Leadership regex extraction |
| `docs/cursor-mcp-setup.md` | MCP install and smoke test |

---

## 9. Related operational notes

- Student wiki content policy in `AGENTS.md` demotes staff bios unless student-support; department chairs may be borderline — leadership pages should be explicitly allowlisted for Lyle/department “who is” queries.
- Gap events are logged to `{site_root}/indexes/self_improving_gaps.jsonl` with `recommended_action: re_discovery_and_rebuild` — useful for batch wiki refresh prioritization.
- `./scripts/validate_llm_wiki_stepper.py` includes MCP stdio probe for regression testing answer paths.
