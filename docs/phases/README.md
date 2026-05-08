# Scrape Cockpit Rebuild Phases

These phase files are written so multiple workers can execute in parallel with clearer ownership.

## Recommended Parallel Assignment

- `phase1-live-scrape-cockpit.md`: Scrape tab visibility and live cockpit.
- `phase2-page-inspector-drawer.md`: Inspector and preview inside Scrape tab.
- `phase3-worker-pool-concurrency.md`: Worker pool and page state contract.
- `phase4-pause-resume-durable-runs.md`: Durable state, pause, resume.
- `phase5-failure-triage-retry.md`: Failure workflow and retries.
- `phase6-navigation-and-app-structure.md`: Navigation cleanup and module extraction.
- `phase7-metrics-and-run-analytics.md`: Metrics and run analytics.
- `phase8-tests-and-quality-gates.md`: Tests and smoke gates.

## Parallel Safety Notes

The highest-conflict files are:

- `app.py`
- `src/scrape_planner/scrape_worker.py`
- `src/scrape_planner/state.py`

To reduce merge pain:

- Prefer adding helper modules over expanding `app.py`.
- Keep session state keys stable.
- Keep page row field names stable.
- Add fields instead of renaming fields when possible.
- Do not delete tabs/features until Phase 6 consolidates them.

## Shared Page State Contract

Workers should converge on this page row shape:

```json
{
  "url": "https://example.edu/page",
  "status": "queued|running|success|failed|cancelled|skipped",
  "worker_id": "worker_1",
  "attempt": 1,
  "fetch_mode": "fetcher|dynamic|stealthy|tavily",
  "http_status": 200,
  "failure_reason": null,
  "error": null,
  "text_length": 1234,
  "link_density": 0.12,
  "raw_html_path": "data/sites/.../raw_html/hash.html",
  "markdown_path": "data/sites/.../markdown/hash.md",
  "metadata_path": "data/sites/.../metadata/hash.json",
  "started_at": "2026-05-08T00:00:00+00:00",
  "updated_at": "2026-05-08T00:00:05+00:00",
  "finished_at": "2026-05-08T00:00:08+00:00",
  "duration_ms": 8000
}
```

## Shared Event Contract

Events should include:

```json
{
  "ts": "2026-05-08T00:00:00+00:00",
  "event": "page_started",
  "status": "running",
  "url": "https://example.edu/page",
  "worker_id": "worker_1",
  "attempt": 1,
  "fetch_mode": "fetcher",
  "http_status": null,
  "failure_reason": null,
  "error": null,
  "duration_ms": null
}
```

## Merge Order

Best final merge order:

1. Phase 3
2. Phase 4
3. Phase 1
4. Phase 2
5. Phase 5
6. Phase 7
7. Phase 8
8. Phase 6

Phase 6 should ideally land late because it moves UI surfaces around.

