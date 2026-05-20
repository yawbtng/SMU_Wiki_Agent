from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from typing import Any
from urllib.parse import urlparse

import requests

from .content_extract import extract_content
from .failure_classifier import classify_failure, to_failure_record
from .models import DiscoveredURL, PageResult
from .pdf_ingest import PdfIngestConfig, ingest_pdfs
from .run_persistence import read_page_states, upsert_page_state, write_page_states, write_run_status
from .state import RunStateStore
from .storage import ensure_run_dirs, write_json

try:
    from scrapling.fetchers import Fetcher, PlayWrightFetcher, StealthyFetcher
except Exception:  # pragma: no cover - optional import
    Fetcher = None
    PlayWrightFetcher = None
    StealthyFetcher = None


def _slug_from_url(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _safe_pdf_filename(url: str) -> str:
    path_name = Path(urlparse(url).path).name or f"{_slug_from_url(url)}.pdf"
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", path_name).strip(".-")
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned or _slug_from_url(url)}.pdf"
    return cleaned[:160]


def _is_pdf_url(item: DiscoveredURL) -> bool:
    content_guess = str(item.content_type_guess or "").lower()
    return urlparse(item.url).path.lower().endswith(".pdf") or "pdf" in content_guess


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_ms(start_iso: str | None) -> int:
    if not start_iso:
        return 0
    try:
        start_dt = datetime.fromisoformat(start_iso)
        return int((datetime.now(timezone.utc) - start_dt).total_seconds() * 1000)
    except Exception:
        return 0


def _response_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    text = str(value)
    return None if text == "None" else text


def _extract_response_parts(resp: Any) -> tuple[int | None, str | None, str]:
    status = getattr(resp, "status_code", None)
    if status is None:
        status = getattr(resp, "status", None)
    headers = getattr(resp, "headers", None) or {}
    content_type = headers.get("content-type") if isinstance(headers, dict) else None
    html = _response_text(getattr(resp, "text", None))
    if html is None and hasattr(resp, "body"):
        html = _response_text(resp.body)
    if html is None and hasattr(resp, "content"):
        html = _response_text(resp.content)
    return status, content_type, html or ""


