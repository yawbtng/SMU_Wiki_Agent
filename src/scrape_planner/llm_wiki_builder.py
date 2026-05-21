from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from .site_layout import ensure_layout_for_site_root
from .source_registry import checksum_file, checksum_text, read_registry_rows, utc_now_iso, write_registry_rows
from .storage import write_json
from .tmux_runner import TmuxRunner


DEFAULT_TOPIC_PATTERNS = {
    "Departments Wiki": ["department", "school of", "college of", "faculty", "academic units"],
    "Finance Wiki": ["tuition", "fees", "cost", "financial aid", "billing", "payment", "student accounts"],
    "Scholarships Wiki": ["scholarship", "grant", "fellowship", "aid", "award"],
    "Admissions Wiki": ["admission", "apply", "application", "deadline", "requirements"],
    "Programs Wiki": ["program", "degree", "major", "minor", "graduate", "undergraduate"],
    "Student Life Wiki": ["housing", "dining", "campus life", "student services", "health", "orientation"],
    "Registrar Wiki": ["registrar", "calendar", "transcript", "enrollment", "course catalog", "academic records"],
}

INTEGRATED_STATES = {"integrated", "complete", "done"}
UNCERTAIN_PATTERNS = ("conflict", "conflicting", "uncertain", "unclear", "unknown", "maybe", "possibly")


