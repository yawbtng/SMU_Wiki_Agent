# Ralph Implementation Plan — Agentic Semantic Wiki/Ingest Automation

Generated/updated by Ralph planning mode on 2026-05-27. This is a planning artifact only; do not treat it as implementation.

## Planning Context

Highest-priority incomplete specs:

1. `specs/000-automated-wiki-ingest-build-update.md` — one-click/automatic Ingest → Clean → Standardize → Lint → Build Wiki → Build Index → Verify.
2. `specs/001-build-smu-llm-wiki.md` — build and verify the SMU LLM Wiki.
3. `specs/002-wire-wiki-ui-pi-sdk.md` — normal Wiki UI must launch Pi SDK streaming runtime.
4. `specs/003-semantic-student-wiki-organization.md` — generated Markdown must become concept-first, citation-backed, retrieval-verified semantic wiki pages.

Current high-signal findings:

- The current app can browse/build wiki artifacts, and index/query tests have meaningful coverage.
- The normal Wiki UI is still effectively Python/tmux deterministic, not Pi-agent semantic orchestration.
- `scripts/pi-sdk-wiki-runner.mjs` is expected by specs but is currently absent.
- Existing Pi skill `.pi/skills/llm-wiki-noninteractive` mostly wraps deterministic Python; it does not make Pi the semantic author.
- Current semantic generation is still scaffolded/hardcoded around Cox and fixed paths.
- The desired architecture is: raw source registry → Pi/Ralph semantic agent → taxonomy/wiki plan → generated semantic pages → deterministic validation → index → smoke queries → UI status.

## Stop Criteria

Ralph may mark the wiki automation work complete only when all are true:

1. Normal UI launches a Pi SDK streaming workflow, not a visible Python deterministic runtime.
2. Build/Update Wiki runs the full pipeline: Ingest → Clean → Standardize → Lint → Build Wiki → Build Index → Verify.
3. The pipeline writes and displays stage-level status/report artifacts.
4. A semantic taxonomy and wiki plan are generated or validated as first-class artifacts.
5. Semantic pages are concept-first, hierarchical, citation-backed, and indexed.
6. The Cox graduate query retrieves organized semantic evidence covering courses/curriculum, fees/costs/aid, and admissions/process/deadlines.
7. Tests, syntax checks, Node checks, and runtime/dry-run smoke checks pass.
8. `WORK_INDEX.md`, `history.md`, and `completion_log/` are updated only when a spec is truly complete.

## Priority 0 — Do Not Deepen the Wrong Architecture

### Task 0.1 — Freeze hardcoded semantic expansion

Files:
- `src/scrape_planner/llm_wiki_builder.py`
- `tests/test_llm_wiki_builder.py`

Actions:
- Do not add more hardcoded school/department/office constants as the main semantic strategy.
- Mark existing Cox-only semantic generation as legacy/scaffold behavior until replaced by taxonomy-driven generation.
- Keep deterministic source-card generation only as traceability/fallback.

Acceptance:
- New semantic work flows through taxonomy/wiki-plan artifacts, not additional hardcoded templates.

### Task 0.2 — Fix nested wiki lint coverage

Files:
- `src/scrape_planner/llm_wiki_builder.py` or new lint module
- `tests/test_llm_wiki_builder.py`

Actions:
- Ensure lint scans `wiki/pages/**/*.md`, not only top-level `wiki/pages/*.md`.
- Preserve path traversal safety and existing report shape.

Verification:
```bash
python -m py_compile src/scrape_planner/llm_wiki_builder.py
python -m pytest tests/test_llm_wiki_builder.py
```

## Priority 1 — Define Semantic Artifact Contracts

### Task 1.1 — Add taxonomy and wiki-plan artifacts

New/updated files:
- New: `src/scrape_planner/semantic_wiki_contracts.py`
- New artifacts under each site:
  - `wiki/taxonomy.yaml` or `wiki/taxonomy.json`
  - `wiki/wiki_plan.md`
  - `wiki/entity_graph.json`
  - `wiki/reports/semantic-wiki-validation-latest.json`
- Tests: new `tests/test_semantic_wiki_contracts.py`

Actions:
- Define a stable taxonomy contract with schools, departments, offices, programs, audiences, intents, source IDs, confidence, and related entities.
- Define a wiki-plan contract listing pages to generate, page purpose, target audience, source IDs, required sections, and related pages.
- Make contracts machine-validated and human-readable.

Acceptance:
- A synthetic taxonomy/wiki plan validates.
- Invalid source IDs, duplicate entity IDs, and malformed related-page paths are rejected.

### Task 1.2 — Add semantic wiki validator

New/updated files:
- New: `src/scrape_planner/semantic_wiki_validator.py`
- Tests: new `tests/test_semantic_wiki_validator.py`

