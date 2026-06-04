## Design

Run exactly one MCP process named `llm-wiki-mcp-global`. The command is:

```bash
python -m mcp_servers.llm_wiki_mcp --data-root <data_root>
```

The server scans `<data_root>/sites/*` and resolves a target university for each tool call by explicit `site_id` first, then a fuzzy `university_hint`/domain match. If global mode is not requested, `--site-root` keeps the old single-site behavior for compatibility.

## API

- `GET /api/mcp/status`
- `POST /api/mcp/start`
- `POST /api/mcp/stop`
- `POST /api/mcp/restart`
- `GET /api/mcp/universities`

The state file is `data/runtime/mcp-server-latest.json`. Legacy site MCP routes are kept as compatibility wrappers around the global runtime during migration.

## UI

The MCP tab is global. It shows gateway status, tmux session, command, last error, available universities, and readiness counts. It remains accessible when no workspace is selected.
