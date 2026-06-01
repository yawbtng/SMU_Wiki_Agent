## MODIFIED Requirements

### Requirement: Indexes include raw sources and wiki pages
The system SHALL build queryable indexes for both normalized raw source chunks and generated wiki pages, embedding documents with a real dense embedding model so retrieval combines BM25 with true semantic vectors.

#### Scenario: Embedding step runs with a real model
- **WHEN** the user starts the embed/index step
- **THEN** the system SHALL embed ready raw source chunks and generated wiki pages into distinguishable corpora using the configured dense embedding provider

#### Scenario: Source changes after indexing
- **WHEN** a raw source or wiki page checksum changes
- **THEN** the embedding step SHALL re-embed only changed documents where possible

### Requirement: Hybrid retrieval fuses lexical and semantic candidates
The system SHALL retrieve candidates from both a BM25 leg and a dense-vector leg and fuse them before optional model reranking.

#### Scenario: Both legs contribute candidates
- **WHEN** a query is retrieved under the auto or hybrid strategy
- **THEN** candidates from both the BM25 leg and the dense-vector leg SHALL be considered in the fused ranking

## ADDED Requirements

### Requirement: Embedding-space integrity
The index SHALL never silently compare vectors from different embedding spaces, and degraded builds SHALL not permanently poison the vector leg.

#### Scenario: Per-row embedding space recorded
- **WHEN** a document is embedded
- **THEN** the stored row SHALL record the embedding space actually used (real dense vs hash fallback)
- **AND** incremental reuse SHALL key on that recorded space and on the index version, not on a constant provider string

#### Scenario: Degraded build is contained
- **WHEN** a build falls back to the hash embedding for any document
- **THEN** the index SHALL either disable the vector leg for that index or force a full re-embed once the dense backend recovers
- **AND** the manifest SHALL record the degraded state

#### Scenario: Cross-space comparison refused
- **WHEN** a query vector and a stored document vector are from different embedding spaces
- **THEN** the similarity computation SHALL NOT treat them as comparable

#### Scenario: Version bump forces rebuild
- **WHEN** the stored index version differs from the current `INDEX_VERSION`
- **THEN** the build SHALL force a full rebuild rather than reusing prior rows

### Requirement: Query responses expose confidence metadata
Query responses used by the MCP SHALL include the confidence decision and its scoring mode so callers can decide whether to escalate.

#### Scenario: Confidence present in metadata
- **WHEN** a wiki query returns evidence
- **THEN** the response metadata SHALL include the confidence decision, its reasons, and the scoring mode that produced it
