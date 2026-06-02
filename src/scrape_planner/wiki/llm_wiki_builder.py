from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..core.data_root import repo_root
from ..core.site_layout import ensure_layout_for_site_root
from ..core.storage import write_json
from ..sources.source_registry import read_registry_rows, utc_now_iso
from .wiki_launcher import assert_no_concurrent_wiki_build, launch_wiki_builder
from .wiki_lint import lint_wiki

_INTEGRATED = frozenset({"integrated", "complete", "done", "excluded", "not-applicable"})


def _candidates(rows: list[dict[str, Any]], *, rebuild: bool, resume: bool) -> list[dict[str, Any]]:
    ready = [row for row in rows if str(row.get("status") or "").lower() == "ready"]
    if rebuild:
        return ready
    if resume:
        return [row for row in ready if str(row.get("wiki_status") or "").lower() not in _INTEGRATED]
    return [row for row in ready if str(row.get("wiki_status") or "").lower() == "pending"]


def _run_pi_compile(site_root: Path, *, rebuild: bool) -> None:
    if os.environ.get("WIKI_SKIP_PI"):
        return
    script = repo_root() / ".pi/skills/llm-wiki-v2/scripts/generate_wiki.sh"
    subprocess.run(["bash", str(script), "--site-root", str(site_root), "--mode", "rebuild" if rebuild else "resume"], check=True, cwd=repo_root())


def build_wiki(
    site_root: Path,
    *,
    registry_path: Path | None = None,
    wiki_dir: Path | None = None,
    report_path: Path | None = None,
    tmux_session: str | None = None,
    no_input: bool = False,
    resume: bool = False,
    rebuild: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    layout = ensure_layout_for_site_root(Path(site_root))
    wiki_root = Path(wiki_dir) if wiki_dir else layout.wiki_dir
    reports = wiki_root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    destination = Path(report_path) if report_path else reports / "wiki-build-latest.json"
    registry = Path(registry_path) if registry_path else layout.registry_path
    timestamp = now or utc_now_iso()
    picks = _candidates(read_registry_rows(registry), rebuild=rebuild, resume=resume)
    if no_input and picks:
        _run_pi_compile(layout.site_root, rebuild=rebuild)
    rows_after = read_registry_rows(registry)
    integrated = sum(1 for row in rows_after if str(row.get("wiki_status") or "").lower() in {"integrated", "complete", "done"})
    report = {
        "status": "complete", "job_status": "complete", "runtime": "pi", "site_root": str(layout.site_root),
        "registry_path": str(registry), "wiki_dir": str(wiki_root), "report_path": str(destination),
        "generated_at": timestamp, "updated_at": timestamp, "job_finished_at": timestamp, "no_input": no_input, "resume": resume, "rebuild": rebuild,
        "no_op": not rebuild and not picks, "sources_considered": len(picks),
        "processed_source_ids": [str(row.get("source_id") or "") for row in picks], "tmux_session": str(tmux_session or ""),
        "semantic_page_count": 0, "integrated_sources": integrated, "pages_created": 0, "pages_updated": 0,
        "required_markdown_paths": ["wiki/index.md", "wiki/review_queue.md"],
    }
    write_json(destination, report)
    write_json(wiki_root / "build_report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Orchestrate Pi LLM wiki compile or lint.")
    parser.add_argument("--site-root", required=True)
    parser.add_argument("--registry-path")
    parser.add_argument("--wiki-dir")
    parser.add_argument("--report-path")
    parser.add_argument("--tmux-session")
    parser.add_argument("--no-input", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--lint", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.site_root)
    kw = {"registry_path": Path(args.registry_path) if args.registry_path else None, "wiki_dir": Path(args.wiki_dir) if args.wiki_dir else None, "report_path": Path(args.report_path) if args.report_path else None}
    if args.lint:
        report = lint_wiki(root, **kw)
    elif not args.no_input:
        parser.error("CLI wiki builds require --no-input.")
    else:
        report = build_wiki(root, tmux_session=args.tmux_session, no_input=True, resume=args.resume, rebuild=args.rebuild, **kw)
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
