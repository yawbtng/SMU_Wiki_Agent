from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from .content_extract import extract_content
from ..wiki.llm_wiki_builder import build_wiki
from ..wiki.llm_wiki_index import build_llm_wiki_index
from ..wiki.ingest_safety import canonicalize_url, safe_fetch
from ..wiki.self_improving import assess_candidate_source, enforce_manual_run_retention, find_registry_row_for_url
from ..sources.raw_source_normalizer import normalize_scraped_markdown
from ..sources.source_registry import checksum_text
from ..core.site_layout import ensure_layout_for_site_root
from ..core.time import utc_now_iso, utc_now_timestamp
from ..core.url_utils import slug_from_url
from .sitemap_discovery import apply_manual_urls
from .url_policy import classify_url_for_student_wiki
from ..core.storage import ensure_run_dirs, write_json
from ..runtime.run_persistence import _write_json_atomic


FetchUrl = Callable[[str], Any]


def run_manual_url_pipeline(
    *,
    site_root: Path,
    site_url: str,
    url: str,
    fetcher: FetchUrl | None = None,
    now: str | None = None,
    job_id: str = "",
    job_status_file: Path | None = None,
    question: str = "",
) -> dict[str, Any]:
    timestamp = now or utc_now_iso()
    layout = ensure_layout_for_site_root(Path(site_root))
    normalized_url = canonicalize_url(str(url or "").strip())
    status_path = Path(job_status_file) if job_status_file else None

    def _write_status(status: str, *, reason: str = "", source_ids: list[str] | None = None, extra: dict[str, Any] | None = None) -> None:
        if status_path is None:
            return
        payload = {
            "id": job_id or "",
            "status": status,
            "url": normalized_url,
            "question": question,
            "reason": reason,
            "source_ids": list(source_ids or []),
            "updated_at": int(utc_now_timestamp()),
        }
        if extra:
            payload.update(extra)
        _write_json_atomic(status_path, payload)

    try:
        accepted = apply_manual_urls(site_url, [normalized_url]) if site_url else []
        if not accepted or accepted[0].excluded_reason or not accepted[0].selected:
            reason = str(accepted[0].excluded_reason if accepted else "invalid_url") or "invalid_url"
            _write_status("failed", reason=reason)
            return {"status": "rejected", "reason": reason, "url": normalized_url}

        policy = classify_url_for_student_wiki(normalized_url)
        if not policy.selected:
            _write_status("failed", reason=policy.reason)
            return {"status": "rejected", "reason": policy.reason, "url": normalized_url, "policy": policy.reason}

        existing = find_registry_row_for_url(layout.site_root, normalized_url)
        if existing and str(existing.get("checksum") or ""):
            _write_status("succeeded", source_ids=[str(existing.get("source_id") or "")], extra={"short_circuit": True})
            enforce_manual_run_retention(layout.site_root)
            return {
                "status": "unchanged",
                "url": normalized_url,
                "source_id": str(existing.get("source_id") or ""),
                "reason": "pre_fetch_short_circuit",
            }

        run_id = f"manual-{_safe_timestamp(timestamp)}-{slug_from_url(normalized_url)}"
        run_root = layout.site_root / run_id
        dirs = ensure_run_dirs(run_root)
        write_json(run_root / "selected_urls.json", [accepted[0].to_dict()])

        if fetcher is None:
            response = _default_fetch(normalized_url, site_root=layout.site_root)
        else:
            response = fetcher(normalized_url)
        http_status, content_type, html = _response_parts(response)
        _raw_title, markdown, text_length, link_density = extract_content(html)

        quality = assess_candidate_source(
            {"url": normalized_url, "title": _raw_title or normalized_url, "snippet": markdown[:500]},
            site_root=layout.site_root,
            markdown=markdown,
        )
        if not quality.accepted:
            _write_status("failed", reason=",".join(quality.reasons) or "quality_gate_failed")
            return {
                "status": "rejected",
                "reason": ",".join(quality.reasons) or "quality_gate_failed",
                "url": normalized_url,
                "quality_gate": quality.to_dict(),
            }

        slug = slug_from_url(normalized_url)
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
                "content_checksum": checksum_text(markdown),
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
        source_ids = [str(row.get("source_id") or "") for row in raw_report.sources if str(row.get("source_id") or "")]
        _write_status("succeeded", source_ids=source_ids)
        enforce_manual_run_retention(layout.site_root)
        return {
            "status": "complete",
            "url": normalized_url,
            "run_id": run_id,
            "run_root": str(run_root.relative_to(layout.site_root)),
            "raw_report": _report_dict(raw_report),
            "wiki_report": wiki_report,
            "index_report": index_report,
            "source_ids": source_ids,
        }
    except Exception as exc:
        _write_status("failed", reason=str(exc))
        return {"status": "failed", "url": normalized_url, "reason": str(exc)}


def _default_fetch(url: str, *, site_root: Path) -> Any:
    return safe_fetch(url, site_root=site_root)


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


def _safe_timestamp(value: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in value).strip("-") or "now"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the manual URL ingestion pipeline for one URL.")
    parser.add_argument("--site-root", required=True)
    parser.add_argument("--site-url", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--job-id", default="")
    parser.add_argument("--job-status-file", default="")
    parser.add_argument("--question", default="")
    args = parser.parse_args(argv)
    status_file = Path(args.job_status_file) if args.job_status_file else None
    print(
        json.dumps(
            run_manual_url_pipeline(
                site_root=Path(args.site_root),
                site_url=args.site_url,
                url=args.url,
                job_id=args.job_id,
                job_status_file=status_file,
                question=args.question,
            ),
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
