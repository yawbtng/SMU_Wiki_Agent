# Automate Wiki Ingest, Build, and Update

## Goal

Provide a one-click and optionally automatic end-to-end workflow that ingests prepared sources, cleans boilerplate/junk, standardizes content structure, builds a student-question-oriented semantic wiki, rebuilds the searchable wiki/source index, and verifies the result without requiring separate manual steps.

The wiki must be useful as organized Markdown knowledge, not just as a BM25/search corpus. It should group related meaning across sources so questions like “I am a new grad likely joining Cox; tell me about courses, course fees, and the admission process” can retrieve coherent, organized answers.

## Terminology

Use **Ingest** as the standard word in the UI, code, reports, and docs for the whole operator action that brings prepared source material into the knowledge base. Avoid mixing "ingest", "import", "update", "sync", and "refresh" for the same top-level action.

Pipeline stage names should be:

- **Ingest:** Convert prepared web scrape markdown, PDF pages/chunks, and tabular uploads into canonical `raw_sources/registry.jsonl` rows with `status="ready"`.
- **Clean:** Remove navigation, headers, footers, cookie banners, repeated menus, breadcrumb boilerplate, social/share blocks, and other low-value layout junk while preserving citations/provenance.
- **Standardize:** Normalize every ready source into a common document shape before wiki generation.
- **Lint:** Validate content quality and structure before indexing.
- **Build Wiki:** Build or refresh generated Markdown wiki pages from cleaned, standardized, ready raw sources, organized by student intent, audience, school/college, program, topic, and related entities.
- **Build Index:** Rebuild/update `indexes/llm_wiki_*` artifacts so the wiki and raw sources are queryable by meaning-rich Markdown pages, not only raw-source chunks.
- **Verify:** Run a representative smoke query against the resulting index.

The existing end-to-end entrypoint is `src.scrape_planner.wiki_ingestion_pipeline`, which already composes normalization → wiki build → index build → optional query. Extend it rather than creating a parallel pipeline.

## Context

- Main UI: FastAPI + React webapp.
- End-to-end Python pipeline: `src/scrape_planner/wiki/wiki_ingestion_pipeline.py::run_wiki_ingestion_pipeline`.
- Wiki builder launcher: `src/scrape_planner/wiki/wiki_launcher.py::launch_wiki_builder`.
- Compile runner: `.pi/skills/llm-wiki-noninteractive/scripts/build_wiki.sh`.
- Target smoke workspace: `data/sites/www.smu.edu`.
- Required runtime for automated operator path: LLM Wiki v2 compile by default. Keep lint/index-only mode as fallback, not as the primary wiki strategy.
- Raw source artifacts are inputs and must not be destructively edited by automation.

## Requirements

1. Add an automated wiki pipeline path that runs, in order:
   1. source ingest/normalization for available prepared inputs,
   2. content cleanup/de-boilerplating,
   3. common structure standardization,
   4. content lint/quality validation,
   5. wiki build/update,
   6. LLM Wiki/source index build/update,
   7. optional smoke query.
2. Expose the pipeline in the UI as a clear single action named around the standard word, for example `Run Ingest Pipeline` or `Ingest Content`. This must be runnable from the webapp UI; users should not need to start the pipeline from the terminal for normal operation.
3. The automated action must use the LLM Wiki v2 compile path by default, so the UI can show agent events/tool output. Remove deterministic framing from normal UI operation.
4. The UI must present LLM Wiki v2 compile status, including runtime, stage, and failure details.
5. Status displays must reflect the actual selected/launched runtime. If the operator launches Pi compile, the UI must not show `Runtime: python` from a stale previous report.
6. The UI should make the relationship clear: Ingest, Clean, Standardize, Lint, Build Wiki, Build Index, and Verify are stages of one automation pipeline.
7. The normal Wiki UI should expose only `Build Wiki` and `Update Wiki` actions: Build performs a full rebuild; Update performs an incremental/resume run.
8. Raw log dumps/operator details/latest report JSON should stay hidden in normal operation; show meaningful stage and agent activity instead.
9. Add a reusable content cleanup layer that removes low-value boilerplate before wiki generation and indexing. It should target repeated/nav-like content, not meaningful academic/program content.
10. Add or enforce a common source document structure, such as:
   - `title`
   - `source_id`
   - `source_kind`
   - `canonical_url` or source path
   - `audience`
   - `content_type`
   - `summary`
   - `main_content`
   - `key_facts`
   - `citations/provenance`
   - `quality_flags`