class ScrapeRunner:
    def __init__(self, state: RunStateStore, base_data_dir: Path) -> None:
        self.state = state
        self.base_data_dir = base_data_dir
        self._threads: dict[str, threading.Thread] = {}

    def _run_key(self, site_id: str, run_id: str) -> str:
        return f"{site_id}:{run_id}"

    def start(self, site_id: str, run_id: str, urls: list[DiscoveredURL], concurrency: int = 4) -> None:
        key = self._run_key(site_id, run_id)
        if key in self._threads and self._threads[key].is_alive():
            return
        self.state.set_cancel(site_id, run_id, False)
        thread = threading.Thread(target=self._execute, args=(site_id, run_id, urls, concurrency), daemon=True)
        self._threads[key] = thread
        thread.start()

    def cancel(self, site_id: str, run_id: str) -> None:
        self.state.set_cancel(site_id, run_id, True)

    def pause(self, site_id: str, run_id: str) -> None:
        self.state.set_pause(site_id, run_id, True)
        status = self.state.get_status(site_id, run_id)
        if status:
            if str(status.get("state") or "").lower() not in {"cancelled", "completed", "failed"}:
                running = int(status.get("running") or 0)
                status["state"] = "pausing" if running > 0 else "paused"
                self.state.set_status(site_id, run_id, status)
        self.state.push_event(
            site_id,
            run_id,
            {"ts": _utc_now_iso(), "event": "run_pause_requested", "status": "pausing", "url": None},
        )

    def unpause(self, site_id: str, run_id: str) -> None:
        self.state.set_pause(site_id, run_id, False)
        status = self.state.get_status(site_id, run_id)
        if status:
            if str(status.get("state") or "").lower() in {"paused", "pausing"}:
                status["state"] = "running"
                self.state.set_status(site_id, run_id, status)
        self.state.push_event(
            site_id,
            run_id,
            {"ts": _utc_now_iso(), "event": "run_unpaused", "status": "running", "url": None},
        )

    def resume(self, site_id: str, run_id: str, concurrency: int = 4) -> bool:
        key = self._run_key(site_id, run_id)
        thread = self._threads.get(key)
        if thread is not None and thread.is_alive():
            self.unpause(site_id, run_id)
            return False

        run_root = self.base_data_dir / "sites" / site_id / run_id
        selected_urls_path = run_root / "selected_urls.json"
        if not selected_urls_path.exists():
            self.unpause(site_id, run_id)
            return False
        try:
            raw = json.loads(selected_urls_path.read_text(encoding="utf-8"))
        except Exception:
            self.unpause(site_id, run_id)
            return False

        urls: list[DiscoveredURL] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            urls.append(
                DiscoveredURL(
                    url=str(row.get("url") or ""),
                    source_sitemap=str(row.get("source_sitemap") or ""),
                    lastmod=row.get("lastmod"),
                    path_category=str(row.get("path_category") or "other"),
                    content_type_guess=str(row.get("content_type_guess") or "html"),
                    excluded_reason=row.get("excluded_reason"),
                    selected=bool(row.get("selected", True)),
                )
            )

        if not urls:
            self.unpause(site_id, run_id)
            return False

        pages = self.state.get_pages(site_id, run_id) or read_page_states(run_root)
        pages_by_url = {str(p.get("url") or ""): p for p in pages if isinstance(p, dict)}
        unfinished = 0
        for item in urls:
            page = pages_by_url.get(item.url, {})
            page_status = str(page.get("status") or "")
            if page_status != "success":
                unfinished += 1
        if unfinished <= 0:
            self.unpause(site_id, run_id)
            return False

        self.state.set_cancel(site_id, run_id, False)
        self.state.set_pause(site_id, run_id, False)
        self.start(site_id, run_id, urls, concurrency=concurrency)
        return True

    def _fetch_with_mode(self, mode: str, url: str) -> Any:
        if mode == "fetcher" and Fetcher is not None:
            return Fetcher.get(url, timeout=20, retries=2)
        if mode == "dynamic" and PlayWrightFetcher is not None:
            return PlayWrightFetcher.fetch(url, headless=True, timeout=30000, network_idle=True)
        if mode == "stealthy" and StealthyFetcher is not None:
            return StealthyFetcher.fetch(url, headless=True, timeout=30000, network_idle=True)
        return requests.get(url, timeout=20)

    def _download_pdf(self, url: str, target: Path) -> tuple[int | None, str | None, int]:
        resp = requests.get(url, timeout=60)
        content_type = resp.headers.get("content-type") if isinstance(resp.headers, dict) else None
        resp.raise_for_status()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(resp.content)
        return getattr(resp, "status_code", None), content_type, len(resp.content)

    def _execute(self, site_id: str, run_id: str, urls: list[DiscoveredURL], concurrency: int = 4) -> None:
        selected_urls = [item for item in urls if item.selected and not item.excluded_reason]
        run_root = self.base_data_dir / "sites" / site_id / run_id
        dirs = ensure_run_dirs(run_root)
        write_json(run_root / "selected_urls.json", [item.to_dict() for item in selected_urls])

        worker_count = max(1, min(int(concurrency or 4), 16))
        status_lock = threading.Lock()
        failures_lock = threading.Lock()
        pdf_lock = threading.Lock()
        failures: list[dict[str, Any]] = []
        pages_order = [item.url for item in selected_urls]
        pages_by_url: dict[str, dict[str, Any]] = {}
        status: dict[str, Any] = {
            "state": "running",
            "total": len(selected_urls),
            "queued": len(selected_urls),
            "running": 0,
            "success": 0,
            "failed": 0,
            "cancelled": 0,
            "current_url": None,
            "concurrency": worker_count,
            "started_at": _utc_now_iso(),
            "finished_at": None,
        }

        def _pages_snapshot_locked() -> list[dict[str, Any]]:
            return [pages_by_url[url].copy() for url in pages_order]

        def _set_state_locked() -> None:
            counts = {"queued": 0, "running": 0, "success": 0, "failed": 0, "cancelled": 0}
            current_url = None
            for url in pages_order:
                row = pages_by_url[url]
                row_status = str(row.get("status") or "queued")
                if row_status in counts:
                    counts[row_status] += 1
                if row_status == "running" and current_url is None:
                    current_url = row.get("url")
            status.update(counts)
            status["current_url"] = current_url
            if str(status.get("state") or "").lower() not in {"cancelled", "completed", "failed"}:
                if self.state.get_pause(site_id, run_id):
                    status["state"] = "pausing" if counts["running"] > 0 else "paused"
                elif str(status.get("state") or "").lower() in {"paused", "pausing", "initializing"}:
                    status["state"] = "running"
            self.state.set_pages(site_id, run_id, _pages_snapshot_locked())
            self.state.set_status(site_id, run_id, status.copy())
            write_run_status(run_root, status.copy())
            write_page_states(run_root, _pages_snapshot_locked())

        existing_pages = {
            str(page.get("url") or ""): page
            for page in (self.state.get_pages(site_id, run_id) or read_page_states(run_root))
            if isinstance(page, dict) and page.get("url")
        }
        initial_queue_urls: list[str] = []
        for item in selected_urls:
            existing = existing_pages.get(item.url)
            if existing and str(existing.get("status") or "").lower() == "success":
                pages_by_url[item.url] = existing.copy()
                continue
            if existing and str(existing.get("status") or "").lower() in {"queued", "cancelled", "failed", "running"}:
                page = existing.copy()
                page["status"] = "queued"
                page["worker_id"] = None
                page["finished_at"] = None
                pages_by_url[item.url] = page
            else:
                pages_by_url[item.url] = PageResult(
                    url=item.url,
                    status="queued",
                    fetch_mode="fetcher",
                    worker_id=None,
                    attempt=0,
                    started_at=None,
                    finished_at=None,
                ).to_dict()
            initial_queue_urls.append(item.url)
            self.state.push_event(
                site_id,
                run_id,
                {
                    "ts": _utc_now_iso(),
                    "event": "page_queued",
                    "status": "queued",
                    "url": item.url,
                    "worker_id": None,
                    "attempt": 0,
                    "fetch_mode": None,
                },
            )

        with status_lock:
            _set_state_locked()

        work_queue: Queue[DiscoveredURL] = Queue()
        for item in selected_urls:
            if item.url in initial_queue_urls:
                work_queue.put(item)

        def _worker(idx: int) -> None:
            worker_id = f"worker-{idx + 1}"
            while True:
                if self.state.get_cancel(site_id, run_id):
                    break
                if self.state.get_pause(site_id, run_id):
                    with status_lock:
                        _set_state_locked()
                    time.sleep(0.1)
                    continue
                try:
                    item = work_queue.get_nowait()
                except Empty:
                    self.state.push_event(
                        site_id,
                        run_id,
                        {
                            "ts": _utc_now_iso(),
                            "event": "worker_idle",
                            "status": "idle",
                            "url": None,
                            "worker_id": worker_id,
                            "attempt": 0,
                            "fetch_mode": None,
                        },
                    )
                    break

                slug = _slug_from_url(item.url)
                raw_html_path = dirs["raw_html"] / f"{slug}.html"
                md_path = dirs["markdown"] / f"{slug}.md"
                meta_path = dirs["metadata"] / f"{slug}.json"
                pdf_path = run_root / "pdf_downloads" / _safe_pdf_filename(item.url)
                last_error: Exception | None = None

                with status_lock:
                    page = pages_by_url[item.url]
                    page["status"] = "running"
                    page["worker_id"] = worker_id
                    page["attempt"] = 0
                    page["started_at"] = _utc_now_iso()
                    page["finished_at"] = None
                    page["failure_reason"] = None
                    page["fetch_mode"] = "fetcher"
                    pages_by_url[item.url] = page
                    _set_state_locked()

                self.state.push_event(
                    site_id,
                    run_id,
                    {
                        "ts": _utc_now_iso(),
                        "event": "page_started",
                        "status": "running",
                        "url": item.url,
                        "worker_id": worker_id,
                        "attempt": 0,
                        "fetch_mode": None,
                    },
                )

                if _is_pdf_url(item):
                    try:
                        http_status, content_type, size_bytes = self._download_pdf(item.url, pdf_path)
                        pdf_result = ingest_pdfs([pdf_path], PdfIngestConfig())
                        with pdf_lock:
                            _merge_jsonl_rows(
                                run_root / "s05" / "pdf_sources.jsonl",
                                [row.to_dict() for row in pdf_result.sources],
                                key="pdf_source_id",
                            )
                            _merge_jsonl_rows(
                                run_root / "s05" / "pdf_chunks.jsonl",
                                [row.to_dict() for row in pdf_result.chunks],
                                key="chunk_id",
                            )
                            _merge_jsonl_rows(
                                run_root / "s05" / "pdf_quarantine.jsonl",
                                [row.to_dict() for row in pdf_result.quarantine],
                                key="pdf_source_id",
                            )
                        accepted = any(row.accepted for row in pdf_result.sources)
                        chunk_count = len(pdf_result.chunks)
                        write_json(
                            meta_path,
                            {
                                "url": item.url,
                                "http_status": http_status,
                                "content_type": content_type,
                                "size_bytes": size_bytes,
                                "fetch_mode": "pdf",
                                "worker_id": worker_id,
                                "attempt": 1,
                                "pdf_path": str(pdf_path),
                                "pdf_chunks": chunk_count,
                                "pdf_quarantine": [row.to_dict() for row in pdf_result.quarantine],
                            },
                        )
                        if not accepted or chunk_count <= 0:
                            reason = "ocr_required" if pdf_result.quarantine else "parse_error"
                            with status_lock:
                                page = pages_by_url[item.url]
                                page["status"] = "failed"
                                page["http_status"] = http_status
                                page["failure_reason"] = reason
                                page["fetch_mode"] = "pdf"
                                page["metadata_path"] = str(meta_path)
                                page["text_length"] = 0
                                page["link_density"] = 0.0
                                page["finished_at"] = _utc_now_iso()
                                pages_by_url[item.url] = page
                                _set_state_locked()
                        else:
                            with status_lock:
                                page = pages_by_url[item.url]
                                page["status"] = "success"
                                page["http_status"] = http_status
                                page["failure_reason"] = None
                                page["fetch_mode"] = "pdf"
                                page["metadata_path"] = str(meta_path)
                                page["raw_html_path"] = str(pdf_path)
                                page["markdown_path"] = None
                                page["text_length"] = sum(chunk.char_count for chunk in pdf_result.chunks)
                                page["link_density"] = 0.0
                                page["finished_at"] = _utc_now_iso()
                                pages_by_url[item.url] = page
                                _set_state_locked()
                            self.state.push_event(
                                site_id,
                                run_id,
                                {
                                    "ts": _utc_now_iso(),
                                    "event": "pdf_artifacts_saved",
                                    "status": "running",
                                    "url": item.url,
                                    "worker_id": worker_id,
                                    "attempt": 1,
                                    "fetch_mode": "pdf",
                                    "http_status": http_status,
                                    "pdf_path": str(pdf_path),
                                    "pdf_chunks": chunk_count,
                                },
                            )
                    except Exception as exc:
                        last_error = exc
                        failure_reason = classify_failure(
                            http_status=None,
                            content_type="application/pdf",
                            text_length=0,
                            link_density=0.0,
                            error=exc,
                        )
                        with status_lock:
                            page = pages_by_url[item.url]
                            page["status"] = "failed"
                            page["failure_reason"] = failure_reason
                            page["fetch_mode"] = "pdf"
                            page["finished_at"] = _utc_now_iso()
                            pages_by_url[item.url] = page
                            _set_state_locked()
                        self.state.push_event(
                            site_id,
                            run_id,
                            {
                                "ts": _utc_now_iso(),
                                "event": "pdf_fetch_exception",
                                "status": "failed",
                                "url": item.url,
                                "worker_id": worker_id,
                                "attempt": 1,
                                "fetch_mode": "pdf",
                                "failure_reason": failure_reason,
                                "error": str(exc),
                            },
                        )
                else:
                    for attempt, mode in enumerate(("fetcher", "dynamic", "stealthy"), start=1):
                        try:
                            with status_lock:
                                page = pages_by_url[item.url]
                                page["attempt"] = attempt
                                page["fetch_mode"] = mode
                                pages_by_url[item.url] = page
                                self.state.set_pages(site_id, run_id, _pages_snapshot_locked())
                            self.state.push_event(
                                site_id,
                                run_id,
                                {
                                    "ts": _utc_now_iso(),
                                    "event": "fetch_attempt",
                                    "status": "running",
                                    "url": item.url,
                                    "worker_id": worker_id,
                                    "attempt": attempt,
                                    "fetch_mode": mode,
                                },
                            )
                            response = self._fetch_with_mode(mode, item.url)
                            http_status, content_type, html = _extract_response_parts(response)
                            _, markdown, text_length, link_density = extract_content(html)
                            reason = classify_failure(
                                http_status=http_status,
                                content_type=content_type,
                                text_length=text_length,
                                link_density=link_density,
                            )
                            if reason is None:
                                raw_html_path.write_text(html, encoding="utf-8")
                                md_path.write_text(markdown, encoding="utf-8")
                                write_json(
                                    meta_path,
                                    {
                                        "url": item.url,
                                        "http_status": http_status,
                                        "content_type": content_type,
                                        "text_length": text_length,
                                        "link_density": link_density,
                                        "fetch_mode": mode,
                                        "worker_id": worker_id,
                                        "attempt": attempt,
                                    },
                                )
                                with status_lock:
                                    page = pages_by_url[item.url]
                                    page["status"] = "success"
                                    page["http_status"] = http_status
                                    page["failure_reason"] = None
                                    page["text_length"] = text_length
                                    page["link_density"] = link_density
                                    page["raw_html_path"] = str(raw_html_path)
                                    page["markdown_path"] = str(md_path)
                                    page["metadata_path"] = str(meta_path)
                                    page["finished_at"] = _utc_now_iso()
                                    pages_by_url[item.url] = page
                                    _set_state_locked()
                                self.state.push_event(
                                    site_id,
                                    run_id,
                                    {
                                        "ts": _utc_now_iso(),
                                        "event": "artifacts_saved",
                                        "status": "running",
                                        "url": item.url,
                                        "worker_id": worker_id,
                                        "attempt": attempt,
                                        "fetch_mode": mode,
                                        "http_status": http_status,
                                        "markdown_path": str(md_path),
                                        "raw_html_path": str(raw_html_path),
                                    },
                                )
                                break

                            with status_lock:
                                page = pages_by_url[item.url]
                                page["status"] = "failed"
                                page["http_status"] = http_status
                                page["failure_reason"] = reason
                                page["text_length"] = text_length
                                page["link_density"] = link_density
                                pages_by_url[item.url] = page
                                self.state.set_pages(site_id, run_id, _pages_snapshot_locked())
                            if reason in {"blocked", "timeout", "parse_error"} and mode != "stealthy":
                                self.state.push_event(
                                    site_id,
                                    run_id,
                                    {
                                        "ts": _utc_now_iso(),
                                        "event": "fetch_retrying_next_mode",
                                        "status": "retry",
                                        "url": item.url,
                                        "worker_id": worker_id,
                                        "attempt": attempt,
                                        "fetch_mode": mode,
                                        "failure_reason": reason,
                                    },
                                )
                                continue
                            break
                        except Exception as exc:
                            last_error = exc
                            failure_reason = classify_failure(
                                http_status=None,
                                content_type=None,
                                text_length=0,
                                link_density=0.0,
                                error=exc,
                            )
                            with status_lock:
                                page = pages_by_url[item.url]
                                page["status"] = "failed"
                                page["failure_reason"] = failure_reason
                                page["fetch_mode"] = mode
                                pages_by_url[item.url] = page
                                self.state.set_pages(site_id, run_id, _pages_snapshot_locked())
                            self.state.push_event(
                                site_id,
                                run_id,
                                {
                                    "ts": _utc_now_iso(),
                                    "event": "fetch_exception",
                                    "status": "failed",
                                    "url": item.url,
                                    "worker_id": worker_id,
                                    "attempt": attempt,
                                    "fetch_mode": mode,
                                    "failure_reason": failure_reason,
                                    "error": str(exc),
                                },
                            )
                            if mode != "stealthy":
                                continue

                with status_lock:
                    page = pages_by_url[item.url]
                    if page.get("status") not in {"success", "failed"}:
                        page["status"] = "failed"
                    if not page.get("finished_at"):
                        page["finished_at"] = _utc_now_iso()
                    pages_by_url[item.url] = page
                    _set_state_locked()
                    page_snapshot = page.copy()

                if page_snapshot.get("status") == "failed":
                    with failures_lock:
                        failures.append(
                            to_failure_record(
                                item.url,
                                str(page_snapshot.get("failure_reason") or "parse_error"),
                                {
                                    "http_status": page_snapshot.get("http_status"),
                                    "fetch_mode": page_snapshot.get("fetch_mode"),
                                    "error": str(last_error or ""),
                                    "worker_id": worker_id,
                                    "attempt": int(page_snapshot.get("attempt") or 0),
                                },
                            )
                        )

                self.state.push_event(
                    site_id,
                    run_id,
                    {
                        "ts": _utc_now_iso(),
                        "event": "page_done",
                        "url": item.url,
                        "status": page_snapshot.get("status"),
                        "fetch_mode": page_snapshot.get("fetch_mode"),
                        "http_status": page_snapshot.get("http_status"),
                        "failure_reason": page_snapshot.get("failure_reason"),
                        "duration_ms": _duration_ms(page_snapshot.get("started_at")),
                        "worker_id": worker_id,
                        "attempt": int(page_snapshot.get("attempt") or 0),
                    },
                )
                work_queue.task_done()

        workers: list[threading.Thread] = []
        for idx in range(worker_count):
            t = threading.Thread(target=_worker, args=(idx,), daemon=True)
            workers.append(t)
            t.start()
        for t in workers:
            t.join()

        if self.state.get_cancel(site_id, run_id):
            with status_lock:
                for url in pages_order:
                    page = pages_by_url[url]
                    if page.get("status") == "queued":
                        page["status"] = "cancelled"
                        page["finished_at"] = _utc_now_iso()
                        pages_by_url[url] = page
                status["state"] = "cancelled"
                _set_state_locked()
            self.state.push_event(
                site_id,
                run_id,
                {
                    "ts": _utc_now_iso(),
                    "event": "run_cancelled",
                    "status": "cancelled",
                    "url": status.get("current_url"),
                },
            )

        status["finished_at"] = _utc_now_iso()
        if status.get("state") != "cancelled":
            status["state"] = "completed"
        with status_lock:
            _set_state_locked()
            self.state.set_status(site_id, run_id, status.copy())

        self.state.push_event(
            site_id,
            run_id,
            {
                "ts": _utc_now_iso(),
                "event": "run_finished",
                "status": status["state"],
                "success": status["success"],
                "failed": status["failed"],
                "cancelled": status["cancelled"],
                "total": status["total"],
            },
        )

        with status_lock:
            pages_final = _pages_snapshot_locked()
        write_json(run_root / "scrape_manifest.json", pages_final)
        write_json(run_root / "failures.json", failures)


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _merge_jsonl_rows(path: Path, rows: list[dict[str, Any]], *, key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = {str(row.get(key) or ""): row for row in _read_jsonl_rows(path) if row.get(key)}
    for row in rows:
        row_key = str(row.get(key) or "")
        if row_key:
            merged[row_key] = row
    path.write_text("".join(json.dumps(row, ensure_ascii=True) + "\n" for row in merged.values()), encoding="utf-8")
