# S01 Research: Source ledger and run log foundation

## Summary

S01 should be implemented as a new raw-first source monitoring layer beside the existing scrape-run machinery, not by mutating the current `ScrapeRunner` path. The codebase already has useful primitives for durable JSON/JSONL writes (`src/scrape_planner/run_persistence.py`, `src/scrape_planner/storage.py`) and a precedent for run roots under `data/sites/<site>/<run_id>/`, but it does not yet have a source ledger, content-hash diffing, deletion-candidate tracking, redirected-source records, or `run.json`/`source_diff.jsonl`/`build_report.md` contracts.

The safest path is to add a small module with pure functions/classes for source records, ledger loading/writing, source classification, run-event writing, and report generation, plus fixture tests that exercise all required statuses without live HTTP. Keep this slice file-artifact-first and dependency-light so S02/S03 can consume stable `source_id` and `content_hash` values.

## Active Requirements Owned / Supported

- **R001 Raw sources are source truth:** S01 creates the raw source ledger; do not make `cleanup_manifest.json` authoritative.
- **R002 V1 stays simple:** Use JSON/JSONL and fixture-driven local proof, no scheduler/database/UI.
- **R003 Source ledger detects lifecycle changes:** Primary owner. Must classify `new`, `unchanged`, `changed`, `redirected`, `failed`, and `deleted_candidate`.
- **R004 Every run writes durable logs:** Primary owner. Must write `run.json`, `events.jsonl`, `source_diff.jsonl`, and `build_report.md` even on partial/failure cases.
- **R006/R007/R008 downstream support:** Stable `source_id`, `url`, `content_hash`, and status fields are inputs to stale dependency tracking and job packets.
- **R011/R012/R014 support:** Same event/report conventions will be reused by PDF quarantine/config/proof flows; keep outputs bounded and parseable.

## Skill Discovery / Relevant Practices

- Installed skills directly relevant to this slice:
  - `observability`: reinforces durable, agent-readable event logs and explicit failure modes. Apply by logging phase transitions and per-source failures into JSONL with timestamps and machine-readable fields.
  - `error-handling-patterns`: relevant for classifying source-check errors without aborting the whole run.
  - `python-testing-patterns`: relevant for fixture tests around pure diff logic and artifact parsing.
  - `write-docs`: relevant for writing `build_report.md` so a fresh agent can understand a run without hidden context.
- Core technology is standard Python + filesystem JSON/JSONL + pytest-style tests. No missing external professional skill is needed for S01.

## Existing Code / Implementation Landscape

### Useful existing files

- `src/scrape_planner/run_persistence.py`
  - Provides thread-safe-ish `_write_json_atomic`, `_append_jsonl`, `_read_jsonl` helpers and public helpers for `run_status.json`, `events.jsonl`, `pages.jsonl`.
  - Current event file name already matches S01 (`events.jsonl`), but current run status file is `run_status.json`, not S01's required `run.json`.
  - `_read_jsonl` skips malformed rows rather than failing; fine for UI resilience, but S01 tests should also parse artifacts strictly to catch bad writes.

- `src/scrape_planner/storage.py`
  - `write_json()` already does atomic JSON replacement with a PID/UUID temp file.
  - `ensure_run_dirs()` only creates scrape-specific dirs (`raw_html`, `markdown`, `metadata`); do not expand it too broadly unless S01 is intentionally sharing run roots.

- `src/scrape_planner/models.py`
  - Existing `DiscoveredURL` and `PageResult` are scrape-run shapes. They lack source IDs, canonical URLs, content hashes, first/last-seen timestamps, and consecutive missing counts.
  - Recommendation: add new dataclasses/types for S01 rather than overloading `PageResult`.

- `src/scrape_planner/scrape_worker.py`
  - Shows current run-root convention: `base_data_dir / "sites" / site_id / run_id`.
  - Current `_slug_from_url()` is `sha1(url)[:12]`; useful precedent, but source IDs should be stable and collision-resistant enough for downstream. Prefer `src_` + 12-16 hex chars from normalized canonical URL, and store the full URL too.
  - Writes `scrape_manifest.json` only at the end, while S01 needs run artifacts during/after diffing.

- `docs/phases/README.md` and `docs/phases/phase4-pause-resume-durable-runs.md`
  - Define existing page/event contracts. Reuse the event style: `ts`, `event`, `status`, URL/source identifiers, failure reason, duration.
  - Existing durable scrape artifacts: `run_status.json`, `pages.jsonl`, `events.jsonl`, `failures.json`, `scrape_manifest.json`, `selected_urls.json`.

