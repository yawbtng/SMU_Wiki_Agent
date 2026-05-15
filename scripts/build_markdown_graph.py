from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.scrape_planner.markdown_graph import answer_context, build_graph, graph_stats, search_pages  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build/query deterministic raw-markdown knowledge graph artifacts.")
    parser.add_argument("--data-root", default="data", help="Project data directory.")
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--query", default="")
    parser.add_argument("--unit", default="")
    parser.add_argument("--budget-chars", type=int, default=12000)
    args = parser.parse_args()

    run_root = Path(args.data_root) / "sites" / args.site_id / args.run_id
    graph = build_graph(run_root, args.site_id, args.run_id)
    output = {"graph": graph["counts"], "stats": graph_stats(run_root)}
    if args.query:
        output["search"] = search_pages(run_root, args.query, unit=args.unit or None, limit=10)
        output["answer_context"] = answer_context(
            run_root,
            args.query,
            unit=args.unit or None,
            budget_chars=args.budget_chars,
        )
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
