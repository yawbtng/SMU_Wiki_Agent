## 1. Operator jobs API

- [x] 1.1 Add `operator_skills.py` and `job_launcher.py`
- [x] 1.2 Add `webapp/jobs.py` payloads
- [x] 1.3 Wire routes in `api.py` (`/api/operator/skills`, `/api/sites/{id}/jobs`)
- [x] 1.4 Remove `_llm_decide_url_chat` and OpenRouter URL chat

## 2. Pi skills

- [x] 2.1 Scaffold `site-discovery` skill + `discover_site.sh`
- [x] 2.2 Scaffold `site-url-curation` skill + `curate_urls.sh`
- [x] 2.3 Update `.gitignore` whitelists for new skills

## 3. Verification

- [x] 3.1 Add/extend `tests/test_webapp_api.py` for jobs API
- [x] 3.2 Run `./scripts/verify-webapp.sh`
- [x] 3.3 `openspec validate operator-agent-runtime --strict`

## 4. Follow-on (not this change)

- [x] 4.1 Split `webapp/api.py` into route modules (`deps`, `schemas`, `approved_urls`, `embeddings`, `routes`, `jobs`)
- [x] 4.2 Delete `markdown_graph.py` cluster and root import shims
- [ ] 4.3 Fold interrogate reliability findings into specs (embedding SSE, wiki POST, PUT secrets — separate change)
