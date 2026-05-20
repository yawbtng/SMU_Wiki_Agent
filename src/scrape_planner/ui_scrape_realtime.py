from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


@dataclass(frozen=True)
class ScrapedMarkdownPreview:
    ready: bool
    markdown: str
    message: str = ""
    path: Path | None = None
    url: str = ""
    http_status: int | None = None
    fetch_mode: str = ""
    text_length: int | None = None


@dataclass(frozen=True)
class RunSummary:
    state: str
    total: int
    success: int
    failed: int
    cancelled: int
    running: int
    queued: int
    done: int
    remaining: int
    progress_label: str


def page_slug(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def build_scraped_page_preview_href(*, site_id: str, run_id: str, url: str) -> str:
    return "?" + urlencode(
        {
            "view": "scraped_page",
            "site_id": site_id,
            "run_id": run_id,
            "page_slug": page_slug(url),
        }
    )


def is_safe_route_part(value: str) -> bool:
    return bool(value) and value != ".." and ".." not in value and all(
        char.isascii() and (char.isalnum() or char in "_-." ) for char in value
    )


def is_safe_page_slug(value: str) -> bool:
    return len(value) == 12 and all(char in "0123456789abcdef" for char in value)


def resolve_scraped_markdown_preview(run_root: Path, slug: str) -> ScrapedMarkdownPreview:
    if not is_safe_page_slug(slug):
        return ScrapedMarkdownPreview(
            ready=False,
            markdown="",
            message="Scraped markdown is not ready yet.",
        )

    markdown_path = run_root / "markdown" / f"{slug}.md"
    metadata_path = run_root / "metadata" / f"{slug}.json"

    if not markdown_path.exists():
        return ScrapedMarkdownPreview(
            ready=False,
            markdown="",
            message="Scraped markdown is not ready yet.",
            path=markdown_path,
        )

    try:
        markdown = markdown_path.read_text(encoding="utf-8")
    except OSError:
        return ScrapedMarkdownPreview(
            ready=False,
            markdown="",
            message="Scraped markdown is not ready yet.",
            path=markdown_path,
        )
    metadata: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            loaded_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded_metadata = {}
        if isinstance(loaded_metadata, dict):
            metadata = loaded_metadata

    text_length: int | None
    try:
        text_length = int(metadata.get("text_length") or len(markdown))
    except (TypeError, ValueError):
        text_length = None

    return ScrapedMarkdownPreview(
        ready=True,
        markdown=markdown,
        path=markdown_path,
        url=str(metadata.get("url", "")),
        http_status=metadata.get("http_status"),
        fetch_mode=str(metadata.get("fetch_mode", "")),
        text_length=text_length,
    )


def derive_run_summary(*, status: dict[str, Any], pages: list[dict[str, Any]], selected_count: int) -> RunSummary:
    success = int(status["success"] if "success" in status else _count_pages(pages, "success"))
    failed = int(status["failed"] if "failed" in status else _count_pages(pages, "failed"))
    cancelled = int(status["cancelled"] if "cancelled" in status else _count_pages(pages, "cancelled"))
    running = int(status["running"] if "running" in status else _count_pages(pages, "running"))
    total = int(status["total"] if "total" in status else selected_count)
    done = success + failed + cancelled
    remaining = max(total - done, 0)
    queued = int(status["queued"] if "queued" in status else max(remaining - running, 0))

    return RunSummary(
        state=str(status.get("state", "ready")),
        total=total,
        success=success,
        failed=failed,
        cancelled=cancelled,
        running=running,
        queued=queued,
        done=done,
        remaining=remaining,
        progress_label=f"{done} / {total}",
    )


def latest_pages_by_status(pages: list[dict[str, Any]], status: str, *, limit: int = 10) -> list[dict[str, Any]]:
    matching = [page for page in pages if page.get("status") == status]
    return sorted(matching, key=_page_sort_key, reverse=True)[:limit]


def _count_pages(pages: list[dict[str, Any]], status: str) -> int:
    return sum(1 for page in pages if page.get("status") == status)


def _page_sort_key(page: dict[str, Any]) -> str:
    return str(page.get("finished_at") or page.get("start_at") or page.get("started_at") or "")
