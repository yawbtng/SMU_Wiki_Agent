## ADDED Requirements

### Requirement: Wiki builder runs non-interactively
The system SHALL run the LLM Wiki builder through a non-interactive Pi or agent skill that does not ask the user for input while running.

#### Scenario: Build is launched from UI
- **WHEN** the user clicks `Build LLM Wiki`
- **THEN** the system SHALL start a tmux session that runs the wiki builder skill with no-input settings

#### Scenario: Builder encounters uncertainty
- **WHEN** the wiki builder cannot confidently place or reconcile information
- **THEN** it SHALL write an entry to `wiki/review_queue.md` or an equivalent review artifact instead of prompting for input

### Requirement: Wiki builder consumes raw source registry
The wiki builder SHALL read `raw_sources/registry.jsonl` to determine which sources are available, changed, or not yet integrated.

#### Scenario: New source is ready
- **WHEN** a registry row is ready and not integrated into the wiki
- **THEN** the wiki builder SHALL consider that source for page creation or page updates

#### Scenario: Source was already integrated and unchanged
- **WHEN** a registry row is already integrated and its checksum is unchanged
- **THEN** the wiki builder SHALL skip unnecessary page rewrites unless explicitly asked to rebuild

### Requirement: Wiki has persistent maintained files
The wiki builder SHALL maintain `wiki/index.md`, `wiki/log.md`, generated markdown pages, source citations, and build reports.

#### Scenario: Wiki page is created
- **WHEN** the builder creates a new wiki page
- **THEN** it SHALL add the page to `wiki/index.md` with a link, one-line summary, and source count

#### Scenario: Wiki build completes
- **WHEN** the wiki builder finishes a run
- **THEN** it SHALL append a chronological entry to `wiki/log.md` with run type, sources processed, pages created, pages updated, review items, and report paths

### Requirement: Wiki pages preserve source evidence
Every generated wiki page SHALL include or reference evidence metadata linking claims back to raw source IDs and paths.

#### Scenario: Page summarizes source content
- **WHEN** a wiki page includes facts from raw sources
- **THEN** the page or its metadata SHALL identify the supporting source IDs and raw markdown paths

### Requirement: Wiki builder supports future additions
The wiki builder SHALL support incremental source additions without requiring a full rebuild.

#### Scenario: New PDF is added after initial wiki build
- **WHEN** the new PDF is normalized into raw sources
- **THEN** the next wiki build SHALL integrate only the new or affected source material and update affected wiki pages
