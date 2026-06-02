from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..core.site_layout import ensure_layout_for_site_root
from ..core.storage import write_json
from ..core.wiki_common import INTEGRATED_STATES, parse_markdown_frontmatter, site_relative, timestamp_slug
from ..sources.source_registry import checksum_file, read_registry_rows, utc_now_iso


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
        rel_page = site_relative(page_path, layout.site_root)
        text = page_path.read_text(encoding="utf-8", errors="replace")
        metadata = parse_markdown_frontmatter(text)
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
    represented = {item["source_id"] for item in review_items if item.get("source_id")}
    for page_path in _iter_wiki_page_paths(wiki_root):
        for item in _page_contradiction_items(page_path, layout.site_root, represented):
            review_items.append(item)
            if item.get("source_id"):
                represented.add(item["source_id"])
    destination = Path(report_path) if report_path else reports_dir / f"wiki-lint-{timestamp_slug(timestamp)}.json"
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
        "review_queue_count": len(review_items),
        "review_items": review_items,
        "missing_index_entries": missing_index_entries,
    }
    _append_log_line(
        wiki_root / "log.md",
        f"| {timestamp} | lint | orphan_pages={len(orphan_pages)} missing_citations={len(missing_citations)} "
        f"stale_sources={len(stale_source_checksums)} review_items={len(review_items)} "
        f"missing_index_entries={len(missing_index_entries)} report={destination} |",
    )
    write_json(destination, report)
    return report


def _iter_wiki_page_paths(wiki_root: Path) -> list[Path]:
    pages_root = wiki_root / "pages"
    return sorted(path for path in pages_root.rglob("*.md") if path.is_file()) if pages_root.exists() else []


def _append_log_line(path: Path, line: str) -> None:
    if not path.exists():
        path.write_text("# Wiki Log\n\n| Timestamp | Event | Details |\n| --- | --- | --- |\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line.rstrip() + "\n")


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


def _parse_review_queue_items(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    heading = ""
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            continue
        if not stripped.startswith("- [ ]"):
            continue
        source_id, reason = _review_source_and_reason(stripped)
        items.append(
            {
                "source_id": source_id,
                "reason": reason,
                "line": line_number,
                "type": "contradiction" if "contradiction" in reason.lower() or "conflict" in reason.lower() else "review",
                "heading": heading,
                "text": stripped,
            }
        )
    return items


def _review_source_and_reason(line: str) -> tuple[str, str]:
    body = re.sub(r"^- \[ \]\s*", "", line).strip()
    source_id = ""
    if match := re.search(r"`([^`]+)`", body):
        source_id = match.group(1).strip()
    reason = ""
    if match := re.search(r"\breason\s*=\s*(.+)$", body):
        reason = match.group(1).strip()
    elif ":" in body:
        reason = body.rsplit(":", 1)[1].strip()
    else:
        reason = body
    return source_id, reason


def _page_contradiction_items(page_path: Path, site_root: Path, represented_source_ids: set[str]) -> list[dict[str, Any]]:
    text = page_path.read_text(encoding="utf-8", errors="replace")
    metadata = parse_markdown_frontmatter(text)
    source_ids = _source_ids_from_metadata(metadata, text)
    source_id = next((candidate for candidate in source_ids if candidate not in represented_source_ids), source_ids[0] if source_ids else "")
    if not source_id or source_id in represented_source_ids:
        return []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if "contradiction" in line.lower():
            return [
                {
                    "source_id": source_id,
                    "reason": line.strip(),
                    "line": line_number,
                    "type": "contradiction",
                    "path": site_relative(page_path, site_root),
                    "text": line.strip(),
                }
            ]
    return []
