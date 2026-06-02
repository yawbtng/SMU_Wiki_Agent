from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..core.models import DiscoveredURL
from ..core.storage import read_json
from .url_policy import classify_url_for_student_wiki

APPROVED_URLS_MARKER = "scrape-planner:approved-urls:v1"
URL_RE = re.compile(r"https?://[^\s)\]}>\"']+")


def parse_approved_urls_markdown(markdown: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in URL_RE.finditer(markdown or ""):
        url = match.group(0).rstrip(".,;")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def approved_urls_path(site_root: Path) -> Path:
    return Path(site_root) / "approved_urls.md"


def apply_policy_to_discovered_url(item: DiscoveredURL, *, title: str = "") -> DiscoveredURL:
    if item.excluded_reason == "operator_rejected_area":
        return DiscoveredURL(
            url=item.url,
            source_sitemap=item.source_sitemap,
            lastmod=item.lastmod,
            path_category=item.path_category,
            content_type_guess=item.content_type_guess,
            selected=False,
            excluded_reason=item.excluded_reason,
        )
    decision = classify_url_for_student_wiki(item.url, title=title, lastmod=item.lastmod)
    if decision.selected:
        return DiscoveredURL(
            url=item.url,
            source_sitemap=item.source_sitemap,
            lastmod=item.lastmod,
            path_category=item.path_category,
            content_type_guess=item.content_type_guess,
            selected=True,
            excluded_reason=None,
        )
    return DiscoveredURL(
        url=item.url,
        source_sitemap=item.source_sitemap,
        lastmod=item.lastmod,
        path_category=item.path_category,
        content_type_guess=item.content_type_guess,
        selected=False,
        excluded_reason=decision.reason,
    )


def discovered_url_from_row(row: dict[str, Any]) -> DiscoveredURL:
    return DiscoveredURL(
        url=str(row.get("url") or ""),
        source_sitemap=str(row.get("source_sitemap") or ""),
        lastmod=row.get("lastmod"),
        path_category=str(row.get("path_category") or "other"),
        content_type_guess=str(row.get("content_type_guess") or "html"),
        excluded_reason=row.get("excluded_reason"),
        selected=bool(row.get("selected", True)),
    )


def filter_urls_for_scrape(urls: list[DiscoveredURL]) -> list[DiscoveredURL]:
    selected: list[DiscoveredURL] = []
    for item in urls:
        if not item.url:
            continue
        if not item.selected or item.excluded_reason:
            continue
        decision = classify_url_for_student_wiki(item.url, lastmod=item.lastmod)
        if decision.selected:
            selected.append(item)
    return selected


def load_discovered_rows(site_root: Path) -> list[DiscoveredURL]:
    raw = read_json(Path(site_root) / "discovered_urls.json", [])
    if not isinstance(raw, list):
        return []
    rows: list[DiscoveredURL] = []
    for row in raw:
        if isinstance(row, dict):
            rows.append(discovered_url_from_row(row))
    return rows


def urls_for_site_scrape(site_root: Path, *, prefer_approved: bool = True) -> list[DiscoveredURL]:
    discovered = load_discovered_rows(site_root)
    discovered_by_url = {item.url: item for item in discovered if item.url}

    approved_path = approved_urls_path(site_root)
    approved_urls: list[str] = []
    if prefer_approved and approved_path.exists():
        approved_urls = parse_approved_urls_markdown(approved_path.read_text(encoding="utf-8"))

    if approved_urls:
        candidates: list[DiscoveredURL] = []
        for url in approved_urls:
            existing = discovered_by_url.get(url)
            if existing is not None:
                candidates.append(existing)
            else:
                parsed = urlparse(url)
                candidates.append(
                    DiscoveredURL(
                        url=url,
                        source_sitemap="approved_urls.md",
                        path_category="other",
                        selected=True,
                    )
                )
    else:
        candidates = [item for item in discovered if item.selected and not item.excluded_reason]

    http_candidates = [
        item
        for item in candidates
        if urlparse(item.url.strip()).scheme in {"http", "https"} and urlparse(item.url.strip()).netloc
    ]
    return filter_urls_for_scrape(http_candidates)
