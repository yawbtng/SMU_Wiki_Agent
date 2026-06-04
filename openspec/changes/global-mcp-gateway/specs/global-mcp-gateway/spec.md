## ADDED Requirements

### Requirement: Global MCP gateway runtime

The operator backend SHALL provide one global MCP runtime that is not scoped to an active workspace/site.

#### Scenario: Start global MCP server

- **WHEN** the operator calls `POST /api/mcp/start`
- **THEN** the backend starts or reuses a tmux session named for the global MCP gateway
- **AND** the command uses the repository MCP server in `--data-root` mode.

#### Scenario: Stop global MCP server

- **WHEN** the operator calls `POST /api/mcp/stop`
- **THEN** the backend stops the global MCP tmux session if present
- **AND** writes global runtime state under the data root runtime directory.

### Requirement: University registry for MCP

The backend and MCP server SHALL expose a registry of universities available under the configured data root.

#### Scenario: List university readiness

- **WHEN** the operator or MCP client asks for universities
- **THEN** each returned row includes site id, display name, URL/domain, wiki readiness, index readiness, and MCP enabled status.

### Requirement: Site-aware MCP tools

The MCP server SHALL support a global multi-site mode while preserving legacy single-site mode.

#### Scenario: Query explicit university

- **WHEN** an MCP client calls a query tool with `site_id`
- **THEN** the server resolves that site under the data root and queries only that university wiki/index.

#### Scenario: Query ambiguous university hint

- **WHEN** an MCP client calls a query tool with a university hint that matches multiple sites
- **THEN** the server returns candidates instead of guessing.

### Requirement: Global operator UI controls

The React operator UI SHALL show MCP controls as a global workspace tab, independent of the active site workspace.

#### Scenario: MCP visible with no workspace selected

- **WHEN** no workspace is open and the operator selects the MCP tab
- **THEN** the UI still renders gateway status, controls, and university readiness.
