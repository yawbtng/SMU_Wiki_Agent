from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..core.site_layout import ensure_layout_for_site_root
from ..core.storage import read_json, write_json
from ..sources.source_registry import utc_now_iso

TERMINAL_STATUSES = frozenset({"complete", "completed", "failed", "error", "cancelled", "canceled"})


def update_wiki_build_report(
    site_root: Path,
    *,
    status: str,
    exit_code: int | None = None,
    message: str = "",
    report_path: Path | None = None,
) -> dict[str, Any]:
    layout = ensure_layout_for_site_root(Path(site_root))
    destination = report_path or (layout.wiki_dir / "reports" / "wiki-build-latest.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = read_json(destination, {})
    if not isinstance(report, dict):
        report = {}
    normalized = str(status or "").strip().lower() or "unknown"
    now = utc_now_iso()
    report.update(
        {
            "status": normalized,
            "job_status": normalized,
            "site_root": str(layout.site_root),
            "wiki_dir": str(layout.wiki_dir),
            "report_path": str(destination),
            "updated_at": now,
        }
    )
    report.setdefault("generated_at", now)
    report.setdefault("runtime", "pi")
    if exit_code is not None:
        report["exit_code"] = int(exit_code)
    if message:
        report["last_progress"] = message
        if normalized in {"failed", "error"}:
            report["last_error"] = message
    if normalized in TERMINAL_STATUSES:
        report["job_finished_at"] = now
    write_json(destination, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update the latest LLM Wiki build report.")
    parser.add_argument("--site-root", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--message", default="")
    parser.add_argument("--report-path")
    args = parser.parse_args(argv)
    report = update_wiki_build_report(
        Path(args.site_root),
        status=args.status,
        exit_code=args.exit_code,
        message=args.message,
        report_path=Path(args.report_path) if args.report_path else None,
    )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
