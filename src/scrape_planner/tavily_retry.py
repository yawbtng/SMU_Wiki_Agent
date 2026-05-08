from __future__ import annotations

import hashlib
from pathlib import Path
import time
from typing import Any
from datetime import datetime, timezone

import requests

from .observability import append_event
from .run_persistence import append_run_event, upsert_page_state
from .storage import write_json


def _slug(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def retry_failed_with_tavily(
    *,
    run_root: Path,
    pages: list[dict[str, Any]],
    tavily_api_key: str,
    extract_depth: str = "basic",
    fmt: str = "markdown",
    target_urls: list[str] | None = None,
    source_run_id: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    markdown_dir = run_root / "markdown"
    metadata_dir = run_root / "metadata"
    markdown_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    updated = []
    retried = 0
    recovered = 0
    failed = 0
    target_set = {str(url).strip() for url in (target_urls or []) if str(url).strip()}
    for page in pages:
        current = dict(page)
        if current.get("status") != "failed":
            updated.append(current)
            continue
        url = current.get("url", "")
        if target_set and url not in target_set:
            updated.append(current)
            continue
        retried += 1
        try:
            t0 = time.perf_counter()
            resp = requests.post(
                "https://api.tavily.com/extract",
                headers={"Authorization": f"Bearer {tavily_api_key}", "Content-Type": "application/json"},
                json={
                    "urls": [url],
                    "extract_depth": extract_depth,
                    "format": fmt,
                    "include_images": False,
                    "include_favicon": False,
                },
                timeout=90,
            )
            resp.raise_for_status()
            latency_ms = int((time.perf_counter() - t0) * 1000)
            payload = resp.json()
            results = payload.get("results", [])
            if not results:
                failed += 1
                current["failure_reason"] = "tavily_no_result"
                current["fetch_mode"] = "tavily"
                current["attempt"] = int(current.get("attempt") or 0) + 1
                upsert_page_state(run_root, current)
                append_run_event(
                    run_root,
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "event": "tavily_retry_done",
                        "status": "failed",
                        "url": url,
                        "fetch_mode": "tavily",
                        "failure_reason": current["failure_reason"],
                        "attempt": current["attempt"],
                        "source_run_id": source_run_id,
                    },
                )
                updated.append(current)
                continue
            raw_content = (results[0].get("raw_content") or "").strip()
            if not raw_content:
                failed += 1
                current["failure_reason"] = "tavily_empty_content"
                current["fetch_mode"] = "tavily"
                current["attempt"] = int(current.get("attempt") or 0) + 1
                upsert_page_state(run_root, current)
                append_run_event(
                    run_root,
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "event": "tavily_retry_done",
                        "status": "failed",
                        "url": url,
                        "fetch_mode": "tavily",
                        "failure_reason": current["failure_reason"],
                        "attempt": current["attempt"],
                        "source_run_id": source_run_id,
                    },
                )
                updated.append(current)
                continue
            slug = _slug(url)
            md_path = markdown_dir / f"{slug}.md"
            meta_path = metadata_dir / f"{slug}.json"
            md_path.write_text(raw_content, encoding="utf-8")
            write_json(
                meta_path,
                {
                    "url": url,
                    "fetch_mode": "tavily",
                    "extract_depth": extract_depth,
                    "format": fmt,
                },
            )
            current["status"] = "success"
            current["fetch_mode"] = "tavily"
            current["failure_reason"] = None
            current["markdown_path"] = str(md_path)
            current["metadata_path"] = str(meta_path)
            current["raw_html_path"] = current.get("raw_html_path")
            current["attempt"] = int(current.get("attempt") or 0) + 1
            recovered += 1
            upsert_page_state(run_root, current)
            append_run_event(
                run_root,
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "event": "tavily_retry_done",
                    "status": "success",
                    "url": url,
                    "fetch_mode": "tavily",
                    "attempt": current["attempt"],
                    "latency_ms": latency_ms,
                    "source_run_id": source_run_id,
                },
            )
            append_event(
                run_root,
                {
                    "provider": "tavily",
                    "operation": "retry_failed_url",
                    "status": "success",
                    "url": url,
                    "latency_ms": latency_ms,
                    "extract_depth": extract_depth,
                },
            )
            updated.append(current)
        except Exception as exc:
            failed += 1
            current["failure_reason"] = f"tavily_error: {exc}"
            current["fetch_mode"] = "tavily"
            current["attempt"] = int(current.get("attempt") or 0) + 1
            upsert_page_state(run_root, current)
            append_run_event(
                run_root,
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "event": "tavily_retry_done",
                    "status": "failed",
                    "url": url,
                    "fetch_mode": "tavily",
                    "failure_reason": current["failure_reason"],
                    "attempt": current["attempt"],
                    "source_run_id": source_run_id,
                },
            )
            append_event(
                run_root,
                {
                    "provider": "tavily",
                    "operation": "retry_failed_url",
                    "status": "failed",
                    "url": url,
                    "extract_depth": extract_depth,
                    "error": str(exc),
                },
            )
            updated.append(current)

    write_json(run_root / "scrape_manifest.json", updated)
    write_json(
        run_root / "failures.json",
        [row for row in updated if str(row.get("status") or "").lower() == "failed"],
    )
    summary = {"retried": retried, "recovered": recovered, "still_failed": failed}
    write_json(run_root / "tavily_retry_summary.json", summary)
    return updated, summary
