from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from .content_extract import extract_content
from .llm_wiki_builder import build_wiki
from .llm_wiki_index import build_llm_wiki_index
from .raw_source_normalizer import normalize_scraped_markdown
from .site_layout import ensure_layout_for_site_root
from .sitemap_discovery import apply_manual_urls
from .storage import ensure_run_dirs, write_json


FetchUrl = Callable[[str], Any]


def run_manual_url_pipeline(
    *,
    site_root: Path,
    site_url: str,
    url: str,
    fetcher: FetchUrl | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = now or datetime.now(timezone.utc).isoformat()
    layout = ensure_layout_for_site_root(Path(site_root))
    normalized_url = str(url or "").strip()
    accepted = apply_manual_urls(site_url, [normalized_url]) if site_url else []
    if not accepted or accepted[0].excluded_reason:
        return {
            "status": "rejected",
            "reason": str(accepted[0].excluded_reason if accepted else "invalid_url") or "invalid_url",
            "url": normalized_url,
        }

    run_id = f"manual-{_safe_timestamp(timestamp)}-{_slug_from_url(normalized_url)}"
    run_root = layout.site_root / run_id
    dirs = ensure_run_dirs(run_root)
    write_json(run_root / "selected_urls.json", [accepted[0].to_dict()])

    response = (fetcher or _default_fetch)(normalized_url)
    http_status, content_type, html = _response_parts(response)
    _raw_title, markdown, text_length, link_density = extract_content(html)

    slug = _slug_from_url(normalized_url)
    raw_html_path = dirs["raw_html"] / f"{slug}.html"
    markdown_path = dirs["markdown"] / f"{slug}.md"
    metadata_path = dirs["metadata"] / f"{slug}.json"
    raw_html_path.write_text(html, encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")
    write_json(
        metadata_path,
        {
            "url": normalized_url,
            "http_status": http_status,
            "content_type": content_type,
            "text_length": text_length,
            "link_density": link_density,
            "fetch_mode": "manual-url-pipeline",
            "worker_id": "manual-url-pipeline",
            "attempt": 1,
        },
    )
    page_row = {
        "url": normalized_url,
        "status": "success",
        "fetch_mode": "manual-url-pipeline",
        "worker_id": "manual-url-pipeline",
        "attempt": 1,
        "http_status": http_status,
        "failure_reason": None,
        "text_length": text_length,
        "link_density": link_density,
        "raw_html_path": str(raw_html_path),
        "markdown_path": str(markdown_path),
        "metadata_path": str(metadata_path),
        "started_at": timestamp,
        "finished_at": timestamp,
    }
    write_json(run_root / "scrape_manifest.json", [page_row])
    write_json(run_root / "failures.json", [])
    write_json(
        run_root / "run_status.json",
        {
            "state": "completed",
            "total": 1,
            "queued": 0,
            "running": 0,
            "success": 1,
            "failed": 0,
            "cancelled": 0,
            "current_url": None,
            "concurrency": 1,
            "started_at": timestamp,
            "finished_at": timestamp,
        },
    )

    raw_report = normalize_scraped_markdown(layout.site_root, run_root, now=timestamp)
    wiki_report = build_wiki(layout.site_root, no_input=True, resume=True, now=timestamp)
    index_report = build_llm_wiki_index(layout.site_root, now=timestamp)
    return {
        "status": "complete",
        "url": normalized_url,
        "run_id": run_id,
        "run_root": str(run_root.relative_to(layout.site_root)),
        "raw_report": _report_dict(raw_report),
        "wiki_report": wiki_report,
        "index_report": index_report,
    }


def _default_fetch(url: str) -> Any:
    response = requests.get(url, timeout=(5, 15), stream=True)
    response.raise_for_status()
    return response


def _response_parts(response: Any) -> tuple[int | None, str, str]:
    status = getattr(response, "status_code", None)
    headers = getattr(response, "headers", {}) or {}
    content_type = str(headers.get("content-type") or headers.get("Content-Type") or "") if isinstance(headers, dict) else ""
    text = getattr(response, "text", None)
    if isinstance(text, str) and text:
        return status, content_type, text
    content = getattr(response, "content", b"")
    if isinstance(content, bytes):
        encoding = getattr(response, "encoding", None) or "utf-8"
        return status, content_type, content.decode(encoding, errors="replace")
    return status, content_type, str(content or "")


def _report_dict(report: Any) -> dict[str, Any]:
    return {
        "counts": dict(report.counts),
        "registry_path": str(report.registry_path),
        "report_path": str(report.report_path),
        "sources": list(report.sources),
    }


def _slug_from_url(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _safe_timestamp(value: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in value).strip("-") or "now"
