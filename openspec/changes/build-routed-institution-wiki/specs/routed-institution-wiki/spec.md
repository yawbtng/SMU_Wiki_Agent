## ADDED Requirements

### Requirement: Source Quality Gate
The system SHALL assess normalized web sources before wiki generation and record approved, cleaned, quarantined, and needs-review outcomes.

#### Scenario: Quarantine binary and redirect sources
- **WHEN** a source contains NUL bytes, PDF signatures, PDF object streams, or redirect-stub text
- **THEN** the source is preserved with diagnostics
- **AND** it is excluded from ready wiki/index inputs

#### Scenario: Clean reusable boilerplate
- **WHEN** a source contains repeated navigation, search, or footer chrome around useful content
- **THEN** the original scrape artifact remains untouched
- **AND** a cleaned derived raw-source artifact is registered for wiki generation

### Requirement: Document Source Normalization
The system SHALL normalize PDFs and documents into raw source registry rows with document provenance.

#### Scenario: Preserve document structure
- **WHEN** a parsed PDF or document is normalized
- **THEN** metadata includes page spans, section paths, parser information, extraction warnings, checksums, and source path or URL

#### Scenario: Preserve tables
- **WHEN** parsed document markdown includes tables
- **THEN** table metadata and a citable table sidecar are written with stable table identifiers

### Requirement: Routed Markdown Wiki
The system SHALL generate a Markdown-first institutional wiki with required routing files, canonical page metadata, and separated source notes.

#### Scenario: Required routed files are generated
- **WHEN** a wiki build processes ready sources
- **THEN** `wiki/index.md`, `wiki/routing/audience.md`, `wiki/routing/intent.md`, `wiki/routing/topics.md`, `wiki/source-notes/index.md`, and `wiki/review_queue.md` exist

#### Scenario: Student pages avoid raw source dumps
- **WHEN** canonical pages are generated
- **THEN** student-facing sections such as Fast Answer, Who This Applies To, Key Facts, Related Pages, Sources, and Last Verified are used
- **AND** raw excerpts are stored under `wiki/source-notes/`

### Requirement: Profile-Aware Query Routing
The system SHALL route optional profile-aware queries through curated wiki metadata before relying on raw-source fallback.

#### Scenario: Route before retrieval
- **WHEN** a query includes or implies education level, role, intent, or academic interest
- **THEN** routed wiki pages matching those fields receive retrieval priority
- **AND** out-of-scope routed pages are penalized

#### Scenario: Insufficient evidence
- **WHEN** no indexed wiki or raw documents match the query
- **THEN** the query response reports insufficient evidence instead of returning unrelated raw hits

### Requirement: Operator Markdown Inspection
The operator UI SHALL make generated Markdown, quality summaries, citations, and query routing decisions visible without making JSON the primary surface.

#### Scenario: Markdown browser
- **WHEN** generated wiki Markdown files exist
- **THEN** the Wiki tab provides a file selector, Markdown preview, metadata summary, and citation display

#### Scenario: Query transparency
- **WHEN** an operator queries the wiki index
- **THEN** the UI shows the route profile, candidate pages, raw fallback status, evidence reasons, and insufficient-evidence state when applicable
