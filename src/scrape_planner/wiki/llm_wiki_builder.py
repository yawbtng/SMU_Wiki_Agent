from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..core.data_root import repo_root
from ..core.site_layout import ensure_layout_for_site_root
from ..sources.source_registry import checksum_file, checksum_text, read_registry_rows, utc_now_iso, write_registry_rows
from ..core.storage import write_json
from ..infra.tmux_runner import TmuxRunner
from ..core.wiki_common import (
    INTEGRATED_STATES,
    parse_markdown_frontmatter,
    session_timestamp_slug,
    site_relative,
    timestamp_slug,
)
from .stepper_status import latest_json_report, tmux_session_alive
from .wiki_graph_artifacts import write_wiki_graph_artifacts


DEFAULT_TOPIC_PATTERNS = {
    "Departments Wiki": ["department", "school of", "college of", "faculty", "academic units"],
    "Finance Wiki": ["tuition", "fees", "cost", "financial aid", "billing", "payment", "student accounts"],
    "Scholarships Wiki": ["scholarship", "grant", "fellowship", "aid", "award"],
    "Admissions Wiki": ["admission", "apply", "application", "deadline", "requirements"],
    "Programs Wiki": ["program", "degree", "major", "minor", "graduate", "undergraduate"],
    "Student Life Wiki": ["housing", "dining", "campus life", "student services", "health", "orientation"],
    "Registrar Wiki": ["registrar", "calendar", "transcript", "enrollment", "course catalog", "academic records"],
}

SCHOOL_ENTITY_PATTERNS = {
    "cox-school-of-business": ("cox school of business", "cox school", "smu cox", "business school", "/cox/"),
    "dedman-college": ("dedman college", "dedman college of humanities", "dedman college of humanities and sciences", "/dedman/"),
    "lyle-school-of-engineering": ("lyle school of engineering", "smu lyle", "engineering school", "/lyle/"),
    "meadows-school-of-the-arts": ("meadows school", "meadows school of the arts", "/meadows/"),
    "simmons-school-of-education": ("simmons school", "simmons school of education", "/simmons/"),
    "perkins-school-of-theology": ("perkins school", "perkins school of theology", "/perkins/"),
    "dedman-school-of-law": ("dedman school of law", "smu law", "law school", "/law/"),
}

SCHOOL_DISPLAY_NAMES = {
    "cox-school-of-business": "Cox School of Business",
    "dedman-college": "Dedman College",
    "lyle-school-of-engineering": "Lyle School of Engineering",
    "meadows-school-of-the-arts": "Meadows School of the Arts",
    "simmons-school-of-education": "Simmons School of Education",
    "perkins-school-of-theology": "Perkins School of Theology",
    "dedman-school-of-law": "Dedman School of Law",
}

DEPARTMENT_ENTITY_PATTERNS = {
    "computer-science": ("computer science department", "department of computer science", "computer science"),
    "finance": ("finance department", "department of finance", "finance"),
    "accounting": ("accounting department", "department of accounting", "accounting"),
    "management": ("management department", "department of management", "management"),
    "marketing": ("marketing department", "department of marketing", "marketing"),
    "business-analytics": ("business analytics", "analytics department"),
    "data-science": ("data science", "department of statistics and data science"),
}

OFFICE_ENTITY_PATTERNS = {
    "admissions": ("admission office", "office of admission", "admissions office", "graduate admissions", "undergraduate admission"),
    "registrar": ("registrar", "office of the registrar", "academic records"),
    "financial-aid": ("financial aid", "office of financial aid", "scholarships and financial aid"),
    "student-accounts": ("student accounts", "bursar", "billing", "payment plan"),
    "student-services": ("student services", "student affairs"),
    "international-student-office": ("international student", "international student office", "isss"),
}