Actions:
- Validate every semantic Markdown page:
  - frontmatter exists,
  - `page_type: semantic`,
  - source IDs exist in registry,
  - related pages exist,
  - required sections exist,
  - citations/source IDs appear near claims,
  - page is not empty/boilerplate-only.
- Validate generated taxonomy/wiki-plan consistency.

Acceptance:
- Validation report includes pass/fail counts and concrete failure paths.
- Severe failures can block indexing or mark pipeline failed.

## Priority 2 — Pi SDK Runner and Agentic Skill

### Task 2.1 — Add `scripts/pi-sdk-wiki-runner.mjs`

Files:
- New: `scripts/pi-sdk-wiki-runner.mjs`
- `src/scrape_planner/llm_wiki_builder.py`
- Tests: `tests/test_llm_wiki_builder.py` or new runner command-shape tests

Actions:
- Implement a non-interactive Node runner that can be launched from tmux.
- Required arguments:
  - `--site-root`
  - `--registry-path`
  - `--wiki-dir`
  - `--report-path`
  - `--event-log-path`
  - `--tmux-session`
  - `--python-executable`
  - `--resume` or `--rebuild`
  - `--model`
  - `--thinking`
  - `--dry-run`
- Runner must write JSONL event rows for launch, tool/stage start, tool/stage completion, assistant summary, errors, and final status.
- Runner must update `wiki-build-latest.json` or an end-to-end latest report with `runtime: pi-sdk`.

Acceptance:
- Dry run prints/records the intended full pipeline command.
- Event log path is created with valid JSONL rows.

Verification:
```bash
node --check scripts/pi-sdk-wiki-runner.mjs
node scripts/pi-sdk-wiki-runner.mjs \
  --site-root data/sites/www.smu.edu \
  --registry-path data/sites/www.smu.edu/raw_sources/registry.jsonl \
  --wiki-dir data/sites/www.smu.edu/wiki \
  --report-path data/sites/www.smu.edu/wiki/reports/wiki-build-latest.json \
  --event-log-path data/sites/www.smu.edu/wiki/reports/pi-sdk-events-latest.jsonl \
  --tmux-session ralph-wiki-sdk-dry-run \
  --python-executable "$(command -v python3)" \
  --rebuild \
  --dry-run
```

### Task 2.2 — Replace deterministic skill wrapper with semantic-wiki-builder skill

Files:
- New: `.pi/skills/semantic-wiki-builder/SKILL.md`
- New: `.pi/skills/semantic-wiki-builder/scripts/semantic_wiki_agent.sh` if needed
- Existing: `.pi/skills/llm-wiki-noninteractive/SKILL.md` may remain as legacy deterministic utility

Actions:
- Skill instructions must make Pi the semantic author, not just a command runner.
- Skill must require:
  1. read `raw_sources/registry.jsonl`,
  2. inspect representative raw Markdown,
  3. create/update taxonomy,
  4. create/update wiki plan,
  5. generate semantic pages,
  6. cite source IDs,
  7. run validators,
  8. build index,
  9. run smoke queries,
  10. revise until validation/retrieval pass.
- Skill must forbid editing raw sources.

Acceptance:
- Skill file can be attached by Pi.
- Runner prompt explicitly invokes this skill or its instructions.

## Priority 3 — Full Pipeline Report and Status Contract

### Task 3.1 — Make `run_wiki_ingestion_pipeline` the authoritative stage orchestrator

Files:
- `src/scrape_planner/wiki_ingestion_pipeline.py`
- `src/scrape_planner/stepper_status.py`
- `src/scrape_planner/app/artifact_contracts.py`
- Tests: `tests/test_wiki_ingestion_pipeline.py`

Actions:
- Produce one latest report, preferably `wiki/reports/wiki-ingest-latest.json`, with stable stage keys:
  - `ingest`, `clean`, `standardize`, `lint`, `build_wiki`, `build_index`, `verify`.
- Include status, counts, started/finished timestamps, errors, and artifact paths per stage.
- Stop dependent stages on failure.
- Preserve backward compatibility with existing `wiki-build-latest.json` readers.

Acceptance:
- UI/status loader can render stages without parsing raw logs.
- Tests cover success and failure report shapes.

### Task 3.2 — Prevent duplicate concurrent launches

Files:
- `src/scrape_planner/llm_wiki_builder.py`
- `src/scrape_planner/tmux_runner.py`
- `app.py`
- Tests

Actions:
- Detect running/queued report for same site and runtime.
- Disable or reject duplicate Build/Update launches.
- Surface clear UI message.

Acceptance:
- Double-click or repeated launch does not create competing tmux sessions for the same site.

## Priority 4 — Reusable Cleanup, Standardization, and Lint

### Task 4.1 — Extract content quality module

Files:
- New: `src/scrape_planner/wiki_content_quality.py`
- `src/scrape_planner/llm_wiki_builder.py`
- `src/scrape_planner/wiki_ingestion_pipeline.py`
- Tests: new or existing builder tests

