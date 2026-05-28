from __future__ import annotations

import posixpath
import re
from pathlib import Path
from urllib.parse import unquote, urlencode, urlparse

from .wiki_common import parse_markdown_frontmatter, strip_markdown_frontmatter


def document_index_label(value: object) -> str:
    label = unquote(str(value or "").strip())
    label = re.sub(r"\s+", " ", label).strip(" /\t\n\r")
    if not label:
        return ""
    label = re.sub(r"\.(?:aspx?|html?|md)$", "", label, flags=re.IGNORECASE)
    label = re.sub(r"[-_]+", " ", label)
    label = re.sub(r"\s+", " ", label).strip()
    if label and label == label.lower():
        label = label.title()
    return label


def list_wiki_markdown_files(wiki_dir: Path) -> list[str]:
    if not wiki_dir.exists():
        return []
    paths: list[str] = []
    for path in sorted(wiki_dir.rglob("*.md")):
        try:
            rel = path.relative_to(wiki_dir)
        except ValueError:
            continue
        if rel.parts and rel.parts[0] == "reports":
            continue
        paths.append(str(rel))
    return paths


def wiki_markdown_title(rel_path: str) -> str:
    path = Path(rel_path)
    stem = path.stem
    if stem.lower() == "index":
        if len(path.parts) <= 1:
            return "Overview"
        return document_index_label(path.parts[-2]) or path.parts[-2]
    return document_index_label(stem) or stem or rel_path


def wiki_markdown_category(rel_path: str) -> str:
    path = Path(rel_path)
    if len(path.parts) <= 1:
        return "Overview"
    return document_index_label(path.parts[0]) or path.parts[0]


def wiki_markdown_records(wiki_markdown_files: list[str]) -> list[dict]:
    records = [
        {
            "path": rel_path,
            "title": wiki_markdown_title(rel_path),
            "category": wiki_markdown_category(rel_path),
            "search_text": " ".join(
                [
                    rel_path,
                    wiki_markdown_title(rel_path),
                    wiki_markdown_category(rel_path),
                    " ".join(document_index_label(part) for part in Path(rel_path).parts),
                ]
            ).lower(),
        }
        for rel_path in wiki_markdown_files
    ]
    return sorted(
        records,
        key=lambda row: (
            str(row["category"]).lower() != "overview",
            str(row["category"]).lower(),
            str(row["title"]).lower(),
            str(row["path"]).lower(),
        ),
    )


def filter_wiki_markdown_records(records: list[dict], query: str) -> list[dict]:
    tokens = [token.lower() for token in re.split(r"\s+", query.strip()) if token.strip()]
    if not tokens:
        return records
    filtered: list[dict] = []
    for record in records:
        haystack = str(record.get("search_text") or "").lower()
        if all(token in haystack for token in tokens):
            filtered.append(record)
    return filtered


def read_wiki_markdown(layout, rel_path: str, *, max_chars: int = 60000) -> tuple[str, str]:
    if not rel_path:
        return "", "No wiki Markdown file selected."
    candidate = layout.wiki_dir / rel_path
    try:
        resolved = candidate.resolve()
        resolved.relative_to(layout.wiki_dir.resolve())
    except ValueError:
        return "", "Wiki Markdown path is outside this workspace."
    if not resolved.exists() or not resolved.is_file():
        return "", "Wiki Markdown file was not found."
    return resolved.read_text(encoding="utf-8", errors="replace")[:max_chars], ""


def safe_wiki_markdown_rel_path(value: object) -> str:
    raw = unquote(str(value or "").strip()).lstrip("/")
    raw = raw.split("#", 1)[0].split("?", 1)[0]
    if not raw:
        return ""
    normalized = posixpath.normpath(raw).lstrip("/")
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        return ""
    if not normalized.lower().endswith(".md"):
        return ""
    return normalized


def wiki_markdown_href(rel_path: str, *, site_id: str = "", fragment: str = "") -> str:
    params = {"view": "wiki_file", "wiki_file": rel_path}
    if site_id:
        params["site_id"] = site_id
    href = "?" + urlencode(params)
    if fragment:
        href += f"#{fragment}"
    return href


def resolve_wiki_markdown_link(current_rel_path: str, href: str) -> tuple[str, str]:
    parsed = urlparse(str(href or "").strip())
    if parsed.scheme or parsed.netloc or not parsed.path:
        return "", ""
    if not parsed.path.lower().endswith(".md"):
        return "", ""
    decoded_path = unquote(parsed.path)
    if decoded_path.startswith("/"):
        candidate = decoded_path.lstrip("/")
    else:
        candidate = posixpath.join(posixpath.dirname(current_rel_path), decoded_path)
    normalized = safe_wiki_markdown_rel_path(candidate)
    if not normalized:
        return "", ""
    return normalized, parsed.fragment


def strip_temp_clipboard_images(markdown_text: str) -> str:
    temp_clipboard_image = r"(?:file://)?/var/folders/[^\s)\"']*/T/pi-clipboard-[A-Za-z0-9-]+\.png"
    without_markdown_images = re.sub(
        rf"!?\[[^\]]*\]\(\s*{temp_clipboard_image}(?:\s+\"[^\"]*\")?\s*\)",
        "",
        markdown_text,
    )
    without_html_images = re.sub(
        rf"<img\b[^>]*\bsrc=[\"']{temp_clipboard_image}[\"'][^>]*>",
        "",
        without_markdown_images,
        flags=re.IGNORECASE,
    )
    return re.sub(temp_clipboard_image, "", without_html_images)


def rewrite_wiki_markdown_links(markdown_text: str, *, current_rel_path: str, site_id: str = "") -> str:
    def rewrite_markdown_link(match: re.Match[str]) -> str:
        label = match.group(1)
        href = match.group(2)
        target, fragment = resolve_wiki_markdown_link(current_rel_path, href)
        if not target:
            return match.group(0)
        return f"[{label}]({wiki_markdown_href(target, site_id=site_id, fragment=fragment)})"

    def rewrite_html_href(match: re.Match[str]) -> str:
        quote = match.group(1)
        href = match.group(2)
        target, fragment = resolve_wiki_markdown_link(current_rel_path, href)
        if not target:
            return match.group(0)
        return f"href={quote}{wiki_markdown_href(target, site_id=site_id, fragment=fragment)}{quote}"

    rewritten = re.sub(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", rewrite_markdown_link, markdown_text)
    return re.sub(r"href=([\"'])([^\"']+\.md(?:#[^\"']*)?)\1", rewrite_html_href, rewritten)

