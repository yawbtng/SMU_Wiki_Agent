---
estimated_steps: 15
estimated_files: 3
skills_used: []
---

# T01: Add simple V1 config contract for maintenance/retrieval/pdf/zvec options

Why: S06 must satisfy R012/R015 by exposing explicit, minimal operational options instead of implicit behavior.

Files:
- `src/scrape_planner/config_v1.py`
- `configs/m001_v1.json`
- `tests/test_m001_config_v1.py`

Do:
1) Implement `config_v1.py` dataclass-based loader/validator from JSON with explicit sections: maintenance, retrieval, pdf, zvec.
2) Enforce boundedness and type checks (e.g., positive ints, top_k/evidence caps, max_pdf_mb, quarantine toggles, zvec limits) with deterministic validation errors.
3) Add a repository-shipped default config file `configs/m001_v1.json` with simple V1-safe defaults.
4) Add unittest coverage for: valid load, missing required sections/keys, out-of-range limits, and deterministic error messages.
5) Keep config scope minimal (no scheduler/UI abstractions) per R002.

Done when:
- Config loader returns a normalized strongly-typed object for valid config.
- Invalid configurations fail fast with clear messages.
- Tests prove bounds and required-option behavior.

## Inputs

- `src/scrape_planner/models.py`
- `src/scrape_planner/run_persistence.py`
- `src/scrape_planner/observability.py`

## Expected Output

- `src/scrape_planner/config_v1.py`
- `configs/m001_v1.json`
- `tests/test_m001_config_v1.py`

## Verification

python3 -m unittest tests.test_m001_config_v1 -v

## Observability Impact

Validation errors become explicit and test-covered so bad operational settings fail before proof execution.
