# Phase 8: Tests And Quality Gates

## Goal

Add enough tests and smoke checks that the rebuilt scrape cockpit does not regress into blank screens, broken run state, or silent worker failures.

## Primary Ownership

- `tests/`
- Optional test helpers under `tests/fixtures/`
- Minimal production code changes only when needed for testability

## Do Not Own

- Major UI redesign
- Worker feature implementation
- Navigation restructure

## Current Problem

There is limited test coverage. The riskiest behavior is long-running state: run initialization, page state transitions, cancellation, persistence, and UI-safe data shaping.

## Required Test Coverage

### Unit Tests

Add tests for:

- Page state initialization
- Status count derivation
- Event append/read behavior
- Durable page state collapse from JSONL if Phase 4 exists
- Failure grouping if Phase 5 exists
- Analytics summaries if Phase 7 exists

### Worker Tests

Use fake fetch behavior instead of real network.

Test:

- Success page path
- Failed page path
- Retry mode path
- Cancel before run
- Cancel mid-run
- Concurrency count consistency if Phase 3 exists

### UI Data Shaping Tests

If UI helper functions are extracted, test:

- Queued rows render from selected URLs
- Empty state data does not crash
- Selected inspector URL fallback works
- Event timeline rows are normalized

### Smoke Script

Add a lightweight command or documented check:

```bash
python3 - <<'PY'
from pathlib import Path
for p in [Path("app.py"), *Path("src/scrape_planner").glob("*.py")]:
    compile(p.read_text(encoding="utf-8"), str(p), "exec")
print("ok")
PY
```

If pytest is already usable:

```bash
python3 -m pytest
```

## Test Design Notes

Avoid hitting real SMU URLs in tests. Use fake HTML strings and monkeypatch fetch calls.

Suggested fake cases:

- Normal HTML with title/body
- Empty HTML
- Blocked page text
- HTTP 500
- Timeout exception

## Acceptance Criteria

- `python3 -m pytest` passes.
- Compile smoke passes.
- Tests cover run status counts.
- Tests cover failure grouping.
- Tests cover at least one successful and one failed scrape page.
- Tests do not require network.

## Verification

Run:

```bash
python3 -m pytest
```

Run compile smoke:

```bash
python3 - <<'PY'
from pathlib import Path
for p in [Path("app.py"), *Path("src/scrape_planner").glob("*.py")]:
    compile(p.read_text(encoding="utf-8"), str(p), "exec")
print("ok")
PY
```

## Merge Notes

This phase is best run alongside other phases as a verification worker. When another phase adds helper functions, extend tests to cover them instead of duplicating logic in tests.

