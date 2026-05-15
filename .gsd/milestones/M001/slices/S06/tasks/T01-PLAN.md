---
estimated_steps: 9
estimated_files: 3
skills_used: []
---

# T01: Implement V1 config schema and defaults for proof orchestration

Why: S06 needs a single operator-editable config contract (R012/R015) before proof wiring can be deterministic.

Do:
1. Add `src/scrape_planner/config_v1.py` with typed loader/validator for maintenance, retrieval, pdf, and zvec sections.
2. Enforce bounded constraints needed by milestone promises (e.g., positive limits, max evidence/page bounds) and return clear validation errors.
3. Add canonical config file `configs/m001_v1.json` with minimal defaults used by proof command.
4. Add unit tests for valid config, missing required sections/keys, and invalid bounds.
5. Keep implementation independent from `.gsd/` paths and legacy cleanup-manifest-first assumptions.

Done when: config load/validation is deterministic, boundedness rules are enforced by tests, and canonical config file exists for downstream proof command consumption.

Expected executor skills: write-docs, verify-before-complete

## Inputs

- `src/scrape_planner/run_persistence.py`
- `src/scrape_planner/models.py`
- `.gsd/milestones/M001/slices/S06/S06-RESEARCH.md`

## Expected Output

- `src/scrape_planner/config_v1.py`
- `configs/m001_v1.json`
- `tests/test_m001_config_v1.py`

## Verification

python3 -m unittest tests.test_m001_config_v1 -v

## Observability Impact

Validation errors include field path + reason to make config failures diagnosable before proof execution.
