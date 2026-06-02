## ADDED Requirements

### Requirement: Populated data root detection
Empty site directories SHALL NOT satisfy populated data root checks.

#### Scenario: Empty sites dir
- **WHEN** `data/sites/` exists but contains no site subdirectories
- **THEN** `_looks_populated_data_root` SHALL return false

#### Scenario: Symlink to populated site
- **WHEN** `data/sites/www.smu.edu` is a symlink to a directory with artifacts
- **THEN** resolver SHALL treat data root as populated

#### Scenario: Sibling fallback
- **WHEN** explicit `SCRAPE_PLANNER_DATA_ROOT` is empty
- **THEN** resolver SHALL search sibling worktrees before returning empty path

### Requirement: Redis fallback visibility
Operators SHALL know when scrape state is memory-only.

#### Scenario: Redis unavailable
- **WHEN** `RunStateStore` cannot connect to Redis
- **THEN** first use SHALL log warning and expose `redis_available: false` in health or status endpoint

### Requirement: Page state atomic writes
Concurrent page state writers SHALL use unique temp files.

#### Scenario: write_page_states
- **WHEN** two workers flush page states
- **THEN** writes SHALL use pid/uuid temp files like `write_json_atomic`

### Requirement: Background runner fd hygiene
Detached launches SHALL not leak file descriptors.

#### Scenario: Repeated MCP or job launches
- **WHEN** `start_detached` is called with log_path repeatedly
- **THEN** parent process fd count SHALL remain stable (parent closes its copy after Popen)
