## ADDED Requirements

### Requirement: Indexes include raw sources and wiki pages
The system SHALL build queryable indexes for both normalized raw source chunks and generated wiki pages.

#### Scenario: Embedding step runs
- **WHEN** the user starts the embed/index step
- **THEN** the system SHALL embed ready raw source chunks and generated wiki pages into separate or distinguishable corpora

#### Scenario: Source changes after indexing
- **WHEN** a raw source or wiki page checksum changes
- **THEN** the embedding step SHALL re-embed only changed documents where possible

### Requirement: Query retrieves candidates before reranking
The system SHALL retrieve a candidate pool from both wiki and raw source indexes before final evidence selection.

#### Scenario: User asks a question
- **WHEN** a query is submitted
- **THEN** the retrieval layer SHALL collect candidate wiki pages and raw source chunks with scores and metadata

### Requirement: Reranker chooses best evidence
The system SHALL rerank retrieved candidates before returning evidence to an answer engine or MCP client.

#### Scenario: Wiki and raw source both match
- **WHEN** both generated wiki pages and raw source chunks are relevant
- **THEN** the reranker SHALL prefer the wiki page for synthesized context and include raw source chunks as supporting evidence

#### Scenario: Wiki has no relevant answer
- **WHEN** wiki candidates are weak or missing
- **THEN** the reranker SHALL allow raw source chunks to become the primary evidence

### Requirement: Reranker output is explainable
The system SHALL return reranker decisions with source kind, path, score, source ID, and reason metadata.

#### Scenario: Query returns ranked evidence
- **WHEN** the reranker returns selected evidence
- **THEN** each selected item SHALL include whether it came from the wiki or raw sources and enough metadata to inspect the original artifact

### Requirement: Reranker implementation is pluggable
The reranker interface SHALL allow local hybrid scoring initially and future local cross-encoder or LLM rerankers.

#### Scenario: Reranker backend changes
- **WHEN** a different reranker backend is configured
- **THEN** query callers SHALL receive the same evidence output schema
