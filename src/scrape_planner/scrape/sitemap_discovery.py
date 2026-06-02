from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urljoin, urlparse, urlunparse

import requests

from ..core.models import DiscoveredURL
from .scrape_url_selection import apply_policy_to_discovered_url

COMMON_SITEMAP_PATHS = (
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/wp-sitemap.xml",
    "/sitemap-index.xml",
)


@dataclass
class DiscoveryResult:
    site_url: str
    sitemap_sources: list[str]
    urls: list[DiscoveredURL]
    notes: list[str]


def normalize_site_url(url: str) -> str:
    raw = url.strip()
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc.lower()
    return f"{scheme}://{netloc}"


def normalize_seed_url(url: str) -> str:
    raw = url.strip()
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") if parsed.path not in ("", "/") else parsed.path
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def category_from_path(path: str) -> str:
    path_lower = path.lower()
    if any(part in path_lower for part in ("blog", "news", "article")):
        return "content"
    if any(part in path_lower for part in ("docs", "guide", "kb")):
        return "docs"
    if any(part in path_lower for part in ("product", "pricing", "features")):
        return "product"
    if any(part in path_lower for part in ("about", "team", "careers")):
        return "company"
    return "other"


def _registered_domain(host: str) -> str:
    parts = [part for part in (host or "").lower().split(".") if part]
    if len(parts) <= 2:
        return ".".join(parts)
    second_level_suffixes = {"co", "ac", "edu", "gov", "org", "net", "com"}
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in second_level_suffixes:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _same_domain(candidate: str, root_host: str) -> bool:
    candidate_host = urlparse(candidate).netloc.lower()
    root_host = root_host.lower()
    return candidate_host == root_host or _registered_domain(candidate_host) == _registered_domain(root_host)


def _extract_sitemap_from_robots(site_url: str, timeout: int = 15) -> tuple[list[str], str | None]:
    robots_url = urljoin(site_url, "/robots.txt")
    try:
        resp = requests.get(robots_url, timeout=timeout)
        if resp.status_code >= 400:
            return [], f"robots.txt returned HTTP {resp.status_code}"
    except Exception as exc:
        return [], f"robots.txt request failed: {exc}"

    urls = []
    for line in resp.text.splitlines():
        if line.lower().startswith("sitemap:"):
            part = line.split(":", 1)[1].strip()
            if part:
                urls.append(part)
    return urls, None


def _parse_sitemap_xml(xml_text: str) -> tuple[list[tuple[str, str | None]], list[str]]:
    namespaces = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.fromstring(xml_text)
    tag = re.sub(r"^\{.*\}", "", root.tag)
    if tag == "sitemapindex":
        children = []
        for node in root.findall("sm:sitemap", namespaces) + root.findall("sitemap"):
            loc = node.findtext("sm:loc", default="", namespaces=namespaces) or node.findtext("loc", default="")
            if loc:
                children.append(loc.strip())
        return [], children
    if tag == "urlset":
        urls = []
        for node in root.findall("sm:url", namespaces) + root.findall("url"):
            loc = node.findtext("sm:loc", default="", namespaces=namespaces) or node.findtext("loc", default="")
            lastmod = node.findtext("sm:lastmod", default=None, namespaces=namespaces) or node.findtext(
                "lastmod", default=None
            )
            if loc:
                urls.append((loc.strip(), lastmod))
        return urls, []
    return [], []


def discover_site_urls(site_url: str, timeout: int = 15) -> DiscoveryResult:
    normalized = normalize_site_url(site_url)
    seed_url = normalize_seed_url(site_url)
    root_host = urlparse(normalized).netloc
    notes: list[str] = []
    sitemap_seeds, robots_error = _extract_sitemap_from_robots(normalized, timeout=timeout)
    if robots_error:
        notes.append(robots_error)

    if not sitemap_seeds:
        sitemap_seeds = [urljoin(normalized, path) for path in COMMON_SITEMAP_PATHS]
        notes.append("No sitemap entries in robots.txt, tried common sitemap paths.")

    discovered_map: dict[str, DiscoveredURL] = {}
    visited_sitemaps: set[str] = set()
    queue = deque(sitemap_seeds)

    while queue:
        sitemap_url = queue.popleft()
        if sitemap_url in visited_sitemaps:
            continue
        visited_sitemaps.add(sitemap_url)
        try:
            resp = requests.get(sitemap_url, timeout=timeout)
            if resp.status_code >= 400:
                notes.append(f"Sitemap {sitemap_url} returned HTTP {resp.status_code}")
                continue
            urls, children = _parse_sitemap_xml(resp.text)
            for child in children:
                queue.append(child)
            for loc, lastmod in urls:
                if not _same_domain(loc, root_host):
                    continue
                parsed = urlparse(loc)
                if loc in discovered_map:
                    continue
                discovered_map[loc] = apply_policy_to_discovered_url(
                    DiscoveredURL(
                        url=loc,
                        source_sitemap=sitemap_url,
                        lastmod=lastmod,
                        path_category=category_from_path(parsed.path),
                        content_type_guess="html",
                        selected=True,
                    )
                )
        except ET.ParseError:
            notes.append(f"Sitemap {sitemap_url} was not valid XML.")
        except Exception as exc:
            notes.append(f"Sitemap {sitemap_url} failed: {exc}")

    seed_parsed = urlparse(seed_url)
    if (seed_parsed.path not in ("", "/") or seed_parsed.query) and _same_domain(seed_url, root_host):
        discovered_map.setdefault(
            seed_url,
            apply_policy_to_discovered_url(
                DiscoveredURL(
                    url=seed_url,
                    source_sitemap="seed",
                    path_category=category_from_path(seed_parsed.path),
                    content_type_guess="html",
                    selected=True,
                )
            ),
        )

    return DiscoveryResult(
        site_url=normalized,
        sitemap_sources=sorted(visited_sitemaps),
        urls=sorted(discovered_map.values(), key=lambda item: item.url),
        notes=notes,
    )


def apply_manual_urls(site_url: str, urls: Iterable[str]) -> list[DiscoveredURL]:
    normalized = normalize_site_url(site_url)
    host = urlparse(normalized).netloc
    items: list[DiscoveredURL] = []
    for raw in urls:
        candidate = raw.strip()
        if not candidate:
            continue
        if not candidate.startswith(("http://", "https://")):
            candidate = urljoin(normalized, candidate)
        parsed = urlparse(candidate)
        if not _same_domain(candidate, host):
            items.append(
                DiscoveredURL(
                    url=candidate,
                    source_sitemap="manual",
                    selected=False,
                    excluded_reason="off_domain",
                    path_category=category_from_path(parsed.path),
                )
            )
            continue
        items.append(
            apply_policy_to_discovered_url(
                DiscoveredURL(
                    url=candidate,
                    source_sitemap="manual",
                    selected=True,
                    path_category=category_from_path(parsed.path),
                )
            )
        )
    deduped: dict[str, DiscoveredURL] = {}
    for item in items:
        deduped[item.url] = item
    return sorted(deduped.values(), key=lambda item: item.url)
