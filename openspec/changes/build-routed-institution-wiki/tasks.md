# Build Routed Institution Wiki Implementation Tasks

## 1. Source Quality Gate

- [x] 1.1 Add source quality model and report helpers.
  - Create a focused helper under `src/scrape_planner/` that computes quality signals for a source: word count, NUL-byte presence, PDF/binary signature, redirect-stub signature, boilerplate ratio, link-line ratio, duplicate checksum, parser kind, and recommended action.
  - Actions must be `approved`, `cleaned`, `quarantined`, or `needs_review`.

- [x] 1.2 Add generic boilerplate/chrome stripping.
  - Strip repeated navigation/search/footer blocks without hard-coding one institution as the only case.
  - Keep the original artifact untouched and write cleaned text as a derived raw-source artifact.

- [x] 1.3 Add quarantine behavior.
  - Quarantine sources that contain NUL bytes, start with `%PDF`, contain PDF object streams in Markdown, or match redirect-stub patterns.
  - Preserve quarantine reports with source ID, reason, original path/URL, checksum, and recommended parser route.

- [x] 1.4 Add quality report UI/status contract.
  - Expose approved, cleaned, quarantined, and needs-review counts through existing status helpers.
  - Keep reports readable in the UI without making raw JSON the main surface.

- [x] 1.5 Add tests.
  - Cover binary/PDF-in-markdown detection, redirect stubs, low-content pages, useful short contact/date pages, boilerplate stripping, duplicate checksum behavior, and report output.

## 2. Document/PDF Raw Source Normalization

- [x] 2.1 Route uploaded PDFs/documents into the raw source registry.
  - Ensure parsed PDF/document chunks create `source_kind` rows such as `pdf` or `document`, not only legacy wiki page-range files.

- [x] 2.2 Preserve document structure.
  - Store page start/end, section path, table identity, parser name/version, extraction warnings, title, source path/URL, and checksum.

- [x] 2.3 Add table-aware artifacts.
  - Preserve extracted tables as Markdown tables or structured sidecar records that can be cited and indexed.

- [x] 2.4 Add document quality gates.
  - Report page coverage, chars/page, table preservation warnings, OCR-required pages, repeated header/footer detection, and empty-section counts.

- [x] 2.5 Add tests.
  - Cover PDF registry rows, section/page provenance, table preservation, parser warning propagation, and exclusion of raw page-range dumps from canonical routed wiki generation.

## 3. Generic Institution Wiki Prompt And Contract

- [x] 3.1 Replace broad keyword bucket generation with generic structure inference.
  - Infer audiences, intents, schools/colleges, departments, programs, offices/services, people/leadership, research/labs, costs, policies, calendars, and source-note clusters from source content and metadata.
  - Do not hard-code institution names, department names, office names, or example URLs.

- [x] 3.2 Create required routed Markdown outputs.
  - Generate `wiki/index.md`, `wiki/routing/audience.md`, `wiki/routing/intent.md`, `wiki/routing/topics.md`, `wiki/source-notes/index.md`, and `wiki/review_queue.md`.

- [x] 3.3 Create optional canonical folders only when source-supported.
  - Supported folders include `academics`, `departments`, `programs`, `offices`, `people`, `research`, `costs`, `policies`, `calendar`, and `student-paths`.

- [x] 3.4 Enforce canonical fact ownership.
  - Track ownership for facts such as leadership, requirements, contacts, tuition/fees, policies, and research centers.
  - Link to canonical pages instead of repeating facts across pages.

- [x] 3.5 Separate student-facing pages from source notes.
  - Student-facing pages must use sections such as Fast Answer, Who This Applies To, Key Facts, Steps Or Requirements, Dates/Costs/Eligibility, Contacts, Related Pages, Caveats, Sources, and Last Verified.
  - Raw excerpts belong under `wiki/source-notes/`, not as the main answer page.

