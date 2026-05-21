## ADDED Requirements

### Requirement: Workflow exposes ordered source-to-query steps
The system SHALL expose a user-visible stepper that guides the user through workspace setup, source collection, raw source normalization, LLM Wiki generation, embedding/reranking, and MCP query readiness.

#### Scenario: New workspace follows the stepper order
- **WHEN** a user creates or opens a workspace
- **THEN** the workflow SHALL show the ordered steps `Workspace`, `Sources`, `Raw Data Sources`, `LLM Wiki`, `Embed + Rerank`, and `MCP Query`

#### Scenario: Stepper blocks unavailable downstream actions
- **WHEN** raw sources have not been normalized
- **THEN** the system SHALL prevent LLM Wiki generation and show the missing prerequisite

### Requirement: Build Graph is replaced by LLM Wiki workflow
The system SHALL make LLM Wiki generation the primary post-source build action instead of a graph-first build action.

#### Scenario: User reaches post-source build stage
- **WHEN** source discovery, upload, or scraping has produced available source material
- **THEN** the primary build action SHALL be `Build LLM Wiki`

#### Scenario: Existing graph artifacts remain secondary
- **WHEN** graph artifacts still exist for a workspace
- **THEN** the system SHALL keep them accessible as supporting artifacts without making them the main stepper destination

### Requirement: Stepper shows durable job status
The system SHALL show durable status for normalization, wiki generation, embedding, reranking, and MCP readiness.

#### Scenario: Long-running wiki job starts
- **WHEN** the user starts the LLM Wiki build
- **THEN** the UI SHALL show the tmux session name, log path, job status, and last progress update

#### Scenario: Job fails
- **WHEN** a stepper job exits with an error
- **THEN** the UI SHALL show the failed step, error summary, and artifact paths needed for debugging
