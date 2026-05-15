# M001: M001: Raw Source Monitor, Run Logs, Retrieval, Tracer Maintenance Job, and PDF/Zvec Proof

**Vision:** Prove the simplest useful raw-first maintenance substrate for a pi-agent-maintained university wiki: source changes are detected, runs are logged, retrieval is bounded, one tracer wiki update is source-grounded, internal PDFs work through Zvec with page citations, and V1 configuration exposes operational choices.

## Success Criteria

- Source ledger and run logs prove source lifecycle changes and failure visibility.
- Raw retrieval is index-first and bounded, suitable for large university corpora.
- One tracer wiki maintenance job proves pi-agent/skill-compatible update artifacts.
- Internal/operator PDF ingestion into Zvec is proven with page-number citations and quarantine behavior.
- Simple V1 configuration exposes maintenance/retrieval/PDF/Zvec options without overbuilding.

## Slices

- [x] **S01: S01** `risk:high` `depends:[]`
  > After this: Given fixture source records, the system writes a run directory with run.json, events.jsonl, source_diff.jsonl, and a report showing new/changed/unchanged/failed/deleted-candidate sources.

- [x] **S02: S02** `risk:high` `depends:[]`
  > After this: A query over fixture raw markdown uses an index-first path and returns bounded evidence without scanning every raw file.

- [x] **S03: S03** `risk:high` `depends:[]`
  > After this: A changed source hash marks a dependent tracer wiki page stale and creates an agent/skill-compatible maintenance job packet.

- [x] **S04: S04** `risk:medium` `depends:[]`
  > After this: A pi-agent/skill-style job updates or creates one cited tracer wiki page with manifest, source map, source usage, events, and handoff/result artifacts.

- [x] **S05: S05** `risk:high` `depends:[]`
  > After this: A born-digital PDF is chunked with page numbers, indexed/queryable through Zvec, and scanned/encrypted/malformed/low-text PDFs are quarantined with reasons.

- [ ] **S06: S06** `risk:medium` `depends:[]`
  > After this: One simple config file controls maintenance options, retrieval limits, PDF limits, and Zvec settings; a proof command runs the M001 fixture workflow and reports pass/fail.

## Boundary Map

## Boundary Map

### S01 → S02

Produces:
- Source ledger JSONL contract with source IDs, URLs, hashes, status, timestamps, and errors.
- Run directory contract with `run.json`, `events.jsonl`, `source_diff.jsonl`, and `build_report.md`.
- Simple config keys for source-check behavior and deletion-candidate thresholds.

Consumes:
- Existing scraped artifacts and fixture source records.

### S01 → S03

Produces:
- Stable source IDs and source hashes that stale dependency tracking can reference.
- Run event/status helpers for logging stale dependency outcomes.

Consumes:
- Existing scraped artifacts and fixture source records.

### S02 → S03/S04

Produces:
- Index-first retrieval API/command returning bounded evidence bundles with source IDs, URLs, paths, snippets, and scores.
- Stale/missing index status contract.

Consumes:
- Source ledger/source records from S01.

### S03 → S04

Produces:
- Tracer wiki page manifest shape with source hashes.
- Source map/reverse dependency shape that maps source IDs to wiki pages.
- Agent/skill-compatible maintenance job packet directory contract.

Consumes:
- Source ledger from S01 and bounded retrieval from S02.

### S04 → S06

Produces:
- One tracer wiki page and job-result artifact shape that the proof command can validate.
- Citation/source usage expectations for maintenance jobs.

Consumes:
- Job packet contract from S03 and retrieval evidence from S02.

### S05 → S06

Produces:
- PDF source/chunk record contract with page numbers.
- Zvec PDF proof manifest/query result contract.
- PDF quarantine reason contract.

Consumes:
- Run log contract from S01.

### S06 final integration

Produces:
- Simple V1 config file and one proof command that validates all slice contracts together.
- Final build/proof report showing M001 readiness.
