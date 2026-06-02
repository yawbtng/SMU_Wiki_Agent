## Why

Operators should run discovery, URL curation, and wiki builds through Pi skills in tmux—not inline OpenRouter calls and regex policy inside `webapp/api.py`. A thin FastAPI layer launches jobs, reads artifacts, and streams status.

## What Changes

- Add `POST /api/sites/{site_id}/jobs` and `GET /api/sites/{site_id}/jobs/{skill}`.
- Add `GET /api/operator/skills` registry.
- Scaffold `.pi/skills/site-discovery/` and `.pi/skills/site-url-curation/`.
- Remove `_llm_decide_url_chat` from the API; sync chat uses keyword intent + existing matchers; async work uses Pi jobs.
- Add `app/job_launcher.py` and `app/operator_skills.py`.

## Non-Goals (follow-on changes)

- Full split of `webapp/api.py` into route modules (task B).
- Deleting `markdown_graph.py` and root shims (task C).
- Folding all `code-review-hardening` interrogate items (wiki POST, PUT secrets, embedding flags)—tracked separately.

## Success Criteria

- `./scripts/verify-webapp.sh` passes.
- `pytest tests/test_webapp_api.py` includes jobs + approved-url chat without LLM mocks.
- No `import streamlit`; no OpenRouter URL chat in `api.py`.
