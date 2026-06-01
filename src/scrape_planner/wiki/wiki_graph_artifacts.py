from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..core.storage import write_json
from ..core.wiki_common import parse_markdown_frontmatter, site_relative, strip_markdown_frontmatter

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]")
RELATIONSHIP_TYPES = {
    "explains",
    "depends_on",
    "related_to",
    "contradicts",
    "implements",
    "example_of",
    "part_of",
    "caused_by",
    "solves",
    "combines",
    "cites",
    "evidence_for",
    "next_step",
    "links_to",
}


def page_id_for_title(value: object) -> str:
    page_id = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return page_id or "untitled"


def parse_wikilinks(markdown_text: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in WIKILINK_RE.finditer(markdown_text):
        target = match.group(1).strip()
        alias = (match.group(2) or target).strip()
        key = (target, alias)
        if target and key not in seen:
            seen.add(key)
            links.append({"target": target, "alias": alias})
    return links


def parse_relationship_edges(markdown_text: str, *, default_from: str) -> list[dict[str, str]]:
    body = strip_markdown_frontmatter(markdown_text)
    relationships = _section_lines(body, "Relationships")
    edges: list[dict[str, str]] = []
    for line in relationships:
        links = parse_wikilinks(line)
        if not links:
            continue
        relation_type = _relationship_type_for_line(line)
        if len(links) >= 2:
            source = links[0]["target"]
            for link in links[1:]:
                edges.append({"from": source, "to": link["target"], "type": relation_type, "source": "relationship_section"})
        else:
            edges.append({"from": default_from, "to": links[0]["target"], "type": relation_type, "source": "relationship_section"})
    return edges


def write_wiki_graph_artifacts(wiki_root: Path, site_root: Path, *, updated_at: str) -> dict[str, Any]:
    pages = _read_page_records(wiki_root, site_root)
    title_to_id = {record["title"]: record["page_id"] for record in pages}
    path_to_id = {record["path"]: record["page_id"] for record in pages}
    edges: list[dict[str, Any]] = []

    for record in pages:
        page_id = record["page_id"]
        for related in record.get("related", []):
            edges.append(_edge(page_id, _resolve_target_id(related, title_to_id, path_to_id), "related_to", "frontmatter", "medium"))
        for source_path in record.get("source_paths", []):
            if source_path:
                edges.append(_edge(page_id, str(source_path), "cites", "frontmatter", "high"))
        for link in record.get("links", []):
            edges.append(_edge(page_id, _resolve_target_id(link["target"], title_to_id, path_to_id), "links_to", "wikilink", "medium"))
        for parsed_edge in record.get("relationship_edges", []):
            edges.append(
                _edge(
                    _resolve_target_id(parsed_edge["from"], title_to_id, path_to_id),
                    _resolve_target_id(parsed_edge["to"], title_to_id, path_to_id),
                    parsed_edge["type"],
                    parsed_edge.get("source", "relationship_section"),
                    "high",
                )
            )

    deduped_edges = _dedupe_edges(edges)
    backlinks: dict[str, list[dict[str, str]]] = {}
    for edge in deduped_edges:
        target = str(edge["to"])
        backlinks.setdefault(target, []).append({"from": str(edge["from"]), "type": str(edge["type"]), "source": str(edge["source"])})

    manifest = {
        "version": "ai-native-wiki-graph-v1",
        "updated_at": updated_at,
        "page_count": len(pages),
        "edge_count": len(deduped_edges),
        "pages": [
            {key: record[key] for key in ("page_id", "path", "title", "summary", "page_type", "tags", "entities", "related", "source_ids", "source_paths", "confidence", "priority", "updated_at") if key in record}
            for record in pages
        ],
    }

    write_json(wiki_root / "navigation_manifest.json", manifest)
    write_json(wiki_root / "backlinks.json", backlinks)
    _write_jsonl(wiki_root / "graph_edges.jsonl", deduped_edges)
    _write_sitemap(wiki_root / "sitemap.md", pages, updated_at=updated_at)
    return {
        "navigation_manifest_path": str(wiki_root / "navigation_manifest.json"),
        "backlinks_path": str(wiki_root / "backlinks.json"),
        "graph_edges_path": str(wiki_root / "graph_edges.jsonl"),
        "sitemap_path": str(wiki_root / "sitemap.md"),
        "navigation_page_count": len(pages),
        "navigation_edge_count": len(deduped_edges),
    }


def _read_page_records(wiki_root: Path, site_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((wiki_root / "pages").rglob("*.md")) if (wiki_root / "pages").exists() else []:
        text = path.read_text(encoding="utf-8", errors="replace")
        metadata = parse_markdown_frontmatter(text)
        title = str(metadata.get("title") or _title_from_body(text) or path.stem.replace("-", " ").title())
        rel_path = site_relative(path, site_root)
        page_type = str(metadata.get("page_type") or "source")
        summary = str(metadata.get("summary") or _summary_from_body(text))
        links = parse_wikilinks(text)
        records.append(
            {
                "page_id": page_id_for_title(title),
                "path": rel_path,
                "title": title,
                "summary": summary,
                "page_type": page_type,
                "tags": _as_list(metadata.get("tags")),
                "entities": _as_list(metadata.get("entities")) or _as_list(metadata.get("schools")) + _as_list(metadata.get("departments")) + _as_list(metadata.get("offices")),
                "related": _as_list(metadata.get("related")) or _as_list(metadata.get("related_pages")),
                "source_ids": _as_list(metadata.get("source_ids")),
                "source_paths": _as_list(metadata.get("source_paths")) or _as_list(metadata.get("source")),
                "confidence": str(metadata.get("confidence") or "medium"),
                "priority": _priority_for(page_type, rel_path),
                "updated_at": str(metadata.get("updated_at") or ""),
                "links": links,
                "relationship_edges": parse_relationship_edges(text, default_from=title),
            }
        )
    return records


def _edge(source: str, target: str, edge_type: str, source_kind: str, confidence: str) -> dict[str, Any]:
    return {"from": source, "to": target, "type": edge_type if edge_type in RELATIONSHIP_TYPES else "related_to", "confidence": confidence, "source": source_kind}


def _dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    rank = {"low": 0, "medium": 1, "high": 2}
    for edge in edges:
        if not edge.get("from") or not edge.get("to") or edge.get("from") == edge.get("to"):
            continue
        key = (str(edge["from"]), str(edge["to"]), str(edge["type"]))
        existing = by_key.get(key)
        if existing is None or rank.get(str(edge.get("confidence")), 0) > rank.get(str(existing.get("confidence")), 0):
            by_key[key] = edge
    return sorted(by_key.values(), key=lambda item: (str(item["from"]), str(item["type"]), str(item["to"])))


def _resolve_target_id(value: str, title_to_id: dict[str, str], path_to_id: dict[str, str]) -> str:
    return title_to_id.get(value) or path_to_id.get(value) or page_id_for_title(value)


def _relationship_type_for_line(line: str) -> str:
    for token in RELATIONSHIP_TYPES:
        if re.search(rf"\b{re.escape(token)}\b", line):
            return token
    return "related_to"


def _section_lines(body: str, heading: str) -> list[str]:
    lines = body.splitlines()
    in_section = False
    section_lines: list[str] = []
    for line in lines:
        if re.match(r"^##\s+", line):
            current = line.lstrip("#").strip().lower()
            in_section = current == heading.lower()
            continue
        if in_section and line.strip().startswith("-"):
            section_lines.append(line.strip())
    return section_lines


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if value in (None, ""):
        return []
    return [str(value)]


def _title_from_body(text: str) -> str:
    for line in strip_markdown_frontmatter(text).splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _summary_from_body(text: str) -> str:
    body = strip_markdown_frontmatter(text)
    for paragraph in re.split(r"\n\s*\n", body):
        cleaned = re.sub(r"\s+", " ", paragraph.replace("#", "")).strip()
        if cleaned:
            return cleaned[:240]
    return ""


def _priority_for(page_type: str, rel_path: str) -> int:
    if page_type in {"semantic", "navigation", "concept", "entity", "workflow", "process"}:
        return 90
    if rel_path.count("/") <= 2:
        return 70
    return 30


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=True) + "\n" for row in rows), encoding="utf-8")


def _write_sitemap(path: Path, pages: list[dict[str, Any]], *, updated_at: str) -> None:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for page in pages:
        grouped.setdefault(str(page.get("page_type") or "source"), []).append(page)
    lines = ["# Wiki Sitemap", "", f"Last updated: `{updated_at}`", "", "Agent entry points for semantic pages, navigation pages, source pages, and evidence fallbacks.", ""]
    for page_type, rows in sorted(grouped.items()):
        lines.extend([f"## {page_type.replace('-', ' ').title()}", ""])
        for row in sorted(rows, key=lambda item: (-int(item.get("priority") or 0), str(item.get("title") or "")))[:250]:
            title = str(row.get("title") or row.get("page_id"))
            rel = _relative_from_wiki_root(str(row.get("path") or ""))
            summary = str(row.get("summary") or "").strip()
            lines.append(f"- [[{title}]] — [{row.get('path')}]({rel})" + (f" — {summary}" if summary else ""))
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _relative_from_wiki_root(site_relative_path: str) -> str:
    prefix = "wiki/"
    return site_relative_path[len(prefix) :] if site_relative_path.startswith(prefix) else site_relative_path
