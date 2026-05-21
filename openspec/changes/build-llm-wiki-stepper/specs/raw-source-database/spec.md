## ADDED Requirements

### Requirement: Sources normalize into immutable markdown records
The system SHALL convert every supported source into durable markdown under `raw_sources/` and register it in `raw_sources/registry.jsonl`.

#### Scenario: PDF source is normalized
- **WHEN** a PDF is uploaded or discovered and normalization runs
- **THEN** the system SHALL write markdown output for the PDF and append or update a registry row with source kind, original path, markdown path, checksum, parser, status, and timestamps

#### Scenario: Excel or CSV source is normalized
- **WHEN** an Excel or CSV file is added and normalization runs
- **THEN** the system SHALL write a markdown representation of sheets/tables and register the source as structured tabular data

#### Scenario: Web source is normalized
- **WHEN** a web page has scraped markdown available
- **THEN** the system SHALL register that markdown as a raw source with the source URL and crawl metadata

### Requirement: Source registry supports incremental updates
The system SHALL use stable source IDs and checksums to detect new, changed, unchanged, and failed sources.

#### Scenario: Unchanged source is seen again
- **WHEN** normalization sees a source with the same stable ID and checksum
- **THEN** the system SHALL preserve the existing registry row and mark the source as unchanged

#### Scenario: Changed source is seen again
- **WHEN** normalization sees a source with the same stable ID and a different checksum
- **THEN** the system SHALL update the registry row, preserve prior generated artifacts when possible, and mark the source as needing wiki integration

### Requirement: Raw sources are not modified by wiki generation
The system SHALL treat `raw_sources/` as source-of-truth input that wiki builders can read but not rewrite.

#### Scenario: Wiki builder processes a source
- **WHEN** the LLM Wiki builder reads raw source markdown
- **THEN** it SHALL write derived outputs under `wiki/` or reports directories without modifying the raw markdown file

### Requirement: Failed normalization is explicit
The system SHALL record failed or low-quality source normalization without pretending the source is ready.

#### Scenario: Source parser fails
- **WHEN** a source parser cannot produce usable markdown
- **THEN** the registry row SHALL have a failed or needs-review status with an error reason and diagnostic path