UNCERTAIN_PATTERNS = ("conflict", "conflicting", "uncertain", "unclear", "unknown", "maybe", "possibly")


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
    excluded_source_ids: list[str] = []
    exclusion_reasons: dict[str, str] = {}

    total_candidates = len(candidates)
    if no_input and total_candidates:
        _emit_progress(f"classify sources 0/{total_candidates}")
    for idx, row in enumerate(candidates, start=1):
        if no_input and (idx == 1 or idx % 250 == 0 or idx == total_candidates):
            _emit_progress(f"classify sources {idx}/{total_candidates}")
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
        text = _clean_source_text_for_wiki(_read_source_text(layout.site_root, row))
        exclusion_reason = _source_exclusion_reason(row, text)
        if exclusion_reason:
            source_id = str(row.get("source_id") or "")
            _append_unique(excluded_source_ids, source_id)
            exclusion_reasons[source_id] = exclusion_reason
            review_items.append(
                {
                    "source_id": source_id,
                    "title": str(row.get("title") or "Untitled source"),
                    "path": str(row.get("markdown_path") or ""),
                    "reason": f"Excluded from student wiki: {exclusion_reason}",
                }
            )
            continue
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
        total_pages_to_write = len(page_groups) + sum(len(group_rows) for group_rows in page_groups.values())
        written_pages = 0
        if no_input and total_pages_to_write:
            _emit_progress(f"write markdown pages 0/{total_pages_to_write}")
        for category, group_rows in sorted(page_groups.items()):
            category_slug = _slugify(category)
            page_path = pages_dir / f"{category_slug}.md"
            existed = page_path.exists()
            page_text, entry = _render_page(category, group_rows, timestamp, layout.site_root, page_path)
            page_path.write_text(page_text, encoding="utf-8")
            page_entries.append(entry)
            written_pages += 1
            if no_input and (written_pages == 1 or written_pages % 250 == 0 or written_pages == total_pages_to_write):
                _emit_progress(f"write markdown pages {written_pages}/{total_pages_to_write}")
            if existed:
                updated_pages += 1
            else:
                created_pages += 1
            source_pages_dir = pages_dir / category_slug
            source_pages_dir.mkdir(parents=True, exist_ok=True)
            used_source_slugs: set[str] = set()
            for row in group_rows:
                source_slug = _source_page_slug(row, used_source_slugs)
                source_page_path = source_pages_dir / f"{source_slug}.md"
                source_existed = source_page_path.exists()
                source_page_text, source_entry = _render_source_page(
                    category,
                    row,
                    timestamp,
                    layout.site_root,
                    source_page_path,
                    category_page_path=_site_relative(page_path, layout.site_root),
                )
                source_page_path.write_text(source_page_text, encoding="utf-8")
                page_entries.append(source_entry)
                written_pages += 1
                if no_input and (written_pages == 1 or written_pages % 250 == 0 or written_pages == total_pages_to_write):
                    _emit_progress(f"write markdown pages {written_pages}/{total_pages_to_write}")
                if source_existed:
                    updated_pages += 1
                else:
                    created_pages += 1
                page_paths_by_source[str(row.get("source_id") or "")] = _site_relative(source_page_path, layout.site_root)

        semantic_entries, semantic_created, semantic_updated = _write_semantic_pages(
            wiki_root,
            page_groups,
            timestamp,
            layout.site_root,
        )
        if no_input and semantic_entries:
            _emit_progress(f"write semantic pages {len(semantic_entries)}")
        page_entries.extend(semantic_entries)
        created_pages += semantic_created
        updated_pages += semantic_updated

        _write_index(wiki_root / "index.md", page_entries, timestamp)
        _write_routing_pages(wiki_root, page_entries, timestamp)
        _write_optional_canonical_indexes(wiki_root, page_entries, timestamp)
        _write_source_notes(wiki_root, page_groups, timestamp, layout.site_root)
        _write_review_queue(wiki_root / "review_queue.md", review_items, timestamp)
        graph_report = write_wiki_graph_artifacts(wiki_root, layout.site_root, updated_at=timestamp)
    else:
        graph_report = {}

    integrated_sources = 0
    if not no_op:
        for row in rows:
            source_id = str(row.get("source_id") or "")
            if source_id in page_paths_by_source:
                row["wiki_status"] = "integrated"
                row["wiki_integrated_at"] = timestamp
                row["wiki_page_paths"] = [page_paths_by_source[source_id]]
                integrated_sources += 1
            elif source_id in exclusion_reasons:
                row["wiki_status"] = "excluded"
                row["wiki_excluded_at"] = timestamp
                row["wiki_exclusion_reason"] = exclusion_reasons[source_id]
                row["wiki_page_paths"] = []
        write_registry_rows(registry, rows)
    else:
        integrated_sources = len(
            [
                row
                for row in rows
                if str(row.get("status") or "").lower() == "ready"
                and str(row.get("wiki_status") or "").lower() in INTEGRATED_STATES
            ]
        )
        review_items = _parse_review_queue_items(wiki_root / "review_queue.md")
        pages_created = int(latest_report.get("pages_created") or latest_report.get("created_pages") or 0)
        pages_updated = int(latest_report.get("pages_updated") or latest_report.get("updated_pages") or 0)
        page_entries = list(latest_report.get("pages") or []) if isinstance(latest_report.get("pages"), list) else []

    destination = Path(report_path) if report_path else reports_dir / f"wiki-build-{_timestamp_slug(timestamp)}.json"
    report = {
        "status": "complete",
        "job_status": "complete",
        "runtime": "python",
        "site_root": str(layout.site_root),
        "registry_path": str(registry),
        "wiki_dir": str(wiki_root),
        "index_path": str(wiki_root / "index.md"),
        "log_path": str(wiki_root / "log.md"),
        "review_queue_path": str(wiki_root / "review_queue.md"),
        "report_path": str(destination),
        "tmux_session": str(tmux_session or ""),
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
        "excluded_source_ids": excluded_source_ids,
        "excluded_source_count": len(excluded_source_ids),
        "exclusion_reasons": exclusion_reasons,
        "review_queue_count": len(review_items),
        "semantic_page_count": len([entry for entry in page_entries if entry.get("page_type") == "semantic"]),
        **graph_report,
        "pages": page_entries,
        "required_markdown_paths": [
            "wiki/index.md",
            "wiki/routing/audience.md",
            "wiki/routing/intent.md",
            "wiki/routing/topics.md",
            "wiki/source-notes/index.md",
            "wiki/review_queue.md",
            "wiki/pages/schools/cox.md",
            "wiki/pages/schools/cox/graduate.md",
            "wiki/pages/schools/cox/admissions.md",
            "wiki/pages/schools/cox/courses.md",
            "wiki/pages/schools/cox/costs-and-aid.md",
        ],
    }
    if no_op:
        _append_noop_log(wiki_root / "log.md", report, timestamp)
    else:
        _append_build_log(wiki_root / "log.md", report, page_entries, timestamp)
    if no_input:
        _emit_progress(
            f"complete status={report['status']} no_op={report['no_op']} "
            f"sources={report['sources_considered']} pages_created={report['pages_created']} "
            f"pages_updated={report['pages_updated']} integrated={report['integrated_sources']}"
        )
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

    for page_path in _iter_wiki_page_paths(wiki_root):
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
    for page_path in _iter_wiki_page_paths(wiki_root):
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


def _iter_wiki_page_paths(wiki_root: Path) -> list[Path]:
    pages_root = wiki_root / "pages"
    if not pages_root.exists():
        return []
    return sorted(path for path in pages_root.rglob("*.md") if path.is_file())


def _active_wiki_build_session_from_report(report_path: Path, runner: TmuxRunner) -> str | None:
    report_dir = report_path.parent
    _, report = latest_json_report(report_dir, "wiki-build-*.json")
    if not report:
        return None
    reported = str(report.get("status") or report.get("job_status") or "").lower()
    session = str(report.get("tmux_session") or "")
    if reported not in {"running", "initializing", "starting"}:
        return None
    if session and tmux_session_alive(session, runner=runner):
        return session
    return None


def assert_no_concurrent_wiki_build(
    site_root: Path,
    *,
    runner: TmuxRunner | None = None,
) -> None:
    layout = ensure_layout_for_site_root(Path(site_root))
    report_path = layout.wiki_dir / "reports" / "wiki-build-latest.json"
    tmux = runner or TmuxRunner()
    active = _active_wiki_build_session_from_report(report_path, tmux)
    if active:
        raise RuntimeError(f"Wiki build already running in tmux session `{active}`.")


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
    name = session_name or _default_session_name(layout.site_root.name, tmux)
    report_path = layout.wiki_dir / "reports" / "wiki-build-latest.json"
    normalized_runtime = _normalize_wiki_runtime(runtime)
    if normalized_runtime != "python":
        return {"ok": False, "error": f"Unsupported wiki builder runtime: {runtime}", "runtime": str(runtime)}

    active_session = _active_wiki_build_session_from_report(report_path, tmux)
    if active_session:
        return {
            "ok": False,
            "error": f"Wiki build already running in tmux session `{active_session}`.",
            "session_name": active_session,
            "runtime": normalized_runtime,
        }

    python_command_parts = [
        python_executable or sys.executable,
        "-m",
        "src.scrape_planner.wiki.llm_wiki_builder",
        "--site-root",
        str(layout.site_root),
        "--registry-path",
        str(layout.registry_path),
        "--wiki-dir",
        str(layout.wiki_dir),
        "--report-path",
        str(report_path),
        "--tmux-session",
        name,
        "--no-input",
    ]
    if resume:
        python_command_parts.append("--resume")
    if rebuild:
        python_command_parts.append("--rebuild")
    python_command = " ".join(shlex.quote(part) for part in python_command_parts)

    command = python_command

    result = tmux.start(name, command, str(repo_root()))
    if result.get("ok"):
        timestamp = utc_now_iso()
        launch_report = {
            "status": "running",
            "job_status": "running",
            "runtime": normalized_runtime,
            "site_root": str(layout.site_root),
            "registry_path": str(layout.registry_path),
            "wiki_dir": str(layout.wiki_dir),
            "index_path": str(layout.wiki_dir / "index.md"),
            "log_path": str(layout.wiki_dir / "log.md"),
            "review_queue_path": str(layout.wiki_dir / "review_queue.md"),
            "report_path": str(report_path),
            "generated_at": timestamp,
            "updated_at": timestamp,
            "last_progress": "Launch requested",
            "tmux_session": name,
            "no_input": True,
            "resume": bool(resume),
            "rebuild": bool(rebuild),
            "no_op": False,
            "sources_considered": 0,
            "processed_source_ids": [],
            "skipped_source_ids": [],
            "resume_source_ids": [],
            "pages_created": 0,
            "created_pages": 0,
            "pages_updated": 0,
            "updated_pages": 0,
            "integrated_sources": 0,
            "failed_source_ids": [],
            "review_queue_count": 0,
            "pages": [],
            "builder_command": command,
        }
        write_json(report_path, launch_report)
    return {
        **result,
        "session_name": name,
        "site_root": str(layout.site_root),
        "registry_path": str(layout.registry_path),
        "wiki_dir": str(layout.wiki_dir),
        "report_path": str(report_path),
        "builder_command": command,
        "python_builder_command": python_command,
        "runtime": normalized_runtime,
    }


