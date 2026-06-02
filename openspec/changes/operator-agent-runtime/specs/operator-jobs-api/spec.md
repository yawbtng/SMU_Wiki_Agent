# Operator Jobs API

## ADDED Requirements

### Requirement: Launch operator job

The system SHALL expose `POST /api/sites/{site_id}/jobs` accepting `{ skill, prompt?, allow_concurrent?, rebuild_wiki? }`.

#### Scenario: Known skill launches tmux session

- **WHEN** the client posts `{ "skill": "site-discovery", "prompt": "discover registrar URLs" }` for an existing site
- **THEN** the API returns 200 with `session_name`, `report_path`, and `builder_command`
- **AND** a tmux session starts when tmux is available

#### Scenario: Unknown skill rejected

- **WHEN** the client posts an unknown `skill` id
- **THEN** the API returns 400 with a list of known skills

#### Scenario: Duplicate job blocked

- **WHEN** a job for the same skill is already running in tmux
- **AND** `allow_concurrent` is false
- **THEN** the API returns 409 with the active session name

### Requirement: Job status

The system SHALL expose `GET /api/sites/{site_id}/jobs/{skill}` returning the latest report JSON and `stale_running` when tmux is gone but status is still running.

#### Scenario: Stale running detected

- **WHEN** the latest report has `status: running` but the tmux session no longer exists
- **THEN** the API returns `stale_running: true` and the last report payload

### Requirement: Skill catalog

The system SHALL expose `GET /api/operator/skills` listing registered Pi skills with id, title, description, and script name.

#### Scenario: Catalog lists core skills

- **WHEN** the client calls `GET /api/operator/skills`
- **THEN** the response includes `site-discovery`, `site-url-curation`, and `llm-wiki-noninteractive`

### Requirement: No inline URL LLM

The webapp SHALL NOT call OpenRouter from URL approval chat. Intent classification SHALL use local operator heuristics; Pi skills handle agentic curation via jobs.

#### Scenario: Analyze question does not autosave

- **WHEN** the client posts an analyze-style message to `POST .../approved-urls/chat`
- **THEN** the response has `intent: analyze` and `saved: false`
