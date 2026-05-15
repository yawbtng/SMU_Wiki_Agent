# S06 Research — Simple V1 configuration and proof command

## Summary
S06 should be implemented as a **thin orchestration/config layer** on top of already-existing primitives in this repo (state persistence, JSON/JSONL artifact writing, observability appenders, terminal runner) plus the S03/S05 contracts described in milestone context. The highest-risk gap is not core infra, but **absence of M001-specific integration files** (no existing `proof` command, no V1 config contract in code, no tracer maintenance executor/test artifacts visible in this worktree).

Given roadmap dependencies, S06 must focus on: (1) one simple config schema spanning maintenance/retrieval/pdf/zvec, and (2) one proof entrypoint that validates artifact contracts from S01–S05 and emits pass/fail report.

## Active Requirement Mapping (slice-owned/supporting)
S06 primarily closes:
- **R012** — simple configurable maintenance/retrieval/PDF/Zvec options.
- **R015** — expose maintenance/config choices.

S06 also validates integration evidence for:
- **R006/R008** stale + job packet contracts (from S03) by checking expected artifacts/fields.
- **R010/R011** PDF chunk citation + quarantine semantics (from S05) by checking proof artifacts.

Constraint to preserve:
- **R001/R013**: do not reintroduce cleanup-manifest-first or hardcoded university taxonomy dependency in proof logic.

## Implementation Landscape (files and purpose)
### Existing reusable files
- `src/scrape_planner/run_persistence.py`
  - Atomic JSON write and JSONL append/read helpers. Best existing seam for proof-report/event output.
- `src/scrape_planner/observability.py`
  - Timestamped event append + summary logic. Can back proof-step event trace.
- `src/scrape_planner/state.py`
  - Run-state abstraction; optional for proof progress status if desired.
- `src/scrape_planner/terminal_skill_runner.py`
  - Async process runner; only needed if proof command shells subcommands.
- `scripts/zvec_index_run.py`
  - Current Zvec script is cleanup/wiki oriented, not page-citation PDF-contract-first. S06 should avoid coupling proof success to this legacy path unless explicitly adapted.
- `mcp_servers/smu_zvec_mcp.py`
  - Query surface exists, but result shape currently lacks explicit PDF page contract fields.

### Missing (to be created by executor)
Likely new integration layer files:
- `src/scrape_planner/config_v1.py` (or similar): parse/validate simple V1 config.
- `configs/m001_v1.json` or `.yaml`: single user-editable config file.
- `src/scrape_planner/proof_m001.py` (or `scripts/m001_proof.py`): orchestration/validation command.
- `tests/test_m001_config_v1.py`, `tests/test_m001_proof_command.py`: contract + pass/fail behavior.

## Natural Seams for planner task decomposition
1. **Config contract task (independent, first-class)**
   - Define schema keys and defaults for: maintenance, retrieval limits, PDF limits, Zvec settings.
   - Include strict bounds (e.g., top_k max, max_pdf_mb, max_evidence_items) to satisfy boundedness requirement.

2. **Proof validator task (depends on config)**
   - Implement stepwise validators that inspect expected artifact files and key fields from S01–S05.
   - Emit deterministic `pass|fail` per check + reason.

3. **Proof command + report output task**
   - CLI entrypoint (`python3 -m ...` or script) consuming config + run root.
   - Write machine-readable summary JSON and human-readable markdown report.

4. **Tests task**
   - Fixture-based tests for missing artifact failure, malformed field failure, and full-pass fixture.

## First Proof (highest-risk unblocker)
Implement and verify a **single deterministic validator** for cross-slice artifacts before any advanced orchestration:
- Inputs: path to M001 fixture/run root.
- Checks:
  - S03 stale packet artifacts present with reason `source_hash_changed` and bounded evidence references.
  - S04 tracer output artifacts exist (page + manifest/source map/source usage/result/handoff contracts).
  - S05 PDF artifacts include chunk `page_number` and quarantine reasons.
- Output: one `proof_result.json` + concise markdown report.

This first proof de-risks S06 by confirming contract surfaces exist in this worktree lane; if not, planner can schedule remediation rather than polishing CLI ergonomics.

## Verification plan (for executor)
Use `python3` only.

Suggested checks:
- Unit/config:
  - `python3 -m unittest tests.test_m001_config_v1 -v`
- Integration/proof:
  - `python3 -m unittest tests.test_m001_proof_command -v`
- CLI smoke:
  - `python3 scripts/m001_proof.py --config configs/m001_v1.json --run-root <fixture_or_run_root>`

Expected outputs:
- Exit code non-zero on failed contract checks.
- Report artifacts written (e.g., `proof_result.json`, `proof_report.md`).
- Report includes failed check IDs and missing/invalid paths.

## Recommendations
- Prefer **contract-verification over execution orchestration** for S06: this slice is integration proof, not new crawler logic.
- Keep config surface minimal and explicit; avoid introducing UI/settings frameworks.
- Reuse `run_persistence` for durable outputs to stay consistent with existing JSON/JSONL patterns.
- Avoid dependence on `cleanup_manifest.json` in S06 pass criteria (per R001 context).

## Risks / watch-outs for planner
- Current worktree shows prior slices with placeholder/blocked summaries; S06 proof may fail legitimately due to missing upstream artifacts.
- `pytest` may be unavailable; use `unittest` path as primary verification.
- Existing Zvec tooling is wiki/cleanup shaped; PDF proof contract checks should target S05 artifacts, not assume current MCP/query schema is already compliant.

## Skill discovery notes (directly relevant)
Installed skills already cover needed methodology:
- `write-docs` (good for clear config/proof contract docs)
- `observability` (step events + failure visibility)
- `decompose-into-slices` (planner decomposition style)

No additional external skill lookup is necessary for core technologies here (Python CLI + local JSON artifacts + existing repo modules).