Actions:
- Implement reusable data structures/functions:
  - `CleanedSource`
  - `clean_source_text_for_wiki(row, text)`
  - `classify_source_value(row, cleaned_text)`
  - `standardize_source_document(row, cleaned_text)`
  - `lint_source_document(document)`
- Remove nav/header/footer/cookie/social/search boilerplate while preserving academic/program content and provenance.
- Flag/exclude redirects, social pages, pure navigation, donor/class notes, award/company tables when not useful for student Q&A.

Acceptance:
- Existing low-value fixture exclusions still pass.
- Useful admissions/program/curriculum/tuition pages remain included.

### Task 4.2 — Build lint into the pipeline

Files:
- `src/scrape_planner/wiki_ingestion_pipeline.py`
- `src/scrape_planner/semantic_wiki_validator.py`
- tests

Actions:
- Run source/document lint before wiki generation.
- Run semantic page lint before indexing.
- Include quality flags and fail/blocking counts in stage report.

Acceptance:
- Lint report is visible in pipeline report and status UI.

## Priority 5 — Taxonomy-Driven Semantic Wiki Generation

### Task 5.1 — Build source clustering and entity extraction from raw corpus

Files:
- New: `src/scrape_planner/wiki_taxonomy_builder.py` or Pi-authored artifact path
- `src/scrape_planner/semantic_wiki_contracts.py`
- Tests with synthetic corpus

Actions:
- Infer schools/colleges, departments, offices, programs, degree levels, audiences, and intents from source titles, URLs/paths, metadata, and cleaned text.
- Use Pi skill for judgment-heavy taxonomy creation; deterministic code validates and writes artifacts.
- Avoid hardcoding every institution entity in Python.

Acceptance:
- Synthetic corpus with Lyle/Computer Science/Registrar/Admissions/Tuition produces correct taxonomy without Cox-specific rules.

### Task 5.2 — Generate semantic pages from taxonomy/wiki plan

Files:
- New: `src/scrape_planner/wiki_semantic_pages.py`
- `src/scrape_planner/llm_wiki_builder.py`
- Tests

Actions:
- Generate pages such as:
  - `wiki/pages/schools/<school>/index.md`
  - `wiki/pages/schools/<school>/graduate.md`
  - `wiki/pages/schools/<school>/admissions.md`
  - `wiki/pages/schools/<school>/courses.md`
  - `wiki/pages/schools/<school>/costs-and-aid.md`
  - `wiki/pages/offices/<office>.md`
  - `wiki/pages/audiences/<audience>.md`
  - `wiki/pages/intents/<intent>.md`
- Required sections:
  - Fast Answer
  - Who This Applies To
  - Courses / Curriculum
  - Costs / Fees / Aid
  - Admissions / Requirements / Deadlines
  - Contacts / Offices
  - Related Pages
  - Sources
- Keep citations/source IDs close to claims.

Acceptance:
- Semantic pages synthesize multiple sources when evidence exists.
- Source-card pages remain available for traceability but are not the primary answer surface.

### Task 5.3 — Bound aggregate page size

Files:
- `src/scrape_planner/llm_wiki_builder.py`
- Tests

Actions:
- Replace oversized category dumps with concise landing pages.
- Link to semantic pages first; link to source indexes second.
- Avoid embedding thousands of source summaries into one Markdown file.

Acceptance:
- `wiki/index.md` and category pages are readable, bounded-size entry points.

## Priority 6 — Indexing, Retrieval, and MCP

### Task 6.1 — Rebuild index after every UI/Pi pipeline run

Files:
- `src/scrape_planner/wiki_ingestion_pipeline.py`
- `scripts/pi-sdk-wiki-runner.mjs`
- `src/scrape_planner/stepper_status.py`
- Tests

Actions:
- Ensure `build_llm_wiki_index` always runs after successful wiki generation in normal pipeline.
- Report index freshness: index manifest timestamp vs wiki build/report timestamp.
- Show stale index state in UI/status when applicable.

Acceptance:
- `indexes/llm_wiki_manifest.json` is at least as fresh as latest wiki build after pipeline completion.

### Task 6.2 — Prioritize semantic pages while keeping raw provenance

Files:
- `src/scrape_planner/llm_wiki_index.py`
- Tests: `tests/test_llm_wiki_index.py`

Actions:
- Ensure nested `wiki/pages/**/*.md` semantic pages are indexed.
- Preserve routing metadata: `page_type`, `school(s)`, `department(s)`, `office(s)`, `programs`, `degree_levels`, `audiences`, `intents`, `topics`, `related_pages`.
- Prefer semantic pages for broad/multi-aspect student questions.
- Keep raw/source-card evidence as supporting provenance, not primary answer surface.