def _normalize_wiki_runtime(runtime: str) -> str:
    value = str(runtime or "python").strip().lower().replace("_", "-")
    if value in {"", "deterministic"}:
        return "python"
    return value


def _should_process(row: dict[str, Any], site_root: Path, *, rebuild: bool) -> bool:
    if str(row.get("status") or "").lower() != "ready":
        return False
    if rebuild:
        return True
    if str(row.get("wiki_status") or "").lower() not in INTEGRATED_STATES:
        return True
    markdown_path = site_root / str(row.get("markdown_path") or "")
    return markdown_path.exists() and str(row.get("checksum") or "") != checksum_file(markdown_path)


def _default_session_name(site_name: str, runner: TmuxRunner) -> str:
    base = f"wiki-{_slugify(site_name)}-{_session_timestamp_slug(utc_now_iso())}"
    name = base
    suffix = 2
    session_exists = getattr(runner, "session_exists", None)
    while callable(session_exists) and session_exists(name):
        name = f"{base}-{suffix}"
        suffix += 1
    return name


def _emit_progress(message: str) -> None:
    print(f"[llm-wiki] {message}", file=sys.stderr, flush=True)


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


def _clean_source_text_for_wiki(text: str) -> str:
    cleaned = str(text or "")
    footer_match = re.search(r"(?im)^##\s+Cox School of Business\s*$", cleaned)
    if footer_match and "### Follow us" in cleaned[footer_match.start() :]:
        cleaned = cleaned[: footer_match.start()].rstrip()
    removable_headings = {
        "Follow us",
        "About",
        "Degrees & Programs",
        "Faculty & Research",
        "AI @ Cox",
        "Apply",
        "Did you know?",
        "Search Submit",
        "Popular Searches",
    }
    social_lines = {"Facebook", "Instagram", "LinkedIn", "X", "TikTok", "YouTube"}
    output: list[str] = []
    skipping = False
    for line in cleaned.splitlines():
        heading = line.strip().lstrip("#").strip()
        if line.lstrip().startswith("#"):
            skipping = heading in removable_headings
            if skipping:
                continue
        if skipping:
            continue
        if line.strip() in social_lines:
            continue
        output.append(line)
    return "\n".join(output).strip()


def _source_exclusion_reason(row: dict[str, Any], text: str) -> str:
    original_url = str(row.get("original_url") or "").lower()
    title = str(row.get("title") or "").lower().replace("-", " ")
    lower = str(text or "").lower()
    source_hint = f"{original_url}\n{title}"
    if re.search(r"/20\d{2}-\d{2}-\d{2}-", original_url) and not re.search(r"/202[56]-", original_url):
        return "old dated article, not current student guidance"
    if re.search(r"\bclass notes\b|\balumni notes\b|\bclass of 19\d{2}\b|\bclass of 20[0-2]\d\b", source_hint):
        return "alumni/class notes, not student guidance"
    if re.search(r"/(magazine|news|stories|press-releases?)/", original_url) and not re.search(r"/202[56]-", original_url):
        return "old news or magazine page, not current student guidance"
    if "previous winners" in lower and "company name" in lower and "city" in lower:
        return "award/company listing, not student guidance"
    if "previous winners" in title:
        return "award archive, not student guidance"
    if title in {"facebook", "instagram", "linkedin", "youtube", "x", "tiktok"}:
        return "social media/navigation page"
    if title in {"authentication redirect", "search", "apply"} and len(lower) < 800:
        return "navigation/redirect page"
    return ""


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
    route = _routing_metadata_for(category, rows)
    content_lines = [
        f"# {category}",
        "",
        "## Fast Answer",
        "",
        summary,
        "",
        "## Who This Applies To",
        "",
        _comma_or_default(route["audiences"], "General institutional users."),
        "",
        "## Key Facts",
        "",
        *_key_fact_lines(rows),
        "",
        "## Steps Or Requirements",
        "",
        *_section_lines_for(rows, ("apply", "requirement", "step", "deadline", "enroll")),
        "",
        "## Dates, Costs, Or Eligibility",
        "",
        *_section_lines_for(rows, ("date", "deadline", "tuition", "fee", "cost", "eligib")),
        "",
        "## Contacts And Offices",
        "",
        *_section_lines_for(rows, ("contact", "office", "email", "phone")),
        "",
        "## Related Pages",
        "",
        "- [Audience routes](../routing/audience.md)",
        "- [Intent routes](../routing/intent.md)",
        "- [Topic routes](../routing/topics.md)",
        "- [Source notes](../source-notes/index.md)",
        "",
        "## Caveats And Review Notes",
        "",
        *_caveat_lines(rows),
        "",
        "## Last Verified",
        "",
        timestamp,
    ]
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
            "audiences": route["audiences"],
            "roles": route["roles"],
            "intents": route["intents"],
            "academic_interests": route["academic_interests"],
            "canonical_facts": route["canonical_facts"],
            "aliases": route["aliases"],
            "source_priority": route["source_priority"],
            "canonical_owner": route["canonical_owner"],
            "schools": route["schools"],
            "departments": route["departments"],
            "offices": route["offices"],
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
            "audiences": route["audiences"],
            "roles": route["roles"],
            "intents": route["intents"],
            "academic_interests": route["academic_interests"],
            "canonical_facts": route["canonical_facts"],
            "aliases": route["aliases"],
            "source_priority": route["source_priority"],
            "canonical_owner": route["canonical_owner"],
            "schools": route["schools"],
            "departments": route["departments"],
            "offices": route["offices"],
        },
    )


