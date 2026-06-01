## ADDED Requirements

### Requirement: Network-safe, trusted-domain ingestion
Ingestion of web content SHALL be governed by an explicit trusted-domain policy and SHALL be protected against server-side request forgery.

#### Scenario: SSRF protection
- **WHEN** a URL resolves to a private, loopback, link-local, or cloud-metadata address, directly or via redirect
- **THEN** the system SHALL refuse to fetch it
- **AND** the fetch SHALL enforce an https scheme allowlist, a redirect cap, and a response-byte cap

#### Scenario: Untrusted domain rejected
- **WHEN** a candidate URL is outside the configured trusted-domain policy
- **THEN** the system SHALL reject it with a recorded reason rather than ingesting it under the site's own domain

### Requirement: Quality-gated write-back on fetched content
The system SHALL only ingest content that passes source-quality scoring and the student-wiki content policy evaluated on the fetched, extracted content.

#### Scenario: Post-fetch quality gate
- **WHEN** a candidate passes the pre-fetch policy and is fetched
- **THEN** the source-quality gate SHALL run on the extracted markdown
- **AND** content that fails SHALL be quarantined and NOT written into the wiki

#### Scenario: Policy rejection recorded
- **WHEN** a candidate fails the quality gate or content policy (e.g., donor, news, staff-bio, non-student-actionable)
- **THEN** the system SHALL record the rejection with a reason and SHALL NOT ingest it

### Requirement: Idempotent ingestion
Re-ingesting an already-ingested URL whose content has not changed SHALL not create duplicate sources or wiki pages, and SHALL be cheap.

#### Scenario: Re-ingest unchanged URL
- **WHEN** a canonicalized URL with an unchanged content checksum is ingested again
- **THEN** the system SHALL short-circuit before fetch/rebuild and SHALL NOT create duplicate sources, wiki pages, or index documents

#### Scenario: Run directories are bounded
- **WHEN** many ingestions accumulate `manual-*` run directories
- **THEN** a retention policy SHALL bound their growth

### Requirement: Concurrency-safe asynchronous ingestion
Ingestion SHALL run detached from the MCP request path and SHALL be safe under concurrent triggers for the same site.

#### Scenario: Provisional answer returned immediately
- **WHEN** a low-confidence answer triggers write-back
- **THEN** the MCP SHALL return a provisional, explicitly unverified web-derived answer and a job handle without waiting for the rebuild

#### Scenario: Concurrent ingests do not corrupt the index
- **WHEN** two ingestions for the same site run concurrently
- **THEN** index writes SHALL be serialized per site and the documents file SHALL be swapped atomically so readers never observe a truncated index

#### Scenario: Portable launcher
- **WHEN** the tmux launcher is unavailable
- **THEN** the system SHALL use a portable background runner and SHALL surface a launch failure rather than silently recording a pending job

### Requirement: Completion-driven loop guard
The loop guard SHALL be cleared by real ingestion completion, not only by TTL expiry, and SHALL not pin a stale provisional answer after a failed ingest.

#### Scenario: Successful ingestion clears the guard
- **WHEN** an ingestion job completes successfully
- **THEN** the job SHALL write a terminal success status and the guard entry for that query SHALL be cleared so the next query is served locally

#### Scenario: Failed ingestion does not pin a stale answer
- **WHEN** an ingestion job fails
- **THEN** the job SHALL write a terminal failure status with a reason, the guard SHALL clear immediately, and the failure SHALL be surfaced
- **AND** retries SHALL be bounded per query

### Requirement: Auditable auto-ingest with rollback
The system SHALL record accepted auto-ingests and support rolling one back.

#### Scenario: Accepted ingest recorded
- **WHEN** an auto-ingest is accepted and queued
- **THEN** an append-only ledger SHALL record the question, job, URL, and resulting source ids

#### Scenario: Rollback
- **WHEN** an operator rolls back a recorded auto-ingest
- **THEN** the system SHALL quarantine the associated sources and wiki pages and rebuild the index
