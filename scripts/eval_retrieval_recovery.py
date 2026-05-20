#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.scrape_planner.retrieval_recovery import (  # noqa: E402
    ANSWERABLE,
    NEEDS_WEB_RECOVERY,
    UNANSWERABLE_AFTER_RECOVERY,
    answer_with_recovery,
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(row, dict) or not row.get("question"):
            raise SystemExit(f"{path}:{line_no}: each case must be an object with a question")
        rows.append(row)
    return rows


def _matches_expected(case: dict[str, Any], result: dict[str, Any]) -> bool:
    expected_state = str(case.get("expected_state") or "").strip()
    if expected_state and result["state"] != expected_state:
        return False
    expected_sources = [str(item) for item in case.get("expected_sources", []) if str(item)]
    if expected_sources:
        evidence_blob = "\n".join(
            f"{item.get('url') or ''}\n{item.get('path') or ''}\n{item.get('title') or ''}"
            for item in result.get("evidence", [])
        )
        if not any(source in evidence_blob for source in expected_sources):
            return False
    if case.get("must_recover") and not result.get("recovery", {}).get("searched"):
        return False
    if case.get("must_not_recover") and result.get("recovery", {}).get("searched"):
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate corpus -> zvec -> graph -> Tavily recovery retrieval behavior.")
    parser.add_argument("run_root", type=Path)
    parser.add_argument("cases", type=Path, help="JSONL cases with question, expected_state, category, expected_sources.")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--tavily-api-key", default=os.getenv("TAVILY_API_KEY"))
    parser.add_argument("--include-domain", action="append", default=[])
    parser.add_argument("--zvec-db", type=Path, default=None)
    parser.add_argument("--reindex-zvec", action="store_true")
    parser.add_argument("--zvec-model", default=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest"))
    parser.add_argument("--ollama", default=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--answer-threshold", type=float, default=10.0)
    parser.add_argument("--max-web-results", type=int, default=5)
    args = parser.parse_args()

    cases = _read_jsonl(args.cases)
    outputs: list[dict[str, Any]] = []
    counts = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        ANSWERABLE: 0,
        NEEDS_WEB_RECOVERY: 0,
        UNANSWERABLE_AFTER_RECOVERY: 0,
        "web_recovery_triggered": 0,
        "post_scrape_evidence_hit": 0,
    }

    for case in cases:
        result = answer_with_recovery(
            str(case["question"]),
            args.run_root,
            tavily_api_key=args.tavily_api_key,
            include_domains=args.include_domain or None,
            top_k=args.top_k,
            answer_threshold=args.answer_threshold,
            max_web_results=args.max_web_results,
            reindex_after_recovery=args.reindex_zvec,
            zvec_db_path=args.zvec_db,
            zvec_model=args.zvec_model,
            ollama_base_url=args.ollama,
        ).to_dict()
        passed = _matches_expected(case, result)
        counts["total"] += 1
        counts["passed" if passed else "failed"] += 1
        counts[result["state"]] = counts.get(result["state"], 0) + 1
        if result.get("recovery", {}).get("searched"):
            counts["web_recovery_triggered"] += 1
        if result.get("recovery", {}).get("searched") and result["state"] == ANSWERABLE:
            counts["post_scrape_evidence_hit"] += 1
        outputs.append({"case": case, "passed": passed, "result": result})

    report = {"summary": counts, "results": outputs}
    text = json.dumps(report, indent=2, ensure_ascii=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