Acceptance:
- Cox graduate query returns semantic pages before raw/source-card chunks.

### Task 6.3 — Fix MCP nested page access

Files:
- `mcp_servers/llm_wiki_mcp.py`
- Tests: `tests/test_llm_wiki_mcp.py`

Actions:
- Allow `get_wiki_page("wiki/pages/schools/cox/graduate.md")` and other nested pages.
- Preserve path traversal protection.

Acceptance:
- Nested page read succeeds; escape attempts fail.

## Priority 7 — Streamlit UI Migration

### Task 7.1 — Make Wiki UI Pi SDK streaming only for normal operation

Files:
- `app.py`
- `src/scrape_planner/llm_wiki_builder.py`
- `tests/test_wiki_ui.py`

Actions:
- Remove normal `Python deterministic` runtime wording/control.
- Fixed normal runtime: `pi-sdk` / `Pi SDK streaming`.
- `Build Wiki` launches full rebuild.
- `Update Wiki` launches resume/update.
- No separate normal `Rebuild Wiki` button.
- Add Pi SDK model/reasoning controls defaulting to `gpt-5.4-mini` and `high`.

Acceptance:
- UI tests assert no deterministic runtime exposure and command uses `runtime="pi-sdk"`.

### Task 7.2 — Render stage and agent activity

Files:
- `app.py`
- `src/scrape_planner/stepper_status.py`
- Tests

Actions:
- Display stage cards for Ingest, Clean, Standardize, Lint, Build Wiki, Build Index, Verify.
- Parse/render `pi-sdk-events-latest.jsonl` into meaningful activity rows.
- Keep raw logs collapsed/secondary.
- Display taxonomy/wiki-plan/validation report links or previews.

Acceptance:
- Operator can tell whether agent is doing real work and which stage is active.

## Priority 8 — Verification and Smoke Tests

### Task 8.1 — Synthetic end-to-end semantic wiki test

Files:
- New test fixture/helpers
- `tests/test_semantic_wiki_validator.py`
- `tests/test_llm_wiki_index.py`

Fixture:
- Lyle School of Engineering
- Computer Science Department
- Graduate Admissions
- Tuition and Fees
- Registrar Office
- Course Catalog

Smoke query:
```text
I am a prospective graduate student in computer science. Tell me about admissions, courses, fees, and registrar steps.
```

Acceptance:
- Generated taxonomy includes school, department, office, intents.
- Generated semantic pages cite correct source IDs.
- Query retrieves semantic pages covering all requested aspects.

### Task 8.2 — SMU Cox runtime smoke

Commands:
```bash
source .venv/bin/activate
python -m py_compile \
  app.py \
  src/scrape_planner/wiki_ingestion_pipeline.py \
  src/scrape_planner/llm_wiki_builder.py \
  src/scrape_planner/llm_wiki_index.py \
  mcp_servers/llm_wiki_mcp.py
node --check scripts/pi-sdk-wiki-runner.mjs
python -m pytest \
  tests/test_llm_wiki_builder.py \
  tests/test_llm_wiki_index.py \
  tests/test_wiki_ingestion_pipeline.py \
  tests/test_wiki_ui.py \
  tests/test_llm_wiki_mcp.py
python -m src.scrape_planner.wiki_ingestion_pipeline \
  --site-root data/sites/www.smu.edu \
  --kind auto \
  --rebuild \
  --query "I am a new graduate student likely joining Cox; tell me about courses, course fees, and the admission process"
```

Acceptance:
- Runtime/dry-run completes without exceptions.
- Query report includes semantic wiki evidence for courses, fees/costs, and admissions.

## Recommended Ralph Build Iteration Order

1. P0.2 — nested lint coverage.
2. P1.1/P1.2 — taxonomy/wiki-plan/validator contracts.
3. P2.1 — Pi SDK runner dry-run/event-log path.
4. P3.1 — stable stage report contract.
5. P7.1 — Wiki UI launches `runtime="pi-sdk"` only.
6. P4.1/P4.2 — reusable cleanup/standardization/lint.
7. P5.1/P5.2 — taxonomy-driven semantic page generation.
8. P6.2/P6.3 — semantic retrieval priority and nested MCP page access.
9. P7.2 — stage/activity UI.
10. P8.1/P8.2 — synthetic + SMU Cox smoke verification.
11. Update `WORK_INDEX.md`, `history.md`, and `completion_log/` only for truly completed specs.

## Notes for Ralph Build Mode

- Do not mark semantic wiki specs complete after only generating thousands of source-card Markdown files.
- Prefer small, testable patches per loop.
- Respect Git Autonomy: do not commit or push unless explicitly asked.
- Preserve raw source artifacts; write only derived wiki/index/report artifacts or code/tests/specs.
- After source/config/test/doc edits, run `codegraph sync` before using CodeGraph again or reporting completion.
