# Codebase Recovery Preflight

Date: 2026-05-22
Checkout: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`
Branch: `codex/active-25k-smu-build`
Dirty status: untracked `docs/superpowers/plans/2026-05-22-codebase-recovery-subagent-execution.md`
Active port check: no listener on `127.0.0.1:8501` at preflight time
Listener cwd: n/a

## Recent commits

- `6efbbd1` merge: consolidate detached worktree 67f9 into main
- `ff15970` merge: consolidate metrics worktree into main
- `54c3c40` merge: consolidate operator redesign into main
- `5d3e057` snapshot: preserve detached worktree 67f9 before consolidation
- `dcb47dd` snapshot: preserve metrics worktree state before consolidation
- `92723c4` snapshot: preserve operator redesign worktree state before consolidation
- `1646f0d` fix: keep operator runtime routes responsive
- `5fcf383` style: polish operator dashboard hierarchy

## Baseline verification matrix

- Compile check passed:
  - `app.py`
  - `src/scrape_planner/ui_navigation.py`
  - `src/scrape_planner/stepper_status.py`
  - `src/scrape_planner/run_analytics.py`
  - `scripts/validate_llm_wiki_stepper.py`
- Wave 1 baseline command:
  - `PYTHONPATH=. /usr/bin/python3 -m pytest tests/test_operator_navigation_ui.py tests/test_wiki_ui.py tests/test_retrieval_ui.py tests/test_stepper_ui.py -q`
- Wave 1 baseline result:
  - `18 passed`
  - `8 failed`
- Known failing tests:
  - all 8 failures are in `tests/test_stepper_ui.py`
- Failure classification:
  - stale assertions expecting the old stepper/workflow labels
  - stale source-structure assumptions tied to old tab ordering
  - stale graph/query copy prohibitions that no longer match the current operator retrieval surface

## Exact failing tests

- `test_stepper_tabs_use_llm_wiki_workflow_order`
- `test_llm_wiki_is_primary_post_source_action`
- `test_llm_wiki_action_blocks_until_raw_sources_are_ready`
- `test_stepper_copy_does_not_present_graph_as_primary_retrieval_path`
- `test_supporting_graph_does_not_expose_primary_query_workbench`
- `test_sources_tab_presents_clean_intake_sections`
- `test_sources_tab_hides_technical_pdf_and_scrape_details_by_default`
- `test_sources_ui_has_next_action_helper`

## Verification commands used

```bash
git status --short --branch
git rev-parse --show-toplevel
git branch --show-current
git log --oneline -8
lsof -nP -iTCP:8501 || true
/usr/bin/python3 -m py_compile app.py src/scrape_planner/ui_navigation.py src/scrape_planner/stepper_status.py src/scrape_planner/run_analytics.py scripts/validate_llm_wiki_stepper.py
PYTHONPATH=. /usr/bin/python3 -m pytest tests/test_operator_navigation_ui.py tests/test_wiki_ui.py tests/test_retrieval_ui.py tests/test_stepper_ui.py -q
```

## Wave 1 handoff

- Canonical operator tabs are currently defined in `src/scrape_planner/ui_navigation.py` as:
  - `Overview`
  - `Sources`
  - `Runs`
  - `Corpus`
  - `Wiki`
  - `Retrieval`
  - `Settings`
- Existing operator-navigation tests already encode the current product direction.
- `tests/test_stepper_ui.py` should be quarantined or rewritten to preserve only still-useful assertions:
  - status/readiness artifact coverage
  - security-sensitive or prohibited legacy copy checks that still fit the current UI
  - tab ownership expectations that do not conflict with current operator navigation