def _write_semantic_pages(
    wiki_root: Path,
    page_groups: dict[str, list[dict[str, Any]]],
    timestamp: str,
    site_root: Path,
) -> tuple[list[dict[str, Any]], int, int]:
    rows = [row for group_rows in page_groups.values() for row in group_rows]
    page_specs: list[dict[str, Any]] = []
    for school_slug, display_name in SCHOOL_DISPLAY_NAMES.items():
        school_rows = [row for row in rows if _school_relevance_score(row, school_slug) >= 3.0]
        if not school_rows:
            continue
        short_name = _school_short_name(display_name)
        base_path = f"wiki/pages/schools/{school_slug}"
        page_specs.extend(
            [
                {
                    "path": wiki_root / "pages" / "schools" / f"{school_slug}.md",
                    "school_slug": school_slug,
                    "school_display": display_name,
                    "title": display_name,
                    "topic": "overview",
                    "rows": school_rows,
                    "summary": f"Start here for {display_name} programs, admissions, curriculum, costs, and student support.",
                    "related": [f"{base_path}/graduate.md", f"{base_path}/admissions.md", f"{base_path}/courses.md", f"{base_path}/costs-and-aid.md"],
                },
                {
                    "path": wiki_root / "pages" / "schools" / school_slug / "graduate.md",
                    "school_slug": school_slug,
                    "school_display": display_name,
                    "title": f"{short_name} Graduate Student Guide",
                    "topic": "graduate",
                    "rows": _semantic_rows(school_rows, ("graduate", "mba", "master", "m.s.", "ms ", "admission", "tuition", "course"), school_slug=school_slug),
                    "summary": f"For prospective or new {display_name} graduate students, this page connects programs, courses, costs, admissions, and next steps.",
                    "related": [f"{base_path}/admissions.md", f"{base_path}/courses.md", f"{base_path}/costs-and-aid.md"],
                },
                {
                    "path": wiki_root / "pages" / "schools" / school_slug / "admissions.md",
                    "school_slug": school_slug,
                    "school_display": display_name,
                    "title": f"{short_name} Graduate Admissions",
                    "topic": "admissions",
                    "rows": _semantic_rows(school_rows, ("admission", "apply", "application", "deadline", "requirement", "gmat", "gre", "transcript"), school_slug=school_slug),
                    "summary": f"{display_name} admissions pages and catalog sources for application process, requirements, deadlines, and applicant next steps.",
                    "related": [f"{base_path}/graduate.md", f"{base_path}/costs-and-aid.md"],
                },
                {
                    "path": wiki_root / "pages" / "schools" / school_slug / "courses.md",
                    "school_slug": school_slug,
                    "school_display": display_name,
                    "title": f"{short_name} Courses And Curriculum",
                    "topic": "courses",
                    "rows": _semantic_rows(school_rows, ("course", "curriculum", "credit", "elective", "degree requirement", "class"), school_slug=school_slug),
                    "summary": f"{display_name} curriculum and course evidence, including degrees, certificates, and catalog details where available.",
                    "related": [f"{base_path}/graduate.md", f"{base_path}/admissions.md"],
                },
                {
                    "path": wiki_root / "pages" / "schools" / school_slug / "costs-and-aid.md",
                    "school_slug": school_slug,
                    "school_display": display_name,
                    "title": f"{short_name} Costs, Fees, And Aid",
                    "topic": "costs",
                    "rows": _semantic_rows(school_rows, ("tuition", "fee", "cost", "scholarship", "aid", "financial"), school_slug=school_slug),
                    "summary": f"{display_name} tuition, fee, scholarship, and aid evidence for applicants and students.",
                    "related": [f"{base_path}/graduate.md", f"{base_path}/admissions.md"],
                },
            ]
        )

    entries: list[dict[str, Any]] = []
    created = 0
    updated = 0
    for spec in page_specs:
        fallback_rows = [row for row in rows if _school_relevance_score(row, str(spec["school_slug"])) >= 3.0]
        spec_rows = list(spec["rows"] or fallback_rows)
        spec_rows = _dedupe_semantic_rows(spec_rows, school_slug=str(spec["school_slug"]))[:80]
        path = Path(spec["path"])
        existed = path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        page_text, entry = _render_semantic_page(
            title=str(spec["title"]),
            topic=str(spec["topic"]),
            summary=str(spec["summary"]),
            rows=spec_rows,
            related_pages=[str(value) for value in spec["related"]],
            timestamp=timestamp,
            site_root=site_root,
            page_path=path,
            school_slug=str(spec["school_slug"]),
            school_display=str(spec["school_display"]),
        )
        path.write_text(page_text, encoding="utf-8")
        entries.append(entry)
        if existed:
            updated += 1
        else:
            created += 1
    return entries, created, updated


def _school_short_name(display_name: str) -> str:
    return str(display_name).replace(" School of Business", "").replace(" School of Engineering", "").replace(" School of the Arts", "").replace(" School of Education", "").replace(" School of Theology", "").replace(" School of Law", "").strip()


def _school_relevance_score(row: dict[str, Any], school_slug: str, topic_needles: tuple[str, ...] = ()) -> float:
    title_path = f"{row.get('title', '')}\n{row.get('markdown_path', '')}".lower()
    text = _safe_semantic_text(str(row.get("_source_text") or "")).lower()
    score = 0.0
    title = str(row.get("title") or "").lower()
    school_terms = SCHOOL_ENTITY_PATTERNS.get(school_slug, ())
    slug_terms = tuple(part for part in school_slug.split("-") if len(part) > 2)
    for term in (*school_terms, school_slug.replace("-", " "), *slug_terms):
        term = str(term).lower()
        if not term:
            continue
        if term in title_path:
            score += 5.0
        elif term in text:
            score += 1.5
    if any(token in title for token in ("graduate", "admission", "program", "tuition", "course", "curriculum")):
        score += 1.0
    for needle in topic_needles:
        if needle in title_path:
            score += 3.0
        elif needle in text:
            score += 0.75
    low_value_title_terms = (
        "class-notes",
        "distinguished-alumni",
        "memories",
        "magazine",
        "commencement",
        "celebrates",
        "honors",
        "families",
    )
    if any(term in title_path for term in low_value_title_terms):
        score -= 3.0
    if re.match(r"^20\d\d-", title):
        score -= 5.0
    return score


def _semantic_rows(rows: list[dict[str, Any]], needles: tuple[str, ...], *, school_slug: str) -> list[dict[str, Any]]:
    scored = [(_school_relevance_score(row, school_slug, needles), row) for row in rows]
    selected = [row for score, row in sorted(scored, key=lambda item: (-item[0], str(item[1].get("title") or ""))) if score >= 3.0]
    return selected or rows


