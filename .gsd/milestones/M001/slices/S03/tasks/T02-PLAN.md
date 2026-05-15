---
estimated_steps: 46
estimated_files: 4
skills_used: []
---

# T02: Persist stale artifacts and emit agent/skill-compatible maintenance job packets

Why
- S03 is not done until stale transitions are durably inspectable and downstream S04 receives executable packet inputs.

Files
- `src/scrape_planner/run_persistence.py`
- `src/scrape_planner/observability.py`
- `src/scrape_planner/terminal_skill_runner.py`
- `tests/test_tracer_job_packet_contract.py`

Do
1. Wire stale evaluator outputs into run persistence using existing S01 durability patterns: atomic JSON snapshot for stale summary and append-only JSONL for stale transitions/events.
2. Add packet emission helper that writes one maintenance job packet directory/file set per stale page with:
   - job metadata (run_id, job_id, created_at, slice marker)
   - target tracer page identifier
   - source references and hash deltas
   - bounded retrieval evidence references (IDs/paths only)
   - explicit expected output contract for S04 (result/manifest/source usage artifacts)
3. Ensure job packet writer is additive and does not overwrite unrelated packet directories.
4. Add integration tests that create a temp run root, trigger one hash change with one dependent page, and assert:
   - stale snapshot JSON exists and parses
   - stale transition/event JSONL appends and parses line-by-line
   - job packet directory/files exist and include required contract keys
5. Add negative integration coverage for unchanged-hash run (no packet emitted, no stale page records).

Must-haves
- Append-only behavior preserved for JSONL streams.
- Packet contract remains bounded (references instead of embedded raw bodies).
- Paths and file names are stable and discoverable for S04.

Verification
- `python3 -m pytest tests/test_tracer_job_packet_contract.py -q`
- `python3 -m pytest tests/test_stale_dependency_tracking.py tests/test_tracer_job_packet_contract.py -q`

Done when
- A reproducible test proves hash change => stale artifact + stale event + packet artifact, and unchanged case emits none.

Threat Surface (Q3)
- Abuse: tampered dependency maps could over-mark pages stale; mitigate with strict schema + deterministic evaluator and explicit source IDs.
- Data exposure: packet contains source metadata only; no secrets/PII expected.
- Input trust: source/dependency inputs are internal run artifacts but still validated before writing events.

Failure Modes (Q5)
- Dependency: filesystem write failure. On error: fail task with explicit error event; no silent success.
- Dependency: malformed evidence refs. On error: reject packet creation and log validation failure event.
- Dependency: JSONL append failure. On timeout/error: propagate failure; do not claim stale dispatch complete.

Load Profile (Q6)
- Shared resources: run artifact filesystem.
- Per-operation cost: O(stale_pages + events_written) file writes.
- 10x breakpoint: many stale pages in one run increase packet file count; maintain per-page bounded packet size.

Negative Tests (Q7)
- Malformed inputs: invalid evidence reference shape rejects packet.
- Error paths: missing run directory causes explicit failure.
- Boundary: multiple stale pages produce one packet each without collisions.

## Inputs

- `src/scrape_planner/run_persistence.py`
- `src/scrape_planner/observability.py`
- `src/scrape_planner/terminal_skill_runner.py`
- `tests/test_stale_dependency_tracking.py`
- `.gsd/milestones/M001/slices/S01/S01-SUMMARY.md`
- `.gsd/milestones/M001/slices/S02/S02-SUMMARY.md`

## Expected Output

- `src/scrape_planner/run_persistence.py`
- `src/scrape_planner/observability.py`
- `src/scrape_planner/terminal_skill_runner.py`
- `tests/test_tracer_job_packet_contract.py`

## Verification

python3 -m pytest tests/test_tracer_job_packet_contract.py -q && python3 -m pytest tests/test_stale_dependency_tracking.py tests/test_tracer_job_packet_contract.py -q

## Observability Impact

Introduces stale transition signals and packet emission/failure events inspectable via run artifacts.