11. Add a lint step that fails or flags sources/pages with missing required fields, excessive boilerplate ratio, empty/near-empty main content, broken provenance, duplicate titles, or malformed frontmatter.
12. The pipeline must be idempotent:
   - unchanged sources are skipped or reported as unchanged,
   - changed/new sources are processed,
   - rerunning the pipeline should not duplicate registry/wiki/index records.
13. Support `Update Wiki` resume/update mode and `Build Wiki` full rebuild mode.
7. If a latest scrape run is available, the automated pipeline should be able to normalize web sources from that run without the user manually entering paths.
8. Always normalize PDF pages/chunks when available.
9. Allow tabular paths when available in the UI/state, but do not require them.
10. Wiki build must produce categorized Markdown pages, not only a JSONL index. For thousands of ready sources, generate thousands of `.md` source pages under `wiki/pages/<category>/...` plus category index/summary pages, so operators can browse the wiki as files.
11. Add rich semantic organization pages that connect related content across raw sources. At minimum, generate useful Markdown entry points for:
    - student audience/persona: new student, prospective grad student, current student, international student where inferable,
    - school/college: Cox, Dedman, Lyle, Meadows, Simmons, Perkins, etc. where source evidence exists,
    - program/degree and academic area,
    - task/intent: admissions, courses, fees/costs, scholarships/aid, registrar/calendar, contacts/offices,
    - cross-topic bundles such as `Cox graduate admissions + courses + fees`.
12. Each semantic page should include a student-friendly structure:
    - `Fast Answer`,
    - `Who This Applies To`,
    - `Courses / Curriculum`,
    - `Costs / Fees / Aid`,
    - `Admissions / Requirements / Deadlines`,
    - `Contacts / Offices`,
    - `Related Pages`,
    - `Sources`.
13. Build relationship metadata/frontmatter so retrieval can find relative content without relying only on plain BM25 text matching. Include audience, school, program, degree level, intent, topic tags, source IDs, related page paths, and canonical owner.
14. After wiki build, automatically build/update embeddings/index artifacts via `build_llm_wiki_index` or the existing pipeline equivalent. The JSONL index is a retrieval artifact, not a replacement for Markdown wiki pages.
11. After indexing, run a smoke query such as `What graduate catalog programs are available?` for the SMU workspace.
15. Write a single report that includes all stage statuses:
    - ingest/normalization counts,
    - cleanup counts and boilerplate removal summary,
    - standardization counts,
    - lint pass/fail counts and quality flags,
    - wiki pages created/updated,
    - index counts,
    - smoke query status/result summary,
    - runtime and event log paths.
16. UI status must show progress and outcome for each stage, not only the wiki build stage.
17. If any stage fails, stop subsequent dependent stages, mark the overall pipeline failed, and surface the error in the UI.
18. Prevent concurrent duplicate pipeline launches for the same site when a pipeline/report is already running.
19. Update `docs/planning/work-index.md` after completion so the queue, completion ledger, and stop point stay visible.
20. Keep existing separate advanced/manual internals if useful, but the normal UI should only expose Build Wiki and Update Wiki.
21. Respect `.specify/memory/constitution.md` Git Autonomy settings; do not commit or push unless explicitly enabled by the user.

## Acceptance Criteria

