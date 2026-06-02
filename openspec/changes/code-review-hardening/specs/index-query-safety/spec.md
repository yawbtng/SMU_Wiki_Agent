## ADDED Requirements

### Requirement: Embedding degradation is recoverable
Process-global embedding flags SHALL reset when backend recovers.

#### Scenario: Ollama recovery
- **WHEN** a prior query set `_DENSE_EMBEDDING_UNAVAILABLE`
- **AND** a subsequent embed succeeds
- **THEN** globals SHALL reset and dense leg SHALL re-enable for that process

#### Scenario: MCP long-lived server
- **WHEN** MCP subprocess handles multiple queries
- **THEN** degradation SHALL NOT latch permanently after one transient timeout

### Requirement: Embed timeout defaults are operable
Default Ollama embed timeout SHALL match realistic local latency.

#### Scenario: Default timeout
- **WHEN** `OLLAMA_EMBED_TIMEOUT` is unset
- **THEN** default SHALL be at least 30 seconds (aligned with index build path)

### Requirement: Query reads consistent index snapshot
Queries during rebuild SHALL not mix artifact generations.

#### Scenario: Query during build
- **WHEN** `query_llm_wiki_index` runs while `build_llm_wiki_index` is in progress
- **THEN** query SHALL read a consistent snapshot (shared read lock, copy-on-read temp dir, or manifest generation token mismatch → retry)

### Requirement: Post-ingest answer gating
MCP answer flow SHALL not report success without confidence after retry.

#### Scenario: Retry local after ingest
- **WHEN** ingest completes and local query re-runs
- **AND** confidence is still below threshold
- **THEN** `answer_question` SHALL return low-confidence status, not `status: ok`

### Requirement: Web search budget is atomic
Concurrent MCP calls SHALL not exceed per-site budget.

#### Scenario: Parallel answer_question
- **WHEN** two calls race to increment web search budget
- **THEN** at most one SHALL succeed when budget is exhausted (file lock or atomic counter)

## MODIFIED Requirements

### Requirement: Build-time BM25 optional cache
The system SHALL reuse BM25 postings built at index time when a cached index exists and manifest version matches; otherwise it SHALL fall back to per-query indexing.

#### Scenario: Index build completes
- **WHEN** `build_llm_wiki_index` finishes
- **THEN** manifest MAY include serialized BM25 token index for wiki corpus

#### Scenario: Query uses cache
- **WHEN** cached BM25 exists and manifest version matches
- **THEN** query SHALL reuse cache instead of calling `retriever.index()` on every query
