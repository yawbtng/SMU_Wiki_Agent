## ADDED Requirements

### Requirement: Pi compile skill is present or fail-fast
The wiki compile step SHALL NOT invoke a missing skill path silently.

#### Scenario: llm-wiki-v2 skill missing
- **WHEN** `build_wiki.sh` or `llm_wiki_builder._run_pi_compile` runs without `WIKI_SKIP_PI=1`
- **AND** `.pi/skills/llm-wiki-v2/scripts/generate_wiki.sh` does not exist
- **THEN** the build SHALL fail with a clear error naming the missing skill and remediation (`git submodule update`, `--skip-pi`, or install instructions)

#### Scenario: Pi skill present
- **WHEN** the skill script exists and `pi` is on PATH
- **THEN** compile SHALL invoke Pi with the llm-wiki-v2 skill and site root arguments

### Requirement: Default runtime uses Pi compile when available
Operator-initiated wiki builds SHALL compile pages unless explicitly configured for lint-only.

#### Scenario: React or API launch with default settings
- **WHEN** `launch_wiki_builder` is called without `runtime="python"`
- **AND** `wiki_builder_runtime` app setting is `pi`
- **THEN** the tmux command SHALL NOT include `--skip-pi`

#### Scenario: Explicit Python-only mode
- **WHEN** `wiki_builder_runtime` is `python` or `wiki_skip_pi` is true
- **THEN** the pipeline SHALL skip Pi compile and run lint/index only

#### Scenario: Streamlit legacy path
- **WHEN** Streamlit triggers a wiki build
- **THEN** it SHALL use the same runtime resolution as app settings (not hardcoded `python`)

### Requirement: Terminal build report on every tmux/shell exit
`wiki-build-latest.json` SHALL reflect terminal state after the build command exits.

#### Scenario: Successful build
- **WHEN** `build_wiki.sh` exits 0
- **THEN** the report SHALL set `status` and `job_status` to `complete`
- **AND** set `job_finished_at`
- **AND** populate `integrated_sources`, `pages_created`, and `pages_updated` from lint/registry where available

#### Scenario: Failed build
- **WHEN** any pipeline step exits nonzero
- **THEN** the report SHALL set `status`/`job_status` to `failed`
- **AND** include `error` or `last_progress` with stderr tail reference

#### Scenario: UI while running
- **WHEN** tmux session is active and report is not finalized
- **THEN** report MAY remain `running` with `tmux_session` set

### Requirement: Concurrent build guard respects finalized jobs
A finished job SHALL NOT block relaunch during tmux grace period.

#### Scenario: Grace period after success
- **WHEN** report has terminal status and `job_finished_at`
- **AND** tmux session still open for log review
- **THEN** `launch_wiki_builder` SHALL allow a new build

#### Scenario: True concurrent build
- **WHEN** report is `running` and tmux session is alive
- **THEN** a second launch SHALL be rejected with the active session name

#### Scenario: Atomic lock
- **WHEN** two launches race
- **THEN** only one SHALL acquire `wiki/reports/.wiki-build.lock` (O_EXCL) and start tmux

### Requirement: Ingestion pipeline includes lint
Programmatic ingestion SHALL match shell orchestrator stages.

#### Scenario: run_wiki_ingestion_pipeline
- **WHEN** ingestion runs after compile
- **THEN** it SHALL call `lint_wiki` and record lint status in stage summary
- **AND** SHALL NOT report `pages_created: 0` when lint reports created pages

### Requirement: Optional smoke query on rebuild
Rebuild launches SHALL run an index smoke query when `wiki_smoke_on_rebuild` is enabled; otherwise they MUST skip smoke query per app setting.

#### Scenario: Rebuild with smoke enabled
- **WHEN** `wiki_smoke_on_rebuild` is true (default false for resume)
- **THEN** `build_wiki.sh` SHALL run smoke query after index build

#### Scenario: Tmux launcher default
- **WHEN** operator triggers rebuild from UI
- **THEN** smoke SHALL follow app setting (not hardcoded `--skip-smoke`)

### Requirement: Dead session reconciliation updates report
Stale running reports SHALL be finalized when tmux is gone.

#### Scenario: Crashed session
- **WHEN** report status is `running` and tmux session no longer exists
- **THEN** `reconcile_expired_tmux_sessions` or `load_wiki_status` SHALL write `failed` or `stale` with timestamp
