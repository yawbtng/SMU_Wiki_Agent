# S02 Research — Index-first raw retrieval

## Summary
- Slice S02 must deliver an **index-first** query path over raw markdown that returns **bounded evidence** and avoids per-query full-corpus scans.
- Current repo has no dedicated retrieval module for raw markdown. Existing retrieval-adjacent logic is either:
  - heuristic topic matching in `src/scrape_planner/wiki_planner.py` (full-text scans over loaded docs), or
  - vector indexing in `scripts/zvec_index_run.py` tied to `cleanup_manifest.json` and wiki outputs.
- Highest-risk gap: there is no existing contract/API proving “index-first and bounded” behavior; this must be introduced with explicit artifact + test evidence.

## Requirements Coverage (active requirements relevant to S02)
- **R001 (supports):** Raw sources as truth. S02 retrieval should index raw markdown paths/URLs directly, not cleanup-manifest-as-truth architecture.
- **R005 (primary):** Retrieval is index-first and bounded. Must be provable in tests (not just implementation intent).
- **R013 (supports):** No hardcoded university taxonomy. Retrieval cannot depend on `DEFAULT_TOPIC_PATTERNS`-style taxonomy assumptions.
- **R014 (supports):** Scales toward large corpora. Requires prebuilt index + bounded candidate set, avoiding O(N files) scans per query.

## Implementation Landscape (what exists and what is missing)

### Existing files/patterns
- `src/scrape_planner/run_persistence.py`
  - Good JSON/JSONL persistence primitives (`_write_json_atomic`, `_append_jsonl`) suitable for writing retrieval artifacts (index manifest, query logs) in inspectable form.
- `src/scrape_planner/wiki_planner.py`
  - `_read_source_files` falls back between `cleanup_manifest.json` and `scrape_manifest.json`; reads all source texts into memory.
  - `suggest_wiki_topics` scores via regex counts over every source text, i.e., scan-oriented and taxonomy-bound.
- `scripts/zvec_index_run.py`
  - Has chunking and embedding/indexing pipeline, but `_load_cleaned_docs` is cleanup/wiki-oriented, not raw-first source-ledger oriented.
  - Useful reference for chunk metadata shape and index manifest writing, but not suitable as S02 primary retrieval path per milestone decisions.
- `README.md`
  - Documents optional Zvec MCP flow; confirms vector path is optional and currently cleanup-run rooted.

### Missing for S02
- A dedicated raw retrieval module/API with:
  - index build step over raw markdown sources,
  - index load/query step,
  - bounded result count + bounded snippet lengths,
  - explicit “stale/missing index” status contract,
  - tests asserting query-time file-read boundedness.

## Recommended Architecture for S02
- Add a new module (suggested): `src/scrape_planner/raw_retrieval.py` with two clear phases:
  1. **Build index (offline/pre-query):** tokenize chunk metadata from raw markdown and write index artifacts.
  2. **Query index (online):** rank candidates from index structures only, then read only top-K chunk payloads if needed.
- Use simple deterministic lexical index first (BM25-like or TF-IDF-lite inverted index) to keep V1 simple and inspectable.
- Persist index in JSON artifacts under run/slice-controlled location (human-readable):
  - `raw_retrieval/index_manifest.json`
  - `raw_retrieval/postings.json` (or sharded postings)
  - `raw_retrieval/chunks.jsonl` (chunk_id, source_id/url/path, byte span or snippet cache)
- Query output contract should include:
  - query string, limits used, index version/hash,
  - evidence list [{source_id, url, path, chunk_id, score, snippet}],
  - truncation flags (`max_results_hit`, `snippet_truncated`).

## Natural Seams for Planner Task Decomposition
1. **Core indexing contract + data model**
   - Define source doc/chunk/index schemas and serialization format.
2. **Indexer implementation**
   - Build chunking/tokenization/inverted map from raw markdown records.
3. **Query engine implementation**
   - Candidate gather/rank/top-K + bounded snippet extraction.
4. **CLI/proof integration**
   - Hook into existing scripts/commands to build and query index during fixture flow.
5. **Tests + verification harness**
   - Unit + integration proving no full scans per query and bounded outputs.

## First Proof (highest-risk unblocker)
- Implement one integration test that:
  - builds an index from N fixture markdown files,
  - monkeypatches file-read calls during query phase,
  - asserts query does **not** read all N files (only index files and maybe top-K snippet files),
  - asserts evidence count/snippet lengths obey configured bounds.
- This directly validates R005 and mitigates scale risk early.

## Verification Strategy
- Unit tests:
  - tokenization/chunking determinism,
  - inverted index correctness for known terms,
  - scoring monotonicity sanity checks,
  - bounds enforcement (results/snippets).
- Integration tests:
  - missing/stale index returns explicit status,
  - query path uses prebuilt index,
  - fixture query returns expected source IDs and citations metadata.
- Suggested commands:
  - `python3 -m pytest -q tests/test_raw_retrieval.py`
  - `python3 -m pytest -q tests/test_raw_retrieval_integration.py`

## Risks / Watch-outs for downstream slices (S03/S04)
- S03/S04 depend on retrieval evidence metadata. Ensure S02 evidence objects already carry stable fields needed later:
  - `source_id`, `source_hash` (if available), `url`, `path`, `chunk_id`, `score`, `snippet`.
- If index schema omits source hash linkage now, S03 stale-tracking may need schema migration.
- Avoid coupling retrieval ranking to any hardcoded domain taxonomy (conflicts with R013).

## Skill Discovery (suggested)
- Core technologies here are Python + local indexing; installed skills already cover optimization/testing if needed:
  - `python-testing-patterns` (for robust retrieval tests)
  - `python-performance-optimization` (for query-time scan avoidance and profiling)
- No additional external skill discovery appears necessary for this slice’s core scope.

## Recommendation
- Deliver S02 as a small, deterministic lexical retrieval subsystem with explicit on-disk index contracts and strict query-time bounds.
- Reuse run-persistence JSON/JSONL patterns, but do **not** reuse cleanup-manifest-oriented Zvec flow as primary path.
- Make “index-first, bounded, no full scan per query” a tested invariant, not a best-effort behavior.