- `app.py`
  - Uses `read_run_status`, `read_page_states`, `read_run_events` for the scrape cockpit.
  - Watch-out: `_load_run_analytics_inputs()` calls `read_json(run_root / "pages.jsonl", [])` and `read_json(run_root / "events.jsonl", [])`; `read_json` is not a JSONL reader and may only decode the first JSON object. S01 should not depend on this UI path.

### Missing for S01

- No `source_ledger.jsonl`/`source_ledger.json` contract.
- No content-hash computation over raw markdown/source content.
- No previous-ledger vs current-record diffing.
- No deleted-candidate threshold logic.
- No redirect/canonical URL recording in a source diff.
- No `run.json` status/summary artifact.
- No `source_diff.jsonl` artifact.
- No `build_report.md` for source lifecycle changes.
- No fixture source records under `tests/fixtures`.
- No proof command yet; S01 can expose a CLI/function now and S06 can wrap it later.

## Recommended S01 Contract

Keep the contract small and downstream-friendly.

### Source input record (fixture/current observation)

```json
{
  "url": "https://example.edu/admissions",
  "content_path": "fixtures/raw/admissions.md",
  "observed_at": "2026-05-15T00:00:00+00:00",
  "http_status": 200,
  "final_url": "https://example.edu/admissions/",
  "error": null
}
```

For fixture tests, `content` can be inline or via `content_path`; implementation can normalize to observed source records.

### Ledger row

```json
{
  "source_id": "src_ab12cd34ef56",
  "url": "https://example.edu/admissions",
  "canonical_url": "https://example.edu/admissions/",
  "content_hash": "sha256:...",
  "status": "active|failed|deleted_candidate",
  "first_seen_at": "...",
  "last_seen_at": "...",
  "last_changed_at": "...",
  "last_success_at": "...",
  "consecutive_failures": 0,
  "consecutive_missing": 0,
  "error": null,
  "metadata": {"http_status": 200}
}
```

### Source diff event row (`source_diff.jsonl`)

```json
{
  "ts": "...",
  "source_id": "src_ab12cd34ef56",
  "url": "https://example.edu/admissions",
  "status": "new|unchanged|changed|redirected|failed|deleted_candidate",
  "previous_hash": null,
  "current_hash": "sha256:...",
  "previous_url": null,
  "current_url": "https://example.edu/admissions/",
  "http_status": 200,
  "error": null
}
```

Notes:
- Treat `redirected` as an additional diff status when `final_url/canonical_url` changes; if content also changes, either emit `redirected` with hash fields or emit two rows (`redirected`, `changed`). For S01 acceptance, one row with both URL and hash fields is enough if report counts are clear.
- Treat HTTP 404/410/missing as `failed` until `delete_candidate_after_failures` or `delete_candidate_after_missing` threshold is reached, then classify as `deleted_candidate`. Never delete ledger rows in S01.
- Failed checks should preserve previous successful `content_hash` in the ledger so downstream pages are not falsely marked changed.

### Run artifact (`run.json`)

```json
{
  "run_id": "source-monitor-fixture-001",
  "started_at": "...",
  "finished_at": "...",
  "status": "completed|completed_with_failures|failed",
  "config": {"delete_candidate_after_failures": 2},
  "counts": {
    "new": 1,
    "unchanged": 1,
    "changed": 1,
    "redirected": 1,
    "failed": 1,
    "deleted_candidate": 1
  },
  "artifact_paths": {
    "ledger": "source_ledger.jsonl",
    "events": "events.jsonl",
    "diff": "source_diff.jsonl",
    "report": "build_report.md"
  }
}
```

### Events (`events.jsonl`)

Follow existing event style but source-oriented:

- `source_run_started`
- `source_loaded_previous_ledger`
- `source_observed`
- `source_classified`
- `source_diff_written`
- `source_ledger_written`
- `source_run_finished`
- `source_run_failed` if an unexpected top-level exception occurs

Each event should include `ts`, `event`, `status`, optional `source_id`, `url`, `failure_reason`, and `error`.

## Natural Seams for Planner

