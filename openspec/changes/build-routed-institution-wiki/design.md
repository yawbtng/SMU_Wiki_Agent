## Context

The current repo already has raw source registration, a wiki builder, wiki indexing, query APIs, and a Streamlit UI. The latest audit shows those pieces run, but the output quality is limited by three issues:

- source quality is uncontrolled, so nav-heavy pages, binary/PDF bytes, redirect stubs, and oversized buckets enter the retrieval path;
- PDF/document artifacts exist but are not normalized into the current `raw_sources` registry as first-class sources;
- generated wiki pages are broad source-note dumps rather than student-facing routed Markdown pages.

The next design must stay generic. The builder should work on a new university without SMU-specific rules. Institution-specific structure must be inferred from source content and metadata, not hard-coded.

## Goals

- Build a generic quality-gated source pipeline for educational institutions.
- Preserve useful sources while quarantining or cleaning low-quality inputs before wiki/index generation.
- Treat PDFs/documents as first-class raw sources with provenance and structure.
- Generate a routed Markdown wiki with canonical fact ownership.
- Support profile-aware query routing before retrieval.
- Make generated wiki output inspectable in the UI as Markdown files, not JSON-first reports.
- Provide measurable validation for source quality, wiki structure, and query usefulness.

## Non-Goals

- No institution-specific page list, department list, office list, or query examples in production prompts.
- No destructive deletion of original scraped artifacts.
- No direct reliance on legacy page-range PDF wiki dumps as the canonical document path.
- No broad graph UI revival.

## Architecture

```text
Fetched Sources / Uploaded Documents
        |
        v
Source Quality Gate
  - detect binary/PDF bytes
  - detect redirects and near-empty pages
  - strip repeated chrome
  - score usefulness
  - quarantine or approve
        |
        v
Normalized Raw Sources
  - web markdown
  - PDF/document sections
  - tables and page spans
  - stable source IDs and provenance
        |
        v
Institution Structure Inference
  - audiences
  - intents
  - schools/colleges
  - departments
  - programs
  - offices/services
  - people/leadership
  - research/labs
  - costs/policies/calendars
        |
        v
Routed Markdown Wiki
  - index.md
  - routing/*.md
  - canonical pages
  - source-notes/*
  - citations and ownership map
        |
        v
Profile-Aware Query
  - route by profile and intent
  - search routed wiki pages first
  - add cited raw/document evidence
  - raw fallback only when needed
```

## Design Decisions

### Decision 1: Quality Gate Before Wiki Generation

Every source must receive a quality record before wiki generation. The record should include binary detection, redirect detection, word count, boilerplate ratio, link-line ratio, duplicate/content checksum state, parser kind, and action.

Allowed actions:

- `approved`: source can feed the wiki and index;
- `cleaned`: source can feed the wiki after chrome stripping;
- `quarantined`: source is preserved but excluded from wiki/index;
- `needs_review`: source is excluded from student-facing pages until reviewed or reparsed.

This prevents junk from becoming authoritative simply because it was successfully fetched.

### Decision 2: PDFs Are Sources, Not Wiki Pages

PDFs and documents must normalize into `raw_sources/document` or `raw_sources/pdf` with structured metadata. A catalog page-range Markdown dump can be a temporary artifact, but it cannot be the canonical input for routed wiki generation.

Document chunks should carry:

- document title and source path/URL;
- page start/end;
- section path;
- table identity when applicable;
- parser name/version;
- extraction warnings;
- stable source ID;
- checksum.

### Decision 3: The Wiki Prompt Is Generic

The prompt must describe the work in institutional terms, not SMU terms.

It may define generic categories such as audiences, intents, schools/colleges, departments, programs, offices, people, costs, policies, calendars, research, and source notes. It must instruct the builder to create only pages supported by sources.

It must not contain specific SMU school names, department names, staff names, or example URLs.

### Decision 4: Canonical Fact Ownership

Each important fact should live in exactly one canonical page. Other pages can link to the canonical owner but should not repeat the full fact.

Ownership examples:

- department leadership belongs to the department page;
- program requirements belong to the program page;
- office contact details belong to the office page;
- tuition/fees belong to cost pages;
- policy text belongs to policy pages;
- lab/research details belong to research pages.

