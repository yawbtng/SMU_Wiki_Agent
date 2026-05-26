---
name: llm-wiki-noninteractive
description: Build or refresh this project's local LLM Wiki from normalized web/PDF/raw_sources artifacts in non-interactive mode. Use when the user wants to attach a Pi skill and run wiki generation, indexing, and smoke verification without prompts.
---

# LLM Wiki Non-Interactive

This skill operates the `ultra-fast-rag` deterministic wiki pipeline without asking follow-up questions.

## When to use

Use this when the user asks to:

- build the wiki from extracted web/PDF sources
- refresh or rebuild `data/sites/<site>/wiki/`
- run the LLM Wiki builder/indexer non-interactively from Pi
- attach a skill via `pi --skill ... -p ...`

## Rules

- Do not prompt the user during execution.
- Do not modify raw source files under `raw_sources/`, scrape runs, or `sources/pdf_uploads/`.
- Treat `wiki/` and `indexes/` as derived artifacts that may be rebuilt.
- Prefer the helper script below for repeatable non-interactive operation.
- Report exact commands run and final artifact paths.

## Non-interactive command

From the repository root:

```bash
.pi/skills/llm-wiki-noninteractive/scripts/build_wiki.sh \
  --site-root data/sites/www.smu.edu \
  --mode rebuild \
  --query "What graduate catalog programs are available?"
```

Modes:

- `--mode rebuild` fully rebuilds derived wiki pages from all normalized ready sources.
- `--mode resume` incrementally processes pending/changed sources only.

## Pi print-mode invocation

Attach this skill explicitly and run Pi in non-interactive print mode:

```bash
pi --no-skills \
  --skill .pi/skills/llm-wiki-noninteractive \
  -p '/skill:llm-wiki-noninteractive Build the SMU wiki non-interactively with --site-root data/sites/www.smu.edu --mode rebuild and run the smoke query "What graduate catalog programs are available?"'
```

If skill commands are disabled, use the same command without `/skill:...`; the explicit `--skill` still makes this skill available to the model.

## Expected outputs

For `data/sites/www.smu.edu`, check:

- `data/sites/www.smu.edu/wiki/index.md`
- `data/sites/www.smu.edu/wiki/log.md`
- `data/sites/www.smu.edu/wiki/review_queue.md`
- `data/sites/www.smu.edu/wiki/reports/wiki-build-latest.json`
- `data/sites/www.smu.edu/indexes/llm_wiki_manifest.json`
- `data/sites/www.smu.edu/indexes/llm_wiki_documents.jsonl`

## Verification

Always run or confirm these checks before reporting completion:

```bash
source .venv/bin/activate
python -m py_compile src/scrape_planner/llm_wiki_builder.py src/scrape_planner/llm_wiki_index.py
.pi/skills/llm-wiki-noninteractive/scripts/build_wiki.sh --site-root data/sites/www.smu.edu --mode resume --query "What graduate catalog programs are available?"
```