1. **Pure model/diff module**
   - Add e.g. `src/scrape_planner/source_monitor.py` or `src/scrape_planner/source_ledger.py`.
   - Responsibilities: normalize URL/source ID, hash content, load prior ledger, classify observations, update ledger rows, produce diff rows and counts.
   - This can be built/tested without filesystem run directory concerns.

2. **Artifact writer/run logger**
   - Add helpers that write `run.json`, `events.jsonl`, `source_diff.jsonl`, `source_ledger.jsonl`, `build_report.md`.
   - Can reuse `storage.write_json` and JSONL append patterns from `run_persistence.py`.
   - Consider exposing generic JSONL helpers publicly instead of using underscored functions.

3. **Fixture/proof runner**
   - Add a function/CLI that accepts fixture current records + previous ledger path/run root and writes the required run directory.
   - Keep it free of live HTTP; live source checking can come later.

4. **Tests and fixtures**
   - Add fixture records that cover new/changed/unchanged/failed/deleted-candidate/redirected.
   - Tests should parse all JSON/JSONL artifacts, assert counts and report content, and verify failed sources do not erase prior hashes.

## First Proof / Highest-Risk Unblocker

First implement the pure diff/classification function and a single integration test that creates:

- a prior ledger with:
  - one unchanged source,
  - one source whose fixture content changes,
  - one source already missing once,
  - one source whose canonical URL will redirect,
- a current observation set with:
  - one new source,
  - one failed source,
  - one repeated missing/404 source crossing the deleted-candidate threshold.

Expected proof: run directory contains parseable `run.json`, `events.jsonl`, `source_diff.jsonl`, updated `source_ledger.jsonl`, and `build_report.md` with counts for all statuses. This unlocks S02/S03 because they can rely on stable source IDs/hashes.

## Verification Recommendations

Baseline observed in this environment:

- `python3 -m pytest tests/test_scrape_worker.py tests/test_observability.py -q` currently fails because pytest is not installed in the active Python (`No module named pytest`). `requirements.txt` does not include pytest.
- Direct compile of relevant modules succeeds:
  - `src/scrape_planner/run_persistence.py`
  - `src/scrape_planner/storage.py`
  - `src/scrape_planner/models.py`
  - `src/scrape_planner/scrape_worker.py`

Suggested commands after implementation:

```bash
python3 - <<'PY'
from pathlib import Path
for p in [
    Path('src/scrape_planner/source_monitor.py'),
    Path('src/scrape_planner/run_persistence.py'),
    Path('src/scrape_planner/storage.py'),
]:
    if p.exists():
        compile(p.read_text(encoding='utf-8'), str(p), 'exec')
print('compile ok')
PY
```

If pytest is available in the executor environment:

```bash
python3 -m pytest tests/test_source_monitor.py -q
```

If pytest remains unavailable, add a small `python3 - <<'PY'` artifact parse smoke check or ensure the task explicitly installs dev test dependencies only if approved by the project workflow.

## Risks / Watch-outs

- **Do not build on `cleanup_manifest.json`:** M001 explicitly rejects cleanup-manifest-first architecture.
- **Do not delete sources:** Deleted behavior should be `deleted_candidate`, not destructive removal.
- **Keep prior good hashes on failure:** A transient failed check must not mark downstream wiki pages stale by replacing `content_hash` with null.
- **URL normalization must be stable:** Source IDs become cross-slice references. Normalize minimally and predictably; store original URL and canonical/final URL separately.
- **JSONL reading/writing:** Existing `read_json` is not suitable for JSONL. Use/read JSONL helpers for `events.jsonl`, `pages.jsonl`, and new `source_diff.jsonl`.
- **Current run persistence helper names:** `_write_json_atomic`, `_append_jsonl`, `_read_jsonl` are private. Either expose generic public helpers or duplicate tiny helpers in the new module; avoid importing underscored helpers if possible.
- **No hardcoded university taxonomy:** S01 source IDs/statuses should not encode SMU/unit/category assumptions.
- **Pytest missing locally:** Planner/executor should account for environment setup or use compile/smoke checks if package installs are out of scope.

## Recommendation

Add a new source-monitor module with pure diff logic plus a fixture proof runner. Reuse existing atomic JSON and event-log style, but define S01-specific artifact names (`run.json`, `source_ledger.jsonl`, `source_diff.jsonl`, `build_report.md`) rather than changing the existing scrape worker's `run_status.json`/`pages.jsonl` behavior. The implementation should prioritize contract stability, parseable artifacts, and preservation of previous source state over live fetching or UI integration.