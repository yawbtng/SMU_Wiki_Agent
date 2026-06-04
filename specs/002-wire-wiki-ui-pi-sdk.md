# Wire Wiki Building UI to LLM Wiki v2 Runtime

## Goal

Make the Wiki tab launch, monitor, and verify LLM Wiki builds through the LLM Wiki v2 noninteractive compile runtime for normal UI operation. Keep lint/index-only operation as an explicit fallback, not the default wiki product path.

## UI Target

Implement in the **FastAPI + React webapp** (`specs/006-fastapi-react-realtime-app.md`, worktree `ultra-fast-rag-webapp`). Do not add major new Streamlit UI for this spec. Streamlit (`app.py`) remains a read-only parity reference until feature parity is reached.

## Context

- Primary UI: `ultra-fast-rag-webapp/frontend/` Wiki tab + `src/scrape_planner/webapp/api.py` action/status endpoints.
- Legacy parity reference: `app.py`, Wiki workflow tab.
- Launcher: `src/scrape_planner/llm_wiki_builder.py::launch_wiki_builder`.
- Compile runner: `.pi/skills/llm-wiki-noninteractive/scripts/build_wiki.sh`.
- Target workspace for smoke verification: `data/sites/www.smu.edu`.
- Pi mode should run the LLM Wiki v2 compile, then Python lint/index/smoke checks, with status/tool events available to the UI.
- The Python lint/index-only path may remain as a fallback, but it should not be the normal wiki generation strategy.

## Requirements

1. Remove the normal Wiki tab deterministic framing or replace it with fixed LLM Wiki v2 compile status/control.
2. Wire only `Build Wiki` and `Update Wiki` buttons to call `launch_wiki_builder(...)` with `runtime="pi"`.
   - `Build Wiki` performs a full rebuild (`resume=False`, `rebuild=True`).
   - `Update Wiki` performs incremental/resume work (`resume=True`).
   - Do not expose a separate `Rebuild Wiki` button in the normal UI.
3. In Pi mode, `launch_wiki_builder(...)` must launch `.pi/skills/llm-wiki-noninteractive/scripts/build_wiki.sh` through tmux, passing:
   - `--site-root`
   - `--mode rebuild` or `--mode resume`
4. The UI must surface meaningful compile activity after launch and during polling:
   - runtime and job state
   - current compile stage, if any
   - stage/progress summaries
   - latest builder output in a collapsed/secondary view
   - assistant summary, if any
5. The Wiki tab must not show raw log dumps, operator details, or latest report JSON panels in normal operation.
6. The latest wiki status/report loader must prefer current report fields and avoid showing stale Python runtime values after a Pi launch.
7. The compile runner must update the latest report with enough status for the UI to render progress, success, or failure.
8. Preserve non-interactive behavior: no prompts in the UI-triggered wiki build path.
9. Keep raw source artifacts read-only; only derived `wiki/`, `indexes/`, report, and event-log artifacts may change during a build.

## Acceptance Criteria

- [ ] The Wiki tab frames LLM Wiki v2 compile as the normal strategy, with lint/index-only clearly marked as fallback.
- [ ] Clicking `Build Wiki` launches a tmux command containing `.pi/skills/llm-wiki-noninteractive/scripts/build_wiki.sh` with rebuild semantics.
- [ ] Clicking `Update Wiki` launches the compile runner with resume semantics.
- [ ] The Wiki tab does not expose a separate `Rebuild Wiki` button.
- [ ] Pi launch/status displays `runtime="pi"` and meaningful activity/progress without raw operator details.
- [ ] `data/sites/www.smu.edu/wiki/reports/wiki-build-latest.json` records compile status/progress fields usable by the UI.
- [ ] The Wiki tab activity panel renders meaningful compile stage/tool events when event data exists.
- [ ] The lint/index-only path remains usable for CI/fallback, but normal UI launch behavior is LLM Wiki v2 compile.
- [ ] Unit tests cover launcher command construction and report fields.
- [ ] UI tests or smoke tests cover the runtime selector/status rendering path.
- [ ] Syntax/compile checks pass for changed Python and Node paths.
- [ ] A runtime smoke check launches or dry-runs the LLM Wiki v2 compile runner for `data/sites/www.smu.edu` without exceptions.

## Suggested Verification

```bash
source .venv/bin/activate
python -m py_compile src/scrape_planner/wiki/llm_wiki_builder.py src/scrape_planner/wiki/llm_wiki_index.py
python -m pytest tests/test_llm_wiki_builder.py tests/test_wiki_ui.py
.pi/skills/llm-wiki-noninteractive/scripts/build_wiki.sh \
  --site-root data/sites/www.smu.edu \
  --mode rebuild \
  --skip-smoke
```

## Status: TODO

<!-- NR_OF_TRIES: 0 -->
