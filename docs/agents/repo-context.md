# Repository Context

## Layout

- Keep the repository root limited to `README.md`, `AGENTS.md`, `CLAUDE.md`, dependency manifests, `start.sh`, `stop.sh`, `status.sh`, and prompt seeds.
- All other docs live under `docs/`.
- Product code lives under `src/scrape_planner/` in domain subpackages: `core`, `scrape`, `pdf`, `sources`, `wiki`, `graph`, `index`, `tracer`, `runtime`, `ui`, `app`, and `infra`.
- See `docs/CODEBASE.md` for the module map.

## Runtime Facts

- The React/FastAPI app (`frontend/`, `src/scrape_planner/webapp/`) is the only operator UI.
- Streamlit (`app.py`, `ui_*.py`) has been removed. Do not reintroduce it.
- Start/stop/status from repo root: `./start.sh`, `./stop.sh`, `./status.sh`.
- Vite runs on port `5173`; backend API runs on port `8000`.
- Default data root is `data/` in this checkout unless `SCRAPE_PLANNER_DATA_ROOT` overrides it.
- `./scripts/verify-webapp.sh` is the main webapp verification gate.
- Docker delivery uses `Dockerfile` plus `docker-compose.yml`; default `WEBAPP_HOST_PORT` is `8000`.

## Operator Workflow Facts

- Prefer Pi skills under `.pi/skills/` for discovery, curation, wiki compile, and scrape planning.
- Keep FastAPI thin: job launch, artifact I/O, validators, and status reads.
- Operator Pi jobs use `POST /api/sites/{site_id}/jobs` with `{ skill, prompt }`.
- Status is `GET /api/sites/{site_id}/jobs/{skill}`; catalog is `GET /api/operator/skills`.
- Registered skills include `site-discovery`, `site-url-curation`, and `llm-wiki-noninteractive`.
- Metrics API under `/api/sites/{site_id}/metrics/*` covers Pi agent runs and embedding-index rebuilds only.

## Durable User Preferences

- Verify the intended repo/worktree before editing when multiple copies may exist.
- Treat only `/Users/abhsheno/Desktop/Projects/ultra-fast-rag` as trusted unless the user re-authorizes another path.
- Make visible UI/operator controls when the user asks for something "in the UI"; do not leave shell-only workarounds.
- For full-app testing, use browser evidence on the running app and walk affected workflow tabs.
- Keep the operator UI minimal: open on a WorkspaceDashboard with site cards and add-workspace, include a clear return-from-workspace control, and show actionable Pi/jobs/embeddings/MCP status without debug clutter.
- Prefer de-bloating stale code and stale UI over preserving misleading controls.
- Keep public README/root docs professional and concise.
- Student-facing answers need citations and low hallucination tolerance.
- Shared prompts and URL-curation copy must stay university-agnostic.
