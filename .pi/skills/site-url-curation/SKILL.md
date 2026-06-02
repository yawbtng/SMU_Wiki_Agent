---
name: site-url-curation
description: Curate approved_urls.md from discovered_urls using an operator prompt (Pi agent; no inline API LLM).
---

# Site URL Curation

The operator prompt drives approve/remove decisions. Python applies deterministic matching only after Pi (or sync API) classifies intent.

## Command

```bash
.pi/skills/site-url-curation/scripts/curate_urls.sh \
  --site-root data/sites/www.example.edu \
  --prompt "approve registrar calendar and housing"
```

## Artifacts

- `{site_root}/approved_urls.md`
- `{site_root}/approved_urls_chat.jsonl` (audit trail when launched from API)
- `{site_root}/jobs/reports/site-url-curation-latest.json`

## API launch

```http
POST /api/sites/{site_id}/jobs
{"skill": "site-url-curation", "prompt": "approve schools", "autosave": true}
```

For interactive chat in React, prefer launching this job and polling job status + reading `approved_urls.md`.
