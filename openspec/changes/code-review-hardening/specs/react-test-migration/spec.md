## ADDED Requirements

### Requirement: React-critical API routes tested
Webapp integration tests SHALL cover primary UI data paths.

#### Scenario: Runs timeline
- **WHEN** test calls `GET /api/sites/{id}/runs` after seeded events
- **THEN** response SHALL include runs with expected `event_count`

#### Scenario: Sources tab
- **WHEN** test calls `GET /api/sites/{id}/sources`
- **THEN** response SHALL return registry summary shape expected by frontend

#### Scenario: Wiki pages
- **WHEN** test calls `GET /api/sites/{id}/wiki/pages`
- **THEN** response SHALL list pages from fixture wiki dir

#### Scenario: Approved URLs PUT
- **WHEN** test round-trips markdown via PUT
- **THEN** persisted file SHALL match submitted markdown

#### Scenario: Invalid site 404
- **WHEN** site id does not exist
- **THEN** routes SHALL return 404 consistently

### Requirement: Wiki launcher and tmux lifecycle tested
Build orchestration SHALL have dedicated tests beyond happy-path fake runner.

#### Scenario: Concurrent launch rejected
- **WHEN** two launches race with active session
- **THEN** second SHALL return error

#### Scenario: Finalize after exit
- **WHEN** build script trap runs with exit code 1
- **THEN** report SHALL show `failed`

#### Scenario: Grace does not block relaunch
- **WHEN** report finalized but tmux alive
- **THEN** new launch SHALL succeed

#### Scenario: reconcile kills expired session
- **WHEN** job finished beyond grace
- **THEN** fake runner records kill action

### Requirement: Streamlit AST tests retired or skipped
Legacy UI tests SHALL not gate React CI by default.

#### Scenario: CI default
- **WHEN** `pytest` runs without legacy flag
- **THEN** tests marked `legacy_streamlit` SHALL be skipped

#### Scenario: Explicit legacy run
- **WHEN** `pytest -m legacy_streamlit` is invoked
- **THEN** Streamlit AST tests MAY run until deleted

### Requirement: Frontend unit tests in CI
ViewModel and critical helpers SHALL run in verify script.

#### Scenario: verify-webapp.sh
- **WHEN** verification script runs
- **THEN** it SHALL execute vitest (or equivalent) for `frontend/src/viewModel.spec.ts`

#### Scenario: Settings save
- **WHEN** vitest mocks PUT app-state
- **THEN** Settings component SHALL call API with wiki/tmux fields

### Requirement: Shell data-root parity test in CI
Bash and Python resolvers SHALL stay aligned.

#### Scenario: CI script test
- **WHEN** `scripts/test-resolve-data-root.sh` runs in CI
- **THEN** it SHALL pass alongside `tests/test_data_root.py`
