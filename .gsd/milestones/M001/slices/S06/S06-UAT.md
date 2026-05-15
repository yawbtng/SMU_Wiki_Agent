# S06: Simple V1 configuration and proof command — UAT

**Milestone:** M001
**Written:** 2026-05-15T19:07:48.208Z

# UAT — S06 Simple V1 Configuration and Proof Command

## UAT Type
Integration readiness / contract verification (artifact + command behavior)

## Preconditions
1. Repository has S01–S05 fixture artifacts available in the expected run-root layout.
2. `configs/m001_v1.json` exists with explicit maintenance/retrieval/PDF/Zvec options.
3. Proof entrypoint is available at `scripts/m001_proof.py` and writes JSON + markdown outputs.

## Steps
1. Run config tests:
   - `python3 -m unittest tests.test_m001_config_v1 -v`
2. Run proof command tests:
   - `python3 -m unittest tests.test_m001_proof_command -v`
3. Run proof command against pass fixture:
   - `python3 scripts/m001_proof.py --config configs/m001_v1.json --run-root tests/fixtures/m001_proof/pass_fixture --output-dir tmp/m001-proof-smoke`
4. Inspect output directory for machine-readable + human-readable proof results.
5. Run proof against a known-failing fixture (missing/malformed contract) and confirm non-zero exit plus check IDs/reasons.

## Expected Outcomes
1. Config + proof unit suites pass.
2. Pass fixture run exits zero and produces deterministic proof artifacts.
3. Fail fixture run exits non-zero and includes explicit failed check IDs/reasons.
4. Reports are durable and suitable for future-agent diagnosis.

## Edge Cases
1. Missing config key that should be explicit (no silent default).
2. Missing stale/job packet artifacts from S03.
3. Missing tracer manifest/source usage/job result artifacts from S04.
4. Missing PDF/Zvec artifacts or malformed quarantine reason entries from S05.
5. Output directory already exists (proof should handle deterministically).

## Not Proven By This UAT
1. Full production scheduler/daemon behavior (deferred by scope).
2. Full 25k-page benchmark performance (deferred by scope).
3. OCR pipeline for scanned PDFs (explicitly deferred).
