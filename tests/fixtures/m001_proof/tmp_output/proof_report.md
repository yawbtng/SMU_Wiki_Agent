# M001 Proof Report

- Run root: `tests/fixtures/m001_proof/pass/run_root`
- Generated at: `2026-05-15T21:33:59Z`
- Overall verdict: **PASS**

| Check ID | Status | Reason | Timestamp |
|---|---|---|---|
| `S03_STALE_PACKET` | pass | `source_hash_changed` | `2026-05-15T21:33:59Z` |
| `S04_MAINTENANCE_ARTIFACTS` | pass | `all_artifacts_present` | `2026-05-15T21:33:59Z` |
| `S05_PDF_CONTRACTS` | pass | `pdf_contracts_valid` | `2026-05-15T21:33:59Z` |

## Details

### S03_STALE_PACKET

- Status: `pass`
- Reason: `source_hash_changed`
- Timestamp: `2026-05-15T21:33:59Z`
- Details:

```json
{
  "evidence_count": 2,
  "path": "tests/fixtures/m001_proof/pass/run_root/s03/stale_packet.json"
}
```

### S04_MAINTENANCE_ARTIFACTS

- Status: `pass`
- Reason: `all_artifacts_present`
- Timestamp: `2026-05-15T21:33:59Z`
- Details:

```json
{
  "artifacts": [
    "page.md",
    "manifest.json",
    "source_map.json",
    "source_usage.json",
    "events.jsonl",
    "result.json",
    "handoff.md"
  ],
  "job_root": "tests/fixtures/m001_proof/pass/run_root/s04/maintenance/job-001"
}
```

### S05_PDF_CONTRACTS

- Status: `pass`
- Reason: `pdf_contracts_valid`
- Timestamp: `2026-05-15T21:33:59Z`
- Details:

```json
{
  "chunk_count": 1,
  "chunks_path": "tests/fixtures/m001_proof/pass/run_root/s05/pdf_chunks.jsonl",
  "quarantine_count": 1,
  "quarantine_path": "tests/fixtures/m001_proof/pass/run_root/s05/pdf_quarantine.jsonl"
}
```
