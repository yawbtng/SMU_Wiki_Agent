#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scrape_planner.raw_retrieval import QueryRequest, build_raw_index, query_raw_index


def _source(path: Path, source_id: str, url: str) -> dict[str, str]:
    return {"source_id": source_id, "url": url, "path": str(path)}


def run_fixture_proof(fixtures_root: Path, index_root: Path) -> dict[str, object]:
    fixtures_root.mkdir(parents=True, exist_ok=True)
    index_root.mkdir(parents=True, exist_ok=True)

    doc_a = fixtures_root / "proof_a.md"
    doc_b = fixtures_root / "proof_b.md"

    doc_a.write_text(
        """
# Index-first Retrieval Fixture A
This fixture proves bounded lexical retrieval over precomputed chunks.
Freshness signal 2026 admissions guidance and application dates.
""".strip(),
        encoding="utf-8",
    )
    doc_b.write_text(
        """
# Index-first Retrieval Fixture B
Another source for evidence snippets without full-corpus scanning.
Campus update bulletin and scholarship timeline references.
""".strip(),
        encoding="utf-8",
    )

    sources = [
        _source(doc_a, "fixture-A", "https://fixture.local/a"),
        _source(doc_b, "fixture-B", "https://fixture.local/b"),
    ]

    build_report = build_raw_index(index_root, sources, chunk_chars=180, overlap=30)
    query_response = query_raw_index(
        index_root,
        sources,
        QueryRequest(query="freshness guidance 2026", max_results=2, max_candidates=3, snippet_chars=120),
    )

    manifest = build_report.get("manifest", {}) if isinstance(build_report, dict) else {}
    return {
        "build": {
            "source_count": manifest.get("source_count", 0),
            "chunk_count": manifest.get("chunk_count", 0),
            "term_count": manifest.get("term_count", 0),
            "fingerprint": manifest.get("source_ledger_hash"),
        },
        "query": {
            "status": query_response.status,
            "reason": query_response.reason,
            "evidence_count": len(query_response.evidence),
            "bounded": query_response.metadata.get("bounded"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build fixture markdown index and prove index-first bounded retrieval behavior."
    )
    parser.add_argument(
        "--fixtures-root",
        type=Path,
        default=Path("tests/fixtures/raw_retrieval"),
        help="Directory where markdown proof fixtures are created (default: tests/fixtures/raw_retrieval).",
    )
    parser.add_argument(
        "--index-root",
        type=Path,
        default=Path("tests/fixtures/raw_retrieval/index"),
        help="Directory where index artifacts are written (default: tests/fixtures/raw_retrieval/index).",
    )
    args = parser.parse_args()

    result = run_fixture_proof(args.fixtures_root, args.index_root)
    print(json.dumps(result, indent=2))

    if result["query"]["status"] != "ok":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