def _dedupe_semantic_rows(rows: list[dict[str, Any]], *, school_slug: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique = []
    for row in sorted(rows, key=lambda item: (-_school_relevance_score(item, school_slug), str(item.get("title") or ""))):
        source_id = str(row.get("source_id") or "")
        if source_id and source_id not in seen:
            seen.add(source_id)
            unique.append(row)
    return unique


def _render_semantic_page(
    *,
    title: str,
    topic: str,
    summary: str,
    rows: list[dict[str, Any]],
    related_pages: list[str],
    timestamp: str,
    site_root: Path,
    page_path: Path,
    school_slug: str,
    school_display: str,
) -> tuple[str, dict[str, Any]]:
    rel_page = _site_relative(page_path, site_root)
    source_ids = [str(row.get("source_id") or "") for row in rows if str(row.get("source_id") or "")]
    source_paths = [str(row.get("markdown_path") or "") for row in rows if str(row.get("markdown_path") or "")]
    school_short = _school_short_name(school_display)
    tags = [school_slug, "graduate", topic]
    entities = _infer_institution_entities(
        "\n".join(f"{row.get('title', '')}\n{row.get('_source_text', '')}" for row in rows)
    )
    answer_paths = _semantic_answer_paths(title, topic, related_pages, rows, school_display=school_display)
    evidence_links = _semantic_evidence_link_lines(rows, max_items=10)
    content_lines = [
        f"# {title}",
        "",
        "## Fast Answer",
        "",
        _semantic_summary_with_links(title, summary, school_display),
        "",
        *_semantic_overview_bullets(rows, school_display=school_display),
        "",
        "## If You Need",
        "",
        *answer_paths,
        "",
        "## Key Concepts",
        "",
        *[_semantic_wikilink_line(value) for value in _semantic_key_concepts(topic, school_display)],
        "",
        "## Who This Applies To",
        "",
        f"Prospective and new graduate students evaluating {school_display} programs, requirements, costs, and next steps.",
        "",
        "## Courses / Curriculum",
        "",
        *_semantic_evidence_lines(rows, ("course", "curriculum", "credit", "elective", "degree requirement", "class"), max_items=8, school_slug=school_slug),
        "",
        "## Costs / Fees / Aid",
        "",
        *_semantic_evidence_lines(rows, ("tuition", "fee", "cost", "scholarship", "aid", "financial"), max_items=8, school_slug=school_slug),
        "",
        "## Admissions / Requirements / Deadlines",
        "",
        *_semantic_evidence_lines(rows, ("admission", "apply", "application", "deadline", "requirement", "gmat", "gre", "transcript"), max_items=8, school_slug=school_slug),
        "",
        "## Contacts / Offices",
        "",
        *_semantic_evidence_lines(rows, ("contact", "admission", "office", "email", "phone"), max_items=6, school_slug=school_slug),
        "",
        "## Related Pages",
        "",
        *[f"- [[{_semantic_page_title_for_path(path)}]] — [{Path(path).stem.replace('-', ' ').title()}]({_semantic_relative_link(rel_page, path)})" for path in related_pages],
        "",
        "## Relationships",
        "",
        *_semantic_relationship_lines(title, topic, related_pages, evidence_links, school_display=school_display),
        "",
        "## Evidence / References",
        "",
        *evidence_links,
        "",
        "## Sources",
        "",
        *_semantic_source_lines(rows),
        "",
        "## Last Verified",
        "",
        timestamp,
    ]
    content = "\n".join(content_lines).rstrip() + "\n"
    metadata = {
        "title": title,
        "category": school_display,
        "page_type": "semantic",
        "page_path": rel_page,
        "page_checksum": checksum_text(content),
        "school": school_slug,
        "schools": sorted({school_slug, *entities["schools"]}),
        "departments": entities["departments"],
        "offices": entities["offices"],
        "programs": _semantic_programs(rows),
        "degree_levels": ["graduate"],
        "topics": tags,
        "summary": summary,
        "entities": sorted({school_display, *[value.replace('-', ' ').title() for value in entities["schools"]]}),
        "related": [_semantic_page_title_for_path(path) for path in related_pages],
        "confidence": "high" if len(source_ids) >= 2 else "medium",
        "created_at": timestamp,
        "source": source_paths[:10],
        "answer_paths": [line.lstrip("- ") for line in answer_paths],
        "source_ids": source_ids,
        "source_paths": source_paths,
        "source_count": len(source_ids),
        "tags": tags,
        "audiences": ["prospective-graduate-student", "new-graduate-student"],
        "roles": ["student", "applicant"],
        "intents": ["study", "apply", "pay"],
        "academic_interests": [_slugify(school_short)],
        "canonical_facts": ["courses", "costs", "admissions", "contacts"],
        "aliases": [f"{school_short.lower()} graduate", f"{school_short.lower()} admissions", f"{school_short.lower()} courses", f"{school_short.lower()} fees"],
        "related_pages": related_pages,
        "source_priority": "semantic-wiki",
        "canonical_owner": rel_page,
        "updated_at": timestamp,
    }
    return (
        f"{_frontmatter(metadata)}\n{content}",
        {
            "title": title,
            "category": school_display,
            "path": rel_page,
            "summary": summary,
            "source_count": len(source_ids),
            "source_ids": source_ids,
            "source_paths": source_paths,
            "tags": tags,
            "audiences": metadata["audiences"],
            "roles": metadata["roles"],
            "intents": metadata["intents"],
            "academic_interests": metadata["academic_interests"],
            "canonical_facts": metadata["canonical_facts"],
            "aliases": metadata["aliases"],
            "source_priority": "semantic-wiki",
            "canonical_owner": rel_page,
            "page_type": "semantic",
            "school": school_slug,
            "schools": metadata["schools"],
            "departments": metadata["departments"],
            "offices": metadata["offices"],
            "programs": metadata["programs"],
            "degree_levels": metadata["degree_levels"],
            "topics": tags,
            "related_pages": related_pages,
        },
    )


def _semantic_summary_with_links(title: str, summary: str, school_display: str) -> str:
    return f"{summary} Start from [[{school_display}]] and use the links below to reach answer pages or source evidence in one or two hops."


def _semantic_page_title_for_path(path: str) -> str:
    path_value = str(path or "")
    for school_slug, display_name in SCHOOL_DISPLAY_NAMES.items():
        short = _school_short_name(display_name)
        if path_value.endswith(f"schools/{school_slug}.md"):
            return display_name
        if path_value.endswith(f"schools/{school_slug}/graduate.md"):
            return f"{short} Graduate Student Guide"
        if path_value.endswith(f"schools/{school_slug}/admissions.md"):
            return f"{short} Graduate Admissions"
        if path_value.endswith(f"schools/{school_slug}/courses.md"):
            return f"{short} Courses And Curriculum"
        if path_value.endswith(f"schools/{school_slug}/costs-and-aid.md"):
            return f"{short} Costs, Fees, And Aid"
    return Path(path_value).stem.replace("-", " ").title()


def _semantic_key_concepts(topic: str, school_display: str) -> list[str]:
    short = _school_short_name(school_display)
    concepts = [school_display, f"{short} Graduate Student Guide"]
    if topic != "admissions":
        concepts.append(f"{short} Graduate Admissions")
    if topic != "courses":
        concepts.append(f"{short} Courses And Curriculum")
    if topic != "costs":
        concepts.append(f"{short} Costs, Fees, And Aid")
    concepts.extend(["Graduate Admissions", "Tuition And Fees", "Curriculum"])
    return list(dict.fromkeys(concepts))


def _semantic_wikilink_line(title: str) -> str:
    return f"- [[{title}]]"


def _semantic_answer_paths(title: str, topic: str, related_pages: list[str], rows: list[dict[str, Any]], *, school_display: str) -> list[str]:
    short = _school_short_name(school_display)
    page_titles = {_semantic_page_title_for_path(path) for path in related_pages}
    if topic == "graduate":
        page_titles.update({f"{short} Graduate Admissions", f"{short} Courses And Curriculum", f"{short} Costs, Fees, And Aid"})
    if topic == "admissions":
        page_titles.update({f"{short} Graduate Student Guide", f"{short} Costs, Fees, And Aid"})
    if topic == "courses":
        page_titles.update({f"{short} Graduate Student Guide", f"{short} Graduate Admissions"})
    if topic == "costs":
        page_titles.update({f"{short} Graduate Student Guide", f"{short} Graduate Admissions"})
    paths = []
    if f"{short} Graduate Admissions" in page_titles or topic == "admissions":
        paths.append(f"- Admissions process and requirements → [[{short} Graduate Admissions]]")
    if f"{short} Costs, Fees, And Aid" in page_titles or topic == "costs":
        paths.append(f"- Costs, fees, scholarships, or aid → [[{short} Costs, Fees, And Aid]]")
    if f"{short} Courses And Curriculum" in page_titles or topic == "courses":
        paths.append(f"- Courses, curriculum, or credits → [[{short} Courses And Curriculum]]")
    if title != school_display:
        paths.append(f"- School-level context → [[{school_display}]]")
    first_source_title = next((str(row.get("title") or "") for row in rows if row.get("title")), "source evidence")
    if first_source_title:
        paths.append(f"- Official evidence and raw details → [[Source: {first_source_title}]]")
    return list(dict.fromkeys(paths))[:7] or ["- Start with related pages below, then open source evidence when verification is needed."]


def _semantic_relationship_lines(title: str, topic: str, related_pages: list[str], evidence_links: list[str], *, school_display: str) -> list[str]:
    short = _school_short_name(school_display)
    lines = [f"- [[{title}]] part_of [[{school_display}]]"] if title != school_display else []
    for path in related_pages[:6]:
        lines.append(f"- [[{title}]] related_to [[{_semantic_page_title_for_path(path)}]]")
    if topic in {"admissions", "courses", "costs"}:
        lines.append(f"- [[{title}]] next_step [[{short} Graduate Student Guide]]")
    if evidence_links:
        match = re.search(r"\[\[([^\]]+)\]\]", evidence_links[0])
        if match:
            lines.append(f"- [[{title}]] cites [[{match.group(1)}]]")
    return lines or [f"- [[{title}]] related_to [[{short} Graduate Student Guide]]"]


def _semantic_evidence_link_lines(rows: list[dict[str, Any]], *, max_items: int) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for row in rows:
        title = str(row.get("title") or row.get("source_id") or "Source").strip()
        source_id = str(row.get("source_id") or "").strip()
        source_path = str(row.get("markdown_path") or "").strip()
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        lines.append(f"- [[Source: {title}]] — `{source_id}` — `{source_path}`")
        if len(lines) >= max_items:
            break
    return lines or ["- No source evidence attached."]


def _semantic_overview_bullets(rows: list[dict[str, Any]], *, school_display: str) -> list[str]:
    first = _first_source_id(rows)
    admissions = _first_source_for_needles(rows, ("admission", "apply", "application")) or first
    courses = _first_source_for_needles(rows, ("course", "curriculum", "credit")) or first
    costs = _first_source_for_needles(rows, ("tuition", "fee", "cost", "aid")) or first
    return [
        f"- Start with the {school_display} overview, then follow the shortest answer path for admissions, costs, curriculum, or source evidence. [`{first}`]",
        f"- Admissions evidence is routed to the school admissions page and source exits for official requirements or deadlines. [`{admissions}`]",
        f"- Curriculum evidence is routed to the courses/curriculum page when source text mentions courses, credits, or degree requirements. [`{courses}`]",
        f"- Cost evidence is routed to costs, fees, and aid pages when source text mentions tuition, fees, scholarships, or financial aid. [`{costs}`]",
    ]


def _first_source_for_needles(rows: list[dict[str, Any]], needles: tuple[str, ...]) -> str:
    for row in rows:
        haystack = f"{row.get('title', '')}\n{row.get('_source_text', '')}".lower()
        if any(needle in haystack for needle in needles):
            return str(row.get("source_id") or "")
    return ""


def _first_source_id(rows: list[dict[str, Any]]) -> str:
    return next((str(row.get("source_id") or "") for row in rows if str(row.get("source_id") or "")), "source")


def _semantic_evidence_lines(rows: list[dict[str, Any]], needles: tuple[str, ...], *, max_items: int, school_slug: str) -> list[str]:
    candidates: list[tuple[float, str, str]] = []
    for row in rows:
        source_id = str(row.get("source_id") or "")
        row_score = _school_relevance_score(row, school_slug, needles)
        title = str(row.get("title") or "")
        for sentence in _sentences(_safe_semantic_text(str(row.get("_source_text") or ""))):
            lower = sentence.lower()
            if not any(needle in lower for needle in needles):
                continue
            if _is_low_value_semantic_sentence(lower):
                continue
            keyword_hits = sum(1 for needle in needles if needle in lower)
            fact_bonus = 2.0 if re.search(r"\b\d+[\d,.$%–—-]*", sentence) else 0.0
            title_bonus = 2.0 if any(needle in title.lower() for needle in needles) else 0.0
            compact = _excerpt(sentence, max_chars=280)
            candidates.append((row_score + keyword_hits + fact_bonus + title_bonus, compact, source_id))
    lines: list[str] = []
    seen: set[str] = set()
    for _score, compact, source_id in sorted(candidates, key=lambda item: (-item[0], item[1].lower())):
        key = compact.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {compact} [`{source_id}`]")
        if len(lines) >= max_items:
            break
    return lines or ["- No source-backed details found yet; inspect related source pages and admissions/program pages."]


def _is_low_value_semantic_sentence(lower_sentence: str) -> bool:
    low_value = (
        "previous cards",
        "next cards",
        "popular searches",
        "follow us",
        "share - facebook",
        "up next",
        "search submit",
        "also in smu cox school of business",
        "coxtoday",
    )
    return any(term in lower_sentence for term in low_value)


def _safe_semantic_text(text: str) -> str:
    without_controls = "".join(ch if ch.isprintable() or ch.isspace() else " " for ch in text)
    without_replacement = without_controls.replace("�", " ")
    return re.sub(r"\s+", " ", without_replacement).strip()


def _semantic_source_lines(rows: list[dict[str, Any]]) -> list[str]:
    lines = []
    for row in rows[:40]:
        lines.append(f"- `{row.get('source_id')}` - {row.get('title') or 'Untitled source'} ({row.get('markdown_path')})")
    return lines or ["- No source rows attached."]


def _semantic_programs(rows: list[dict[str, Any]]) -> list[str]:
    haystack = "\n".join(f"{row.get('title', '')}\n{row.get('_source_text', '')}" for row in rows).lower()
    programs = []
    patterns = {
        "online-mba": ("online mba",),
        "mba": ("mba", "master of business administration"),
        "business-analytics": ("business analytics", "msba"),
        "finance": ("finance",),
        "accounting": ("accounting",),
        "management": ("management",),
    }
    for label, needles in patterns.items():
        if any(needle in haystack for needle in needles):
            programs.append(label)
    return programs or ["cox-graduate"]


def _semantic_relative_link(current_rel_page: str, target_rel_page: str) -> str:
    current_dir = Path(current_rel_page).parent
    try:
        return Path(target_rel_page).relative_to(current_dir).as_posix()
    except ValueError:
        return Path(target_rel_page).as_posix()


def _source_page_slug(row: dict[str, Any], used_slugs: set[str]) -> str:
    base = _slugify(str(row.get("title") or row.get("source_id") or "source"))
    source_id = _slugify(str(row.get("source_id") or ""))
    slug = f"{base}-{source_id}" if source_id and source_id not in base else base
    candidate = slug
    suffix = 2
    while candidate in used_slugs:
        candidate = f"{slug}-{suffix}"
        suffix += 1
    used_slugs.add(candidate)
    return candidate


def _render_source_page(
    category: str,
    row: dict[str, Any],
    timestamp: str,
    site_root: Path,
    page_path: Path,
    *,
    category_page_path: str,
) -> tuple[str, dict[str, Any]]:
    source_id = str(row.get("source_id") or "")
    source_path = str(row.get("markdown_path") or "")
    source_title = str(row.get("title") or "Untitled source")
    title = f"Source: {source_title}"
    text = str(row.get("_source_text") or "")
    rel_page = _site_relative(page_path, site_root)
    route = _routing_metadata_for(category, [row])
    tags = [_slugify(category), _slugify(str(row.get("source_kind") or "source"))]
    summary = _excerpt(text, max_chars=220) or f"Source-backed {category.lower()} page."
    content_lines = [
        f"# {title}",
        "",
        "## Fast Answer",
        "",
        summary,
        "",
        "## Category",
        "",
        f"- [[{category}]] — [{category}](../{Path(category_page_path).name})",
        "",
        "## Main Content",
        "",
        _clean_source_body_for_wiki(text),
        "",
        "## Key Facts",
        "",
        *_key_fact_lines([row]),
        "",
        "## Dates, Costs, Or Eligibility",
        "",
        *_section_lines_for([row], ("date", "deadline", "tuition", "fee", "cost", "eligib")),
        "",
        "## Contacts And Offices",
        "",
        *_section_lines_for([row], ("contact", "office", "email", "phone")),
        "",
        "## Caveats And Review Notes",
        "",
        *_caveat_lines([row]),
        "",
        "## Relationships",
        "",
        f"- [[{title}]] evidence_for [[{category}]]",
        "",
        "## Sources",
        "",
        f"- `{source_id}` - {source_path}",
        "",
        "## Last Verified",
        "",
        timestamp,
    ]
    content = "\n".join(content_lines).rstrip() + "\n"
    frontmatter = _frontmatter(
        {
            "title": title,
            "category": category,
            "page_type": "source",
            "page_path": rel_page,
            "page_checksum": checksum_text(content),
            "source_ids": [source_id],
            "source_paths": [source_path],
            "source_count": 1,
            "summary": summary,
            "entities": route["schools"] + route["departments"] + route["offices"],
            "related": [category],
            "confidence": "high",
            "created_at": timestamp,
            "source": [source_path],
            "tags": tags,
            "audiences": route["audiences"],
            "roles": route["roles"],
            "intents": route["intents"],
            "academic_interests": route["academic_interests"],
            "canonical_facts": route["canonical_facts"],
            "aliases": route["aliases"],
            "source_priority": route["source_priority"],
            "canonical_owner": rel_page,
            "category_page": category_page_path,
            "schools": route["schools"],
            "departments": route["departments"],
            "offices": route["offices"],
            "updated_at": timestamp,
        }
    )
    return (
        f"{frontmatter}\n{content}",
        {
            "title": title,
            "category": category,
            "path": rel_page,
            "summary": summary,
            "source_count": 1,
            "source_ids": [source_id],
            "source_paths": [source_path],
            "tags": tags,
            "audiences": route["audiences"],
            "roles": route["roles"],
            "intents": route["intents"],
            "academic_interests": route["academic_interests"],
            "canonical_facts": route["canonical_facts"],
            "aliases": route["aliases"],
            "source_priority": route["source_priority"],
            "canonical_owner": rel_page,
            "page_type": "source",
            "schools": route["schools"],
            "departments": route["departments"],
            "offices": route["offices"],
        },
    )


def _clean_source_body_for_wiki(text: str, *, max_chars: int = 12000) -> str:
    lines = []
    boilerplate_patterns = (
        "skip to", "main navigation", "secondary navigation", "footer", "cookie", "privacy policy",
        "share this", "follow us", "copyright", "all rights reserved",
    )
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            if lines and lines[-1]:
                lines.append("")
            continue
        lower = stripped.lower()
        if any(pattern in lower for pattern in boilerplate_patterns) and len(stripped) < 160:
            continue
        lines.append(stripped)
    cleaned = "\n".join(lines).strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rstrip() + "\n\n..."
    return cleaned or "No cleaned source content available."


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


def _routing_metadata_for(category: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    haystack = "\n".join([category, *(str(row.get("title") or "") + "\n" + str(row.get("_source_text") or "") for row in rows)]).lower()
    intents = _infer_values(
        haystack,
        {
            "apply": ("admission", "apply", "application", "deadline", "requirement"),
            "pay": ("tuition", "fee", "cost", "financial aid", "billing", "scholarship"),
            "study": ("program", "degree", "major", "minor", "course", "catalog"),
            "contact": ("contact", "office", "email", "phone", "address"),
            "research": ("research", "lab", "faculty", "publication"),
            "visit": ("visit", "tour", "campus"),
            "enroll": ("registrar", "enroll", "transcript", "academic calendar"),
        },
        default="explore",
    )
    audiences = _infer_values(
        haystack,
        {
            "applicant": ("admission", "apply", "application"),
            "current-student": ("registrar", "student services", "billing", "transcript"),
            "graduate": ("graduate", "master", "doctoral", "phd"),
            "undergraduate": ("undergraduate", "bachelor", "major", "minor"),
            "researcher": ("research", "lab", "faculty"),
            "parent": ("parent", "family"),
        },
        default="general",
    )
    roles = _infer_values(
        haystack,
        {
            "student": ("student", "admitted", "current"),
            "applicant": ("applicant", "admission", "apply"),
            "faculty-staff": ("faculty", "staff"),
            "visitor": ("visitor", "visit", "tour"),
        },
        default="general",
    )
    academic_interests = _infer_academic_interests(haystack)
    canonical_facts = _infer_values(
        haystack,
        {
            "requirements": ("requirement", "transcript", "application"),
            "contacts": ("contact", "email", "phone", "office"),
            "costs": ("tuition", "fee", "cost"),
            "leadership": ("dean", "chair", "director", "president"),
            "policies": ("policy", "eligibility", "procedure"),
            "research": ("research", "lab", "center"),
        },
        default=_slugify(category),
    )
    entities = _infer_institution_entities(haystack)
    return {
        "audiences": audiences,
        "roles": roles,
        "intents": intents,
        "academic_interests": academic_interests,
        "canonical_facts": canonical_facts,
        "aliases": sorted({_slugify(str(row.get("title") or "")) for row in rows if row.get("title")}),
        "source_priority": "curated-wiki",
        "canonical_owner": f"wiki/pages/{_slugify(category)}.md",
        "schools": entities["schools"],
        "departments": entities["departments"],
        "offices": entities["offices"],
    }


def _infer_institution_entities(haystack: str) -> dict[str, list[str]]:
    text = str(haystack or "").lower()
    return {
        "schools": _infer_entity_values(text, SCHOOL_ENTITY_PATTERNS),
        "departments": _infer_entity_values(text, DEPARTMENT_ENTITY_PATTERNS),
        "offices": _infer_entity_values(text, OFFICE_ENTITY_PATTERNS),
    }


def _infer_entity_values(haystack: str, patterns: dict[str, tuple[str, ...]]) -> list[str]:
    return sorted(label for label, needles in patterns.items() if any(needle in haystack for needle in needles))


def _infer_values(haystack: str, patterns: dict[str, tuple[str, ...]], *, default: str) -> list[str]:
    values = [label for label, needles in patterns.items() if any(needle in haystack for needle in needles)]
    return values or [default]


def _infer_academic_interests(haystack: str) -> list[str]:
    interests = []
    for value in ("business", "engineering", "science", "arts", "law", "education", "medicine", "data", "computer"):
        if value in haystack:
            interests.append(value)
    return interests or ["general"]


def _comma_or_default(values: list[str], default: str) -> str:
    return ", ".join(value.replace("-", " ") for value in values) if values else default


def _key_fact_lines(rows: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        excerpt = _excerpt(str(row.get("_source_text") or "")).replace("\n", " ")
        lines.append(f"- {row.get('title') or 'Untitled source'}: {excerpt}")
    return lines or ["- No source-backed facts generated yet."]


def _section_lines_for(rows: list[dict[str, Any]], needles: tuple[str, ...]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        for sentence in _sentences(str(row.get("_source_text") or "")):
            lower = sentence.lower()
            if any(needle in lower for needle in needles):
                lines.append(f"- {sentence}")
                break
    return lines or ["- No source-backed details found for this section."]


def _caveat_lines(rows: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        reason = _review_reason(row, str(row.get("_source_text") or ""))
        if reason:
            lines.append(f"- `{row.get('source_id')}`: {reason}")
    return lines or ["- No caveats detected in the current source set."]


def _sentences(text: str) -> list[str]:
    compact = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+", compact)
    return [part.strip("# ").strip() for part in parts if part.strip("# ").strip()]


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


def _write_routing_pages(wiki_root: Path, page_entries: list[dict[str, Any]], timestamp: str) -> None:
    routing_dir = wiki_root / "routing"
    routing_dir.mkdir(parents=True, exist_ok=True)
    _write_route_page(
        routing_dir / "audience.md",
        "Audience Routes",
        "audiences",
        page_entries,
        timestamp,
        "General and profile-specific entry points inferred from source metadata.",
    )
    _write_route_page(
        routing_dir / "intent.md",
        "Intent Routes",
        "intents",
        page_entries,
        timestamp,
        "Task routes such as explore, apply, enroll, pay, study, contact, research, transfer, and visit.",
    )
    _write_route_page(
        routing_dir / "topics.md",
        "Topic Routes",
        "tags",
        page_entries,
        timestamp,
        "Academic and administrative topic routes inferred from generated pages.",
    )


def _write_route_page(
    path: Path,
    title: str,
    metadata_key: str,
    page_entries: list[dict[str, Any]],
    timestamp: str,
    intro: str,
) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in page_entries:
        values = entry.get(metadata_key) or ["general"]
        for value in values:
            grouped[str(value or "general")].append(entry)
    lines = [f"# {title}", "", f"Updated: {timestamp}", "", intro, ""]
    if not grouped:
        lines.append("No routes generated yet.")
    for route in sorted(grouped):
        lines.extend(["", f"## {route.replace('-', ' ').title()}"])
        for entry in sorted(grouped[route], key=lambda item: str(item.get("title") or "")):
            page_ref = str(entry["path"]).removeprefix("wiki/")
            lines.append(f"- [{entry['title']}](../{page_ref}) - {entry['summary']}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_source_notes(
    wiki_root: Path,
    page_groups: dict[str, list[dict[str, Any]]],
    timestamp: str,
    site_root: Path,
) -> None:
    notes_dir = wiki_root / "source-notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    index_lines = ["# Source Notes", "", f"Updated: {timestamp}", ""]
    for category, rows in sorted(page_groups.items()):
        note_path = notes_dir / f"{_slugify(category)}.md"
        note_lines = [f"# {category} Source Notes", "", f"Updated: {timestamp}", ""]
        for row in rows:
            note_lines.extend(
                [
                    f"## {row.get('title') or 'Untitled source'}",
                    "",
                    f"- Source ID: `{row.get('source_id')}`",
                    f"- Source path: `{row.get('markdown_path')}`",
                    "",
                    _excerpt(str(row.get("_source_text") or "")),
                    "",
                ]
            )
        note_path.write_text("\n".join(note_lines).rstrip() + "\n", encoding="utf-8")
        index_lines.append(f"- [{category}]({_site_relative(note_path, site_root).removeprefix('wiki/source-notes/')}) - {len(rows)} source(s).")
    (notes_dir / "index.md").write_text("\n".join(index_lines).rstrip() + "\n", encoding="utf-8")


def _write_optional_canonical_indexes(wiki_root: Path, page_entries: list[dict[str, Any]], timestamp: str) -> None:
    folder_map = {
        "Admissions": "student-paths",
        "Programs": "programs",
        "Departments": "departments",
        "Finance": "costs",
        "Scholarships": "costs",
        "Registrar": "calendar",
        "Student Life": "offices",
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in page_entries:
        folder = folder_map.get(str(entry.get("category") or ""))
        if folder:
            grouped[folder].append(entry)
    for folder, entries in grouped.items():
        folder_dir = wiki_root / folder
        folder_dir.mkdir(parents=True, exist_ok=True)
        lines = [f"# {folder.replace('-', ' ').title()}", "", f"Updated: {timestamp}", ""]
        for entry in sorted(entries, key=lambda item: str(item.get("title") or "")):
            page_ref = str(entry["path"]).removeprefix("wiki/")
            lines.append(f"- [{entry['title']}](../{page_ref}) - canonical owner: `{entry.get('canonical_owner')}`")
        (folder_dir / "index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


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
    return parse_markdown_frontmatter(text)


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
    return timestamp_slug(value)


def _session_timestamp_slug(value: str) -> str:
    return session_timestamp_slug(value)


def _site_relative(path: Path, site_root: Path) -> str:
    return site_relative(path, site_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or lint the local LLM wiki without prompts.")
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
            tmux_session=args.tmux_session,
            no_input=args.no_input,
            resume=args.resume,
            rebuild=args.rebuild,
        )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