- [x] 3.6 Add tests.
  - Use a fixture institution with multiple schools/departments/offices and no SMU-specific names.
  - Assert routed index files exist, optional folders are source-driven, duplicate facts are linked rather than repeated, and source notes are separate.

## 4. Profile-Aware Query Routing

- [x] 4.1 Add routing metadata extraction.
  - Persist page metadata for audiences, roles, intents, academic interests, canonical facts, aliases, and source priority.

- [x] 4.2 Add query profile input model.
  - Support optional profile fields: education level, role, intent, academic interest, and free-form query.
  - Infer missing profile fields from the query when possible.

- [x] 4.3 Route before retrieval.
  - Select candidate routing pages and canonical folders before searching all raw chunks.
  - Avoid irrelevant folders when profile routing makes them clearly out of scope.

- [x] 4.4 Prefer curated wiki evidence.
  - Rank routed wiki pages above raw lexical matches when both have reasonable evidence.
  - Include cited raw/document chunks as supporting evidence.
  - Use raw fallback only when routed wiki evidence is absent or weak.

- [x] 4.5 Add no-answer behavior.
  - Return a clear insufficient-evidence status when the best available hits are unrelated instead of showing misleading raw results.

- [x] 4.6 Add tests.
  - Cover a younger/early-explorer profile avoiding deep graduate department docs.
  - Cover a graduate applicant profile routing to program and department pages.
  - Cover an exact leadership/faculty answer where the canonical department page outranks broad raw chunks.
  - Cover insufficient evidence.

## 5. Operator UI

- [x] 5.1 Add generated Markdown file browser to the Wiki tab.
  - Show folder/file tree or grouped file list for `wiki/*.md` and supported subfolders.
  - Show selected Markdown content in a large readable preview.

- [x] 5.2 Add page metadata and citations.
  - Show page audience, intent, canonical owner, source count, citations, and last verified date where available.

- [x] 5.3 Keep JSON secondary.
  - Move machine reports behind debug expanders.
  - The default operator surface should be Markdown pages, quality summaries, build log, and review queue.

- [x] 5.4 Add source/document quality UI.
  - Show quarantine reasons, cleaned/approved counts, document extraction coverage, and examples needing review.

- [x] 5.5 Add query routing transparency.
  - Show which profile/intent route was used, candidate pages searched, and why raw fallback was or was not used.

- [x] 5.6 Add UI tests.
  - Assert Wiki tab exposes Markdown preview and review queue.
  - Assert raw JSON is not the default primary display.
  - Assert query results show routing/evidence details.

## 6. End-To-End Validation

- [x] 6.1 Build a noisy fixture institution.
  - Include useful pages, nav-heavy pages, redirect stubs, binary/PDF contamination, PDF/document tables, multiple departments, offices, costs, policies, and student-profile routes.

- [x] 6.2 Validate source quality.
  - Run source quality gate and assert expected approved, cleaned, quarantined, and needs-review counts.

- [x] 6.3 Validate document normalization.
  - Assert PDF/document rows exist in `raw_sources`, with page spans, sections, tables, and provenance.

- [x] 6.4 Validate routed wiki generation.
  - Assert required routing Markdown files exist and optional folders match source-supported categories.
  - Assert no oversized broad bucket page is generated for thousands of unrelated sources.

- [x] 6.5 Validate query behavior.
  - Run profile-aware query probes and assert routed wiki pages beat noisy raw chunks.
  - Assert unrelated raw hits do not become answers.

- [x] 6.6 Validate current SMU workspace in limited mode.
  - Run the new path on a bounded SMU sample that includes web pages, noisy pages, and the uploaded graduate catalog PDF.
  - Record quality counts, generated Markdown pages, and query probes in a validation report.

- [x] 6.7 Run verification before completion.
  - Run compile/syntax checks for changed Python paths.
  - Run focused unit tests for quality gate, document normalization, wiki contract, query routing, and UI.
  - Run the end-to-end validation script on the fixture and bounded SMU sample.
  - Start the Streamlit app and confirm logs show no new exceptions after opening source quality, wiki, and query views.
