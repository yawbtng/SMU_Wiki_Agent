# S03: Stale dependency tracking and tracer job contract — UAT

**Milestone:** M001
**Written:** 2026-05-15T18:04:08.459Z

# UAT Type
Integration / Contract validation (stale tracking + packet contract)

# Preconditions
1. A prior source-hash view exists (from S01-style source ledger state).
2. A current source-hash view exists with at least one changed hash.
3. Source→tracer-page dependency map exists for at least one page.
4. Bounded retrieval evidence identifiers exist (from S02) and are referencable by packet metadata.

# Steps
1. Run stale evaluation with prior/current source hash views and dependency map.
2. Inspect stale evaluation output for affected page IDs and reasons.
3. Persist stale artifacts for the run (snapshot + transition events append).
4. Emit maintenance job packet(s) for each stale page.
5. Parse each packet as downstream S04 input and validate required fields.
6. Re-run with unchanged hashes and verify no stale pages/packets are generated.

# Expected Outcomes
1. Only pages depending on changed source hashes are marked stale.
2. Each stale reason is `source_hash_changed`.
3. Stale snapshot JSON exists in the run artifacts.
4. Stale transition events are appended to JSONL history without truncating prior events.
5. One packet directory exists per stale page.
6. Packet includes target page ID, metadata, bounded evidence references (no full raw body payload), and explicit output contract for S04.
7. Unchanged-hash run yields zero stale pages and zero new packets.

# Edge Cases
1. Changed source hash with no mapped dependent page → no stale page emitted.
2. Multiple changed sources mapping to same page → one stale page output with deterministic handling.
3. Missing/empty dependency map → no stale pages, explicit empty result.
4. Existing event history present → new events append-only and readable.

# Not Proven By This UAT
1. Actual tracer page content update/write behavior (covered in S04).
2. Multi-page production-scale performance characteristics.
3. End-to-end autonomous scheduling/daemon execution behavior (deferred scope).

