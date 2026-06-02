## ADDED Requirements

### Requirement: Localhost trust boundary documented and enforced by default
Operator API SHALL bind to loopback unless explicitly configured otherwise.

#### Scenario: Default bind
- **WHEN** `./scripts/run-webapp.sh` starts without `HOST`
- **THEN** uvicorn SHALL bind `127.0.0.1`

#### Scenario: Non-loopback bind warning
- **WHEN** `HOST` is `0.0.0.0` or a LAN IP
- **THEN** startup SHALL log a security warning that no auth is configured

### Requirement: App state secrets redacted on read
API keys SHALL not be returned in plaintext from GET.

#### Scenario: GET app state
- **WHEN** `GET /api/app-state` returns state containing `openrouter_api_key`
- **THEN** value SHALL be replaced with `"set"` or `"missing"` (never the raw key)

#### Scenario: PUT allowlist
- **WHEN** client sends unknown keys in PUT payload
- **THEN** server SHALL ignore or reject keys outside the settings contract

#### Scenario: Secrets in discover response
- **WHEN** discover endpoint returns summary
- **THEN** it SHALL NOT embed full app state with secrets

### Requirement: SSRF-safe discovery and scrape fetch
HTTP fetches for discovery and scrape SHALL use shared safety checks.

#### Scenario: Private IP in discover URL
- **WHEN** operator POSTs discover with `http://127.0.0.1/`
- **THEN** request SHALL be rejected before network fetch

#### Scenario: Sitemap redirect to metadata IP
- **WHEN** sitemap fetch redirects to `169.254.169.254`
- **THEN** fetch SHALL abort

#### Scenario: Scrape fetcher mode
- **WHEN** scrape uses HTTP fetcher mode
- **THEN** it SHALL use the same safe fetch helper as ingest

### Requirement: MCP tmux commands are shell-safe
MCP server launch SHALL quote arguments.

#### Scenario: MCP command with spaces
- **WHEN** MCP server command includes arguments with spaces
- **THEN** tmux SHALL receive a properly quoted shell command

### Requirement: CORS origins validated
Configured CORS origins SHALL be explicit URLs.

#### Scenario: Wildcard origin env
- **WHEN** `SCRAPE_PLANNER_CORS_ORIGINS` contains invalid entries
- **THEN** startup SHALL reject or filter invalid origins and log effective list

### Requirement: Docker stack aligned or deprecated
Container docs SHALL not expose unauthenticated Streamlit/Redis by default.

#### Scenario: Docker compose
- **WHEN** operator runs `docker compose up`
- **THEN** README SHALL state FastAPI/React is primary
- **AND** compose SHALL either serve webapp on loopback or mark legacy services deprecated

### Requirement: Dependency pinning strategy
Python dependencies SHALL be reproducible for operator deployments.

#### Scenario: CI install
- **WHEN** CI runs tests
- **THEN** it SHALL use locked versions from `requirements.lock` or upper-bounded pins documented in README
