## ADDED Requirements

### Requirement: Student URL policy at discovery
Discovery SHALL classify URLs before marking them selected.

#### Scenario: Donor URL in sitemap
- **WHEN** sitemap contains `https://www.smu.edu/giving/donate`
- **THEN** discovered row SHALL have `selected=false` and `excluded_reason` from policy

#### Scenario: Registrar URL
- **WHEN** sitemap contains `/registrar/academic-calendar`
- **THEN** row SHALL remain eligible (`selected=true`) unless other policy excludes it

#### Scenario: Discover API summary
- **WHEN** `POST /api/discover` completes
- **THEN** response SHALL include `eligible_total` and `excluded_by_policy` counts

### Requirement: Student URL policy at scrape selection
Scrape worker SHALL not fetch URLs failing policy even if legacy rows were selected.

#### Scenario: Legacy selected donor URL
- **WHEN** `selected_urls.json` contains a donor URL marked selected
- **THEN** worker SHALL skip or downgrade it using policy before fetch

### Requirement: Manual ingest applies policy
Manual URL pipeline SHALL reject policy-excluded URLs before scrape.

#### Scenario: Manual advancement URL
- **WHEN** operator ingests `https://www.smu.edu/about/leadership/president`
- **THEN** pipeline SHALL reject with policy reason without creating registry row

### Requirement: Scrape crash-safe persistence
Runs SHALL not stall silently on worker crash.

#### Scenario: Worker exception mid-run
- **WHEN** an unhandled exception occurs in `_execute`
- **THEN** run status SHALL be set to `failed` in a `finally` block
- **AND** partial `pages.jsonl` and `failures.json` SHALL be flushed

#### Scenario: Periodic failure flush
- **WHEN** failures accumulate during long runs
- **THEN** worker SHALL append to `failures.json` at least every N pages (configurable, default 25)

### Requirement: Registry merge integrity
Concurrent registry writers SHALL not drop rows.

#### Scenario: Concurrent normalize
- **WHEN** two normalization jobs merge registry for same site
- **THEN** one SHALL wait on file lock or retry merge with fresh read

#### Scenario: Corrupt JSONL line
- **WHEN** a registry line fails JSON parse
- **THEN** system SHALL log line number and increment `registry_corrupt_lines` metric in status

#### Scenario: Duplicate checksum in batch
- **WHEN** two manifest rows share checksum in one normalization run
- **THEN** later duplicate SHALL be quarantined, not marked `ready`
