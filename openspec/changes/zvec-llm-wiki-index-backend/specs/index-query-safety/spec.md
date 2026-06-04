## ADDED Requirements

### Requirement: Zvec-backed dense wiki index

The system SHALL store LLM wiki dense vectors in a site-scoped zvec collection while preserving JSONL document metadata and BM25/postings lexical artifacts.

#### Scenario: Build stores OpenRouter vectors in zvec

- **WHEN** `build_llm_wiki_index` builds a ready site index
- **THEN** it stores dense document vectors in a zvec collection scoped to that site
- **AND** the stored vector dimension matches the configured OpenRouter embedding dimension
- **AND** the manifest records `embedding_space` as `dense-openrouter`.

#### Scenario: Metadata fields are available from zvec results

- **WHEN** dense retrieval returns zvec documents
- **THEN** each candidate can be converted back to evidence using stored `id`, `corpus`, `source_kind`, `source_id`, `source_ids`, `path`, `title`, `checksum`, and `text`.

#### Scenario: Lexical artifacts remain available

- **WHEN** the dense zvec collection is built
- **THEN** `llm_wiki_documents.jsonl` remains available as canonical chunk metadata
- **AND** `llm_wiki_postings.json` remains available as the BM25/postings sidecar.

### Requirement: Zvec dense retrieval participates in MCP query fusion

The MCP wiki query path SHALL retrieve dense candidates from the site zvec collection and fuse them with BM25 lexical candidates before evidence formatting.

#### Scenario: Query uses zvec dense leg

- **WHEN** `query_mcp_wiki_index` runs with a dense-ready manifest and zvec collection
- **THEN** the vector retrieval leg queries zvec using the OpenRouter query embedding
- **AND** the fused candidates include dense zvec candidates and lexical BM25 candidates where both legs have hits.

#### Scenario: Factual query preserves BM25-first behavior

- **WHEN** a factual query has strong BM25 wiki hits
- **THEN** BM25 remains the leading retrieval strategy
- **AND** zvec dense candidates still participate in fusion and downstream reranking.

#### Scenario: Evidence contract is preserved

- **WHEN** a zvec-backed query returns evidence
- **THEN** evidence rows preserve existing fields including source kind, source id, path, title, snippet, scores, ranking reasons, checksum, parser, tags, and metadata
- **AND** response metadata preserves routing, retrieval, next pages, query expansion, and confidence details.

### Requirement: Zvec readiness is explicit

Index health and MCP readiness surfaces SHALL distinguish lexical/page availability from dense zvec vector readiness.

#### Scenario: Ready dense index reports zvec mode

- **WHEN** `index_info` reads a dense-ready zvec-backed manifest
- **THEN** it reports zvec path, zvec readiness, embedding provider/model/dimensions/space, index version, and available query modes including vector.

#### Scenario: Legacy hash index is not vector-ready

- **WHEN** `index_info` reads a legacy manifest with deterministic hash embeddings, 64-dimensional vectors, missing `embedding_space`, or no zvec collection metadata
- **THEN** it SHALL NOT report vector query readiness
- **AND** it SHALL return an actionable not-ready reason.

#### Scenario: Missing zvec collection is not silent success

- **WHEN** a manifest claims vector mode but the zvec collection cannot be opened
- **THEN** vector queries SHALL fail explicitly with not-ready or `embedding_unavailable` metadata
- **AND** they SHALL NOT return an empty successful result as if no evidence exists.

### Requirement: Production wiki path does not depend on legacy SMU zvec MCP

The production `query_wiki` path SHALL use the shared LLM wiki zvec backend and SHALL NOT depend on the legacy SMU-only zvec MCP server.

#### Scenario: Query wiki uses shared backend

- **WHEN** a client calls `query_wiki` through `mcp_servers/llm_wiki_mcp.py`
- **THEN** dense retrieval is performed by the shared `llm_wiki_index` zvec backend
- **AND** it does not import or call `mcp_servers/smu_zvec_mcp.py`.
