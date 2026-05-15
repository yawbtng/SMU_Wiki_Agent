#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scrape_planner.config_v1 import load_config_v1
from scrape_planner.proof_m001 import proof_result_to_json, proof_result_to_markdown, run_proof


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run M001 cross-slice proof checks")
    parser.add_argument("--config", required=True, help="Path to M001 V1 config JSON")
    parser.add_argument("--run-root", required=True, help="Path to run root containing s03/s04/s05 artifacts")
    parser.add_argument("--output-dir", required=True, help="Directory where proof_result.json and proof_report.md are written")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config_v1(args.config)
    run_root = Path(args.run_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    result = run_proof(run_root, config)

    result_json_path = output_dir / "proof_result.json"
    report_md_path = output_dir / "proof_report.md"

    result_json_path.write_text(json.dumps(proof_result_to_json(result), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_md_path.write_text(proof_result_to_markdown(result), encoding="utf-8")

    return 0 if result.overall_verdict == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
