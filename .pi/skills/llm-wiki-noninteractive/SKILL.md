---
name: llm-wiki-noninteractive
description: Build or refresh this project's local LLM Wiki via Pi llm-wiki-v2 compile, Python lint, and hybrid index.
---

# LLM Wiki Non-Interactive

Orchestrates [LLM Wiki v2](https://gist.githubusercontent.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2/raw/99d0366312ec10bd13326e74bfecb67ed4f587a2/llm-wiki.md):

1. **Pi llm-wiki-v2** — compile wiki pages from `raw_sources/`
2. **Python lint** — orphans, citations, stale checksums
3. **Python index** — hybrid BM25 + vector search

Python `llm_wiki_builder.py` is orchestration only (~100 lines); it does not render markdown.

## Command

```bash
.pi/skills/llm-wiki-noninteractive/scripts/build_wiki.sh \
  --site-root data/sites/www.smu.edu \
  --mode rebuild
```

`--skip-pi` for lint/index-only (CI). `--skip-smoke` to skip query check.

## Pi invocation

```bash
pi --no-skills --skill .pi/skills/llm-wiki-noninteractive \
  -p 'Run build_wiki.sh --site-root data/sites/www.smu.edu --mode rebuild'
```
