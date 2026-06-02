# Operator UI simplification (React / FastAPI)

The operator UI is **React + Vite + FastAPI** (`frontend/`, `src/scrape_planner/webapp/`). Streamlit was removed; do not reintroduce `app.py` or Streamlit tabs.

## Goals

- One primary path per concern: discover → approve → scrape → sources → wiki → embeddings → MCP.
- Tabs show **actionable status** (Pi progress, jobs, index health) without debug clutter.
- Settings hold provider keys, scrape options, tmux lifecycle, and MCP controls.

## Historical reference

The original Streamlit tab-rename plan lives in [../archive/streamlit/simple-ui-cleanup-plan.md](../archive/streamlit/simple-ui-cleanup-plan.md). Use it only for intent, not for ports or Streamlit APIs.

## Verification

- `./scripts/verify-webapp.sh` — API tests + frontend build
- `./start.sh` — local operator stack (Vite **5173**, API **8000**)
