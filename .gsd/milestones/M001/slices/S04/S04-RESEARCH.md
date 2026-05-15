# S04 Research — Tracer wiki page maintenance proof

## Summary
S04 can be delivered as a thin integration slice on top of S03’s stale/page packet contract: consume one emitted maintenance packet, materialize one tracer wiki page, and write the full execution artifact chain (manifest, source map, source usage, events, result, handoff). The current repo has persistence primitives (`run_persistence.py`, `observability.py`) and process orchestration scaffolding (`terminal_skill_runner.py`), but no explicit S04 executor module or tests for page-maintenance artifacts in this worktree. This slice should avoid broad architecture churn and instead add a focused “packet -> page + artifacts” executor path with bounded evidence references only (no raw full-body source embedding), preserving R006/R008/R014 constraints.

## Requirements Focus (Active requirements this slice supports)
- **R006** (staleness contract): S04 must preserve source-hash-driven stale provenance when generating the page update result.
- **R007** (one tracer wiki page proof): direct owner behavior for this slice.
- **R008** (agent/skill-compatible jobs): output artifacts must remain downstream-executable and resumable.
- **R014** (anti-scale bounds): source usage and evidence references must stay bounded and pointer-based.

## Implementation Landscape (what exists, what’s missing)
### Existing reusable pieces
- `src/scrape_planner/run_persistence.py`
  - Atomic JSON writes + append-only JSONL helpers.
  - Natural fit for `events.jsonl`, `source_usage.jsonl`, `result.json` writing in run/job roots.
- `src/scrape_planner/observability.py`
  - Timestamped event append/summarization pattern; useful for maintenance lifecycle logging semantics.
- `src/scrape_planner/terminal_skill_runner.py`
  - Existing process wrapper for “skill-like” command execution; optional seam if S04 chooses subprocess-backed executor mode.
- `src/scrape_planner/models.py`
  - Dataclass pattern already present; S04 can add compact packet/result dataclasses for contract validation.

### Missing for S04 proof
- No dedicated tracer maintenance executor module in this worktree.
- No explicit page artifact writer for:
  - tracer page markdown (with citations),
  - page manifest with source hashes,
  - source-map update/reverse-dependency link,
  - bounded source usage record,
  - handoff/resume note.
- No visible S04-specific tests in `tests/` for packet consumption and artifact contract validation.

## Natural seams for planner task decomposition
1. **Contract + validation seam**
   - Add packet/result schema validation (required keys, bounded evidence list, target page ID).
2. **Artifact writer seam**
   - Deterministic writers for page markdown + manifest/source_map/source_usage/events/result/handoff.
3. **Execution seam**
   - “Run one packet” orchestration function with explicit status transitions (started/succeeded/failed).
4. **Verification seam**
   - Fixture-style test proving end-to-end artifact presence + parseability + citation/source-hash invariants.

These seams are independent enough for separate tasks and parallelizable once contract shape is fixed.

## First proof (highest-risk unblocker)
Implement and verify the **single-packet happy path** first:
- input: one S03-style stale packet with bounded evidence handles,
- output: one tracer wiki page with cited claims + manifest/source_map/source_usage/events/result/handoff.

Why first: this is the critical S03->S04 boundary and de-risks all acceptance criteria faster than building retries/advanced failure handling first.

## Recommended file targets
- `src/scrape_planner/` (new module likely needed, e.g., tracer maintenance executor/writer).
- `src/scrape_planner/run_persistence.py` (reuse; possibly minimal extension only if required).
- `tests/` (new S04 contract + integration tests).

## Verification plan for S04
Given this worktree’s prior gaps (pytest missing in S03 run), design dual verification commands:
1. Primary:
   - `python3 -m pytest tests/test_tracer_maintenance_proof.py -q`
2. Fallback:
   - `python3 -m unittest tests.test_tracer_maintenance_proof -v`

Expected checks:
- All expected artifacts exist and are machine-parseable JSON/JSONL/MD.
- Result links to target page ID and success status.
- Source usage entries reference bounded evidence IDs/paths, not full raw source bodies.
- Manifest/source map retain source hash provenance for stale reason continuity (`source_hash_changed`).
- Events trail includes start + completion/failure transition.

## Constraints / watch-outs for planner
- Keep artifact payloads bounded; avoid embedding large raw markdown bodies in packet/result files (R014).
- Maintain append-only event trails for diagnosability (S03 pattern continuity).
- Do not introduce cleanup-manifest-first dependencies (M001 architectural decision).
- Keep implementation local and deterministic; this slice is proof-of-contract, not full scheduler/autonomous loop.

## Skill discovery notes
Reviewed installed skills list; no additional external skill discovery needed for core S04 technology. Relevant already-installed optional skills for execution/review phases:
- `write-docs` (if artifact contract docs need tightening)
- `observability` (if event schema needs stronger operational signals)
- `verify-before-complete` (before claiming slice completion)

No `npx skills find` run because core work is Python/local artifact wiring already covered by existing project patterns.

## Recommendation
Proceed with a targeted implementation that introduces one dedicated S04 executor path and tests it against a fixed fixture packet. Prioritize contract conformance and artifact determinism over extensibility. If planner enforces task order, do: (1) contract validator, (2) artifact writers, (3) one-packet executor, (4) verification tests.
