from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..core.data_root import repo_root
from ..core.site_layout import ensure_layout_for_site_root
from ..core.storage import write_json
from ..sources.source_registry import read_registry_rows, utc_now_iso, write_registry_rows
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
    subprocess.run(
        ["bash", str(script), "--site-root", str(site_root), "--mode", "rebuild" if rebuild else "resume"],
        check=True,
        cwd=repo_root(),
    )


def _pi_compile_skipped() -> bool:
    return bool(os.environ.get("WIKI_SKIP_PI"))


def _read_source_markdown(site_root: Path, row: dict[str, Any]) -> str:
    path = Path(str(row.get("markdown_path") or ""))
    if not path.is_absolute():
        path = site_root / path
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _topic_for_row(row: dict[str, Any], body: str) -> tuple[str, str]:
    kind = str(row.get("source_kind") or "").lower()
    haystack = f"{row.get('title') or ''}\n{row.get('original_url') or ''}\n{body[:1000]}".lower()
    if kind in {"excel", "csv", "tabular"} or "program" in haystack:
        return "programs", "Programs"
    if "tuition" in haystack or "billing" in haystack or "finance" in haystack or "financial" in haystack:
        return "finance", "Finance"
    if "admission" in haystack or "apply" in haystack or "deadline" in haystack:
        return "admissions", "Admissions"
    title = str(row.get("title") or row.get("source_id") or "source")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "source"
    return slug[:80], title.strip() or slug.replace("-", " ").title()


def _scaffold_source_pages(site_root: Path, wiki_root: Path, rows: list[dict[str, Any]], *, now: str) -> tuple[int, list[dict[str, Any]]]:
    if not rows:
        return 0, rows
    pages_dir = wiki_root / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        body = _read_source_markdown(site_root, row)
        slug, title = _topic_for_row(row, body)
        bucket = grouped.setdefault(slug, {"title": title, "rows": [], "bodies": []})
        bucket["rows"].append(row)
        bucket["bodies"].append(body)

    page_paths: dict[str, str] = {}
    for slug, bucket in sorted(grouped.items()):
        source_ids = [str(row.get("source_id") or "") for row in bucket["rows"] if str(row.get("source_id") or "")]
        excerpts = []
        for body in bucket["bodies"]:
            text = strip_markdown_for_excerpt(body)
            if text:
                excerpts.append(text[:1200])
        page_path = pages_dir / f"{slug}.md"
        page_paths[slug] = str(page_path.relative_to(site_root))
        page_path.write_text(
            "---\n"
            f"title: {bucket['title']}\n"
            "page_type: source\n"
            "source_ids:\n"
            + "".join(f"  - {source_id}\n" for source_id in source_ids)
            + f"updated_at: {now}\n"
            "---\n\n"
            f"# {bucket['title']}\n\n"
            + "\n\n".join(excerpts or ["Source content is available in the raw source registry."])
            + "\n\n## Sources\n"
            + "".join(f"- {source_id}\n" for source_id in source_ids),
            encoding="utf-8",
        )

    index_lines = ["# Wiki Index", ""]
    for slug, bucket in sorted(grouped.items()):
        rel = Path(page_paths[slug]).relative_to("wiki")
        index_lines.append(f"- [{bucket['title']}]({rel})")
    (wiki_root / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    (wiki_root / "review_queue.md").write_text("# Review Queue\n\n", encoding="utf-8")

    updated_rows = []
    source_to_path: dict[str, str] = {}
    for slug, bucket in grouped.items():
        for row in bucket["rows"]:
            source_to_path[str(row.get("source_id") or "")] = page_paths[slug]
    for row in read_registry_rows(site_root / "raw_sources" / "registry.jsonl"):
        source_id = str(row.get("source_id") or "")
        if source_id in source_to_path:
            row = {
                **row,
                "wiki_status": "integrated",
                "wiki_integrated_at": now,
                "wiki_page_paths": [source_to_path[source_id]],
            }
        updated_rows.append(row)
    write_registry_rows(site_root / "raw_sources" / "registry.jsonl", updated_rows)
    return len(grouped), updated_rows


def strip_markdown_for_excerpt(text: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines()]
    cleaned = [line.lstrip("# ").strip() for line in lines if line.strip() and not line.strip().startswith("---")]
    return "\n".join(cleaned).strip()


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
    pages_created = 0
    if no_input and picks:
        _run_pi_compile(layout.site_root, rebuild=rebuild)
        if _pi_compile_skipped():
            pages_created, _ = _scaffold_source_pages(layout.site_root, wiki_root, picks, now=timestamp)
    rows_after = read_registry_rows(registry)
    integrated = sum(1 for row in rows_after if str(row.get("wiki_status") or "").lower() in {"integrated", "complete", "done"})
    report = {
        "status": "complete", "job_status": "complete", "runtime": "pi", "site_root": str(layout.site_root),
        "registry_path": str(registry), "wiki_dir": str(wiki_root), "report_path": str(destination),
        "generated_at": timestamp, "updated_at": timestamp, "job_finished_at": timestamp, "no_input": no_input, "resume": resume, "rebuild": rebuild,
        "no_op": not rebuild and not picks, "sources_considered": len(picks),
        "processed_source_ids": [str(row.get("source_id") or "") for row in picks], "tmux_session": str(tmux_session or ""),
        "semantic_page_count": pages_created, "integrated_sources": integrated, "pages_created": pages_created, "pages_updated": 0,
        "required_markdown_paths": ["wiki/index.md", "wiki/review_queue.md"],
    }
    write_json(destination, report)
    write_json(wiki_root / "build_report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Orchestrate LLM Wiki v2 compile reporting or lint.")
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
