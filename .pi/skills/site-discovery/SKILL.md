---
name: site-discovery
description: Discover university site URLs from robots/sitemaps and write discovered_urls.json for operator review.
---

# Site Discovery

Thin shell discovers URLs; Pi may refine exclusions before scrape planning.

## Command

```bash
.pi/skills/site-discovery/scripts/discover_site.sh \
  --site-root data/sites/www.example.edu
```

Optional seed:

```bash
.pi/skills/site-discovery/scripts/discover_site.sh \
  --site-root data/sites/www.example.edu \
  --site-url https://www.example.edu
```

## Artifacts

- `{site_root}/discovered_urls.json`
- `{site_root}/discovery_summary.json`
- `{site_root}/jobs/reports/site-discovery-latest.json` (runtime status)

## API launch

```http
POST /api/sites/{site_id}/jobs
{"skill": "site-discovery", "prompt": "Discover registrar and financial-aid URLs"}
```
