## ADDED Requirements

### Requirement: Single orchestrated answer entrypoint
The MCP SHALL expose an `answer_question` tool that returns the best available answer by composing local hybrid retrieval, a confidence decision, and—only when needed and permitted—web fallback and asynchronous write-back.

#### Scenario: Confident local answer
- **WHEN** `answer_question` is called and local retrieval is assessed as confident
- **THEN** the tool SHALL return the answer with its citations and `provenance="wiki"`
- **AND** it SHALL NOT call web search or trigger ingestion

#### Scenario: Low local confidence escalates
- **WHEN** `answer_question` is called, local retrieval is not confident, the index is ready, and web search is available
- **THEN** the tool SHALL obtain web candidates, return a provisional answer flagged `provenance="web_provisional"`, and report the ingestion job it queued

#### Scenario: No answer anywhere
- **WHEN** local retrieval is not confident and web search is unavailable or returns nothing usable
- **THEN** the tool SHALL return a no-confident-answer result with the confidence reasons and the local evidence it found
- **AND** it SHALL NOT fabricate an answer

### Requirement: Mode-aware calibrated confidence
The confidence assessment SHALL produce a decision that is valid regardless of whether the model reranker is active, because the underlying score scale differs between reranker-on and reranker-off.

#### Scenario: Decision is independent of reranker availability
- **WHEN** the same query result is assessed with the reranker on and with it off
- **THEN** the confidence decision SHALL gate on a normalized or mode-appropriate score rather than a single raw threshold that means different things in each mode

#### Scenario: Scoring mode is recorded
- **WHEN** a confidence decision is produced
- **THEN** the decision SHALL record which scoring mode (reranked or fused) produced it, along with the thresholds and reasons

#### Scenario: Citation excludes wiki self-reference
- **WHEN** the only evidence is a wiki page citing itself by path
- **THEN** the citation check SHALL NOT be satisfied by that wiki path alone

### Requirement: Cold-start protection
The orchestrator SHALL NOT trigger web fallback when the site index is not ready, and SHALL bound web-search frequency per site.

#### Scenario: Empty or missing index
- **WHEN** `answer_question` runs for a site whose index is missing or below the minimum document count
- **THEN** the tool SHALL return an index-not-ready status and SHALL NOT issue a web search

#### Scenario: Web-search budget enforced
- **WHEN** web fallbacks for a site exceed the configured per-site rate or budget
- **THEN** further fallbacks SHALL be suppressed until the window resets

### Requirement: Indexes remain query-only from MCP
The MCP SHALL NOT synchronously build, refresh, or mutate index artifacts inside the request/response path.

#### Scenario: Orchestrator defers mutation
- **WHEN** `answer_question` decides web content should be written back
- **THEN** the index mutation SHALL be performed by the ingestion pipeline detached from the MCP request
- **AND** the MCP response SHALL return without waiting for the rebuild to finish
