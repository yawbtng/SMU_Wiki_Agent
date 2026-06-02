# Build SMU LLM Wiki

## Goal

Refresh the local LLM Wiki for the SMU workspace from existing normalized source artifacts, then verify the wiki and index outputs are queryable.

## Context

- Site root: `data/sites/www.smu.edu`
- Preferred workflow: use the local Pi skill `.pi/skills/llm-wiki-noninteractive`
- Derived outputs under `wiki/` and `indexes/` may be rebuilt.
- Do **not** modify raw source artifacts under `raw_sources/`, scrape run folders, or `sources/pdf_uploads/`.

## Requirements

1. Run the deterministic non-interactive wiki pipeline for `data/sites/www.smu.edu`.
2. Prefer rebuild mode for the first Ralph run so the derived wiki is refreshed from normalized ready sources.
3. Generate/refresh the LLM Wiki pages, reports, manifest, and document index artifacts.
4. Run a smoke query against the generated wiki/index.
5. Run the relevant syntax/compile checks for changed wiki code paths before completion.
6. Record completion in `docs/planning/history.md` and `docs/planning/completion_log/` if the build succeeds.
7. Respect `.specify/memory/constitution.md` Git Autonomy settings; do not commit or push unless explicitly enabled by the user.

## Suggested Commands

```bash
source .venv/bin/activate
python -m py_compile src/scrape_planner/llm_wiki_builder.py src/scrape_planner/llm_wiki_index.py
.pi/skills/llm-wiki-noninteractive/scripts/build_wiki.sh \
  --site-root data/sites/www.smu.edu \
  --mode rebuild \
  --query "What graduate catalog programs are available?"
```

If rebuild succeeds, a follow-up resume smoke check is acceptable:

```bash
.pi/skills/llm-wiki-noninteractive/scripts/build_wiki.sh \
  --site-root data/sites/www.smu.edu \
  --mode resume \
  --query "What graduate catalog programs are available?"
```

## Acceptance Criteria

- [ ] `data/sites/www.smu.edu/wiki/index.md` exists and is non-empty.
- [ ] `data/sites/www.smu.edu/wiki/log.md` exists and records the latest build activity.
- [ ] `data/sites/www.smu.edu/wiki/review_queue.md` exists.
- [ ] `data/sites/www.smu.edu/wiki/reports/wiki-build-latest.json` exists and indicates a successful/latest build state.
- [ ] `data/sites/www.smu.edu/indexes/llm_wiki_manifest.json` exists and is non-empty.
- [ ] `data/sites/www.smu.edu/indexes/llm_wiki_documents.jsonl` exists and is non-empty.
- [ ] The smoke query `What graduate catalog programs are available?` runs without exceptions and returns a useful answer or retrievable supporting content.
- [ ] `python -m py_compile src/scrape_planner/llm_wiki_builder.py src/scrape_planner/llm_wiki_index.py` passes.
- [ ] No raw source artifacts are modified.
- [ ] `docs/planning/history.md` and a timestamped `docs/planning/completion_log/` entry summarize the build and verification.

## Status: TODO

<!-- NR_OF_TRIES: 0 -->
