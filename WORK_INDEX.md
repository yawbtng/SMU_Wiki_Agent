# Ralph Work Index

This file is the human-readable checkpoint for Ralph loop work.

## Stop Rule

Ralph should stop when every spec in `specs/` has `## Status: COMPLETE` and the latest verification pass is recorded here, in `history.md`, and in `completion_log/`.

When no incomplete specs remain, Ralph should output:

```xml
<promise>ALL_DONE</promise>
```

## Current Queue

| Priority | Spec | Status | Purpose |
| --- | --- | --- | --- |
| 000 | `specs/000-automated-wiki-ingest-build-update.md` | TODO | Automate Ingest → Clean → Standardize → Lint → Build Wiki → Build Index → Verify |
| 001 | `specs/001-build-smu-llm-wiki.md` | TODO | Build and verify the SMU LLM Wiki |
| 002 | `specs/002-wire-wiki-ui-pi-sdk.md` | TODO | Wire Build/Update Wiki controls and meaningful Pi SDK activity/status to streaming runtime |
| 003 | `specs/003-semantic-student-wiki-organization.md` | TODO | Ralph-loop churn beyond fast source-card generation until Karpathy-style semantic wiki organization answers student questions |

## Completion Ledger

| Date | Spec | Result | Verification | Notes |
| --- | --- | --- | --- | --- |
| _pending_ | _pending_ | _pending_ | _pending_ | _pending_ |

## Update Rules

After each completed spec, Ralph should:

1. Change that spec to `## Status: COMPLETE`.
2. Add a one-line entry to `history.md`.
3. Add a detailed timestamped note in `completion_log/`.
4. Update this `WORK_INDEX.md` queue/status table and completion ledger.
5. Continue to the next incomplete spec, or output `<promise>ALL_DONE</promise>` if no incomplete specs remain.
