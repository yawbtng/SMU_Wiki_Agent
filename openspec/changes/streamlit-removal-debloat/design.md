## Context

React/FastAPI is canonical per `AGENTS.md`. Streamlit remains as `app.py` (4,663 lines) plus five `ui_*` modules only used by Streamlit. `webapp/api.py` already serves the operator UI but still imports `ui_navigation.WORKFLOW_TABS`.

## Goals / Non-Goals

**Goals:** Remove Streamlit from default install and CI; single navigation contract in `app/`; shrink test surface to webapp + domain tests.

**Non-Goals:** Deleting scrape/index engines; migrating discovery to Pi skills (Phase 3 separate change).

## Decisions

### Decision 1: Delete Streamlit, do not archive in-repo
Archive in git history is sufficient. A `legacy/` copy invites continued imports.

### Decision 2: WORKFLOW_TABS lives in `app/navigation.py`
Shared between FastAPI `/api/navigation` and frontend; not under `ui_*`.

### Decision 3: Streamlit tests deleted, not skipped
AST tests on `app.py` have no value after removal. Domain tests for `stepper_status`, discovery, etc. remain under non-UI test modules.

### Decision 4: Optional `requirements-streamlit.txt` omitted
No supported Streamlit path; reduces confusion.

## Risks

| Risk | Mitigation |
|------|------------|
| Scripts/docs reference `streamlit run` | Update README and top-level docs |
| Docker compose still exposes 8501 | Note in README; compose update in follow-up |
| Root shims still used by tests | Phase 2 import cleanup |
