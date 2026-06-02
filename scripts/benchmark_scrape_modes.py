from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.scrape_planner.scrape.scrape_benchmark import benchmark_mode, build_report, load_sample_urls


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark scrape modes on the same URL sample.")
    parser.add_argument("--selected-urls", required=True, help="Path to selected_urls.json")
    parser.add_argument("--limit", type=int, default=12, help="How many URLs to benchmark")
    parser.add_argument("--offset", type=int, default=0, help="Start offset inside selected_urls.json")
    parser.add_argument("--concurrency", type=int, default=4, help="Parallel requests per mode")
    parser.add_argument("--modes", nargs="+", default=["fetcher", "lightpanda"], help="Modes to benchmark")
    parser.add_argument("--lightpanda-cdp-url", default="", help="CDP URL for Lightpanda mode")
    parser.add_argument("--output", default="", help="Optional report output path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected_urls_path = Path(args.selected_urls)
    urls = load_sample_urls(selected_urls_path, args.limit, offset=args.offset)
    summaries = [
        benchmark_mode(
            urls,
            mode=mode,
            concurrency=args.concurrency,
            lightpanda_cdp_url=args.lightpanda_cdp_url,
        )
        for mode in args.modes
    ]
    report = build_report(
        benchmark_name=selected_urls_path.stem,
        sample_urls=urls,
        summaries=summaries,
    )
    text = json.dumps(report, indent=2, ensure_ascii=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