### Decision 5: Route Before Search

The query path should narrow scope before retrieval. A student profile and query intent should identify candidate routing pages and canonical pages before raw chunks are searched.

Profiles should be generic and optional:

- education level: early learner, secondary student, undergraduate, graduate, professional, alumni;
- role: applicant, admitted student, current student, parent, researcher, faculty/staff, visitor;
- intent: explore, apply, enroll, pay, study, contact, research, transfer, visit;
- academic interest: inferred from query or selected by user.

If no profile is provided, the router should still infer likely audience and intent from the question.

## Output Contract

The generated wiki should use Markdown as the primary artifact.

Required files:

- `wiki/index.md`: human-readable routed index;
- `wiki/routing/audience.md`: audience/profile routes;
- `wiki/routing/intent.md`: task/intent routes;
- `wiki/routing/topics.md`: academic and administrative topic routes;
- `wiki/source-notes/index.md`: source-note index for raw evidence and builder notes;
- `wiki/review_queue.md`: uncertain, conflicting, or low-confidence items;
- `wiki/reports/wiki-build-latest.json`: machine report only, not the primary user surface.

Optional folders, created only when supported by sources:

- `wiki/academics/`
- `wiki/departments/`
- `wiki/programs/`
- `wiki/offices/`
- `wiki/people/`
- `wiki/research/`
- `wiki/costs/`
- `wiki/policies/`
- `wiki/calendar/`
- `wiki/student-paths/`

Canonical page sections:

```markdown
# Page Title

## Fast Answer

## Who This Applies To

## Key Facts

## Steps Or Requirements

## Dates, Costs, Or Eligibility

## Contacts And Offices

## Related Pages

## Caveats And Review Notes

## Sources

## Last Verified
```

Sections with no source-backed content may be omitted, but the page must still be readable without raw JSON.

## Source Quality Rules

The first implementation should include conservative generic rules:

- quarantine files containing NUL bytes;
- quarantine Markdown that starts with `%PDF` or has PDF object streams;
- quarantine obvious redirect stubs;
- mark low-word-count pages for review unless they contain strong structured contact/date/cost signals;
- strip repeated global navigation and footer blocks;
- cap chunks per source unless the source is an approved long document;
- report oversized pages and broad buckets.

## Query Design

Query should happen in three phases:

1. Route:
   - infer profile and intent;
   - load routing pages and canonical page metadata;
   - choose candidate pages/folders.
2. Retrieve:
   - search routed wiki pages first;
   - include cited raw/document chunks;
   - search broader raw sources only when routed wiki evidence is weak.
3. Answer/evidence:
   - show fast answer when available;
   - show evidence rows with page, source, score, and excerpt;
   - show “not enough evidence” instead of unrelated raw hits.

## UI Design

The Wiki tab should show generated Markdown as the primary interface:

- folder tree / file list;
- selected Markdown preview;
- page metadata summary;
- source citations;
- review queue;
- build log;
- debug JSON hidden behind secondary expanders.

The Source/Document areas should show quality status:

- approved/cleaned/quarantined/needs-review counts;
- examples and reasons;
- document extraction coverage;
- table preservation warnings.

## Risks And Trade-Offs

- Aggressive cleaning may remove useful content. Mitigation: preserve originals and keep a `needs_review` state.
- Generic routing may miss institution-specific terminology. Mitigation: infer aliases from headings, URLs, titles, and source clusters.
- Profile-aware routing can over-filter. Mitigation: allow fallback to broader wiki search and show routing decisions.
- Document parsing may be expensive. Mitigation: cache by checksum and parser version.
- Markdown contract may feel rigid. Mitigation: required pages are minimal and optional folders are source-driven.

## Validation Strategy

Validation must include fixture and real-workspace checks:

- noisy HTML with repeated navigation/footer;
- redirect stub;
- binary/PDF contamination;
- useful low-word-count contact page;
- structured PDF with table and sections;
- multiple schools/departments inferred from source headings;
- student-profile query that should avoid irrelevant departments;
- query where curated wiki page must beat raw lexical noise;
- UI smoke check that Markdown preview renders and JSON is secondary.
