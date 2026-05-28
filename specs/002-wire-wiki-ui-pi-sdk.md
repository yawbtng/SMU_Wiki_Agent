# Wire Wiki Building UI to Pi SDK Runtime

## Goal

Make the Streamlit Wiki tab launch, monitor, and verify LLM Wiki builds through the Pi SDK streaming runtime only for normal UI operation. Remove the user-facing deterministic Python runtime path from the Wiki UI.

## Context

- Main UI: `app.py`, Wiki workflow tab.
- Launcher: `src/scrape_planner/llm_wiki_builder.py::launch_wiki_builder`.
- Pi SDK runner: `scripts/pi-sdk-wiki-runner.mjs`.
- Target workspace for smoke verification: `data/sites/www.smu.edu`.
- Pi SDK mode should wrap the deterministic builder in an observable Pi AgentSession and stream status/tool events to a JSONL event log.
- The deterministic Python builder may remain as an internal implementation detail/tool invoked by the Pi SDK runner, but it should not be exposed as the normal UI runtime choice.

## Requirements

1. Remove the normal Wiki tab runtime selector or replace it with a fixed Pi SDK streaming status/control. The UI should not offer `Python deterministic` as a normal operator choice.
2. Wire only `Build Wiki` and `Update Wiki` buttons to call `launch_wiki_builder(...)` with `runtime="pi-sdk"`.
   - `Build Wiki` performs a full rebuild (`resume=False`, `rebuild=True`).
   - `Update Wiki` performs incremental/resume work (`resume=True`).
   - Do not expose a separate `Rebuild Wiki` button in the normal UI.
3. In Pi SDK mode, `launch_wiki_builder(...)` must launch `scripts/pi-sdk-wiki-runner.mjs` through tmux, passing:
   - `--site-root`
   - `--registry-path`
   - `--wiki-dir`
   - `--report-path`
   - `--event-log-path`
   - `--tmux-session`
   - `--python-executable`
   - `--resume` or `--rebuild` as appropriate
4. The UI must surface meaningful Pi SDK activity after launch and during polling:
   - runtime and job state
   - current Pi SDK tool, if any
   - stage/progress summaries
   - latest builder output in a collapsed/secondary view
   - assistant summary, if any
5. The Wiki tab must not show raw log dumps, operator details, or latest report JSON panels in normal operation.
6. The latest wiki status/report loader must prefer Pi SDK report fields and avoid showing stale Python runtime values after a Pi SDK launch.
7. The Pi SDK runner must update the latest report with enough status for the UI to render progress, success, or failure.
8. Preserve non-interactive behavior: no prompts in the UI-triggered wiki build path.
9. Keep raw source artifacts read-only; only derived `wiki/`, `indexes/`, report, and event-log artifacts may change during a build.

## Acceptance Criteria

- [ ] The Wiki tab no longer exposes `Python deterministic` as a normal runtime choice.
- [ ] Clicking `Build Wiki` launches a tmux command containing `node scripts/pi-sdk-wiki-runner.mjs` with rebuild semantics.
- [ ] Clicking `Update Wiki` launches the SDK runner with `--resume`.
- [ ] The Wiki tab does not expose a separate `Rebuild Wiki` button.
- [ ] Pi SDK launch/status displays `runtime="pi-sdk"` and meaningful activity/progress without raw operator details.
- [ ] `data/sites/www.smu.edu/wiki/reports/pi-sdk-events-latest.jsonl` is created during a Pi SDK build and contains JSONL event rows.
- [ ] `data/sites/www.smu.edu/wiki/reports/wiki-build-latest.json` records Pi SDK status/progress fields usable by the UI.
- [ ] The Wiki tab Agent Activity panel renders meaningful Pi SDK stage/tool events when the event log exists.
- [ ] The deterministic Python builder remains usable internally by the Pi SDK runner, but normal UI launch behavior is Pi SDK streaming only.
- [ ] Unit tests cover Pi SDK launcher command construction and report fields.
- [ ] UI tests or smoke tests cover the runtime selector/status rendering path.
- [ ] Syntax/compile checks pass for changed Python and Node paths.
- [ ] A runtime smoke check launches or dry-runs the Pi SDK runner for `data/sites/www.smu.edu` without exceptions.

## Suggested Verification

```bash
source .venv/bin/activate
python -m py_compile app.py src/scrape_planner/llm_wiki_builder.py src/scrape_planner/llm_wiki_index.py
python -m pytest tests/test_llm_wiki_builder.py tests/test_wiki_ui.py
node --check scripts/pi-sdk-wiki-runner.mjs
node scripts/pi-sdk-wiki-runner.mjs \
  --site-root data/sites/www.smu.edu \
  --registry-path data/sites/www.smu.edu/raw_sources/registry.jsonl \
  --wiki-dir data/sites/www.smu.edu/wiki \
  --report-path data/sites/www.smu.edu/wiki/reports/wiki-build-latest.json \
  --event-log-path data/sites/www.smu.edu/wiki/reports/pi-sdk-events-latest.jsonl \
  --tmux-session ralph-wiki-sdk-smoke \
  --python-executable "$(command -v python3)" \
  --rebuild \
  --dry-run
```

## Status: TODO

<!-- NR_OF_TRIES: 0 -->