- [ ] The UI has a single automated action that runs Ingest → Clean → Standardize → Lint → Build Wiki → Build Index → Verify without requiring a terminal command.
- [ ] The UI exposes LLM Wiki v2 compile status for this action.
- [ ] The UI consistently uses **Ingest** as the standard top-level word for this pipeline.
- [ ] The UI labels or help text explains that cleanup, standardization, wiki building, and index updating are stages of the same end-to-end Ingest pipeline.
- [ ] The automated action runs using LLM Wiki v2 compile and emits/records progress for live review.
- [ ] The normal UI exposes LLM Wiki v2 compile as the wiki/ingest strategy, with lint/index-only clearly marked as fallback.
- [ ] When Pi compile is selected/launched, runtime status displays `pi`, not stale `python` values from older reports.
- [ ] For `data/sites/www.smu.edu`, running the automated pipeline updates/creates `raw_sources/registry.jsonl` without duplicate source records.
- [ ] Source content passed to wiki generation excludes obvious nav/header/footer/menu/cookie/social boilerplate while preserving useful academic/program content and provenance.
- [ ] Ready source documents conform to the common structure or include lint quality flags explaining any exceptions.
- [ ] The wiki includes student-question-oriented semantic pages that combine related sources by audience, school/college, program, task/intent, and topic.
- [ ] A Cox/prospective-graduate query can find organized Markdown content covering courses/curriculum, fees/costs, and admissions/process without requiring the user to manually inspect dozens of raw pages.
- [ ] Semantic wiki pages include relationship metadata/frontmatter for audience, school, program, intent, topic tags, related pages, and source IDs.
- [ ] The lint stage reports pass/fail counts and flags excessive boilerplate, empty main content, duplicate titles, missing provenance, and malformed metadata.
- [ ] For `data/sites/www.smu.edu`, the wiki artifacts are updated/created, including `wiki/index.md`, `wiki/log.md`, `wiki/review_queue.md`, and `wiki/reports/wiki-build-latest.json` or an end-to-end pipeline report linked from the UI.
- [ ] For `data/sites/www.smu.edu`, the wiki includes categorized Markdown source pages under `wiki/pages/<category>/...`; page count should scale with ready sources rather than collapsing thousands of sources into a handful of aggregate pages.
- [ ] For `data/sites/www.smu.edu`, index artifacts are updated/created, including `indexes/llm_wiki_manifest.json` and `indexes/llm_wiki_documents.jsonl`.
- [ ] The smoke query `What graduate catalog programs are available?` runs after indexing and records a useful answer or retrievable evidence in the report.
- [ ] A smoke query similar to `I am a new graduate student likely joining Cox; tell me about courses, course fees, and the admission process` retrieves organized wiki pages/evidence that cover all three aspects: courses, fees, and admissions.
- [ ] The UI displays per-stage status for Ingest, Clean, Standardize, Lint, Build Wiki, Build Index, and Verify.
- [ ] If the pipeline is already running for a site, clicking the automated action again does not start a duplicate concurrent run.
- [ ] `docs/planning/work-index.md` is updated with status and verification notes after completion.
- [ ] Unit tests cover cleanup/de-boilerplating, common-structure standardization, lint rules, and automated pipeline command/status report behavior.
- [ ] UI tests or smoke tests cover the automated action and per-stage status rendering.
- [ ] Syntax/compile checks pass for changed Python and Node paths.
- [ ] A runtime smoke check or dry run demonstrates the automated pipeline command for `data/sites/www.smu.edu` without exceptions.

## Suggested Implementation Notes

- Prefer using `run_wiki_ingestion_pipeline(...)` as the core stage implementation instead of duplicating stage logic.
- Prefer extending the existing LLM Wiki v2 compile runner/reporting before adding another runtime wrapper.
- Keep report formats backward-compatible with `_load_wiki_status(...)` and embedding/index status loaders.
- If adding a new report file, link it from the existing wiki latest report or UI status so operators can find it.

## Suggested Verification

```bash
source .venv/bin/activate
python -m py_compile \
  app.py \
  src/scrape_planner/wiki/wiki_ingestion_pipeline.py \
  src/scrape_planner/wiki/llm_wiki_builder.py \
  src/scrape_planner/wiki/llm_wiki_index.py
python -m pytest tests/test_llm_wiki_builder.py tests/test_llm_wiki_index.py tests/test_wiki_ui.py
python -m src.scrape_planner.wiki_ingestion_pipeline \
  --site-root data/sites/www.smu.edu \
  --kind auto \
  --resume \
  --query "What graduate catalog programs are available?"
```

For a no-write command-shape check, use a report/status-only runner path if the implementation adds one for the full pipeline.

## Status: TODO

<!-- NR_OF_TRIES: 2 -->
