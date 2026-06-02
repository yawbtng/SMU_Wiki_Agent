## Architecture

```
React → POST /api/sites/{id}/jobs { skill, prompt }
     → job_launcher → tmux + pi --skill .pi/skills/<name>
     → artifacts under data/sites/<id>/
     → GET /api/sites/{id}/jobs/{skill} (report JSON + stale tmux detection)
```

## Skill registry

| skill | Script | Artifacts |
|-------|--------|-----------|
| `site-discovery` | `discover_site.sh` | `discovered_urls.json`, `discovery_summary.json`, `jobs/reports/site-discovery-latest.json` |
| `site-url-curation` | `curate_urls.sh` | `approved_urls.md`, `jobs/reports/site-url-curation-latest.json` |
| `llm-wiki-noninteractive` | `build_wiki.sh` (via `wiki_launcher`) | `wiki/reports/wiki-build-latest.json` |

## Sync vs async

- **Sync:** `POST .../approved-urls/chat` keeps deterministic approve/remove via `_operator_intent_from_message` (no network LLM).
- **Async:** React and operators should prefer `POST .../jobs` with `site-url-curation` or `site-discovery` for Pi-driven work.

## Interrogate findings (deferred)

- `auto_rebuild_embeddings` vs `embedding_enabled` mismatch on SSE.
- Missing `POST /wiki/build` alias for React.
- PUT `app-state` secret clobber when GET redacts to `"set"`.
- Wiki session stale / lock recovery / shared `wiki-build-latest.json` race.

These belong in a follow-on `webapp-operator-reliability` spec, not deterministic Python patches.
