# S03 Research — Stale dependency tracking and tracer job contract

## Summary
- Slice S03 should build directly on existing JSON/JSONL durability patterns in `src/scrape_planner/run_persistence.py` (atomic JSON writes + append-only JSONL), which already match M001’s artifact-first contract style.
- No existing stale-dependency or tracer job packet module is present in the current tree; this slice is mostly net-new contract and wiring work.
- Highest-risk first proof: deterministic stale marking from `source_id + source_hash` change to affected tracer page IDs, with durable events and an inspectable job packet directory.

## Requirement Alignment (Active requirements this slice owns/supports)
- **R006 (primary for S03):** wiki pages track source dependencies and staleness.
  - Risk: without a normalized source-map/reverse-dependency contract, stale marking will be ambiguous.
- **R008 (supports/bridges to S04):** LLM maintenance through agent/skill-compatible jobs.
  - Risk: if packet schema is underspecified now, S04 executor compatibility will drift.
- **R001/R004/R005 support constraints:** raw-source truth, durable run logs, index-first bounded retrieval must remain intact in S03 interfaces.
  - Risk: S03 must consume retrieval evidence outputs, not reintroduce full-file scanning.

## Implementation Landscape (files and purpose)
- `src/scrape_planner/run_persistence.py`
  - Reusable persistence primitives:
    - `_write_json_atomic(...)` for snapshot artifacts (`run.json`, stale summary, packet manifest).
    - `_append_jsonl(...)` for event streams (`events.jsonl`, stale transitions).
  - Existing pattern strongly suggests implementing S03 artifacts as JSON snapshot + JSONL append logs.
- No dedicated files currently found for:
  - tracer page manifest contract
  - source-map/reverse-dependency index
  - stale-evaluation engine
  - maintenance job packet writer

## Natural seams for planner task decomposition
1. **Contract definitions (pure schema/shape task)**
   - Define canonical JSON shapes for:
     - tracer page manifest (page_id, sources[{source_id, hash}], last_built_at)
     - reverse dependency map (source_id -> [page_id])
     - stale record (run_id, source_id, old_hash, new_hash, affected_pages, reason)
     - job packet (job metadata, bounded evidence refs, instructions, output contract)
2. **Stale evaluation engine (deterministic logic task)**
   - Input: previous/current source ledger hash views + dependency map.
   - Output: stale page set + transition records.
3. **Artifact + event persistence wiring (I/O task)**
   - Persist stale snapshot and append events via run persistence patterns.
4. **Job packet emission (handoff contract task)**
   - Create packet directory/files for downstream agent/skill executor compatibility.
5. **Verification tests (unit/integration task)**
   - Assert hash change => stale page + packet + events parseability.

## First proof (highest risk / biggest unblocker)
- **Proof target:** one changed source hash deterministically marks dependent tracer page stale and emits one job packet.
- Minimal acceptance check:
  1. Seed source map: `srcA -> [pageX]`.
  2. Change `srcA` hash from H1 to H2.
  3. Run stale evaluator.
  4. Verify:
     - stale artifact includes `pageX` with reason `source_hash_changed`.
     - run events include stale-marked transition.
     - job packet exists with page target + evidence references.

## Verification strategy
- **Unit tests**
  - stale evaluator (no I/O): unchanged hashes => no stale pages; changed hash => expected affected pages only.
  - schema validation/parsing for packet + stale artifacts.
- **Integration tests**
  - filesystem run-root test asserting:
    - JSON artifacts written atomically
    - JSONL events append and remain parseable
    - packet directory contract created
- **Suggested commands**
  - `python3 -m pytest tests -k stale -q`
  - `python3 -m pytest tests -k tracer -q`
  - If targeted tests are added under new files, run explicit paths to keep cycle fast.

## Constraints and watch-outs
- Keep all contracts raw-source-referenced (`source_id`, hash), not taxonomy-bound (avoid legacy SMU unit assumptions).
- Preserve append-only event history semantics; never overwrite `events.jsonl`.
- Packet should reference bounded retrieval evidence IDs/paths rather than embedding large bodies (context safety and S02 contract alignment).
- Prefer additive modules; avoid coupling S03 logic to UI/Streamlit surfaces (`app.py`) since milestone path is proof-command/test-first.

## Skill discovery suggestions
- Installed relevant skills already available:
  - `design-an-interface` (recommended for job packet + artifact contract alternatives before coding)
  - `observability` (recommended for event taxonomy and failure-state logging)
  - `write-docs` (recommended if packet contract/spec needs durable handoff docs)
- No external tech-specific missing skill discovery was necessary from current code scan; work is primarily local Python artifact-contract design.

## Recommendation
- Plan S03 as contract-first: lock packet + stale artifact schemas before wiring logic.
- Reuse `run_persistence.py` write/append idioms to stay consistent with S01 durability patterns.
- Implement deterministic stale marking as a pure function first, then wrap with persistence.
- Gate S03 done-state on concrete artifact existence and parseability checks to avoid prior placeholder-style completion drift.

## Sources
- `src/scrape_planner/run_persistence.py` (existing JSON/JSONL durability primitives and conventions)
- Inlined roadmap/context requirements for M001/S03 dependency and acceptance expectations
