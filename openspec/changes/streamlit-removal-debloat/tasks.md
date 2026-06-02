## 1. Streamlit removal

- [x] 1.1 Add `app/navigation.py` with `WORKFLOW_TABS`; update `webapp/api.py` import.
- [x] 1.2 Delete `app.py` and `src/scrape_planner/ui_*.py`.
- [x] 1.3 Delete root `wiki_markdown_ui.py` shim and `wiki/wiki_markdown_ui.py`.
- [x] 1.4 Remove streamlit packages from `requirements.txt`.
- [x] 1.5 Delete Streamlit-only tests; preserve domain tests in `test_stepper_status.py`.
- [x] 1.6 Fix `repo_root()` to use `start.sh` instead of `app.py`.
- [x] 1.7 Update README (React-only).

## 2. Verification

- [x] 2.1 `./scripts/verify-webapp.sh`
- [x] 2.2 `pytest` on remaining domain tests (webapp, wiki, scrape, index).
- [x] 2.3 `openspec validate streamlit-removal-debloat --strict`

## 3. Follow-on (separate changes)

- [x] 3.1 Remove root import shims; canonical subpackage imports.
- [x] 3.2 Split `webapp/api.py`; Pi skills for discovery/curation (`operator-agent-runtime`).
- [x] 3.3 Remove `markdown_graph.py` / `graph_profile.py` cluster.