def build_wiki(
    site_root: Path,
    *,
    registry_path: Path | None = None,
    wiki_dir: Path | None = None,
    report_path: Path | None = None,
    no_input: bool = False,
    resume: bool = False,
    rebuild: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = now or utc_now_iso()
    layout = ensure_layout_for_site_root(Path(site_root))
    registry = Path(registry_path) if registry_path else layout.registry_path
    wiki_root = Path(wiki_dir) if wiki_dir else layout.wiki_dir
    pages_dir = wiki_root / "pages"
    reports_dir = wiki_root / "reports"
    pages_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    if rebuild:
        _remove_generated_pages(wiki_root)

    rows = read_registry_rows(registry)
    latest_report = _read_resume_report(reports_dir, Path(report_path) if report_path else None) if resume and not rebuild else {}
    resume_source_ids = _resume_source_ids(latest_report, rows) if latest_report else []
    resume_source_id_set = set(resume_source_ids)
    if resume_source_ids:
        candidates = [
            _row
            for _row in rows
            if str(_row.get("status") or "").lower() == "ready"
            and str(_row.get("source_id") or "") in resume_source_id_set
            and _should_process(_row, layout.site_root, rebuild=rebuild)
        ]
        resume_source_ids = [str(_row.get("source_id") or "") for _row in candidates]
    else:
        candidates = [_row for _row in rows if _should_process(_row, layout.site_root, rebuild=rebuild)]
    skipped_source_ids = [
        str(row.get("source_id") or "")
        for row in rows
        if str(row.get("status") or "").lower() == "ready" and row not in candidates
    ]
    no_op = not rebuild and not candidates
    page_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    review_items: list[dict[str, str]] = []
    failed_source_ids: list[str] = []

    for row in candidates:
        source_issue = _source_text_issue(layout.site_root, row)
        if source_issue:
            source_id = str(row.get("source_id") or "")
            _append_unique(failed_source_ids, source_id)
            review_items.append(
                {
                    "source_id": source_id,
                    "title": str(row.get("title") or "Untitled source"),
                    "path": str(row.get("markdown_path") or ""),
                    "reason": source_issue,
                }
            )
            continue
        text = _read_source_text(layout.site_root, row)
        category = _category_for(row, text)
        page_groups[category].append({**row, "_source_text": text})
        reason = _review_reason(row, text)
        if reason:
            review_items.append(
                {
                    "source_id": str(row.get("source_id") or ""),
                    "title": str(row.get("title") or "Untitled source"),
                    "path": str(row.get("markdown_path") or ""),
                    "reason": reason,
                }
            )

    page_entries: list[dict[str, Any]] = []
    created_pages = 0
    updated_pages = 0
    page_paths_by_source: dict[str, str] = {}

    if not no_op:
        for category, group_rows in sorted(page_groups.items()):
            page_path = pages_dir / f"{_slugify(category)}.md"
            existed = page_path.exists()
            page_text, entry = _render_page(category, group_rows, timestamp, layout.site_root, page_path)
            page_path.write_text(page_text, encoding="utf-8")
            page_entries.append(entry)
            if existed:
                updated_pages += 1
            else:
                created_pages += 1
            for row in group_rows:
                page_paths_by_source[str(row.get("source_id") or "")] = _site_relative(page_path, layout.site_root)

        _write_index(wiki_root / "index.md", page_entries, timestamp)
        _write_review_queue(wiki_root / "review_queue.md", review_items, timestamp)

    integrated_sources = 0
    if not no_op:
        for row in rows:
            source_id = str(row.get("source_id") or "")
            if source_id in page_paths_by_source:
                row["wiki_status"] = "integrated"
                row["wiki_integrated_at"] = timestamp
                row["wiki_page_paths"] = [page_paths_by_source[source_id]]
                integrated_sources += 1
        write_registry_rows(registry, rows)

    destination = Path(report_path) if report_path else reports_dir / f"wiki-build-{_timestamp_slug(timestamp)}.json"
    report = {
        "status": "complete",
        "job_status": "complete",
        "site_root": str(layout.site_root),
        "registry_path": str(registry),
        "wiki_dir": str(wiki_root),
        "index_path": str(wiki_root / "index.md"),
        "log_path": str(wiki_root / "log.md"),
        "review_queue_path": str(wiki_root / "review_queue.md"),
        "report_path": str(destination),
        "generated_at": timestamp,
        "updated_at": timestamp,
        "no_input": bool(no_input),
        "resume": bool(resume),
        "rebuild": bool(rebuild),
        "no_op": no_op,
        "sources_considered": len(candidates),
        "processed_source_ids": [str(row.get("source_id") or "") for row in candidates],
        "skipped_source_ids": skipped_source_ids,
        "resume_source_ids": resume_source_ids,
        "pages_created": created_pages,
        "created_pages": created_pages,
        "pages_updated": updated_pages,
        "updated_pages": updated_pages,
        "integrated_sources": integrated_sources,
        "failed_source_ids": failed_source_ids,
        "review_queue_count": len(review_items),
        "pages": page_entries,
    }
    if no_op:
        _append_noop_log(wiki_root / "log.md", report, timestamp)
    else:
        _append_build_log(wiki_root / "log.md", report, page_entries, timestamp)
    write_json(destination, report)
    if destination.name != "wiki-build-latest.json":
        write_json(reports_dir / "wiki-build-latest.json", {**report, "report_path": str(reports_dir / "wiki-build-latest.json")})
    write_json(wiki_root / "build_report.json", report)
    return report


def lint_wiki(
    site_root: Path,
    *,
    registry_path: Path | None = None,
    wiki_dir: Path | None = None,
    report_path: Path | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = now or utc_now_iso()
    layout = ensure_layout_for_site_root(Path(site_root))
    registry = Path(registry_path) if registry_path else layout.registry_path
    wiki_root = Path(wiki_dir) if wiki_dir else layout.wiki_dir
    reports_dir = wiki_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    rows = read_registry_rows(registry)
    rows_by_source_id = {str(row.get("source_id") or ""): row for row in rows}
    expected_pages = {
        str(path)
        for row in rows
        for path in row.get("wiki_page_paths", [])
        if str(row.get("wiki_status") or "").lower() in INTEGRATED_STATES
    }
    index_text = (wiki_root / "index.md").read_text(encoding="utf-8", errors="replace") if (wiki_root / "index.md").exists() else ""

    orphan_pages: list[str] = []
    missing_citations: list[str] = []
    missing_index_entries: list[str] = []
    stale_source_checksums: list[str] = []

    for page_path in sorted((wiki_root / "pages").glob("*.md")) if (wiki_root / "pages").exists() else []:
        rel_page = _site_relative(page_path, layout.site_root)
        text = page_path.read_text(encoding="utf-8", errors="replace")
        metadata = _parse_frontmatter(text)
        if rel_page not in expected_pages:
            orphan_pages.append(rel_page)
        if not _has_citations(metadata, text):
            missing_citations.append(rel_page)
        if rel_page not in index_text:
            missing_index_entries.append(rel_page)

    for row in rows:
        if str(row.get("status") or "") != "ready":
            continue
        markdown_path = layout.site_root / str(row.get("markdown_path") or "")
        if markdown_path.exists() and str(row.get("checksum") or "") != checksum_file(markdown_path):
            stale_source_checksums.append(str(row.get("source_id") or ""))

    review_items = _parse_review_queue_items(wiki_root / "review_queue.md")
    represented_review_source_ids = {item["source_id"] for item in review_items if item.get("source_id")}
    for page_path in sorted((wiki_root / "pages").glob("*.md")) if (wiki_root / "pages").exists() else []:
        for item in _page_contradiction_items(page_path, layout.site_root, represented_review_source_ids):
            review_items.append(item)
            if item.get("source_id"):
                represented_review_source_ids.add(item["source_id"])
    review_queue_count = len(review_items)
    destination = Path(report_path) if report_path else reports_dir / f"wiki-lint-{_timestamp_slug(timestamp)}.json"
    report = {
        "status": "complete",
        "generated_at": timestamp,
        "site_root": str(layout.site_root),
        "registry_path": str(registry),
        "wiki_dir": str(wiki_root),
        "report_path": str(destination),
        "orphan_pages": orphan_pages,
        "missing_citations": missing_citations,
        "stale_source_checksums": stale_source_checksums,
        "review_queue_count": review_queue_count,
        "review_items": review_items,
        "missing_index_entries": missing_index_entries,
    }
    _append_log_line(
        wiki_root / "log.md",
        f"| {timestamp} | lint | orphan_pages={len(orphan_pages)} missing_citations={len(missing_citations)} "
        f"stale_sources={len(stale_source_checksums)} review_items={review_queue_count} "
        f"missing_index_entries={len(missing_index_entries)} report={destination} |",
    )
    write_json(destination, report)
    return report


def launch_wiki_builder(
    site_root: Path,
    *,
    session_name: str | None = None,
    runner: TmuxRunner | None = None,
    python_executable: str | None = None,
    resume: bool = True,
    rebuild: bool = False,
    runtime: str = "python",
) -> dict[str, Any]:
    layout = ensure_layout_for_site_root(Path(site_root))
    tmux = runner or TmuxRunner()
    name = session_name or f"llm-wiki-{layout.site_root.name}"
    report_path = layout.wiki_dir / "reports" / "wiki-build-latest.json"
    python_command_parts = [
        python_executable or sys.executable,
        "-m",
        "src.scrape_planner.llm_wiki_builder",
        "--site-root",
        str(layout.site_root),
        "--registry-path",
        str(layout.registry_path),
        "--wiki-dir",
        str(layout.wiki_dir),
        "--report-path",
        str(report_path),
        "--no-input",
    ]
    if resume:
        python_command_parts.append("--resume")
    if rebuild:
        python_command_parts.append("--rebuild")
    python_command = " ".join(shlex.quote(part) for part in python_command_parts)

    pi_bin = shutil.which("pi")
    use_pi = runtime == "pi" and pi_bin is not None
    if use_pi:
        skill_path = _repo_root() / ".pi" / "skills" / "karpathy-wiki-builder" / "SKILL.md"
        pi_prompt = (
            "Run the wiki builder non-interactively for this repo and site. "
            "Do not ask questions. Do not edit source files. "
            f"Execute exactly this command and wait until it exits: {python_command}"
        )
        command = " ".join(
            shlex.quote(part)
            for part in [
                pi_bin,
                "-p",
                "--skill",
                str(skill_path),
                pi_prompt,
            ]
        )
    else:
        command = python_command
    result = tmux.start(name, command, str(_repo_root()))
    return {
        **result,
        "session_name": name,
        "site_root": str(layout.site_root),
        "registry_path": str(layout.registry_path),
        "wiki_dir": str(layout.wiki_dir),
        "report_path": str(report_path),
        "builder_command": command,
        "runtime": "pi" if use_pi else "python",
    }


def _should_process(row: dict[str, Any], site_root: Path, *, rebuild: bool) -> bool:
    if str(row.get("status") or "").lower() != "ready":
        return False
    if rebuild:
        return True
    if str(row.get("wiki_status") or "").lower() not in INTEGRATED_STATES:
        return True
    markdown_path = site_root / str(row.get("markdown_path") or "")
    return markdown_path.exists() and str(row.get("checksum") or "") != checksum_file(markdown_path)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _remove_generated_pages(wiki_root: Path) -> None:
    maintained = {
        wiki_root / "index.md",
        wiki_root / "log.md",
        wiki_root / "review_queue.md",
    }
    for page_path in wiki_root.rglob("*.md"):
        if page_path in maintained:
            continue
        try:
            relative = page_path.relative_to(wiki_root)
        except ValueError:
            continue
        if relative.parts and relative.parts[0] == "reports":
            continue
        page_path.unlink()


def _read_resume_report(reports_dir: Path, requested_report_path: Path | None) -> dict[str, Any]:
    candidates: list[Path] = []
    if requested_report_path and requested_report_path.exists():
        candidates.append(requested_report_path)
    latest = reports_dir / "wiki-build-latest.json"
    if latest.exists() and latest not in candidates:
        candidates.append(latest)
    candidates.extend(
        path
        for path in sorted(reports_dir.glob("wiki-build-*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        if path not in candidates
    )
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        status = str(payload.get("status") or payload.get("job_status") or "").lower()
        job_status = str(payload.get("job_status") or payload.get("status") or "").lower()
        if status not in {"complete", "completed", "success"} or job_status not in {"complete", "completed", "success"}:
            return payload
    return {}


def _resume_source_ids(report: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    source_ids: list[str] = []
    for key in ("failed_source_ids", "pending_source_ids", "unintegrated_source_ids", "retry_source_ids"):
        for source_id in report.get(key, []) or []:
            _append_unique(source_ids, str(source_id))
    if source_ids:
        return source_ids
    processed = {str(source_id) for source_id in report.get("processed_source_ids", []) or []}
    pending = report.get("pending_source_ids")
    if isinstance(pending, list):
        for source_id in pending:
            _append_unique(source_ids, str(source_id))
    if source_ids:
        return source_ids
    if str(report.get("status") or report.get("job_status") or "").lower() in {"failed", "incomplete", "partial", "running"}:
        for row in rows:
            source_id = str(row.get("source_id") or "")
            if str(row.get("status") or "").lower() == "ready" and source_id not in processed:
                _append_unique(source_ids, source_id)
    return source_ids


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _read_source_text(site_root: Path, row: dict[str, Any]) -> str:
    path = site_root / str(row.get("markdown_path") or "")
    return path.read_text(encoding="utf-8", errors="replace")


def _source_text_issue(site_root: Path, row: dict[str, Any]) -> str:
    raw_path = str(row.get("markdown_path") or "")
    if not raw_path:
        return "Source markdown path is missing."
    path = site_root / raw_path
    if not path.exists():
        return "Source markdown is missing."
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Source markdown is unreadable: {exc}"
    if not text.strip():
        return "Source markdown is empty."
    return ""


def _category_for(row: dict[str, Any], text: str) -> str:
    haystack = f"{row.get('title', '')}\n{text}".lower()
    best_category = "General"
    best_score = 0
    for topic, patterns in DEFAULT_TOPIC_PATTERNS.items():
        label = topic.replace(" Wiki", "")
        score = sum(haystack.count(pattern.lower()) for pattern in patterns)
        if score > best_score:
            best_category = label
            best_score = score
    return best_category


def _review_reason(row: dict[str, Any], text: str) -> str:
    status = str(row.get("status") or "")
    if status == "needs-review":
        return str(row.get("error_reason") or "Source marked needs-review")
    lower = text.lower()
    for pattern in UNCERTAIN_PATTERNS:
        if pattern in lower:
            return f"Source contains uncertain or conflicting language matching `{pattern}`"
    return ""


def _render_page(
    category: str,
    rows: list[dict[str, Any]],
    timestamp: str,
    site_root: Path,
    page_path: Path,
) -> tuple[str, dict[str, Any]]:
    source_ids = [str(row.get("source_id") or "") for row in rows]
    source_paths = [str(row.get("markdown_path") or "") for row in rows]
    titles = [str(row.get("title") or "Untitled source") for row in rows]
    summary = _summary_for(category, titles)
    tags = [_slugify(category)]
    rel_page = _site_relative(page_path, site_root)
    content_lines = [
        f"# {category}",
        "",
        summary,
        "",
        "## Source Notes",
    ]
    for row in rows:
        content_lines.extend(
            [
                "",
                f"### {row.get('title') or 'Untitled source'}",
                "",
                _excerpt(str(row.get("_source_text") or "")),
            ]
        )
    content_lines.extend(["", "## Sources"])
    for row in rows:
        content_lines.append(f"- `{row.get('source_id')}` - {row.get('markdown_path')}")
    content = "\n".join(content_lines).rstrip() + "\n"
    frontmatter = _frontmatter(
        {
            "title": category,
            "category": category,
            "page_path": rel_page,
            "page_checksum": checksum_text(content),
            "source_ids": source_ids,
            "source_paths": source_paths,
            "source_count": len(rows),
            "tags": tags,
            "updated_at": timestamp,
        }
    )
    body = f"{frontmatter}\n{content}"
    return (
        body,
        {
            "title": category,
            "category": category,
            "path": rel_page,
            "summary": summary,
            "source_count": len(rows),
            "source_ids": source_ids,
            "source_paths": source_paths,
            "tags": tags,
        },
    )


def _frontmatter(values: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in values.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def _write_index(path: Path, page_entries: list[dict[str, Any]], timestamp: str) -> None:
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in page_entries:
        by_category[str(entry["category"])].append(entry)
    lines = [
        "# Wiki Index",
        "",
        f"Updated: {timestamp}",
        "",
    ]
    if not page_entries:
        lines.append("No generated pages yet.")
    for category in sorted(by_category):
        lines.extend(["", f"## {category}"])
        for entry in sorted(by_category[category], key=lambda item: str(item["title"])):
            page_ref = str(entry["path"]).removeprefix("wiki/")
            lines.append(
                f"- [{entry['title']}]({page_ref}) - {entry['summary']} Sources: {entry['source_count']}."
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_review_queue(path: Path, review_items: list[dict[str, str]], timestamp: str) -> None:
    lines = ["# Wiki Review Queue", "", f"Updated: {timestamp}", ""]
    for item in review_items:
        lines.append(f"- [ ] `{item['source_id']}` {item['title']} ({item['path']}): {item['reason']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _append_build_log(path: Path, report: dict[str, Any], page_entries: list[dict[str, Any]], timestamp: str) -> None:
    _ensure_log_header(path)
    _append_log_line(path, f"| {timestamp} | ingest | sources_considered={report['sources_considered']} |")
    for entry in sorted(page_entries, key=lambda item: str(item["path"])):
        _append_log_line(path, f"| {timestamp} | page-create | {entry['path'].removeprefix('wiki/')} | sources={entry['source_count']} |")
        _append_log_line(path, f"| {timestamp} | query-derived-page-create | {entry['path'].removeprefix('wiki/')} | sources={entry['source_count']} |")
    _append_log_line(
        path,
        f"| {timestamp} | rebuild | status={report['status']} created={report['pages_created']} "
        f"updated={report['pages_updated']} review_items={report['review_queue_count']} report={report['report_path']} |",
    )


def _append_noop_log(path: Path, report: dict[str, Any], timestamp: str) -> None:
    _ensure_log_header(path)
    _append_log_line(
        path,
        f"| {timestamp} | no-op | sources_considered=0 skipped={len(report['skipped_source_ids'])} "
        f"resume_sources={len(report['resume_source_ids'])} report={report['report_path']} |",
    )


def _ensure_log_header(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Wiki Log\n\n| Timestamp | Event | Details |\n| --- | --- | --- |\n", encoding="utf-8")


def _append_log_line(path: Path, line: str) -> None:
    _ensure_log_header(path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line.rstrip() + "\n")


def _parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    metadata: dict[str, Any] = {}
    current_key = ""
    for line in text[4:end].splitlines():
        if line.startswith("  - ") and current_key:
            metadata.setdefault(current_key, []).append(line[4:].strip())
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            current_key = key.strip()
            metadata[current_key] = value.strip() if value.strip() else []
    return metadata


def _source_ids_from_metadata(metadata: dict[str, Any], text: str) -> list[str]:
    values = metadata.get("source_ids")
    if isinstance(values, list):
        return [str(value) for value in values if str(value)]
    return re.findall(r"`([^`]+)`\s+-\s+raw_sources/", text)


def _has_citations(metadata: dict[str, Any], text: str) -> bool:
    source_ids = _source_ids_from_metadata(metadata, text)
    paths = metadata.get("source_paths")
    has_paths = isinstance(paths, list) and any(str(path).startswith("raw_sources/") for path in paths)
    return bool(source_ids and has_paths and "## Sources" in text)


def _review_queue_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip().startswith("- [ ]"))


def _parse_review_queue_items(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    current_heading = ""
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            current_heading = stripped.lstrip("#").strip()
            continue
        if not stripped.startswith("- [ ]"):
            continue
        source_id, reason = _review_source_and_reason(stripped)
        item_type = "contradiction" if "contradiction" in reason.lower() or "conflict" in reason.lower() else "review"
        items.append(
            {
                "source_id": source_id,
                "reason": reason,
                "line": line_number,
                "type": item_type,
                "heading": current_heading,
                "text": stripped,
            }
        )
    return items


def _review_source_and_reason(line: str) -> tuple[str, str]:
    body = re.sub(r"^- \[ \]\s*", "", line).strip()
    source_id = ""
    source_match = re.search(r"`([^`]+)`", body)
    if source_match:
        source_id = source_match.group(1).strip()
    if not source_id:
        source_match = re.search(r"\bsource_id\s*=\s*([^\s,;:]+)", body)
        if source_match:
            source_id = source_match.group(1).strip("`'\"")
    if not source_id:
        source_match = re.match(r"([A-Za-z0-9_.:-]+)", body)
        if source_match:
            source_id = source_match.group(1).strip("`'\"")
    reason = ""
    reason_match = re.search(r"\breason\s*=\s*(.+)$", body)
    if reason_match:
        reason = reason_match.group(1).strip()
    elif ":" in body:
        reason = body.rsplit(":", 1)[1].strip()
    else:
        reason = body
    return source_id, reason


def _page_contradiction_items(page_path: Path, site_root: Path, represented_source_ids: set[str]) -> list[dict[str, Any]]:
    text = page_path.read_text(encoding="utf-8", errors="replace")
    metadata = _parse_frontmatter(text)
    source_ids = _source_ids_from_metadata(metadata, text)
    source_id = next((candidate for candidate in source_ids if candidate not in represented_source_ids), "")
    if not source_id:
        source_id = next(iter(source_ids), "")
    if source_id in represented_source_ids:
        return []
    items: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if "contradiction" not in line.lower():
            continue
        items.append(
            {
                "source_id": source_id,
                "reason": line.strip(),
                "line": line_number,
                "type": "contradiction",
                "path": _site_relative(page_path, site_root),
                "text": line.strip(),
            }
        )
        break
    return items


def _summary_for(category: str, titles: list[str]) -> str:
    if not titles:
        return f"{category} summary."
    if len(titles) == 1:
        return f"{titles[0]}."
    return f"{category} summary from {len(titles)} sources."


def _excerpt(text: str, max_chars: int = 420) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return "No source text was readable."
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 3].rstrip() + "..."


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return slug or "general"


def _timestamp_slug(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "-", value).strip("-")


def _site_relative(path: Path, site_root: Path) -> str:
    try:
        return str(Path(path).relative_to(site_root))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or lint the local LLM wiki without prompts.")
    parser.add_argument("--site-root", required=True)
    parser.add_argument("--registry-path")
    parser.add_argument("--wiki-dir")
    parser.add_argument("--report-path")
    parser.add_argument("--no-input", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--lint", action="store_true")
    args = parser.parse_args(argv)
    if args.lint:
        report = lint_wiki(
            Path(args.site_root),
            registry_path=Path(args.registry_path) if args.registry_path else None,
            wiki_dir=Path(args.wiki_dir) if args.wiki_dir else None,
            report_path=Path(args.report_path) if args.report_path else None,
        )
    else:
        if not args.no_input:
            parser.error("CLI wiki builds require --no-input; call build_wiki() directly for programmatic use.")
        report = build_wiki(
            Path(args.site_root),
            registry_path=Path(args.registry_path) if args.registry_path else None,
            wiki_dir=Path(args.wiki_dir) if args.wiki_dir else None,
            report_path=Path(args.report_path) if args.report_path else None,
            no_input=args.no_input,
            resume=args.resume,
            rebuild=args.rebuild,
        )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
