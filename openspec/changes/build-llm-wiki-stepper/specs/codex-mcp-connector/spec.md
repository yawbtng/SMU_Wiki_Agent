## ADDED Requirements

### Requirement: MCP server exposes local wiki query tools
The system SHALL provide a local MCP server that Codex can use to query ready wiki and raw source indexes.

#### Scenario: Codex calls query tool
- **WHEN** Codex invokes the wiki query MCP tool with a question and site ID
- **THEN** the MCP server SHALL return reranked evidence from the local indexes without rebuilding artifacts

### Requirement: MCP server is query-only
The MCP server SHALL NOT normalize sources, build the wiki, mutate raw sources, or rebuild indexes.

#### Scenario: MCP receives query
- **WHEN** the MCP server handles a query request
- **THEN** it SHALL read existing indexes and source/wiki files only

### Requirement: MCP exposes inspection tools
The MCP server SHALL expose tools for querying, source search, wiki page retrieval, and index health.

#### Scenario: Client requests index info
- **WHEN** Codex invokes the index info tool
- **THEN** the MCP server SHALL return site root, index availability, document counts, last build metadata, and readiness status

#### Scenario: Client requests wiki page
- **WHEN** Codex invokes a wiki page retrieval tool with a path
- **THEN** the MCP server SHALL return the page markdown and metadata if the path is inside the configured site root

### Requirement: Codex configuration is one-click friendly
The system SHALL generate or document a Codex-compatible MCP configuration snippet with absolute paths for the local server command.

#### Scenario: User wants to add MCP to Codex
- **WHEN** the user opens the MCP connector setup output
- **THEN** the system SHALL provide a ready command/config snippet pointing at the local MCP server and selected site root

### Requirement: MCP answers include citations
MCP query results SHALL include source IDs and paths that can be used as citations or evidence references.

#### Scenario: Query evidence is returned
- **WHEN** MCP returns ranked evidence for a question
- **THEN** each evidence item SHALL include citation-ready source metadata
