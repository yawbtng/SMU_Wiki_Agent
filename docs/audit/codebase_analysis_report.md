# Codebase Duplicate Cleanup Report

This audit focused on backend duplicate helpers and unused exports that were safe to remove without changing runtime behavior.

## Fixed

- Centralized UTC timestamp helpers in `src/scrape_planner/core/time.py`.
- Centralized float environment parsing in `src/scrape_planner/core/env.py`.
- Centralized URL slug and approved-URL markdown parsing in `src/scrape_planner/core/url_utils.py`.
- Reused `site_root_for` from `src/scrape_planner/core/site_layout.py` instead of keeping a repository-local duplicate.
- Removed unused helper exports from runtime, scrape, source-quality, tmux, and app modules where no live code or tests referenced them.
- Removed unused modules:
  - `src/scrape_planner/scrape/url_approval_review.py`
  - `src/scrape_planner/wiki/wiki_graph_artifacts.py`
- Updated docs that referenced the removed modules.

## Preserved

- Kept `select_scored_urls` because the root `score_urls.py` CLI imports it.
- Kept the approved-URLs regex exported as `APPROVED_URL_RE` because both parsing and line-level matching need the same pattern.
- Left OpenSpec references to future reliability work intact, including `append_run_event`, because those are requirements for a future change rather than current runtime imports.

## Verification

- `python -m py_compile` over changed backend modules passed.
- Focused backend tests passed: `102 passed`.
- Full backend suite passed: `256 passed`.
- Webapp verification passed: `31 passed`, frontend production build passed.
