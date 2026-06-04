## Why

MCP is currently modeled as a site-scoped server controlled from an active workspace. That does not scale when Cursor or another MCP client should connect once and access any university wiki allowed by the local/API configuration.

## What Changes

- Replace the operator-facing MCP runtime with one global tmux server.
- Add global MCP API routes for status, start, stop, restart, and university readiness.
- Build a university registry from `data/sites/*` plus workspace/discovery metadata.
- Refactor the MCP server to support both legacy single-site mode and global multi-site mode with site-aware tools.
- Move React MCP controls from the active site view to a global MCP workspace tab that can be used without an open workspace.

## Impact

- Affected backend: `src/scrape_planner/webapp/api.py`, `routes.py`, navigation.
- Affected MCP server: `mcp_servers/llm_wiki_mcp.py`.
- Affected frontend: `frontend/src/main.tsx`, `viewModel.ts`, styles.
- Affected tests: webapp MCP route tests, navigation tests, MCP server tool tests.
