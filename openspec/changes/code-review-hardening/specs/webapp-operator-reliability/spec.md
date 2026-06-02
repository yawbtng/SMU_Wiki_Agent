## ADDED Requirements

### Requirement: No passive embedding auto-queue
SSE and read-only overview endpoints SHALL NOT launch embedding rebuild jobs by default.

#### Scenario: SSE polling
- **WHEN** a client maintains `GET /api/stream/sites/{site_id}`
- **THEN** the server SHALL NOT call `trigger_embedding_rebuild(launch=True)` unless `auto_rebuild_embeddings` is enabled in app state

#### Scenario: Overview GET
- **WHEN** `GET /api/sites/{site_id}/overview` is called
- **THEN** it SHALL NOT auto-launch embedding rebuild unless explicitly enabled

#### Scenario: Explicit rebuild
- **WHEN** operator calls `POST /api/sites/{site_id}/embeddings/rebuild`
- **THEN** rebuild SHALL proceed with existing lock semantics

### Requirement: Stale embedding lock recovery
Embedding job lock files SHALL not block jobs forever after a crash.

#### Scenario: Dead PID in lock
- **WHEN** `.embedding-job.lock` exists and recorded PID is not running
- **THEN** the next rebuild attempt SHALL remove or override the stale lock

#### Scenario: Lock TTL
- **WHEN** lock age exceeds configured TTL (default 2 hours)
- **THEN** acquire SHALL succeed after reaping

#### Scenario: Force unlock API
- **WHEN** operator calls force unlock endpoint or setting
- **THEN** lock file SHALL be removed and job status reset to `idle`

### Requirement: Scrape events persisted for webapp runs API
Run timelines in React SHALL reflect scrape activity.

#### Scenario: Event during scrape
- **WHEN** scrape worker emits a progress event
- **THEN** `append_run_event` SHALL append a JSONL line to `{run_root}/events.jsonl`

#### Scenario: Runs list
- **WHEN** `GET /api/sites/{site_id}/runs` is called after scrape
- **THEN** each run SHALL include nonzero `event_count` when events occurred

### Requirement: SSE disconnect stops heavy work
Event streams SHALL not spin after client disconnect.

#### Scenario: Client closes tab
- **WHEN** the HTTP connection drops
- **THEN** the SSE generator SHALL exit within one poll interval

#### Scenario: Lightweight SSE payload
- **WHEN** SSE tick fires
- **THEN** it SHALL use a compact digest endpoint or cached snapshot, not full `site_overview_payload` with all side effects on every tick unless digest changed

### Requirement: Frontend error handling and wiki actions
React Settings and workflow tabs SHALL handle API failures and expose wiki controls.

#### Scenario: Approval save failure
- **WHEN** `PUT /api/sites/{id}/approved-urls` returns 4xx/5xx
- **THEN** UI SHALL show error text including FastAPI `detail` when present

#### Scenario: Wiki build button
- **WHEN** operator clicks Build/Update Wiki
- **THEN** UI SHALL call the wiki launch API and show session name or error

#### Scenario: Overview before first SSE event
- **WHEN** SSE is connected but no `site` event received yet
- **THEN** Overview SHALL still show data from REST overview query

### Requirement: Start/stop script hardening
Dev stack scripts SHALL verify process identity and optional tmux cleanup.

#### Scenario: stop with kill tmux
- **WHEN** `./stop.sh --kill-tmux` is passed
- **THEN** tmux session `ultra-fast-rag-webapp` SHALL be killed after stopping ports

#### Scenario: Port listener verification
- **WHEN** port 8000 is listening
- **THEN** `start.sh` SHALL verify command line contains expected uvicorn module before skipping restart

#### Scenario: Env file drift
- **WHEN** `./status.sh` runs
- **THEN** it SHALL warn if `logs/webapp.env` data root differs from resolved data root
