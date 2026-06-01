## ADDED Requirements

### Requirement: Provider-abstracted web search with explicit precedence
The system SHALL provide a `web_search` capability behind a swappable provider interface, selecting the concrete provider by explicit configuration.

#### Scenario: Provider selection precedence
- **WHEN** `RAG_WEB_SEARCH_PROVIDER` is set
- **THEN** that provider SHALL be used; otherwise the system SHALL fall back to Brave when its key is present, then Tavily when its key is present

#### Scenario: Search returns ranked candidates
- **WHEN** `web_search` is invoked with a query and a provider is configured
- **THEN** it SHALL return ranked results each containing at least a title, URL, and snippet

#### Scenario: Provider is mockable
- **WHEN** tests run without network access
- **THEN** a mock provider SHALL satisfy the same interface and return deterministic results

### Requirement: Web search is invoked only on low confidence and when permitted
The system SHALL invoke web search only when local retrieval is not confident, the index is ready, and the per-site web budget is not exhausted.

#### Scenario: Confident answer skips web search
- **WHEN** local confidence is sufficient
- **THEN** web search SHALL NOT be called

#### Scenario: Missing provider degrades cleanly
- **WHEN** web search is needed but no provider/API key is configured
- **THEN** the system SHALL return a `web_search_unavailable` status instead of raising

### Requirement: Web search does not write to disk
The `web_search` capability SHALL be query-only and SHALL NOT persist results or mutate indexes itself.

#### Scenario: Search has no side effects
- **WHEN** `web_search` returns candidates
- **THEN** any persistence or ingestion SHALL be performed only by the self-improving ingest capability
