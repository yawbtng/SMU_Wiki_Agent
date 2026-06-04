#!/usr/bin/env python3
"""Score discovered university URLs for student-facing wiki scraping value."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.scrape_planner.scrape.url_policy import TARGET_YEAR, detect_dated_archive
from src.scrape_planner.scrape.url_scoring import DEFAULT_THRESHOLD, score_url, select_scored_urls


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score discovered URLs using shared student URL policy signals.")
    parser.add_argument("--input", required=True, help="Path to discovered_urls.json")
    parser.add_argument("--output", required=True, help="Path to selected_urls_llm.json")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    output_path = Path(args.output)
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("Input JSON must be a list of discovered URL rows")

    scored = [score_url(item if isinstance(item, dict) else {"url": str(item)}) for item in data]
    scored.sort(key=lambda row: int(row.get("score") or 0), reverse=True)
    selected = select_scored_urls(scored, threshold=int(args.threshold))

    output = {
        "selection_method": "url_scoring_module",
        "default_threshold": int(args.threshold),
        "target_year": TARGET_YEAR,
        "total_scored": len(scored),
        "total_selected": len(selected),
        "scored_urls": scored,
        "selected_urls": selected,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Selected {len(selected)} URLs out of {len(scored)} (threshold={args.threshold}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
