from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import unquote, urlparse

import altair as alt
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
try:
    from streamlit_autorefresh import st_autorefresh
except Exception:
    st_autorefresh = None

from src.scrape_planner.app import APP_STATE_DEFAULTS, AppContext
from src.scrape_planner.failure_classifier import classify_failure
from src.scrape_planner.markdown_graph import (
    answer_context as graph_answer_context,
    build_graph as build_markdown_graph,
    discover_raw_markdown_files,
    get_unit_pages as graph_get_unit_pages,
    graph_stats as load_graph_stats,
    knowledge_graph_dir,
    list_units as graph_list_units,
    load_edges as load_graph_edges,
    load_page_nodes as load_graph_page_nodes,
    load_tags as load_graph_tags,
    orphan_pages as load_graph_orphan_pages,
    pages_without_unit_tags as load_pages_without_unit_tags,
    rebuild_query_index as rebuild_graph_query_index,
    run_graphify_enrichment_for_unit,
    search_pages as graph_search_pages,
    shortest_path as graph_shortest_path,
    traverse_from_page as graph_traverse_from_page,
    unit_distribution as load_unit_distribution,
)
from src.scrape_planner.models import DiscoveredURL
from src.scrape_planner.pdf_ingest import PdfIngestConfig, PdfParserUnavailableError, ingest_pdfs
from src.scrape_planner.observability import load_events
from src.scrape_planner.run_persistence import read_page_states, read_run_events, read_run_status
from src.scrape_planner.run_analytics import (
    build_completion_timeseries,
    build_llm_calls_timeseries,
    build_llm_cost_breakdown,
    build_llm_latency_table,
    build_llm_model_counts,
    build_llm_token_timeseries,
    build_slowest_pages_table,
    summarize_durations,
    summarize_failures,
    summarize_output_volume,
    summarize_pages,
)
from src.scrape_planner.scrape_worker import ScrapeRunner
from src.scrape_planner.sitemap_discovery import apply_manual_urls, discover_site_urls, normalize_site_url
from src.scrape_planner.site_layout import site_layout
from src.scrape_planner.state import RunStateStore
from src.scrape_planner.stepper_status import (
    load_embedding_status as _stepper_load_embedding_status,
    load_wiki_status as _stepper_load_wiki_status,
    raw_source_status as _stepper_raw_source_status,
    raw_sources_ready as _stepper_raw_sources_ready,
    read_jsonl_rows as _stepper_read_jsonl_rows,
    wiki_ready as _stepper_wiki_ready,
)
from src.scrape_planner.storage import persist_discovered, read_json, write_json
from src.scrape_planner.tmux_runner import TmuxRunner
from src.scrape_planner.llm_wiki_builder import launch_wiki_builder
from src.scrape_planner.llm_wiki_index import build_llm_wiki_index
from src.scrape_planner.manual_url_pipeline import run_manual_url_pipeline
from src.scrape_planner.raw_source_normalizer import normalize_pdf_pages
from src.scrape_planner.ui_scrape_realtime import (
    build_scraped_page_preview_href,
    derive_run_summary,
    is_safe_route_part,
    latest_pages_by_status,
    resolve_scraped_markdown_preview,
)
from src.scrape_planner.ui_navigation import WORKFLOW_TABS
from src.scrape_planner.ui_operator_components import (
    render_metric_strip,
    render_operator_details,
    render_status_band,
)
from src.scrape_planner.ui_operator_status import (
    build_operator_run_status,
    build_operator_source_status,
)
from src.scrape_planner.ui_preview_quality import (
    build_chunk_quality_summary,
    classify_chunk_row,
)
from src.scrape_planner.wiki_markdown_ui import (
    filter_wiki_markdown_records as _filter_wiki_markdown_records,
    list_wiki_markdown_files as _list_wiki_markdown_files,
    parse_markdown_frontmatter as _parse_markdown_frontmatter,
    read_wiki_markdown as _read_wiki_markdown,
    rewrite_wiki_markdown_links as _rewrite_wiki_markdown_links,
    safe_wiki_markdown_rel_path as _safe_wiki_markdown_rel_path,
    strip_markdown_frontmatter as _strip_markdown_frontmatter,
    strip_temp_clipboard_images as _strip_temp_clipboard_images,
    wiki_markdown_records as _wiki_markdown_records,
)

ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / "data"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
ENV_PATH = ROOT / ".env"
APP_STATE_PATH = DATA_ROOT / "app_state.json"


def _app_context() -> AppContext:
    if "app_context" not in st.session_state:
        st.session_state["app_context"] = AppContext.build(
            data_root=DATA_ROOT,
            session_state=st.session_state,
            app_state_path=APP_STATE_PATH,
            app_state_defaults={**APP_STATE_DEFAULTS, "ollama_base_url": OLLAMA_BASE_URL},
        )
    return st.session_state["app_context"]


def _site_slug(url: str) -> str:
    return normalize_site_url(url).replace("https://", "").replace("http://", "").replace("/", "_")


def _safe_text(value: object, default: str = "") -> str:
    if value is None:
        return default
    text = str(value)
    return text if text else default


def _init_state() -> None:
    defaults = {
        "active_workspace_id": "",
        "workspaces": [],
        "site_url": "",
        "site_id": "",
        "run_id": "",
        "discovered": [],
        "manual_urls": "",
        "selected_df": pd.DataFrame(),
        "llm_selected": [],
        "ollama_model": "",
        "openrouter_api_key": "",
        "openrouter_models": [],
        "ollama_models": [],
        "llm_provider": "openrouter",
        "ollama_base_url": OLLAMA_BASE_URL,
        "site_history": [],
        "tavily_api_key": "",
        "default_or_model": "deepseek/deepseek-v4-flash",
        "default_llm_cap": 150,
        "default_llm_batch_size": 250,
        "default_llm_sleep_sec": 0.0,
        "url_reasoning_provider": "openrouter",
        "url_reasoning_openrouter_model": "deepseek/deepseek-v4-flash",
        "url_reasoning_ollama_model": "qwen2.5:3b",
        "graph_enrichment_provider": "openrouter",
        "graph_answer_provider": "openrouter",
        "scrape_concurrency": 10,
        "scrape_browser_mode": "none",
        "lightpanda_cdp_url": "",
        "embedding_enabled": True,
        "embedding_model": "nomic-embed-text:latest",
        "zvec_enabled": True,
        "zvec_index_path": "",
        "zvec_collection": "university_wiki",
        "use_tavily_for_map": False,
        "tavily_cost_per_call_usd": 0.0,
        "ollama_input_per_m_usd": 0.0,
        "ollama_output_per_m_usd": 0.0,
        "selector_chat": [],
        "last_selection_payload": {},
        "graphify_provider": "openrouter",
        "graphify_model": "openai/gpt-4.1-mini",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _get_store() -> RunStateStore:
    if "state_store" not in st.session_state:
        st.session_state["state_store"] = RunStateStore(redis_url=REDIS_URL)
    return st.session_state["state_store"]


def _get_runner() -> ScrapeRunner:
    if "runner" not in st.session_state:
        st.session_state["runner"] = ScrapeRunner(_get_store(), DATA_ROOT)
    return st.session_state["runner"]

def _get_tmux_runner() -> TmuxRunner:
    if "tmux_runner" not in st.session_state:
        st.session_state["tmux_runner"] = TmuxRunner()
    return st.session_state["tmux_runner"]


def _run_root(site_id: str, run_id: str) -> Path:
    return _app_context().site_artifacts.run_root(site_id, run_id)


def _load_scrape_runtime(site_id: str, run_id: str, max_events: int = 1500) -> tuple[dict, list[dict], list[dict]]:
    status = store.get_status(site_id, run_id)
    pages = store.get_pages(site_id, run_id)
    events = store.get_events(site_id, run_id, max_items=max_events)
    run_root = _run_root(site_id, run_id)
    if not status:
        status = read_run_status(run_root)
    if not pages:
        pages = read_page_states(run_root)
    if not events:
        events = read_run_events(run_root, limit=max_events)
    return status, pages, events


def _safe_read_text(path_value: object, *, limit_chars: int | None = None) -> tuple[str | None, Path | None, int | None, str | None]:
    try:
        raw = str(path_value or "").strip()
        if not raw:
            return None, None, None, "No artifact path recorded."
        path = Path(raw)
        if not path.exists():
            return None, path, None, "File not found (path is stale or artifact was removed)."
        size_bytes = int(path.stat().st_size)
        content = path.read_text(encoding="utf-8", errors="replace")
        if limit_chars is not None and limit_chars >= 0:
            content = content[:limit_chars]
        return content, path, size_bytes, None
    except Exception as exc:
        return None, None, None, f"Failed to read file: {exc}"


def _normalize_failure_reason(row: dict) -> str:
    reason_raw = str(row.get("failure_reason") or row.get("error") or "").strip().lower()
    http_status = row.get("http_status")
    if "timeout" in reason_raw:
        return "timeout"
    if "blocked" in reason_raw or "captcha" in reason_raw or "forbidden" in reason_raw:
        return "blocked"
    if "network" in reason_raw or "connection" in reason_raw or "dns" in reason_raw:
        return "network_error"
    if "parse" in reason_raw:
        return "parse_error"
    if "empty" in reason_raw or "no_result" in reason_raw:
        return "empty_content"
    if "http_error" in reason_raw:
        return "http_error"
    if isinstance(http_status, int) and http_status >= 400:
        return "http_error"
    inferred = classify_failure(
        http_status=http_status if isinstance(http_status, int) else None,
        content_type=None,
        text_length=int(row.get("text_length") or 0),
        link_density=float(row.get("link_density") or 0.0),
        error=None,
    )
    if inferred in {"timeout", "blocked", "http_error", "empty_content", "parse_error"}:
        return inferred
    return "unknown"


def _safe_uploaded_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name or "document.pdf")).strip(".-")
    return cleaned[:160] or "document.pdf"


def _path_fingerprint(path: Path) -> tuple[int, int, int]:
    """Small cache key for local artifact reads."""
    try:
        candidate = Path(path)
        if candidate.is_file():
            stat = candidate.stat()
            return (int(stat.st_mtime_ns), int(stat.st_size), 1)
        if candidate.is_dir():
            latest_mtime = 0
            total_size = 0
            file_count = 0
            for child in candidate.glob("*"):
                if child.is_file():
                    stat = child.stat()
                    latest_mtime = max(latest_mtime, int(stat.st_mtime_ns))
                    total_size += int(stat.st_size)
                    file_count += 1
            return (latest_mtime, total_size, file_count)
    except OSError:
        return (0, 0, 0)
    return (0, 0, 0)


@st.cache_data(show_spinner=False)
def _cached_jsonl_rows(path: str, fingerprint: tuple[int, int, int]) -> list[dict]:
    return _stepper_read_jsonl_rows(Path(path))


def _read_jsonl_rows(path: Path) -> list[dict]:
    return _cached_jsonl_rows(str(path), _path_fingerprint(path))


@st.cache_data(show_spinner=False)
def _cached_raw_source_status(site_root: str, registry_fingerprint: tuple[int, int, int], reports_fingerprint: tuple[int, int, int]) -> dict:
    del registry_fingerprint, reports_fingerprint
    return _stepper_raw_source_status(site_layout(Path(site_root)))


def _raw_source_status(layout) -> dict:
    return _cached_raw_source_status(
        str(layout.site_root),
        _path_fingerprint(layout.registry_path),
        _path_fingerprint(layout.raw_reports_dir),
    )


def _raw_sources_ready(raw_status: dict) -> bool:
    return _stepper_raw_sources_ready(raw_status)


def _load_wiki_status(layout, raw_status: dict) -> dict:
    return _stepper_load_wiki_status(layout, raw_status)


def _wiki_ready(wiki_status: dict) -> bool:
    return _stepper_wiki_ready(wiki_status)


def _wiki_primary_action_label(wiki_status: dict) -> str:
    integrated = int(wiki_status.get("integrated_sources") or 0)
    pending = int(wiki_status.get("pending_source_count") or 0)
    changed = int(wiki_status.get("changed_source_count") or 0)
    if integrated <= 0:
        return "Build Wiki"
    if pending > 0 or changed > 0:
        return "Update Wiki"
    return "Wiki Current"


@st.cache_data(show_spinner=False)
def _cached_embedding_status(site_root: str, indexes_fingerprint: tuple[int, int, int]) -> dict:
    del indexes_fingerprint
    return _stepper_load_embedding_status(site_layout(Path(site_root)))


def _load_embedding_status(layout) -> dict:
    return _cached_embedding_status(str(layout.site_root), _path_fingerprint(layout.indexes_dir))


def _merge_jsonl_rows_app(path: Path, rows: list[dict], *, key: str) -> None:
    existing = {str(row.get(key)): row for row in _read_jsonl_rows(path) if row.get(key)}
    for row in rows:
        if row.get(key):
            existing[str(row.get(key))] = row
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in existing.values()), encoding="utf-8")


def _count_pdf_page_artifacts(pages_dir: Path) -> int:
    count = 0
    for pages_index in sorted(pages_dir.glob("*/pages.json")) if pages_dir.exists() else []:
        payload = read_json(pages_index, [])
        if isinstance(payload, list):
            count += len([row for row in payload if isinstance(row, dict)])
    return count


def _summarize_pdf_rows(source_rows: list[dict], page_rows: list[dict], chunk_rows: list[dict], quarantine_rows: list[dict]) -> dict:
    accepted = [row for row in source_rows if bool(row.get("accepted"))]
    pages_done = sum(int(row.get("page_count") or 0) for row in accepted)
    unknown_page_sources = len([row for row in accepted if row.get("page_count") is None])
    return {
        "documents": len(source_rows),
        "accepted": len(accepted),
        "pages_done": pages_done,
        "unknown_page_sources": unknown_page_sources,
        "page_artifacts": len(page_rows),
        "chunks": len(chunk_rows),
        "quarantine": len(quarantine_rows),
    }


def _quick_pdf_page_count(path: Path) -> int | None:
    try:
        import pypdfium2 as pdfium
    except Exception:
        return None
    try:
        pdf = pdfium.PdfDocument(str(path))
        try:
            return int(len(pdf))
        finally:
            pdf.close()
    except Exception:
        return None


def _summarize_pdf_manifest_queue(pdf_manifest: list[dict]) -> dict:
    total_pages = 0
    unknown_pages = 0
    for row in pdf_manifest:
        if not isinstance(row, dict):
            continue
        page_count = row.get("page_count")
        if page_count is None and row.get("path"):
            page_count = _quick_pdf_page_count(Path(str(row.get("path"))))
            if page_count is not None:
                row["page_count"] = int(page_count)
        if page_count is None:
            unknown_pages += 1
        else:
            total_pages += int(page_count or 0)
    return {"pdfs": len([row for row in pdf_manifest if isinstance(row, dict)]), "pages": total_pages, "unknown_pages": unknown_pages}


def _render_pdf_extraction_metrics(*, pdfs_done: int, pdfs_total: int, pages_done: int, pages_total: int | None, chunks: int, review: int) -> None:
    page_value = f"{pages_done:,}" if pages_total is None else f"{pages_done:,}/{pages_total:,}"
    render_metric_strip(
        [
            {"label": "PDFs Done", "value": f"{pdfs_done:,}/{pdfs_total:,}"},
            {"label": "Pages Done", "value": page_value},
            {"label": "Search Chunks", "value": f"{chunks:,}"},
            {"label": "Needs Review", "value": f"{review:,}"},
        ]
    )


def _pdf_extraction_status_path(site_root: Path) -> Path:
    return site_root / "sources" / "pdf_ingest" / "pdf_extraction_status.json"


def _read_pdf_extraction_status(site_root: Path) -> dict:
    status = read_json(_pdf_extraction_status_path(site_root), {})
    if not isinstance(status, dict):
        return {}
    if status.get("state") == "running" and status.get("pid") != os.getpid():
        status = dict(status)
        status["state"] = "interrupted"
        status["error"] = "Previous extraction worker is no longer attached to this app process."
    return status


def _write_pdf_extraction_status(site_root: Path, status: dict) -> None:
    status_path = _pdf_extraction_status_path(site_root)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(status_path, status)


def _pdf_upload_signature(uploaded_pdfs: list) -> str:
    parts = []
    for uploaded in uploaded_pdfs or []:
        parts.append(f"{getattr(uploaded, 'name', '')}:{getattr(uploaded, 'size', '')}")
    return "|".join(parts)


def _start_pdf_extraction_job(site_root: Path, pdf_manifest: list[dict]) -> dict:
    queue_summary = _summarize_pdf_manifest_queue(pdf_manifest)
    status = {
        "job_id": uuid.uuid4().hex,
        "pid": os.getpid(),
        "state": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "pdfs_total": queue_summary["pdfs"],
        "pdfs_done": 0,
        "pages_total": queue_summary["pages"] if not queue_summary["unknown_pages"] else None,
        "pages_done": 0,
        "chunks": 0,
        "review": 0,
        "raw_ready": 0,
        "page_artifacts": 0,
        "current_pdf": "",
        "error": "",
    }
    _write_pdf_extraction_status(site_root, status)

    manifest_snapshot = [dict(row) for row in pdf_manifest if isinstance(row, dict)]
    thread = threading.Thread(
        target=_run_pdf_extraction_job,
        args=(site_root, manifest_snapshot, status),
        daemon=True,
    )
    thread.start()
    return status


def _render_pdf_live_status_loop(site_root: Path, *, poll_seconds: float = 1.0, max_seconds: int = 60 * 60) -> None:
    metrics_slot = st.empty()
    message_slot = st.empty()
    started = time.monotonic()
    while True:
        status = _read_pdf_extraction_status(site_root)
        state = str(status.get("state") or "")
        with metrics_slot.container():
            _render_pdf_extraction_metrics(
                pdfs_done=int(status.get("pdfs_done") or 0),
                pdfs_total=int(status.get("pdfs_total") or 0),
                pages_done=int(status.get("pages_done") or 0),
                pages_total=status.get("pages_total"),
                chunks=int(status.get("chunks") or 0),
                review=int(status.get("review") or 0),
            )
        if state == "running":
            current_pdf = str(status.get("current_pdf") or "PDF")
            parser = str(status.get("parser") or "hybrid selector")
            reason = str(status.get("parser_reason") or "choosing best extractor")
            message_slot.info(f"Extracting {current_pdf} with {parser} ({reason})… live updates without page refresh.")
            if time.monotonic() - started > max_seconds:
                message_slot.warning("Extraction is still running in the background. You can leave this page and return later.")
                break
            time.sleep(poll_seconds)
            continue
        if state == "complete":
            message_slot.success(
                f"PDF extraction complete: {int(status.get('pages_done') or 0):,} page(s), "
                f"{int(status.get('chunks') or 0):,} search chunks, "
                f"{int(status.get('review') or 0):,} needing review."
            )
        elif state in {"failed", "parser_unavailable"}:
            message_slot.error(f"PDF extraction failed: {status.get('error') or 'unknown error'}")
        break


def _pdf_source_id(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:16]


def _chunk_pdf_text(source_id: str, page_number: int, text: str, *, chunk_size: int = 1200, overlap: int = 200) -> list[dict]:
    if not text:
        return []
    step = max(1, chunk_size - overlap)
    chunks = []
    for chunk_index, start in enumerate(range(0, len(text), step)):
        chunk_text = text[start : start + chunk_size]
        if not chunk_text.strip():
            continue
        digest = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()[:16]
        chunks.append(
            {
                "chunk_id": f"{source_id}-p{page_number:04d}-c{chunk_index:04d}-{digest}",
                "pdf_source_id": source_id,
                "page_number": page_number,
                "chunk_index": chunk_index,
                "text": chunk_text,
                "char_count": len(chunk_text),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "parser": "pypdfium2-pagewise",
                "source_path": "",
            }
        )
    return chunks


def _docling_pdf_result(path: Path, pages_dir: Path, status: dict, *, reason: str) -> dict:
    status["parser"] = "docling"
    status["parser_reason"] = reason
    status["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = ingest_pdfs([path], PdfIngestConfig(page_markdown_dir=pages_dir))
    sources = [row.to_dict() for row in result.sources]
    chunks = [row.to_dict() for row in result.chunks]
    quarantine = [row.to_dict() for row in result.quarantine]
    for source in sources:
        if source.get("accepted") and source.get("page_count") is not None:
            status["pages_done"] = int(status.get("pages_done") or 0) + int(source.get("page_count") or 0)
    status["chunks"] = int(status.get("chunks") or 0) + len(chunks)
    return {"sources": sources, "chunks": chunks, "quarantine": quarantine}


def _page_text_from_pdfium_page(page: object) -> str:
    textpage = page.get_textpage()
    return str(textpage.get_text_range() or "").strip()


def _pdf_text_strategy(pdf: object, *, max_sample_pages: int = 40) -> dict:
    page_count = int(len(pdf))
    if page_count <= 0:
        return {"strategy": "docling", "reason": "empty_pdf", "page_count": 0}
    sample_count = min(page_count, max_sample_pages)
    char_counts: list[int] = []
    table_like = 0
    for page_index in range(sample_count):
        page = pdf[page_index]
        try:
            text = _page_text_from_pdfium_page(page)
        finally:
            try:
                page.close()
            except Exception:
                pass
        meaningful = len(re.findall(r"[A-Za-z0-9]", text))
        char_counts.append(meaningful)
        lines = [line for line in text.splitlines() if line.strip()]
        multi_column_lines = len([line for line in lines if re.search(r"\S\s{3,}\S", line)])
        numeric_dense_lines = len([line for line in lines if len(re.findall(r"\d", line)) >= 8])
        if lines and (multi_column_lines / max(1, len(lines)) > 0.35 or numeric_dense_lines / max(1, len(lines)) > 0.45):
            table_like += 1
    text_coverage = len([count for count in char_counts if count >= 120]) / max(1, sample_count)
    avg_chars = sum(char_counts) / max(1, sample_count)
    table_like_ratio = table_like / max(1, sample_count)
    if text_coverage < 0.85:
        return {"strategy": "docling", "reason": f"low_text_coverage={text_coverage:.0%}", "page_count": page_count}
    if avg_chars < 500:
        return {"strategy": "docling", "reason": f"low_average_text={avg_chars:.0f}_chars", "page_count": page_count}
    if table_like_ratio > 0.40:
        return {"strategy": "docling", "reason": f"layout_table_heavy={table_like_ratio:.0%}", "page_count": page_count}
    return {"strategy": "pypdfium2-pagewise", "reason": f"text_heavy coverage={text_coverage:.0%} avg_chars={avg_chars:.0f}", "page_count": page_count}


def _extract_pdf_pagewise(path: Path, pages_dir: Path, site_root: Path, status: dict) -> dict:
    forced_mode = os.getenv("PDF_EXTRACTION_MODE", "hybrid").strip().lower()
    try:
        import pypdfium2 as pdfium
    except Exception:
        return _docling_pdf_result(path, pages_dir, status, reason="pypdfium2_unavailable")

    source_id = _pdf_source_id(path)
    now = datetime.now(timezone.utc).isoformat()
    if not path.exists() or not path.is_file():
        return {
            "sources": [{"pdf_source_id": source_id, "path": str(path), "size_bytes": 0, "page_count": None, "accepted": False, "created_at": now}],
            "chunks": [],
            "quarantine": [{"pdf_source_id": source_id, "path": str(path), "reason": "malformed", "detail": "File does not exist", "quarantined_at": now}],
        }

    if forced_mode == "docling":
        return _docling_pdf_result(path, pages_dir, status, reason="forced_docling")

    pdf = pdfium.PdfDocument(str(path))
    try:
        page_count = int(len(pdf))
        if forced_mode != "pagewise":
            strategy = _pdf_text_strategy(pdf)
            status["parser"] = str(strategy.get("strategy") or "")
            status["parser_reason"] = str(strategy.get("reason") or "")
            status["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_pdf_extraction_status(site_root, status)
            if strategy.get("strategy") == "docling":
                pdf.close()
                return _docling_pdf_result(path, pages_dir, status, reason=str(strategy.get("reason") or "hybrid_selected_docling"))
        else:
            status["parser"] = "pypdfium2-pagewise"
            status["parser_reason"] = "forced_pagewise"
            status["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_pdf_extraction_status(site_root, status)
        source_dir = pages_dir / source_id
        source_dir.mkdir(parents=True, exist_ok=True)
        index_rows = []
        chunks = []
        total_chars = 0
        for page_number in range(1, page_count + 1):
            page = pdf[page_number - 1]
            try:
                text = _page_text_from_pdfium_page(page)
            finally:
                try:
                    page.close()
                except Exception:
                    pass
            page_chunks = []
            if text:
                markdown = f"# Page {page_number}\n\n{text}\n"
                page_path = source_dir / f"page-{page_number:04d}.md"
                page_path.write_text(markdown, encoding="utf-8")
                index_rows.append(
                    {
                        "pdf_source_id": source_id,
                        "source_path": str(path),
                        "page_number": page_number,
                        "parser": "pypdfium2-pagewise",
                        "markdown_path": str(page_path),
                        "char_count": len(text),
                    }
                )
                page_chunks = _chunk_pdf_text(source_id, page_number, text)
                for chunk in page_chunks:
                    chunk["source_path"] = str(path)
                chunks.extend(page_chunks)
                total_chars += len(re.findall(r"[A-Za-z0-9]", text))
            status["pages_done"] = int(status.get("pages_done") or 0) + 1
            status["chunks"] = int(status.get("chunks") or 0) + len(page_chunks)
            status["page_artifacts"] = len(index_rows)
            status["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_pdf_extraction_status(site_root, status)
        if index_rows:
            (source_dir / "pages.json").write_text(json.dumps(index_rows, indent=2), encoding="utf-8")
        accepted = total_chars >= 80
        quarantine = [] if accepted else [{"pdf_source_id": source_id, "path": str(path), "reason": "low_text", "detail": f"meaningful_chars={total_chars} pages={page_count}", "quarantined_at": datetime.now(timezone.utc).isoformat()}]
        return {
            "sources": [{"pdf_source_id": source_id, "path": str(path), "size_bytes": int(path.stat().st_size), "page_count": page_count, "accepted": accepted, "created_at": now}],
            "chunks": chunks if accepted else [],
            "quarantine": quarantine,
        }
    finally:
        pdf.close()


def _run_pdf_extraction_job(site_root: Path, pdf_manifest: list[dict], status: dict) -> None:
    out_dir = site_root / "sources" / "pdf_ingest"
    pages_dir = site_root / "sources" / "pdf_pages"
    try:
        for row in pdf_manifest:
            path = Path(str(row.get("path") or ""))
            status["current_pdf"] = str(row.get("name") or path.name)
            status["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_pdf_extraction_status(site_root, status)

            result = _extract_pdf_pagewise(path, pages_dir, site_root, status)
            _merge_jsonl_rows_app(out_dir / "pdf_sources.jsonl", result["sources"], key="pdf_source_id")
            _merge_jsonl_rows_app(out_dir / "pdf_chunks.jsonl", result["chunks"], key="chunk_id")
            _merge_jsonl_rows_app(out_dir / "pdf_quarantine.jsonl", result["quarantine"], key="pdf_source_id")

            status["pdfs_done"] = int(status.get("pdfs_done") or 0) + 1
            status["review"] = int(status.get("review") or 0) + len(result["quarantine"])
            status["page_artifacts"] = _count_pdf_page_artifacts(pages_dir)
            status["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_pdf_extraction_status(site_root, status)

        normalization_report = normalize_pdf_pages(site_root)
        status["raw_ready"] = int(normalization_report.counts.get("ready", 0))
        status["state"] = "complete"
        status["current_pdf"] = ""
        status["completed_at"] = datetime.now(timezone.utc).isoformat()
        status["updated_at"] = status["completed_at"]
        _write_pdf_extraction_status(site_root, status)
    except PdfParserUnavailableError as exc:
        status["state"] = "parser_unavailable"
        status["error"] = str(exc)
        status["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_pdf_extraction_status(site_root, status)
    except Exception as exc:
        status["state"] = "failed"
        status["error"] = str(exc)
        status["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_pdf_extraction_status(site_root, status)


def _selected_url_strings_from_state() -> list[str]:
    selected_rows = st.session_state.get("selected_df", pd.DataFrame())
    if isinstance(selected_rows, pd.DataFrame) and not selected_rows.empty:
        if "selected" in selected_rows.columns:
            selected_url_rows = selected_rows[selected_rows["selected"] == True]  # noqa: E712
        else:
            selected_url_rows = selected_rows
        selected_url_strings = selected_url_rows.get("url", pd.Series(dtype=str)).dropna().astype(str).tolist()
    else:
        selected_url_strings = []
    return [url for url in selected_url_strings if url.strip()]


def _source_next_action(*, selected_url_count: int, pdf_count: int, run_state: str, raw_ready: bool) -> str:
    if run_state in {"paused", "pausing"}:
        return "Open Runs to continue the scrape"
    if run_state in {"running", "initializing"}:
        return "Open Runs to monitor the scrape"
    if selected_url_count > 0 and run_state in {"none", "ready", "completed", "cancelled", "failed"}:
        return "Open Runs to scrape selected URLs"
    if pdf_count > 0 and not raw_ready:
        return "Prepare sources"
    return "Add sources"


def _discovered_json_path(site_id: str) -> Path:
    return _app_context().site_artifacts.discovered_path(site_id)


def _to_discovered_rows(items: list[DiscoveredURL]) -> list[dict]:
    return [item.to_dict() for item in items]


DISCOVERED_URL_FIELDS = {
    "url",
    "source_sitemap",
    "lastmod",
    "path_category",
    "content_type_guess",
    "excluded_reason",
    "selected",
}


def _rows_to_discovered_urls(rows: list[dict]) -> list[DiscoveredURL]:
    selected_items: list[DiscoveredURL] = []
    for row in rows:
        if not bool(row.get("selected", False)):
            continue
        cleaned = {key: row.get(key) for key in DISCOVERED_URL_FIELDS if key in row}
        cleaned["selected"] = True
        selected_items.append(DiscoveredURL(**cleaned))
    return selected_items


def _render_paginated_df(df: pd.DataFrame, *, key_prefix: str, default_page_size: int = 100) -> None:
    if df.empty:
        st.info("No rows to display.")
        return
    c1, c2 = st.columns([1, 1])
    page_size = c1.selectbox("Page size", options=[25, 50, 100, 200, 500], index=[25, 50, 100, 200, 500].index(default_page_size) if default_page_size in [25, 50, 100, 200, 500] else 2, key=f"{key_prefix}_page_size")
    total_rows = len(df)
    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    page = c2.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1, key=f"{key_prefix}_page")
    start = (int(page) - 1) * int(page_size)
    end = start + int(page_size)
    st.caption(f"Showing rows {start + 1}-{min(end, total_rows)} of {total_rows}")
    st.dataframe(df.iloc[start:end], use_container_width=True)


def _load_app_state() -> dict:
    return _app_context().app_state.load()


def _app_state_payload() -> dict:
    return {
        "active_workspace_id": st.session_state.get("active_workspace_id", ""),
        "workspaces": st.session_state.get("workspaces", []),
        "last_site_url": st.session_state.get("site_url", ""),
        "last_site_id": st.session_state.get("site_id", ""),
        "last_run_id": st.session_state.get("run_id", ""),
        "last_run_by_site": st.session_state.get("last_run_by_site", {}),
        "manual_urls": st.session_state.get("manual_urls", ""),
        "ollama_model": st.session_state.get("ollama_model", ""),
        "llm_provider": st.session_state.get("llm_provider", "openrouter"),
        "ollama_base_url": st.session_state.get("ollama_base_url", OLLAMA_BASE_URL),
        "scrape_browser_mode": st.session_state.get("scrape_browser_mode", "none"),
        "lightpanda_cdp_url": st.session_state.get("lightpanda_cdp_url", ""),
        "site_history": st.session_state.get("site_history", []),
        "tavily_api_key": st.session_state.get("tavily_api_key", ""),
        "default_or_model": st.session_state.get("default_or_model", "deepseek/deepseek-v4-flash"),
        "default_llm_cap": int(st.session_state.get("default_llm_cap", 150)),
        "default_llm_batch_size": int(st.session_state.get("default_llm_batch_size", 250)),
        "default_llm_sleep_sec": float(st.session_state.get("default_llm_sleep_sec", 0.0)),
        "url_reasoning_provider": st.session_state.get("url_reasoning_provider", "openrouter"),
        "url_reasoning_openrouter_model": st.session_state.get("url_reasoning_openrouter_model", "deepseek/deepseek-v4-flash"),
        "url_reasoning_ollama_model": st.session_state.get("url_reasoning_ollama_model", "qwen2.5:3b"),
        "graph_enrichment_provider": st.session_state.get("graph_enrichment_provider", "openrouter"),
        "graph_enrichment_openrouter_model": st.session_state.get("graph_enrichment_openrouter_model", "openai/gpt-4.1-mini"),
        "graph_enrichment_ollama_model": st.session_state.get("graph_enrichment_ollama_model", "qwen2.5:3b"),
        "graph_answer_provider": st.session_state.get("graph_answer_provider", "openrouter"),
        "graph_answer_openrouter_model": st.session_state.get("graph_answer_openrouter_model", "deepseek/deepseek-v4-flash"),
        "graph_answer_ollama_model": st.session_state.get("graph_answer_ollama_model", "qwen2.5:3b"),
        "scrape_concurrency": int(st.session_state.get("scrape_concurrency", 10)),
        "embedding_enabled": bool(st.session_state.get("embedding_enabled", True)),
        "embedding_model": st.session_state.get("embedding_model", "nomic-embed-text:latest"),
        "zvec_enabled": bool(st.session_state.get("zvec_enabled", True)),
        "zvec_index_path": st.session_state.get("zvec_index_path", ""),
        "zvec_collection": st.session_state.get("zvec_collection", "university_wiki"),
        "use_tavily_for_map": bool(st.session_state.get("use_tavily_for_map", False)),
        "tavily_cost_per_call_usd": float(st.session_state.get("tavily_cost_per_call_usd", 0.0)),
        "ollama_input_per_m_usd": float(st.session_state.get("ollama_input_per_m_usd", 0.0)),
        "ollama_output_per_m_usd": float(st.session_state.get("ollama_output_per_m_usd", 0.0)),
    }


def _save_app_state() -> None:
    _app_context().app_state.save(_app_state_payload())


def _load_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, val = stripped.split("=", 1)
        data[key.strip()] = val.strip().strip('"').strip("'")
    return data


def _hydrate_site_workspace(site_id: str) -> None:
    if not site_id:
        return
    rows = _app_context().site_artifacts.load_discovered_rows(site_id)
    if rows:
        st.session_state["discovered"] = rows
        st.session_state["selected_df"] = pd.DataFrame(rows)
    elif st.session_state.get("discovered"):
        st.session_state["discovered"] = []
        st.session_state["selected_df"] = pd.DataFrame()


def _site_run_ids(site_id: str) -> list[str]:
    if not site_id:
        return []
    site_root = DATA_ROOT / "sites" / site_id
    if not site_root.exists():
        return []
    return sorted([d.name for d in site_root.iterdir() if d.is_dir() and d.name != "meta"])


def _run_human_timestamp(run_id: str) -> str:
    value = str(run_id or "").strip()
    if not value:
        return "unknown"
    stem = value.split("-", 1)[0]
    try:
        dt = datetime.strptime(stem, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return value


def _is_real_scrape_run(site_id: str, run_id: str) -> bool:
    if not site_id or not run_id:
        return False
    if run_id.startswith("pi_url_"):
        return False
    run_root = _run_root(site_id, run_id)
    scrape_markers = [
        "selected_urls.json",
        "scrape_manifest.json",
        "run_status.json",
        "pages.jsonl",
        "events.jsonl",
        "failures.json",
    ]
    return any((run_root / marker).exists() for marker in scrape_markers)


def _resolve_active_run_id(site_id: str, current_run_id: str) -> str:
    run_ids = _site_run_ids(site_id)
    if not run_ids:
        return ""
    if current_run_id and current_run_id in run_ids:
        return current_run_id
    real_runs = [rid for rid in run_ids if _is_real_scrape_run(site_id, rid)]
    if real_runs:
        return real_runs[-1]
    return run_ids[-1]


def _load_markdown_preview(markdown_path: str, max_chars: int = 16000) -> str:
    path = Path(str(markdown_path or ""))
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:max_chars]


def _chunk_section_path(row: dict) -> list[str]:
    raw_section = row.get("section_path") or row.get("sections") or row.get("section") or []
    if isinstance(raw_section, str):
        return [part.strip() for part in re.split(r"\s*(?:>|/|::)\s*", raw_section) if part.strip()]
    if isinstance(raw_section, (list, tuple)):
        return [str(part).strip() for part in raw_section if str(part).strip()]
    return []


def _chunk_source_title(row: dict) -> str:
    title = str(row.get("source_title") or row.get("title") or "").strip()
    if title:
        return title
    source_path = str(row.get("source_path") or "").strip()
    if source_path:
        return Path(source_path).stem or source_path
    return "Untitled source"


def _chunk_source_location(row: dict) -> str:
    url = str(row.get("url") or row.get("source_url") or row.get("original_url") or "").strip()
    if url:
        return url
    source_path = str(row.get("source_path") or row.get("markdown_path") or "").strip()
    page_number = row.get("page_number")
    if page_number not in (None, "") and source_path:
        return f"Page {page_number} - {source_path}"
    if page_number not in (None, ""):
        return f"Page {page_number}"
    return source_path or "n/a"


if hasattr(st, "dialog"):
    @st.dialog("Page Markdown Preview")
    def _open_page_markdown_dialog(markdown_path: str) -> None:
        st.caption(f"`{markdown_path}`")
        preview_text = _load_markdown_preview(markdown_path)
        if preview_text:
            st.markdown(preview_text)
        else:
            st.warning("Could not load markdown preview from this path.")


def _save_env_key(path: Path, key: str, value: str) -> None:
    existing = []
    if path.exists():
        existing = path.read_text(encoding="utf-8").splitlines()
    updated = []
    found = False
    for line in existing:
        if line.strip().startswith(f"{key}="):
            updated.append(f"{key}={value}")
            found = True
        else:
            updated.append(line)
    if not found:
        updated.append(f"{key}={value}")
    path.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")


def _normalize_ollama_base_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "http://localhost:11434"
    cleaned = raw.rstrip("/")
    # Users often paste endpoint paths; keep only the API host base.
    for suffix in ("/api/generate", "/api/chat", "/api/tags", "/api/pull", "/api"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    return cleaned.rstrip("/") or "http://localhost:11434"


def _detect_reachable_ollama_url(current_value: str) -> str:
    candidates = [
        _normalize_ollama_base_url(current_value),
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://[::1]:11434",
        "http://host.docker.internal:11434",
    ]
    seen: set[str] = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        if _ollama_available(url):
            return url
    return _normalize_ollama_base_url(current_value)


def _ollama_available(base_url: str = "http://localhost:11434") -> bool:
    try:
        response = requests.get(f"{_normalize_ollama_base_url(base_url)}/api/tags", timeout=0.75)
        return response.status_code == 200
    except Exception:
        return False


PROVIDERS = ["openrouter", "ollama", "tavily"]


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _event_cost_usd(
    event: dict,
    *,
    model_map: dict,
    tavily_per_call: float,
    ollama_in_per_m: float,
    ollama_out_per_m: float,
) -> float:
    provider = str(event.get("provider") or "")
    operation = str(event.get("operation") or "")
    status = str(event.get("status") or "")
    prompt_tokens = _safe_float(event.get("prompt_tokens"), 0.0)
    completion_tokens = _safe_float(event.get("completion_tokens"), 0.0)
    if provider == "openrouter":
        if operation == "select_urls_summary":
            return 0.0
        model = event.get("model")
        row = model_map.get(model, {}) if model else {}
        pp = _safe_float(row.get("prompt_price"), 0.0)
        cp = _safe_float(row.get("completion_price"), 0.0)
        return (pp * prompt_tokens) + (cp * completion_tokens)
    if provider == "tavily":
        return tavily_per_call if status == "success" else 0.0
    if provider == "ollama":
        return (ollama_in_per_m * (prompt_tokens / 1_000_000.0)) + (ollama_out_per_m * (completion_tokens / 1_000_000.0))
    return 0.0


def _build_trace_df(
    *,
    run_events: list[dict],
    site_events: list[dict],
    model_map: dict,
    tavily_per_call: float,
    ollama_in_per_m: float,
    ollama_out_per_m: float,
) -> pd.DataFrame:
    rows = []
    for source, events in [("run", run_events), ("site_meta", site_events)]:
        for event in events:
            row = dict(event)
            row["source"] = source
            row["provider"] = str(row.get("provider") or "unknown")
            row["status"] = str(row.get("status") or "unknown")
            row["operation"] = str(row.get("operation") or "unknown")
            row["prompt_tokens"] = _safe_float(row.get("prompt_tokens"), 0.0)
            row["completion_tokens"] = _safe_float(row.get("completion_tokens"), 0.0)
            row["total_tokens"] = _safe_float(row.get("total_tokens"), row["prompt_tokens"] + row["completion_tokens"])
            row["latency_ms"] = _safe_float(row.get("latency_ms"), float("nan"))
            row["cost_usd"] = _event_cost_usd(
                row,
                model_map=model_map,
                tavily_per_call=tavily_per_call,
                ollama_in_per_m=ollama_in_per_m,
                ollama_out_per_m=ollama_out_per_m,
            )
            row["is_summary"] = bool(row["provider"] == "openrouter" and row["operation"] == "select_urls_summary")
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["ts_dt"] = pd.to_datetime(df.get("ts"), errors="coerce", utc=True)
    df = df.sort_values("ts_dt", ascending=False, na_position="last").reset_index(drop=True)
    df["api_call_id"] = [f"call_{idx + 1:05d}" for idx in range(len(df))]
    return df


def _schedule_live_refresh(*, key: str, enabled: bool, active: bool, interval_seconds: float = 1.0) -> None:
    if not enabled or not active:
        return
    if st_autorefresh is not None:
        st_autorefresh(interval=max(250, int(interval_seconds * 1000)), key=key)


def _tail_text(path: Path, max_lines: int = 120) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    if not lines:
        return ""
    return "\n".join(lines[-max_lines:])


def _shorten_middle(text: object, *, max_chars: int = 86) -> str:
    value = str(text or "").strip()
    if len(value) <= max_chars:
        return value
    head = max(12, (max_chars - 1) // 2)
    tail = max(8, max_chars - head - 1)
    return f"{value[:head].rstrip()}…{value[-tail:].lstrip()}"


def _format_document_title(title: object) -> str:
    value = str(title or "Untitled source").strip()
    value = re.sub(r"\.pdf\s+p\.\s*(\d+)", r".pdf — page \1", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value)
    return value or "Untitled source"


def _looks_like_url(value: object) -> bool:
    return str(value or "").strip().lower().startswith(("http://", "https://"))


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _widget_key_token(value: object) -> str:
    token = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "item").lower()).strip("_")
    return token[:96] or "item"


def _url_path_segments(value: object) -> list[str]:
    source = str(value or "").strip()
    if not _looks_like_url(source):
        return []
    parsed = urlparse(source)
    path = unquote(parsed.path or "").strip("/")
    return [segment for segment in path.split("/") if segment]


def _url_path_label(value: object, *, max_chars: int = 96) -> str:
    source = str(value or "").strip()
    if not source:
        return "No source path"
    if _looks_like_url(source):
        parsed = urlparse(source)
        path = unquote(parsed.path or "").strip("/")
        label = f"/{path}" if path else "/"
        query = unquote(parsed.query or "").strip()
        if query:
            label = f"{label}?{query}"
        return _shorten_middle(label, max_chars=max_chars)
    return _shorten_middle(Path(source).name or source, max_chars=max_chars)


def _web_path_category(source: object) -> tuple[str, str]:
    segments = _url_path_segments(source)
    if not segments:
        return "web:/", "Home"
    group_path = f"/{segments[0]}"
    return f"web:{group_path.lower()}", group_path


def _pdf_document_label(row: dict) -> str:
    source = str(row.get("original_path") or row.get("source_path") or row.get("url_or_path") or "").strip()
    name = ""
    if source:
        if _looks_like_url(source):
            name = Path(unquote(urlparse(source).path or "")).name
        else:
            name = Path(source).name
    if not name:
        name = _format_document_title(row.get("title"))
        name = re.sub(r"\s+—\s+page\s+\d+.*$", "", name, flags=re.IGNORECASE).strip()
        name = re.sub(r"\s+p\.\s*\d+.*$", "", name, flags=re.IGNORECASE).strip()
    return name or "Uploaded PDF"


def _document_page_number(row: dict) -> int:
    for key in ("page_number", "raw_page_number"):
        page_number = _coerce_int(row.get(key), 0)
        if page_number:
            return page_number
    match = re.search(r"(?:page|p\.)\s*(\d+)", str(row.get("title") or ""), flags=re.IGNORECASE)
    return _coerce_int(match.group(1), 0) if match else 0


def _document_row_display_fields(row: dict) -> dict[str, object]:
    kind = str(row.get("kind") or row.get("source_kind") or "unknown").lower()
    source = str(row.get("original_url") or row.get("url_or_path") or row.get("original_path") or row.get("source_path") or "")
    source_id = str(row.get("source_id") or "")
    if kind == "web":
        category_key, category_label = _web_path_category(source)
        display_path = _url_path_label(source, max_chars=128)
        return {
            "category_key": category_key,
            "category_label": category_label,
            "collection_label": category_label,
            "display_path": display_path,
            "sort_path": display_path.lower(),
        }
    if kind == "pdf":
        document_label = _pdf_document_label(row)
        pdf_source_id = str(row.get("pdf_source_id") or "")
        source_identity = hashlib.sha1(source.lower().encode("utf-8")).hexdigest()[:12] if source else ""
        category_identity = pdf_source_id or source_identity or document_label.lower()
        category_key = f"pdf:{category_identity}"
        page_number = _document_page_number(row)
        display_path = f"{document_label} · page {page_number}" if page_number else document_label
        return {
            "category_key": category_key,
            "category_label": document_label,
            "collection_label": document_label,
            "display_path": display_path,
            "sort_path": f"{document_label.lower()}::{page_number:08d}::{source_id}",
        }
    display_path = _url_path_label(source or row.get("title"), max_chars=128)
    category_label = display_path or "Other documents"
    return {
        "category_key": f"other:{category_label.lower()}",
        "category_label": category_label,
        "collection_label": category_label,
        "display_path": display_path,
        "sort_path": display_path.lower(),
    }


def _compact_source_rows(rows: list[dict], layout) -> list[dict]:
    del layout
    compact_rows: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
        markdown_path = str(row.get("markdown_path") or "").strip()
        title = str(row.get("title") or row.get("source_id") or "Untitled source")
        original_url = str(row.get("original_url") or "").strip()
        original_path = str(row.get("original_path") or row.get("source_path") or row.get("path") or "").strip()
        source_path = str(row.get("source_path") or row.get("path") or original_path).strip()
        compact_row = {
            "kind": str(row.get("source_kind") or "unknown").lower(),
            "status": str(row.get("status") or "unknown"),
            "title": title,
            "url_or_path": str(original_url or original_path or source_path),
            "original_url": original_url,
            "original_path": original_path,
            "source_path": source_path,
            "markdown": markdown_path,
            "source_id": str(row.get("source_id") or ""),
            "pdf_source_id": str(provenance.get("pdf_source_id") or row.get("pdf_source_id") or ""),
            "page_number": _coerce_int(provenance.get("raw_page_number") or provenance.get("page_number") or row.get("page_number"), 0),
            "part_index": _coerce_int(provenance.get("part_index") or row.get("part_index"), 0),
        }
        compact_row.update(_document_row_display_fields(compact_row))
        compact_rows.append(compact_row)
    return _disambiguate_pdf_document_labels(compact_rows)


def _pdf_document_hint(row: dict) -> str:
    token = str(row.get("pdf_source_id") or row.get("source_id") or "").replace("pdf_", "")
    if token:
        return token[:8]
    source = str(row.get("original_path") or row.get("source_path") or row.get("url_or_path") or "").strip()
    if source:
        source_path = unquote(urlparse(source).path or "") if _looks_like_url(source) else source
        parent = Path(source_path).parent.name
        parent_label = _document_index_label(parent)
        if parent_label and parent_label not in {".", "/"}:
            return parent_label
    return ""


def _disambiguate_pdf_document_labels(compact_rows: list[dict]) -> list[dict]:
    label_to_keys: dict[str, set[str]] = {}
    key_to_rows: dict[str, list[dict]] = {}
    for row in compact_rows:
        if row.get("kind") != "pdf":
            continue
        base_label = str(row.get("collection_label") or row.get("category_label") or "Uploaded PDF")
        category_key = str(row.get("category_key") or base_label.lower())
        label_to_keys.setdefault(base_label.lower(), set()).add(category_key)
        key_to_rows.setdefault(category_key, []).append(row)

    duplicate_keys = {
        category_key
        for keys in label_to_keys.values()
        if len(keys) > 1
        for category_key in keys
    }
    for category_key in duplicate_keys:
        rows = key_to_rows.get(category_key) or []
        if not rows:
            continue
        first = rows[0]
        base_label = str(first.get("collection_label") or first.get("category_label") or "Uploaded PDF")
        hint = _pdf_document_hint(first)
        display_label = f"{base_label} · {hint}" if hint and hint.lower() not in base_label.lower() else base_label
        for row in rows:
            row["category_label"] = display_label
            page_number = _document_page_number(row)
            row["display_path"] = f"{display_label} · page {page_number}" if page_number else display_label
            row["sort_path"] = f"{display_label.lower()}::{page_number:08d}::{row.get('source_id') or ''}"
    return compact_rows


def _source_website_label(row: dict) -> str:
    source = str(row.get("url_or_path") or "").strip()
    if _looks_like_url(source):
        parsed = urlparse(source)
        return parsed.netloc or source
    if source:
        return Path(source).name or source
    return "Uploaded document"


def _documents_for_group(docs_df: pd.DataFrame, source_group: str) -> pd.DataFrame:
    if source_group == "Scraped URLs":
        return docs_df[docs_df["kind"] == "web"].copy()
    if source_group == "PDF pages":
        return docs_df[docs_df["kind"] == "pdf"].copy()
    return docs_df[~docs_df["kind"].isin(["web", "pdf"])].copy()


def _document_category_axis_label(source_group: str) -> str:
    if source_group == "Scraped URLs":
        return "Section"
    if source_group == "PDF pages":
        return "PDF document"
    return "Source"


def _document_all_category_label(source_group: str) -> str:
    if source_group == "Scraped URLs":
        return "All sections"
    if source_group == "PDF pages":
        return "All PDF pages"
    return "All sources"


def _document_category_records(group_docs: pd.DataFrame) -> list[dict]:
    if group_docs.empty or "category_key" not in group_docs.columns:
        return []
    records: list[dict] = []
    for category_key, frame in group_docs.groupby("category_key", sort=True, dropna=False):
        if frame.empty:
            continue
        first = frame.iloc[0]
        label = str(first.get("category_label") or category_key or "Uncategorized")
        records.append({"key": str(category_key), "label": label, "count": int(len(frame))})
    return sorted(records, key=lambda item: str(item["label"]).lower())


def _document_category_display_label(label: object, source_group: str) -> str:
    value = str(label or "Uncategorized").strip()
    if source_group == "Scraped URLs":
        return _document_index_label(value) or "Home"
    return value or "Uncategorized"


def _document_search_label(source_group: str) -> str:
    if source_group == "Scraped URLs":
        return "Search scraped URLs"
    if source_group == "PDF pages":
        return "Search PDF pages"
    return "Search sources"


def _document_search_placeholder(source_group: str) -> str:
    if source_group == "Scraped URLs":
        return "Title, URL path, or section"
    if source_group == "PDF pages":
        return "Document, page number, or source id"
    return "Title, path, or source id"


def _document_search_blob(row: pd.Series, source_group: str) -> str:
    field_names = [
        "title",
        "display_path",
        "category_label",
        "collection_label",
        "url_or_path",
        "original_url",
        "original_path",
        "source_path",
        "markdown",
        "source_id",
        "pdf_source_id",
        "page_number",
    ]
    values = [str(row.get(field) or "") for field in field_names]
    if source_group == "Scraped URLs":
        segments = _url_path_segments(row.get("url_or_path"))
        values.extend(segments)
        values.extend(_document_index_label(segment) for segment in segments)
    elif source_group == "PDF pages":
        page_number = _coerce_int(row.get("page_number"), 0)
        if page_number:
            values.extend([f"page {page_number}", f"p {page_number}"])
    return " ".join(value for value in values if value).lower()


def _filter_document_rows_by_search(visible_docs: pd.DataFrame, query: str, source_group: str) -> pd.DataFrame:
    tokens = [token.lower() for token in re.split(r"\s+", query.strip()) if token.strip()]
    if visible_docs.empty or not tokens:
        return visible_docs
    searchable = visible_docs.apply(lambda row: _document_search_blob(row, source_group), axis=1)
    mask = pd.Series(True, index=visible_docs.index)
    for token in tokens:
        mask = mask & searchable.str.contains(re.escape(token), case=False, na=False, regex=True)
    return visible_docs[mask]


def _document_category_selector(group_docs: pd.DataFrame, *, source_group: str) -> str:
    records = _document_category_records(group_docs)
    total_count = int(len(group_docs))
    all_key = "__all__"
    options = [all_key] + [record["key"] for record in records]
    labels = {all_key: f"{_document_all_category_label(source_group)} ({total_count:,})"}
    labels.update(
        {
            record["key"]: f"{_document_category_display_label(record['label'], source_group)} ({record['count']:,})"
            for record in records
        }
    )
    widget_key = f"documents_category_{_widget_key_token(source_group)}"
    if st.session_state.get(widget_key) not in options:
        st.session_state[widget_key] = all_key
    selected = st.selectbox(
        _document_category_axis_label(source_group),
        options=options,
        format_func=lambda value: labels.get(str(value), str(value)),
        key=widget_key,
        disabled=len(records) <= 1,
    )
    return str(selected or all_key)


def _sort_document_rows(visible_docs: pd.DataFrame) -> pd.DataFrame:
    if visible_docs.empty:
        return visible_docs
    sortable = visible_docs.copy()
    for column in ("category_label", "sort_path", "display_path", "title", "source_id"):
        if column not in sortable.columns:
            sortable[column] = ""
    if "page_number" in sortable.columns:
        sortable["_page_sort"] = pd.to_numeric(sortable["page_number"], errors="coerce").fillna(0).astype(int)
    else:
        sortable["_page_sort"] = 0
    return sortable.sort_values(
        ["category_label", "_page_sort", "sort_path", "title", "source_id"],
        ascending=[True, True, True, True, True],
        kind="stable",
    ).drop(columns=["_page_sort"], errors="ignore")


def _document_index_label(value: object) -> str:
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


def _document_web_index_title(row: dict) -> str:
    title = _document_index_label(row.get("title"))
    if title and not title.lower().startswith("web "):
        return title
    segments = _url_path_segments(row.get("url_or_path"))
    if not segments:
        return "Home"
    return _document_index_label(segments[-1]) or segments[-1]


def _document_source_title(row: dict, source_group: str) -> str:
    if source_group == "Scraped URLs":
        return _shorten_middle(_document_web_index_title(row), max_chars=58)
    if source_group == "PDF pages":
        page_number = _document_page_number(row)
        part_index = _coerce_int(row.get("part_index"), 0)
        title = f"Page {page_number}" if page_number else _format_document_title(row.get("title"))
        if part_index:
            title = f"{title} · part {part_index}"
        return _shorten_middle(title, max_chars=58)
    return _shorten_middle(_format_document_title(row.get("title")), max_chars=58)


def _document_source_subtitle(row: dict, source_group: str) -> str:
    status = str(row.get("status") or "unknown").replace("-", " ")
    status_note = "" if status == "ready" else status
    if source_group == "Scraped URLs":
        return status_note
    if source_group == "PDF pages":
        part_index = _coerce_int(row.get("part_index"), 0)
        notes = [f"part {part_index}"] if part_index else []
        if status_note:
            notes.append(status_note)
        return " · ".join(notes)
    return status_note


def _mark_source_index_loading(selected_key: str, loading_key: str, item_id: str) -> None:
    st.session_state[selected_key] = item_id
    st.session_state[loading_key] = item_id


def _source_index_picker(
    records: list[dict],
    *,
    group_token: str,
    selected_key: str,
    loading_key: str,
    item_id_func,
    title_func,
    category_func,
    subtitle_func=None,
    max_items: int = 220,
    default_id: str | None = None,
    overflow_hint: str = "Refine by section or search.",
) -> dict | None:
    if not records:
        return None
    rendered_records = records[:max_items]
    valid_ids = [str(item_id_func(row, idx) or idx) for idx, row in enumerate(rendered_records)]
    if st.session_state.get(selected_key) not in valid_ids:
        st.session_state[selected_key] = default_id if default_id in valid_ids else valid_ids[0]

    if len(records) > len(rendered_records):
        st.caption(f"Showing first {len(rendered_records):,} of {len(records):,}. {overflow_hint}")
    with st.container(height=620, border=False, key=f"source_index_list_{group_token}"):
        last_category = ""
        for idx, row in enumerate(rendered_records):
            item_id = valid_ids[idx]
            category_label = str(category_func(row) or "")
            if category_label and category_label != last_category:
                st.markdown(f'<div class="document-index-section">{escape(category_label)}</div>', unsafe_allow_html=True)
                last_category = category_label
            title = str(title_func(row) or "Untitled")
            subtitle = str(subtitle_func(row) or "") if subtitle_func else ""
            selected = item_id == st.session_state.get(selected_key)
            card_state = "selected" if selected else "item"
            with st.container(
                border=False,
                key=f"source_index_card_{card_state}_{group_token}_{_widget_key_token(item_id)}_{idx}",
            ):
                st.button(
                    title,
                    key=f"source_index_button_{group_token}_{_widget_key_token(item_id)}_{idx}",
                    use_container_width=True,
                    type="primary" if selected else "secondary",
                    on_click=_mark_source_index_loading,
                    args=(selected_key, loading_key, item_id),
                )
                if subtitle:
                    st.markdown(
                        f'<div class="document-index-note">{escape(_shorten_middle(subtitle, max_chars=72))}</div>',
                        unsafe_allow_html=True,
                    )
    selected_id = str(st.session_state.get(selected_key) or valid_ids[0])
    selected_index = valid_ids.index(selected_id) if selected_id in valid_ids else 0
    return rendered_records[selected_index]


def _document_source_picker(visible_docs: pd.DataFrame, *, source_group: str, max_cards: int = 220) -> dict | None:
    visible_docs = _sort_document_rows(visible_docs)
    all_records = visible_docs.to_dict("records")
    group_token = _widget_key_token(source_group)
    return _source_index_picker(
        all_records,
        group_token=f"documents_{group_token}",
        selected_key=f"documents_selected_source_{group_token}",
        loading_key=f"documents_loading_source_{group_token}",
        item_id_func=lambda row, idx: str(row.get("source_id") or idx),
        title_func=lambda row: _document_source_title(row, source_group),
        category_func=lambda row: _document_category_display_label(str(row.get("category_label") or ""), source_group),
        subtitle_func=lambda row: _document_source_subtitle(row, source_group),
        max_items=max_cards,
    )


def _render_markdown_preview(markdown_text: str, title: object = "Preview", *, source_label: object = "") -> None:
    if source_label:
        st.caption(f"Source: {_shorten_middle(source_label, max_chars=120)}")
    st.markdown(f"#### {_format_document_title(title)}")
    with st.container(border=True, key="documents_markdown_preview"):
        st.markdown(markdown_text or "_No markdown content was extracted._")


def _read_source_markdown(layout, markdown_path: str, *, max_chars: int | None = None) -> tuple[str, str]:
    if not markdown_path:
        return "", "No markdown path is recorded for this source."
    candidate = Path(markdown_path)
    if not candidate.is_absolute():
        candidate = layout.site_root / markdown_path
    try:
        resolved = candidate.resolve()
        resolved.relative_to(layout.site_root.resolve())
    except ValueError:
        return "", "Source markdown path is outside this workspace."
    if not resolved.exists() or not resolved.is_file():
        return "", "Source markdown file was not found."
    text = resolved.read_text(encoding="utf-8", errors="replace")
    return (text[:max_chars] if max_chars is not None else text), ""


def _wiki_markdown_picker(records: list[dict], *, max_cards: int = 220) -> dict | None:
    return _source_index_picker(
        records,
        group_token="wiki_markdown",
        selected_key="wiki_markdown_file_browser",
        loading_key="wiki_loading_markdown_file",
        item_id_func=lambda row, idx: str(row.get("path") or idx),
        title_func=lambda row: str(row.get("title") or row.get("path") or "Untitled"),
        category_func=lambda row: str(row.get("category") or "Overview"),
        max_items=max_cards,
        default_id="index.md",
        overflow_hint="Refine by section or search.",
    )


WIKI_FILE_QUERY_VIEW = {"view": "wiki_file"}


def _apply_wiki_file_query_state() -> None:
    if str(st.query_params.get("view", "") or "").strip() != WIKI_FILE_QUERY_VIEW["view"]:
        return
    rel_path = _safe_wiki_markdown_rel_path(st.query_params.get("wiki_file", ""))
    if not rel_path:
        return
    site_id = str(st.query_params.get("site_id", "") or "").strip()
    if site_id and is_safe_route_part(site_id):
        workspace = next((w for w in st.session_state.get("workspaces", []) if w.get("id") == site_id), None)
        st.session_state["active_workspace_id"] = site_id
        st.session_state["site_id"] = site_id
        if workspace:
            st.session_state["site_url"] = workspace.get("url", st.session_state.get("site_url", ""))
    query_key = f"{site_id}:{rel_path}"
    if st.session_state.get("_last_wiki_file_query") == query_key:
        return
    st.session_state["workflow_active_tab"] = WORKFLOW_TABS[4]
    st.session_state["wiki_markdown_file_browser"] = rel_path
    st.session_state["wiki_loading_markdown_file"] = rel_path
    st.session_state["_last_wiki_file_query"] = query_key


def _load_run_analytics_inputs(site_id: str, run_id: str, run_root: Path) -> tuple[list[dict], list[dict], dict, list[dict]]:
    pages: list[dict] = []
    seen_urls: set[str] = set()

    def _merge_rows(rows: list[dict]) -> None:
        nonlocal pages, seen_urls
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            if not url:
                pages.append(dict(row))
                continue
            if url in seen_urls:
                for idx, existing in enumerate(pages):
                    if str(existing.get("url") or "").strip() == url:
                        pages[idx] = dict(row)
                        break
            else:
                pages.append(dict(row))
                seen_urls.add(url)

    _merge_rows(read_json(run_root / "scrape_manifest.json", []))
    _merge_rows(read_page_states(run_root))
    failures = read_json(run_root / "failures.json", [])
    run_status = read_run_status(run_root)
    scrape_events = read_run_events(run_root)

    store = _get_store()
    live_pages = store.get_pages(site_id, run_id)
    if isinstance(live_pages, list) and live_pages:
        _merge_rows(live_pages)
    live_status = store.get_status(site_id, run_id)
    if isinstance(live_status, dict) and live_status:
        run_status = {**run_status, **live_status}
    live_events = store.get_events(site_id, run_id, max_items=2000)
    if isinstance(live_events, list) and live_events:
        scrape_events = live_events

    return pages, failures if isinstance(failures, list) else [], run_status if isinstance(run_status, dict) else {}, scrape_events if isinstance(scrape_events, list) else []


def _fmt_compact_number(value: float) -> str:
    val = float(value or 0.0)
    abs_val = abs(val)
    if abs_val >= 1_000_000_000:
        return f"{val/1_000_000_000:.1f}B"
    if abs_val >= 1_000_000:
        return f"{val/1_000_000:.1f}M"
    if abs_val >= 1_000:
        return f"{val/1_000:.1f}K"
    return f"{int(val)}" if val.is_integer() else f"{val:.1f}"


def _fmt_usd(value: float) -> str:
    val = float(value or 0.0)
    if abs(val) < 0.01:
        return f"${val:.4f}"
    if abs(val) < 1000:
        return f"${val:.2f}"
    return f"${val/1000:.1f}K"


def _parse_metrics_ts(value: object):
    try:
        return pd.to_datetime(value, utc=True, errors="coerce")
    except Exception:
        return pd.NaT


def _run_id_timestamp(run_id: str):
    value = str(run_id or "").strip()
    if not value:
        return pd.NaT
    try:
        return pd.Timestamp(datetime.strptime(value.split("-", 1)[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc))
    except ValueError:
        pass
    manual_match = re.match(r"^manual-(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})-(\d{2})(?:-(\d{1,6}))?", value)
    if manual_match:
        year, month, day, hour, minute, second, micros = manual_match.groups()
        return pd.Timestamp(
            datetime(
                int(year),
                int(month),
                int(day),
                int(hour),
                int(minute),
                int(second),
                int((micros or "0").ljust(6, "0")[:6]),
                tzinfo=timezone.utc,
            )
        )
    return pd.NaT


def _run_metrics_timestamp(run_id: str, run_status: dict, pages: list[dict], events: list[dict]):
    candidates = [
        _parse_metrics_ts(run_status.get("started_at")),
        _parse_metrics_ts(run_status.get("finished_at")),
        _parse_metrics_ts(run_status.get("created_at")),
        _run_id_timestamp(run_id),
    ]
    for page in pages:
        if not isinstance(page, dict):
            continue
        candidates.append(_parse_metrics_ts(page.get("started_at")))
        candidates.append(_parse_metrics_ts(page.get("finished_at")))
    for event in events:
        if isinstance(event, dict):
            candidates.append(_parse_metrics_ts(event.get("ts")))
    valid = [item for item in candidates if pd.notna(item)]
    return min(valid) if valid else pd.NaT


def _metrics_window_start(window_label: str):
    now = pd.Timestamp.now(tz="UTC")
    days_by_label = {
        "Last 7 days": 7,
        "Last 30 days": 30,
        "Last 3 months": 90,
        "Last 6 months": 180,
        "Last year": 365,
    }
    days = days_by_label.get(window_label)
    return None if days is None else now - pd.Timedelta(days=days)


def _normalize_trace_metrics(trace_df: pd.DataFrame) -> pd.DataFrame:
    if trace_df.empty:
        return pd.DataFrame()
    df = trace_df.copy()
    df["provider"] = (df["provider"] if "provider" in df.columns else pd.Series("unknown", index=df.index)).fillna("unknown").astype(str)
    df["operation"] = (df["operation"] if "operation" in df.columns else pd.Series("unknown", index=df.index)).fillna("unknown").astype(str)
    df["model"] = (df["model"] if "model" in df.columns else pd.Series("unknown", index=df.index)).fillna("unknown").astype(str)
    for col in ("prompt_tokens", "completion_tokens", "total_tokens", "cost_usd"):
        values = df[col] if col in df.columns else pd.Series(0.0, index=df.index)
        df[col] = pd.to_numeric(values, errors="coerce").fillna(0.0)
    return df[~df.get("is_summary", pd.Series(False, index=df.index)).fillna(False).astype(bool)].copy()


def _build_run_metrics_row(
    *,
    site_id: str,
    run_id: str,
    site_root: Path,
    model_map: dict,
    tavily_per_call: float,
    ollama_in_per_m: float,
    ollama_out_per_m: float,
) -> dict:
    run_root = site_root / run_id
    run_events = load_events(run_root)
    pages, failures, run_status, scrape_events = _load_run_analytics_inputs(site_id, run_id, run_root)
    selected_urls = read_json(run_root / "selected_urls.json", [])
    cleanup_manifest = read_json(run_root / "cleanup_manifest.json", [])
    selected_count = len(selected_urls) if isinstance(selected_urls, list) else 0
    cleaned_count = len([row for row in cleanup_manifest if isinstance(row, dict) and row.get("status") == "cleaned"])
    skipped_count = len([row for row in cleanup_manifest if isinstance(row, dict) and row.get("status") == "skipped"])
    page_summary = summarize_pages(pages, run_status=run_status, total_hint=selected_count)
    duration_summary = summarize_durations(pages)
    output_summary = summarize_output_volume(pages)
    trace_df = _build_trace_df(
        run_events=run_events,
        site_events=[],
        model_map=model_map,
        tavily_per_call=tavily_per_call,
        ollama_in_per_m=ollama_in_per_m,
        ollama_out_per_m=ollama_out_per_m,
    )
    billable_trace = _normalize_trace_metrics(trace_df)
    run_ts = _run_metrics_timestamp(run_id, run_status, pages, scrape_events + run_events)
    return {
        "run_id": run_id,
        "run_label": _run_human_timestamp(run_id),
        "run_ts": run_ts,
        "state": str(run_status.get("state") or page_summary.get("state") or "unknown"),
        "selected_urls": selected_count,
        "total_pages": int(page_summary.get("total") or 0),
        "done_pages": int(page_summary.get("done") or 0),
        "scraped_pages": int(page_summary.get("success") or 0),
        "cleaned_pages": cleaned_count,
        "skipped_pages": skipped_count,
        "failed_pages": int(page_summary.get("failed") or 0),
        "cancelled_pages": int(page_summary.get("cancelled") or 0),
        "success_rate": float(page_summary.get("success_rate") or 0.0),
        "elapsed_min": float(page_summary.get("elapsed_sec") or 0.0) / 60.0,
        "pages_per_min": float(page_summary.get("pages_per_min") or 0.0),
        "p50_sec": float(duration_summary.get("p50_sec") or 0.0),
        "p95_sec": float(duration_summary.get("p95_sec") or 0.0),
        "markdown_bytes": int(output_summary.get("markdown_total_bytes") or 0),
        "raw_html_bytes": int(output_summary.get("raw_html_total_bytes") or 0),
        "provider_requests": int(len(billable_trace)),
        "total_tokens": float(billable_trace["total_tokens"].sum()) if not billable_trace.empty else 0.0,
        "cost_usd": float(billable_trace["cost_usd"].sum()) if not billable_trace.empty else 0.0,
        "failure_records": len(failures),
    }


def _nice_metric_axis_max(value: float, *, minimum: float = 1.0) -> float:
    max_value = max(float(value or 0.0), 0.0)
    if max_value <= 0:
        return minimum
    target = max(max_value * 1.14, minimum)
    magnitude = 10 ** math.floor(math.log10(target))
    normalized = target / magnitude
    if normalized <= 1:
        nice = 1
    elif normalized <= 2:
        nice = 2
    elif normalized <= 5:
        nice = 5
    else:
        nice = 10
    return float(nice * magnitude)


def _metric_money_axis_format(max_value: float) -> str:
    value = abs(float(max_value or 0.0))
    if value < 0.01:
        return "$,.4f"
    if value < 1:
        return "$,.3f"
    if value < 1000:
        return "$,.2f"
    return "$,.0f"


def _metrics_usage_grain(chart_metrics_df: pd.DataFrame) -> str:
    dated = chart_metrics_df.dropna(subset=["run_ts"]).sort_values("run_ts")
    if dated.empty or len(dated) <= 12:
        return "run"
    span_days = max(1, int((dated["run_ts"].max() - dated["run_ts"].min()).days))
    if span_days <= 45:
        return "day"
    if span_days <= 210:
        return "week"
    return "month"


def _metrics_period_bucket(series: pd.Series, grain: str) -> pd.Series:
    if grain == "day":
        return series.dt.floor("D")
    naive = series.dt.tz_convert("UTC").dt.tz_localize(None)
    if grain == "week":
        return pd.to_datetime(naive.dt.to_period("W").dt.start_time, utc=True)
    return pd.to_datetime(naive.dt.to_period("M").dt.start_time, utc=True)


def _metrics_usage_chart_data(filtered_metrics_df: pd.DataFrame) -> dict[str, object]:
    chart_metrics_df = filtered_metrics_df.dropna(subset=["run_ts"]).sort_values("run_ts").copy()
    if chart_metrics_df.empty:
        return {}
    grain = _metrics_usage_grain(chart_metrics_df)
    if grain == "run":
        chart_metrics_df["bucket"] = chart_metrics_df["run_label"].fillna(chart_metrics_df["run_id"]).astype(str)
        x_sort = chart_metrics_df["bucket"].tolist()
        x_title = "Run"
        x_axis = alt.Axis(labelAngle=-30 if len(x_sort) > 5 else 0, labelLimit=140)
        x_encoding = alt.X("bucket:N", title=x_title, sort=x_sort, axis=x_axis)
    else:
        chart_metrics_df["bucket"] = _metrics_period_bucket(chart_metrics_df["run_ts"], grain)
        x_sort = None
        x_title = {"day": "Day", "week": "Week", "month": "Month"}.get(grain, "Date")
        x_format = "%b %d" if grain in {"day", "week"} else "%b %Y"
        x_axis = alt.Axis(format=x_format, tickCount=min(8, max(2, int(chart_metrics_df["bucket"].nunique()))))
        x_encoding = alt.X("bucket:T", title=x_title, axis=x_axis)

    grouped = (
        chart_metrics_df.groupby("bucket", as_index=False, sort=False)
        .agg(
            runs=("run_id", "count"),
            scraped_pages=("scraped_pages", "sum"),
            failed_pages=("failed_pages", "sum"),
            cost_usd=("cost_usd", "sum"),
            provider_requests=("provider_requests", "sum"),
        )
        .sort_values("bucket", kind="stable")
    )
    grouped["page_total"] = grouped["scraped_pages"] + grouped["failed_pages"]
    page_columns = ["scraped_pages"] + (["failed_pages"] if float(grouped["failed_pages"].sum()) > 0 else [])
    pages_long = grouped.melt(
        id_vars=["bucket", "runs", "provider_requests"],
        value_vars=page_columns,
        var_name="page_type",
        value_name="pages",
    )
    pages_long["page_type"] = pages_long["page_type"].map({"scraped_pages": "Scraped", "failed_pages": "Failed"}).fillna(pages_long["page_type"])
    return {
        "grain": grain,
        "x_encoding": x_encoding,
        "x_sort": x_sort,
        "x_title": x_title,
        "grouped": grouped,
        "pages_long": pages_long,
    }


def _apply_compact_ui_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --canvas: #faf9f5;
            --ink: #141413;
            --body: #3d3d3a;
            --muted: #6c6a64;
            --hairline: #e6dfd8;
            --primary: #cc785c;
            --primary-rgb: 204, 120, 92;
            --primary-active: #a9583e;
            --electric: #66f2d5;
            --sunburst: #ffd166;
            --plum: #8f6cff;
            --on-primary: #ffffff;
            --on-dark: #faf9f5;
            --on-dark-rgb: 250, 249, 245;
            --shadow-soft: 0 18px 42px rgba(24, 23, 21, 0.08);
            --shadow-card: 0 12px 28px rgba(24, 23, 21, 0.05);
            --radius-md: 12px;
            --radius-lg: 18px;
            --radius-xl: 24px;
            --display-font: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
            --body-font: "Avenir Next", "Segoe UI", Inter, sans-serif;
            --code-font: "JetBrains Mono", "SFMono-Regular", ui-monospace, monospace;
        }
        html, body, .stApp, [data-testid="stApp"], [data-testid="stAppViewContainer"] {
            font-size: 14px;
            color: var(--body);
            font-family: var(--body-font);
        }
        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at top left, rgba(204, 120, 92, 0.10), transparent 28%),
                radial-gradient(circle at 88% 8%, rgba(93, 184, 166, 0.08), transparent 24%),
                linear-gradient(180deg, #f8f5ee 0%, var(--canvas) 14%, var(--canvas) 100%);
        }
        .main .block-container {
            padding-top: 2.4rem;
            padding-bottom: 2.5rem;
            max-width: 1240px;
        }
        h1 {
            font-family: var(--display-font) !important;
            font-size: 3.6rem !important;
            line-height: 1.03 !important;
            letter-spacing: -0.04em !important;
            margin-bottom: 0.55rem !important;
            color: var(--ink) !important;
            font-weight: 500 !important;
        }
        h2, h3 {
            font-family: var(--display-font) !important;
            line-height: 1.15 !important;
            margin-top: 1.1rem !important;
            margin-bottom: 0.55rem !important;
            color: var(--ink) !important;
            font-weight: 500 !important;
            letter-spacing: -0.02em !important;
        }
        h2 {
            font-size: 2rem !important;
        }
        h3 {
            font-size: 1.35rem !important;
        }
        p, label, .stMarkdown, .stCaption, [data-testid="stMarkdownContainer"] {
            font-size: 0.95rem !important;
            line-height: 1.55 !important;
            color: var(--body);
        }
        [data-testid="stCaptionContainer"] p, .stCaption {
            color: var(--muted) !important;
        }
        [data-testid="stMetric"] {
            position: relative;
            overflow: hidden;
            border: 1px solid rgba(var(--on-dark-rgb), 0.18);
            border-radius: var(--radius-md);
            padding: 16px 18px;
            background:
                radial-gradient(circle at top right, rgba(102, 242, 213, 0.16), transparent 34%),
                radial-gradient(circle at bottom left, rgba(255, 209, 102, 0.13), transparent 30%),
                linear-gradient(145deg, rgba(18, 17, 16, 0.98), rgba(44, 34, 31, 0.96));
            box-shadow: 0 16px 34px rgba(24, 23, 21, 0.18), inset 0 1px 0 rgba(255,255,255,0.08);
        }
        [data-testid="stMetric"]::before {
            content: none;
            display: none;
        }
        [data-testid="stMetricLabel"],
        [data-testid="stMetricLabel"] *,
        [data-testid="stMetricLabel"] p {
            font-size: 0.74rem !important;
            text-transform: uppercase;
            letter-spacing: 0.13em;
            color: rgba(var(--on-dark-rgb), 0.82) !important;
            -webkit-text-fill-color: rgba(var(--on-dark-rgb), 0.82) !important;
        }
        [data-testid="stMetricValue"],
        [data-testid="stMetricValue"] *,
        [data-testid="stMetricValue"] div {
            font-family: var(--display-font) !important;
            font-size: 1.55rem !important;
            line-height: 1.05 !important;
            letter-spacing: -0.03em !important;
            color: #fffaf0 !important;
            -webkit-text-fill-color: #fffaf0 !important;
            opacity: 1 !important;
            font-weight: 650 !important;
            text-shadow: 0 1px 0 rgba(0,0,0,0.45), 0 0 18px rgba(255, 209, 102, 0.12);
        }
        [data-testid="stMetricDelta"] svg {
            fill: rgba(102, 242, 213, 0.78) !important;
        }
        [data-testid="stMetricDelta"],
        [data-testid="stMetricDelta"] *,
        [data-testid="stMetricDelta"] > div {
            color: rgba(var(--on-dark-rgb), 0.82) !important;
            -webkit-text-fill-color: rgba(var(--on-dark-rgb), 0.82) !important;
        }
        .operator-metric-strip {
            display: grid;
            grid-template-columns: repeat(var(--metric-columns, 4), minmax(0, 1fr));
            gap: 1rem;
            margin: 0 0 1.1rem 0;
        }
        .operator-metric-card {
            position: relative;
            overflow: hidden;
            min-height: 82px;
            border: 1px solid rgba(var(--on-dark-rgb), 0.18);
            border-radius: var(--radius-md);
            padding: 14px 16px 13px;
            background:
                radial-gradient(circle at 92% 12%, rgba(102, 242, 213, 0.18), transparent 32%),
                radial-gradient(circle at 8% 98%, rgba(255, 209, 102, 0.12), transparent 28%),
                linear-gradient(145deg, rgba(18, 17, 16, 0.985), rgba(45, 35, 31, 0.96));
            box-shadow: 0 16px 34px rgba(24, 23, 21, 0.18), inset 0 1px 0 rgba(255,255,255,0.08);
        }
        .operator-metric-card::after {
            content: none;
            display: none;
        }
        .operator-metric-label {
            display: flex;
            align-items: center;
            gap: 0.42rem;
            color: rgba(var(--on-dark-rgb), 0.84);
            font-family: var(--code-font);
            font-size: 0.66rem;
            font-weight: 760;
            letter-spacing: 0.13em;
            text-transform: uppercase;
        }
        .operator-metric-sigil {
            color: var(--electric);
            text-shadow: 0 0 14px rgba(102, 242, 213, 0.34);
        }
        .operator-metric-value {
            margin-top: 0.48rem;
            color: #fffaf0;
            font-family: var(--display-font);
            font-size: clamp(1.12rem, 1.55vw, 1.52rem);
            font-weight: 720;
            line-height: 1.08;
            letter-spacing: -0.035em;
            text-shadow: 0 1px 0 rgba(0,0,0,0.48), 0 0 22px rgba(255, 209, 102, 0.12);
        }
        .operator-metric-foot {
            margin-top: 0.4rem;
            color: rgba(var(--on-dark-rgb), 0.78);
            font-size: 0.72rem;
            font-weight: 650;
        }
        button, input, textarea, select, [role="tab"] {
            font-size: 0.9rem !important;
            font-family: var(--body-font) !important;
        }
        .stButton > button, [data-testid="stFormSubmitButton"] button {
            border-radius: 999px !important;
            border: 1px solid var(--primary) !important;
            background: var(--primary) !important;
            color: var(--on-primary) !important;
            min-height: 2.85rem !important;
            padding: 0.7rem 1.15rem !important;
            box-shadow: none !important;
            transition: all 120ms ease !important;
            font-weight: 600 !important;
        }
        .stButton > button *, [data-testid="stFormSubmitButton"] button * {
            color: var(--on-primary) !important;
        }
        .stButton > button[kind="primary"],
        .stButton > button[data-kind="primary"],
        [data-testid="stBaseButton-primary"],
        [data-testid="stBaseButton-primary"] > button,
        [data-testid="stFormSubmitButton"] button[kind="primary"] {
            background: var(--primary) !important;
            color: var(--on-primary) !important;
            border-color: var(--primary) !important;
        }
        .stButton > button[kind="primary"]:hover,
        .stButton > button[data-kind="primary"]:hover,
        [data-testid="stBaseButton-primary"]:hover,
        [data-testid="stBaseButton-primary"] > button:hover,
        [data-testid="stFormSubmitButton"] button[kind="primary"]:hover {
            background: var(--primary-active) !important;
            border-color: var(--primary-active) !important;
            color: var(--on-primary) !important;
        }
        .stButton > button[kind="secondary"] {
            background: var(--primary) !important;
            color: var(--on-primary) !important;
            border-color: var(--primary) !important;
        }
        .stButton > button:hover {
            transform: translateY(-1px);
            background: var(--primary-active) !important;
            border-color: var(--primary-active) !important;
            color: var(--on-primary) !important;
        }
        .stButton > button:hover *, [data-testid="stFormSubmitButton"] button:hover * {
            color: var(--on-primary) !important;
        }
        [data-testid="stTextInputRootElement"] > div,
        [data-testid="stTextAreaRootElement"] textarea,
        [data-testid="stNumberInput"] input,
        [data-baseweb="select"] > div,
        [data-testid="stDateInputField"] {
            border-radius: var(--radius-md) !important;
            border-color: var(--hairline) !important;
            background: rgba(255, 255, 255, 0.70) !important;
        }
        [data-testid="stTextInputRootElement"] > div:focus-within,
        [data-testid="stTextAreaRootElement"] textarea:focus,
        [data-testid="stNumberInput"] input:focus,
        [data-baseweb="select"] > div:focus-within,
        [data-testid="stDateInputField"]:focus-within {
            border-color: rgba(204, 120, 92, 0.48) !important;
            box-shadow: 0 0 0 1px rgba(204, 120, 92, 0.32), 0 8px 18px rgba(204, 120, 92, 0.10) !important;
        }
        [data-testid="stForm"] {
            background: linear-gradient(180deg, rgba(255,255,255,0.62), rgba(255,255,255,0.38));
            border: 1px solid var(--hairline);
            border-radius: var(--radius-lg);
            padding: 1rem 1rem 0.6rem;
            box-shadow: var(--shadow-card);
        }
        [data-testid="stTabs"] [data-baseweb="tab-list"],
        [data-testid="stRadio"] [role="radiogroup"] {
            gap: 0.45rem;
            background: rgba(239, 233, 222, 0.80);
            border: 1px solid var(--hairline);
            border-radius: 999px;
            padding: 0.35rem;
            width: 100%;
            overflow-x: auto;
            scrollbar-width: none;
            margin-bottom: 1.25rem;
        }
        [data-testid="stTabs"] [data-baseweb="tab-list"]::-webkit-scrollbar,
        [data-testid="stRadio"] [role="radiogroup"]::-webkit-scrollbar {
            display: none;
        }
        [data-testid="stTabs"] [data-baseweb="tab"],
        [data-testid="stRadio"] [role="radiogroup"] label {
            border-radius: 999px !important;
            color: var(--muted) !important;
            padding: 0.55rem 0.95rem !important;
            height: auto !important;
            font-weight: 600 !important;
            letter-spacing: 0.01em;
        }
        [data-testid="stTabs"] [aria-selected="true"],
        [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) {
            background: rgba(255, 255, 255, 0.9) !important;
            color: var(--ink) !important;
            box-shadow: 0 2px 10px rgba(24, 23, 21, 0.08);
        }
        [data-testid="stAlert"] {
            border-radius: var(--radius-md);
            border: 1px solid var(--hairline);
            background: rgba(255, 255, 255, 0.72);
        }
        [data-testid="stDataFrame"] {
            font-size: 0.82rem !important;
            border-radius: var(--radius-md) !important;
            overflow: hidden !important;
            border: 1px solid var(--hairline) !important;
        }
        [data-testid="stCodeBlock"] pre {
            font-family: var(--code-font) !important;
            border-radius: var(--radius-md) !important;
        }
        div[data-testid="stExpander"] {
            border-radius: var(--radius-md);
            border: 1px solid var(--hairline);
            background: rgba(255, 255, 255, 0.62);
        }
        div[data-testid="stExpander"] details summary p {
            font-size: 0.88rem !important;
            color: var(--ink) !important;
            font-weight: 600 !important;
        }
        [data-testid="stFileUploaderDropzone"] {
            border-radius: var(--radius-lg) !important;
            border: 1.5px dashed rgba(204, 120, 92, 0.35) !important;
            background: rgba(255, 255, 255, 0.60) !important;
        }
        .design-shell {
            position: relative;
            overflow: hidden;
            border-radius: var(--radius-xl);
            border: 1px solid rgba(255, 255, 255, 0.14);
            background:
                linear-gradient(180deg, rgba(204, 120, 92, 0.10), rgba(204, 120, 92, 0.00) 38%),
                radial-gradient(circle at top right, rgba(93, 184, 166, 0.12), transparent 28%),
                linear-gradient(135deg, rgba(24, 23, 21, 0.98), rgba(37, 35, 32, 0.96));
            padding: 2rem 2rem 1.85rem;
            color: var(--on-dark);
            box-shadow: var(--shadow-soft);
            margin-bottom: 1.4rem;
        }
        .design-shell::before {
            content: "";
            position: absolute;
            inset: 0 auto auto 0;
            width: 34%;
            height: 1px;
            background: rgba(250, 249, 245, 0.22);
        }
        .design-shell::after {
            content: "";
            position: absolute;
            inset: 0;
            background: linear-gradient(120deg, transparent 0%, rgba(255,255,255,0.04) 52%, transparent 100%);
            pointer-events: none;
        }
        .design-kicker {
            font-size: 0.74rem;
            letter-spacing: 0.18em;
            text-transform: uppercase;
            color: rgba(250, 249, 245, 0.78);
            margin-bottom: 0.85rem;
            font-weight: 600;
        }
        .design-shell h1,
        .design-shell h2,
        .design-shell p {
            color: var(--on-dark) !important;
            margin: 0;
        }
        .design-shell h1 {
            font-size: 3.2rem !important;
            max-width: 13ch;
        }
        .design-shell p {
            max-width: 64ch;
            margin-top: 0.9rem;
            color: rgba(250, 249, 245, 0.78) !important;
        }
        .design-shell-copy {
            display: grid;
            grid-template-columns: minmax(0, 1.3fr) minmax(260px, 0.8fr);
            gap: 1.25rem;
            align-items: end;
        }
        .design-stat-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.75rem;
            margin-top: 1.35rem;
            justify-content: flex-end;
        }
        .design-stat {
            min-width: 144px;
            border-radius: 14px;
            padding: 0.8rem 0.95rem;
            background: rgba(250, 249, 245, 0.07);
            border: 1px solid rgba(250, 249, 245, 0.10);
            backdrop-filter: blur(4px);
        }
        .design-stat-label {
            font-size: 0.72rem;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: rgba(250, 249, 245, 0.65);
            margin-bottom: 0.4rem;
        }
        .design-stat-value {
            font-size: 1.2rem;
            font-weight: 650;
            color: var(--on-dark);
        }
        [class*="st-key-workspace_card_"] {
            border-radius: var(--radius-lg);
            padding: 1.15rem;
            background:
                radial-gradient(circle at top right, rgba(var(--primary-rgb), 0.10), transparent 26%),
                linear-gradient(180deg, rgba(255,255,255,0.78), rgba(255,255,255,0.56));
            border: 1px solid var(--hairline);
            box-shadow: var(--shadow-card);
            margin-bottom: 1rem;
        }
        .catalog-card-title {
            font-family: var(--display-font);
            color: var(--ink);
            font-size: 1.35rem;
            line-height: 1.15;
            margin-bottom: 0.35rem;
        }
        .catalog-card-meta {
            color: var(--muted);
            font-size: 0.9rem;
        }
        .workspace-card-divider {
            height: 1px;
            margin: 1rem 0 0.9rem;
            background: rgba(var(--primary-rgb), 0.16);
        }
        .workspace-toolbar {
            border: 1px solid var(--hairline);
            border-radius: var(--radius-lg);
            background: linear-gradient(180deg, rgba(255,255,255,0.68), rgba(255,255,255,0.48));
            padding: 1rem 1.1rem;
            margin-bottom: 1rem;
            box-shadow: var(--shadow-card);
        }
        .workspace-toolbar-title {
            font-family: var(--display-font);
            color: var(--ink);
            font-size: 1.6rem;
            margin-bottom: 0.15rem;
        }
        .workspace-toolbar-copy {
            color: var(--muted);
            font-size: 0.92rem;
        }
        .workspace-toolbar-meta {
            display: inline-flex;
            align-items: center;
            gap: 0.55rem;
            margin-top: 0.65rem;
            padding: 0.35rem 0.7rem;
            border-radius: 999px;
            background: rgba(24, 23, 21, 0.06);
            color: var(--body);
            font-size: 0.8rem;
            letter-spacing: 0.04em;
        }
        .workspace-toolbar-meta strong {
            color: var(--ink);
            font-weight: 650;
        }
        [class*="st-key-documents_review_shell"] {
            border-color: rgba(var(--primary-rgb), 0.14) !important;
            background: linear-gradient(180deg, rgba(255,255,255,0.70), rgba(255,255,255,0.48)) !important;
            box-shadow: var(--shadow-card);
        }
        .document-preview-countline {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            border-radius: 999px;
            padding: 0.28rem 0.62rem;
            margin: 0.05rem 0 0.65rem;
            background: rgba(24,23,21,0.055);
            color: var(--muted);
            font-size: 0.78rem;
            font-weight: 650;
        }
        [class*="st-key-source_index_list_"] {
            border: 1px solid rgba(24,23,21,0.08);
            border-radius: 16px;
            background: linear-gradient(180deg, rgba(255,255,255,0.42), rgba(255,255,255,0.22));
            padding: 0.28rem 0.26rem;
        }
        .document-index-section {
            margin: 0.42rem 0 0.18rem;
            padding: 0.18rem 0.55rem;
            color: var(--muted);
            font-family: var(--code-font);
            font-size: 0.66rem;
            font-weight: 750;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }
        [class*="st-key-source_index_card_"] {
            position: relative;
            border-bottom: 0;
            margin: 0.02rem 0;
            padding: 0;
        }
        [class*="st-key-source_index_card_"] .stButton {
            margin: 0 !important;
        }
        [class*="st-key-source_index_card_"] .stButton > button {
            position: relative;
            width: 100%;
            min-height: 2.05rem !important;
            border-radius: 10px !important;
            justify-content: flex-start !important;
            text-align: left !important;
            padding: 0.38rem 0.62rem 0.38rem 1rem !important;
            box-shadow: none !important;
            font-size: 0.84rem !important;
            font-weight: 620 !important;
            letter-spacing: -0.005em;
            white-space: nowrap !important;
            overflow: hidden !important;
            transform: none !important;
            transition: none !important;
        }
        [class*="st-key-source_index_card_"] .stButton > button p,
        [class*="st-key-source_index_card_"] .stButton > button span {
            display: block;
            width: 100%;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            text-align: left;
            margin: 0 !important;
        }
        [class*="st-key-source_index_card_"] [data-testid="stBaseButton-secondary"],
        [class*="st-key-source_index_card_"] .stButton > button[kind="secondary"] {
            background: transparent !important;
            border-color: transparent !important;
            color: var(--body) !important;
        }
        [class*="st-key-source_index_card_"] [data-testid="stBaseButton-secondary"] *,
        [class*="st-key-source_index_card_"] .stButton > button[kind="secondary"] * {
            color: var(--body) !important;
            -webkit-text-fill-color: var(--body) !important;
        }
        [class*="st-key-source_index_card_"] .stButton > button:hover {
            background: transparent !important;
            border-color: transparent !important;
            color: var(--body) !important;
            box-shadow: none !important;
            transform: none !important;
        }
        [class*="st-key-source_index_card_"] .stButton > button:hover * {
            color: var(--body) !important;
            -webkit-text-fill-color: var(--body) !important;
        }
        [class*="st-key-source_index_card_"] [data-testid="stBaseButton-primary"],
        [class*="st-key-source_index_card_"] .stButton > button[kind="primary"],
        [class*="st-key-source_index_card_selected_"] .stButton > button {
            background: linear-gradient(90deg, rgba(var(--primary-rgb), 0.12), rgba(255,209,102,0.07) 72%, rgba(255,255,255,0.16)) !important;
            border-color: rgba(var(--primary-rgb), 0.32) !important;
            color: var(--ink) !important;
            box-shadow: none !important;
        }
        [class*="st-key-source_index_card_"] [data-testid="stBaseButton-primary"] *,
        [class*="st-key-source_index_card_"] .stButton > button[kind="primary"] *,
        [class*="st-key-source_index_card_selected_"] .stButton > button * {
            color: var(--ink) !important;
            -webkit-text-fill-color: var(--ink) !important;
        }
        [class*="st-key-source_index_card_"] [data-testid="stBaseButton-primary"]:hover,
        [class*="st-key-source_index_card_"] .stButton > button[kind="primary"]:hover,
        [class*="st-key-source_index_card_selected_"] .stButton > button:hover {
            background: linear-gradient(90deg, rgba(var(--primary-rgb), 0.12), rgba(255,209,102,0.07) 72%, rgba(255,255,255,0.16)) !important;
            border-color: rgba(var(--primary-rgb), 0.32) !important;
            color: var(--ink) !important;
            box-shadow: none !important;
            transform: none !important;
        }
        .document-index-note {
            margin: -0.05rem 0 0.24rem 1rem;
            color: var(--muted);
            font-size: 0.72rem;
            line-height: 1.25;
        }
        [class*="st-key-documents_markdown_preview"],
        [class*="st-key-wiki_markdown_preview"] {
            border-color: rgba(var(--primary-rgb), 0.12) !important;
            background: rgba(255,255,255,0.56) !important;
        }
        [class*="st-key-documents_markdown_preview"] [data-testid="stMarkdownContainer"],
        [class*="st-key-wiki_markdown_preview"] [data-testid="stMarkdownContainer"] {
            font-size: 0.9rem !important;
            line-height: 1.5 !important;
        }
        [class*="st-key-documents_markdown_preview"] [data-testid="stMarkdownContainer"] h1,
        [class*="st-key-wiki_markdown_preview"] [data-testid="stMarkdownContainer"] h1 {
            font-family: var(--display-font) !important;
            font-size: 1.65rem !important;
            line-height: 1.16 !important;
            letter-spacing: -0.025em !important;
            margin: 0.55rem 0 0.45rem !important;
        }
        [class*="st-key-documents_markdown_preview"] [data-testid="stMarkdownContainer"] h2,
        [class*="st-key-wiki_markdown_preview"] [data-testid="stMarkdownContainer"] h2 {
            font-size: 1.28rem !important;
            line-height: 1.22 !important;
            margin: 0.85rem 0 0.38rem !important;
        }
        [class*="st-key-documents_markdown_preview"] [data-testid="stMarkdownContainer"] h3,
        [class*="st-key-wiki_markdown_preview"] [data-testid="stMarkdownContainer"] h3 {
            font-size: 1.08rem !important;
            line-height: 1.25 !important;
            margin: 0.7rem 0 0.28rem !important;
        }
        [class*="st-key-documents_markdown_preview"] [data-testid="stMarkdownContainer"] h4,
        [class*="st-key-documents_markdown_preview"] [data-testid="stMarkdownContainer"] h5,
        [class*="st-key-documents_markdown_preview"] [data-testid="stMarkdownContainer"] h6,
        [class*="st-key-wiki_markdown_preview"] [data-testid="stMarkdownContainer"] h4,
        [class*="st-key-wiki_markdown_preview"] [data-testid="stMarkdownContainer"] h5,
        [class*="st-key-wiki_markdown_preview"] [data-testid="stMarkdownContainer"] h6 {
            font-size: 0.98rem !important;
            line-height: 1.3 !important;
            margin: 0.6rem 0 0.24rem !important;
        }
        [class*="st-key-documents_markdown_preview"] [data-testid="stMarkdownContainer"] p,
        [class*="st-key-documents_markdown_preview"] [data-testid="stMarkdownContainer"] li,
        [class*="st-key-wiki_markdown_preview"] [data-testid="stMarkdownContainer"] p,
        [class*="st-key-wiki_markdown_preview"] [data-testid="stMarkdownContainer"] li {
            font-size: 0.9rem !important;
            line-height: 1.5 !important;
        }
        [class*="st-key-runs_control_panel"] {
            border: 1px solid var(--hairline);
            border-radius: var(--radius-lg);
            background: rgba(255, 255, 255, 0.62);
            padding: 0.85rem 0.95rem 0.75rem;
            margin: 0.35rem 0 1rem;
            box-shadow: var(--shadow-card);
        }
        [class*="st-key-runs_control_panel"] .stButton > button {
            min-height: 2.35rem !important;
            padding: 0.46rem 0.72rem !important;
            border-radius: 12px !important;
            background: rgba(255,255,255,0.78) !important;
            border: 1px solid rgba(24,23,21,0.14) !important;
            color: var(--ink) !important;
            box-shadow: none !important;
            font-size: 0.82rem !important;
            font-weight: 700 !important;
        }
        [class*="st-key-runs_control_panel"] .stButton > button * {
            color: var(--ink) !important;
        }
        [class*="st-key-runs_control_panel"] .stButton > button[kind="primary"],
        [class*="st-key-runs_control_panel"] [data-testid="stBaseButton-primary"] {
            background: var(--primary) !important;
            border-color: var(--primary) !important;
            color: var(--on-primary) !important;
        }
        [class*="st-key-runs_control_panel"] .stButton > button[kind="primary"] *,
        [class*="st-key-runs_control_panel"] [data-testid="stBaseButton-primary"] * {
            color: var(--on-primary) !important;
        }
        [class*="st-key-runs_control_panel"] [data-testid="stNumberInput"] input {
            min-height: 2.35rem !important;
            border-radius: 12px !important;
            background: rgba(255,255,255,0.82) !important;
        }
        [class*="st-key-runs_control_panel"] label,
        [class*="st-key-runs_control_panel"] label p {
            font-size: 0.78rem !important;
            color: var(--muted) !important;
            font-weight: 650 !important;
        }
        .run-meta-line {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            align-items: center;
            margin-top: 0.5rem;
        }
        .run-meta-pill {
            display: inline-flex;
            gap: 0.35rem;
            align-items: center;
            border-radius: 999px;
            background: rgba(24,23,21,0.055);
            color: var(--muted);
            padding: 0.3rem 0.62rem;
            font-size: 0.76rem;
            font-weight: 650;
        }
        .run-meta-pill strong,
        .run-meta-pill code {
            color: var(--ink);
            font-weight: 750;
            font-family: var(--code-font);
            font-size: 0.74rem;
        }
        @media (max-width: 980px) {
            .main .block-container {
                padding-top: 1.3rem;
                padding-bottom: 1.5rem;
            }
            h1 {
                font-size: 2.8rem !important;
            }
            .design-shell {
                padding: 1.45rem 1.2rem 1.35rem;
            }
            .design-shell h1 {
                font-size: 2.55rem !important;
                max-width: none;
            }
            .design-shell-copy {
                grid-template-columns: 1fr;
            }
            .design-stat-row {
                justify-content: flex-start;
            }
            .operator-metric-strip {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
            [data-testid="stTabs"] [data-baseweb="tab-list"],
            [data-testid="stRadio"] [role="radiogroup"] {
                width: calc(100vw - 2.2rem);
            }
        }
        @media (max-width: 640px) {
            .operator-metric-strip {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_workflow_navigation(options: list[str]) -> str:
    """Render a lazy top-level section selector.

    Streamlit tabs eagerly execute every tab body on each interaction, which made
    this app feel slow once source tables, wiki reports, and metrics grew large.
    A keyed radio keeps the same workflow affordance while only rendering the
    selected section below.
    """
    if not options:
        return ""
    if st.session_state.get("workflow_active_tab") not in options:
        st.session_state["workflow_active_tab"] = options[0]
    return str(
        st.radio(
            "Workflow section",
            options=options,
            key="workflow_active_tab",
            horizontal=True,
            label_visibility="collapsed",
        )
    )


def _render_shell_banner(*, kicker: str, title: str, subtitle: str, stats: list[tuple[str, str]] | None = None) -> None:
    stats = stats or []
    stats_html = "".join(
        (
            '<div class="design-stat">'
            f'<div class="design-stat-label">{escape(_safe_text(label), quote=True)}</div>'
            f'<div class="design-stat-value">{escape(_safe_text(value), quote=True)}</div>'
            "</div>"
        )
        for label, value in stats
    )
    st.markdown(
        (
            '<section class="design-shell">'
            f'<div class="design-kicker">{escape(_safe_text(kicker), quote=True)}</div>'
            '<div class="design-shell-copy">'
            '<div>'
            f"<h1>{escape(_safe_text(title), quote=True)}</h1>"
            f"<p>{escape(_safe_text(subtitle), quote=True)}</p>"
            "</div>"
            f'<div class="design-stat-row">{stats_html}</div>'
            "</div>"
            "</section>"
        ),
        unsafe_allow_html=True,
    )


def _render_toolbar_card(*, title: str, copy: str, meta_label: str | None = None, meta_value: str | None = None) -> None:
    meta_html = ""
    if meta_label and meta_value:
        meta_html = (
            '<div class="workspace-toolbar-meta">'
            f"<span>{escape(_safe_text(meta_label), quote=True)}</span>"
            f"<strong>{escape(_safe_text(meta_value), quote=True)}</strong>"
            "</div>"
        )
    st.markdown(
        (
            '<section class="workspace-toolbar">'
            f'<div class="workspace-toolbar-title">{escape(_safe_text(title), quote=True)}</div>'
            f'<div class="workspace-toolbar-copy">{escape(_safe_text(copy), quote=True)}</div>'
            f"{meta_html}"
            "</section>"
        ),
        unsafe_allow_html=True,
    )


def _render_scraped_page_preview() -> None:
    if str(st.query_params.get("view", "") or "").strip() != "scraped_page":
        return

    site_id = str(st.query_params.get("site_id", "") or "").strip()
    run_id = str(st.query_params.get("run_id", "") or "").strip()
    slug = str(st.query_params.get("page_slug", "") or "").strip()

    st.subheader("Scraped page preview")
    if st.button("Back to Runs"):
        st.query_params.clear()
        st.rerun()
    if not site_id or not run_id or not slug:
        st.error("Preview link is missing site, run, or page information.")
        render_operator_details(
            "Operator Details",
            {
                "Expected query params": "view=scraped_page, site_id, run_id, page_slug",
                "site_id": site_id or "missing",
                "run_id": run_id or "missing",
                "page_slug": slug or "missing",
            },
            expanded=True,
        )
        st.stop()
    if not is_safe_route_part(site_id) or not is_safe_route_part(run_id):
        st.error("Preview link contains invalid site or run information.")
        render_operator_details(
            "Operator Details",
            {
                "Expected query params": "safe site_id and run_id route parts",
                "site_id": site_id,
                "run_id": run_id,
                "page_slug": slug,
            },
            expanded=True,
        )
        st.stop()

    run_root = _run_root(site_id, run_id)
    preview = resolve_scraped_markdown_preview(run_root, slug)
    first_heading = ""
    for line in preview.markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            first_heading = stripped.lstrip("#").strip()
            break
    preview_source_path = _url_path_label(preview.url, max_chars=140) if preview.url else "Not recorded"
    preview_title = first_heading or (preview_source_path if preview_source_path not in {"/", "Not recorded"} else Path(slug).name) or "Untitled scraped page"

    st.markdown(f"### {preview_title}")
    st.caption(f"Source path: `{preview_source_path}`")
    st.caption(f"Run id: `{run_id}`")
    st.caption(f"Page slug: `{slug}`")

    meta_cols = st.columns(4)
    meta_cols[0].metric("Scrape status", "Ready" if preview.ready else "Missing")
    meta_cols[1].metric("HTTP status", preview.http_status if preview.http_status is not None else "n/a")
    meta_cols[2].metric("Fetch mode", preview.fetch_mode or "n/a")
    meta_cols[3].metric("Text length", preview.text_length if preview.text_length is not None else "n/a")

    expected_markdown_path = preview.path or (run_root / "markdown" / f"{slug}.md")
    metadata_summary_rows = [
        {"Metric": "Source path", "Value": preview_source_path},
        {"Metric": "HTTP status", "Value": preview.http_status if preview.http_status is not None else "n/a"},
        {"Metric": "Fetch mode", "Value": preview.fetch_mode or "n/a"},
        {"Metric": "Text length", "Value": preview.text_length if preview.text_length is not None else "n/a"},
    ]
    st.markdown("#### Metadata summary")
    st.dataframe(pd.DataFrame(metadata_summary_rows), use_container_width=True, hide_index=True)

    render_operator_details(
        "Operator Details",
        {
            "Preview route": "view=scraped_page",
            "Source URL": preview.url or "Not recorded",
            "Scrape status": "ready" if preview.ready else "missing",
            "Run id": run_id,
            "Page slug": slug,
            "Expected markdown path": str(expected_markdown_path),
            "Metadata summary": {
                "http_status": preview.http_status,
                "fetch_mode": preview.fetch_mode or "n/a",
                "text_length": preview.text_length,
            },
        },
        expanded=not preview.ready,
    )

    if not preview.ready:
        st.warning(preview.message or "Scraped markdown is not ready yet.")
        st.stop()

    st.divider()
    st.markdown("#### Extracted content")
    st.markdown(preview.markdown)
    st.stop()


st.set_page_config(page_title="Scrapling Scrape Planner", layout="wide")
_apply_compact_ui_styles()
_render_scraped_page_preview()
_init_state()
loaded_env = _load_env_file(ENV_PATH)
loaded_app_state = _load_app_state()
if loaded_env.get("OPENROUTER_API_KEY"):
    os.environ["OPENROUTER_API_KEY"] = loaded_env["OPENROUTER_API_KEY"]
if not st.session_state.get("openrouter_api_key"):
    st.session_state["openrouter_api_key"] = loaded_env.get("OPENROUTER_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))
if not st.session_state.get("site_url"):
    st.session_state["site_url"] = loaded_app_state.get("last_site_url", "")
if not st.session_state.get("site_id"):
    st.session_state["site_id"] = loaded_app_state.get("last_site_id", "")
if not st.session_state.get("manual_urls"):
    st.session_state["manual_urls"] = loaded_app_state.get("manual_urls", "")
if not st.session_state.get("ollama_model"):
    st.session_state["ollama_model"] = loaded_app_state.get("ollama_model", "")
if "ollama_base_url" not in st.session_state:
    st.session_state["ollama_base_url"] = loaded_env.get(
        "OLLAMA_BASE_URL", loaded_app_state.get("ollama_base_url", OLLAMA_BASE_URL)
    )
if not st.session_state.get("llm_provider"):
    st.session_state["llm_provider"] = loaded_app_state.get("llm_provider", "openrouter")
if not st.session_state.get("site_history"):
    st.session_state["site_history"] = loaded_app_state.get("site_history", [])
if not st.session_state.get("tavily_api_key"):
    st.session_state["tavily_api_key"] = loaded_env.get("TAVILY_API_KEY", loaded_app_state.get("tavily_api_key", ""))
if not st.session_state.get("default_or_model"):
    st.session_state["default_or_model"] = loaded_app_state.get("default_or_model", "deepseek/deepseek-v4-flash")
if not st.session_state.get("default_llm_cap"):
    st.session_state["default_llm_cap"] = int(loaded_app_state.get("default_llm_cap", 150))
if not st.session_state.get("default_llm_batch_size"):
    st.session_state["default_llm_batch_size"] = int(loaded_app_state.get("default_llm_batch_size", 250))
if "default_llm_sleep_sec" not in st.session_state:
    st.session_state["default_llm_sleep_sec"] = float(loaded_app_state.get("default_llm_sleep_sec", 0.0))
if not st.session_state.get("workspaces"):
    st.session_state["workspaces"] = loaded_app_state.get("workspaces", [])
if not st.session_state.get("active_workspace_id"):
    st.session_state["active_workspace_id"] = loaded_app_state.get("active_workspace_id", "")
active_workspace_for_recovery = next(
    (w for w in st.session_state.get("workspaces", []) if w.get("id") == st.session_state.get("active_workspace_id")),
    None,
)
if active_workspace_for_recovery:
    if not st.session_state.get("site_id"):
        st.session_state["site_id"] = active_workspace_for_recovery.get("id", "")
    if not st.session_state.get("site_url"):
        st.session_state["site_url"] = active_workspace_for_recovery.get("url", "")
_apply_wiki_file_query_state()
if "last_run_by_site" not in st.session_state:
    st.session_state["last_run_by_site"] = loaded_app_state.get("last_run_by_site", {})
if not st.session_state.get("run_id"):
    if st.session_state.get("site_id"):
        st.session_state["run_id"] = st.session_state["last_run_by_site"].get(
            st.session_state["site_id"], loaded_app_state.get("last_run_id", "")
        )
_hydrate_site_workspace(st.session_state.get("site_id", ""))
if st.session_state.get("site_id"):
    resolved_run_id = _resolve_active_run_id(st.session_state["site_id"], st.session_state.get("run_id", ""))
    if resolved_run_id != st.session_state.get("run_id", ""):
        st.session_state["run_id"] = resolved_run_id
        st.session_state.setdefault("last_run_by_site", {})[st.session_state["site_id"]] = resolved_run_id
if "tavily_cost_per_call_usd" not in st.session_state:
    st.session_state["tavily_cost_per_call_usd"] = float(loaded_app_state.get("tavily_cost_per_call_usd", 0.0))
if "ollama_input_per_m_usd" not in st.session_state:
    st.session_state["ollama_input_per_m_usd"] = float(loaded_app_state.get("ollama_input_per_m_usd", 0.0))
if "ollama_output_per_m_usd" not in st.session_state:
    st.session_state["ollama_output_per_m_usd"] = float(loaded_app_state.get("ollama_output_per_m_usd", 0.0))
if st.session_state.get("scrape_browser_mode", "none") == "none" and loaded_app_state.get("scrape_browser_mode"):
    st.session_state["scrape_browser_mode"] = loaded_app_state.get("scrape_browser_mode", "none")
if not st.session_state.get("lightpanda_cdp_url"):
    st.session_state["lightpanda_cdp_url"] = loaded_env.get(
        "LIGHTPANDA_CDP_URL", loaded_env.get("LIGHTPANDA_WS_ENDPOINT", loaded_app_state.get("lightpanda_cdp_url", ""))
    )
store = _get_store()
runner = _get_runner()
tmux_runner = _get_tmux_runner()

workspace_count = len(st.session_state.get("workspaces", []))
active_run_label = _run_human_timestamp(st.session_state.get("run_id", "")) if st.session_state.get("run_id") else "No run yet"

_render_shell_banner(
    kicker="Knowledge Operations Platform",
    title="University Knowledge Ops",
    subtitle="Coordinate source intake, scrape operations, document review, wiki production, embeddings, and metrics from one operator workspace.",
    stats=[
        ("Workflow", f"{len(WORKFLOW_TABS)} stages"),
        ("Workspaces", f"{workspace_count:,}"),
        ("Active run", active_run_label),
    ],
)

if not st.session_state.get("active_workspace_id"):
    _render_toolbar_card(
        title="Workspace catalog",
        copy="Create one workspace per university and reopen the full pipeline with its sources, runs, wiki, and embeddings state intact.",
    )

    with st.form("new_workspace_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        ws_name = c1.text_input("University Name", placeholder="Southern Methodist University")
        ws_url = c2.text_input("Website URL", placeholder="https://www.smu.edu")
        submitted = st.form_submit_button("+ Add Workspace", type="primary")
        if submitted and ws_name.strip() and ws_url.strip():
            normalized = normalize_site_url(ws_url.strip())
            ws_id = _site_slug(normalized)
            new_ws = {"id": ws_id, "name": ws_name.strip(), "url": normalized}
            existing = [w for w in st.session_state["workspaces"] if w.get("id") != ws_id]
            st.session_state["workspaces"] = [new_ws] + existing
            (DATA_ROOT / "sites" / ws_id).mkdir(parents=True, exist_ok=True)
            _save_app_state()
            st.rerun()

    if st.session_state["workspaces"]:
        for ws in st.session_state["workspaces"]:
            with st.container(key=f"workspace_card_{ws.get('id', 'unknown')}"):
                ws_name = _safe_text(ws.get("name"), "Unnamed University")
                ws_url = _safe_text(ws.get("url"))
                st.markdown(f'<div class="catalog-card-title">{escape(ws_name, quote=True)}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="catalog-card-meta">{escape(ws_url, quote=True)}</div>', unsafe_allow_html=True)
                st.markdown('<div class="workspace-card-divider"></div>', unsafe_allow_html=True)
                b1, b2 = st.columns([1, 1])
                if b1.button("Open Workspace", key=f"open_ws_{ws.get('id')}"):
                    st.session_state["active_workspace_id"] = ws.get("id", "")
                    st.session_state["site_url"] = ws.get("url", "")
                    st.session_state["site_id"] = ws.get("id", "")
                    st.session_state["run_id"] = st.session_state.get("last_run_by_site", {}).get(ws.get("id", ""), "")
                    _hydrate_site_workspace(st.session_state["site_id"])
                    _save_app_state()
                    st.rerun()
                if b2.button("Delete Workspace", key=f"del_ws_{ws.get('id')}"):
                    st.session_state["workspaces"] = [w for w in st.session_state["workspaces"] if w.get("id") != ws.get("id")]
                    if st.session_state.get("active_workspace_id") == ws.get("id"):
                        st.session_state["active_workspace_id"] = ""
                    _save_app_state()
                    st.rerun()
    else:
        st.info("No workspaces yet. Create the first one above and this catalog will fill in.")
    st.stop()

active_ws = next((w for w in st.session_state.get("workspaces", []) if w.get("id") == st.session_state.get("active_workspace_id")), None)
if active_ws:
    top1, top2 = st.columns([3, 1])
    with top1:
        _render_toolbar_card(
            title=_safe_text(active_ws.get("name"), "Unnamed workspace"),
            copy=_safe_text(active_ws.get("url")),
            meta_label="Active run",
            meta_value=_run_human_timestamp(st.session_state.get("run_id", "")) if st.session_state.get("run_id") else "No run yet",
        )
    if top2.button("Back to Workspaces"):
        st.session_state["active_workspace_id"] = ""
        _save_app_state()
        st.rerun()

active_tab = _render_workflow_navigation(WORKFLOW_TABS)

if active_tab == WORKFLOW_TABS[0]:
    st.subheader("Overview")
    if active_ws:
        discovered_count = len(st.session_state.get("discovered") or read_json(_discovered_json_path(st.session_state["site_id"]), []))
        selected_df_for_setup = st.session_state.get("selected_df", pd.DataFrame())
        selected_count = 0
        if isinstance(selected_df_for_setup, pd.DataFrame) and not selected_df_for_setup.empty:
            selected_count = int(selected_df_for_setup["selected"].fillna(False).sum()) if "selected" in selected_df_for_setup.columns else len(selected_df_for_setup)

        site_id = st.session_state.get("site_id", "")
        site_root = DATA_ROOT / "sites" / site_id if site_id else None
        pdf_manifest = read_json(site_root / "sources" / "pdf_manifest.json", []) if site_root else []
        pdf_count = len([row for row in pdf_manifest if isinstance(row, dict)])
        pdf_page_count = 0
        pdf_chunk_count = 0
        if site_root:
            pdf_ingest_dir = site_root / "sources" / "pdf_ingest"
            pdf_pages_dir = site_root / "sources" / "pdf_pages"
            pdf_chunk_count = len(_read_jsonl_rows(pdf_ingest_dir / "pdf_chunks.jsonl"))
            page_rows = []
            for pages_index in sorted(pdf_pages_dir.glob("*/pages.json")) if pdf_pages_dir.exists() else []:
                payload = read_json(pages_index, [])
                if isinstance(payload, list):
                    page_rows.extend([row for row in payload if isinstance(row, dict)])
            pdf_page_count = len(page_rows)
            if not pdf_page_count and pdf_pages_dir.exists():
                pdf_page_count = len([path for path in pdf_pages_dir.rglob("*.md") if path.is_file()])

        layout = site_layout(site_root) if site_root else None
        raw_status = _raw_source_status(layout) if layout else {"rows": []}
        raw_rows = raw_status.get("rows", [])
        raw_ready_count = len([row for row in raw_rows if str(row.get("status") or "") == "ready"])
        raw_failed_count = len([row for row in raw_rows if str(row.get("status") or "") == "failed"])
        raw_review_count = len([row for row in raw_rows if str(row.get("status") or "") in {"needs-review", "needs_review"}])

        run_id = st.session_state.get("run_id", "")
        run_state = "none"
        done_count = 0
        total_count = selected_count
        failed_count = 0
        running_count = 0
        queued_count = selected_count
        if run_id and site_id:
            run_status, run_pages, _run_events = _load_scrape_runtime(site_id, run_id, max_events=800)
            run_summary = derive_run_summary(status=run_status or {}, pages=run_pages or [], selected_count=selected_count)
            run_state = run_summary.state
            done_count = int(run_summary.done)
            total_count = int(run_summary.total)
            failed_count = int(run_summary.failed)
            running_count = int(run_summary.running)
            queued_count = int(run_summary.queued)

        operator_run = build_operator_run_status(
            state=run_state,
            done=done_count,
            total=total_count,
            running=running_count,
            failed=failed_count,
            queued=queued_count,
            has_live_runner=bool(run_id and site_id and runner.has_live_run(site_id, run_id)),
        )
        operator_sources = build_operator_source_status(
            selected_url_count=selected_count,
            pdf_count=pdf_count,
            raw_source_count=len(raw_rows),
            raw_ready_count=raw_ready_count,
            raw_failed_count=raw_failed_count,
            raw_review_count=raw_review_count,
            pdf_page_count=pdf_page_count,
            pdf_chunk_count=pdf_chunk_count,
        )

        render_status_band(
            title=f"{active_ws.get('name', 'Workspace')} operations",
            subtitle=f"{active_ws.get('url') or st.session_state.get('site_url') or 'No site URL'}",
            status_label=operator_run.state_label,
            tone=operator_run.attention_level,
            action_label=operator_run.primary_action,
        )
        render_metric_strip(
            [
                {"label": "Run Progress", "value": f"{operator_run.done:,}/{operator_run.total:,}"},
                {"label": "Running", "value": f"{operator_run.running:,}"},
                {"label": "Failures", "value": f"{operator_run.failed:,}"},
                {"label": "Queued", "value": f"{operator_run.queued:,}"},
            ]
        )

        source_tone = "ready" if operator_sources.readiness == "ready" else "warning"
        render_status_band(
            title="Source readiness",
            subtitle=operator_sources.message,
            status_label=operator_sources.readiness.title(),
            tone=source_tone,
            action_label="Build wiki" if operator_sources.readiness == "ready" else "Normalize corpus",
        )
        render_metric_strip(
            [
                {"label": "Selected URLs", "value": f"{operator_sources.selected_url_count:,}"},
                {"label": "PDF Extraction", "value": operator_sources.pdf_detail},
                {"label": "Raw Sources", "value": f"{operator_sources.raw_source_count:,}"},
                {"label": "Needs Review", "value": f"{operator_sources.raw_review_count:,}"},
            ]
        )

        recent_failures = [
            row for row in (raw_rows or [])
            if str(row.get("status") or "") in {"failed", "needs-review", "needs_review"} or str(row.get("error_reason") or "").strip()
        ][:5]
        if recent_failures:
            with st.expander("Attention Needed", expanded=False):
                fail_preview = [
                    {
                        "source": row.get("title", ""),
                        "kind": row.get("source_kind", ""),
                        "status": row.get("status", ""),
                        "reason": row.get("error_reason", ""),
                    }
                    for row in recent_failures
                ]
                st.dataframe(pd.DataFrame(fail_preview), use_container_width=True, hide_index=True)
    else:
        st.warning("No active workspace selected. Go back to the workspace list and open one.")

if active_tab == WORKFLOW_TABS[1]:
    st.subheader("Sources")
    discovered_path = _discovered_json_path(st.session_state["site_id"])
    discovered_rows_for_summary = st.session_state.get("discovered") or read_json(discovered_path, [])
    source_count = len(
        {
            row.get("source_sitemap")
            for row in discovered_rows_for_summary
            if isinstance(row, dict) and row.get("source_sitemap")
        }
    )
    last_refreshed = "never"
    if discovered_path.exists():
        last_refreshed = datetime.fromtimestamp(discovered_path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    site_id = st.session_state.get("site_id", "")
    site_root = DATA_ROOT / "sites" / site_id if site_id else None
    selected_url_strings = _selected_url_strings_from_state()
    pdf_manifest = []
    raw_ready = False
    run_state_label = "none"
    status = {}
    raw_pages = []
    summary = None
    pages_df = pd.DataFrame()
    elapsed_label = "n/a"
    eta_label = "n/a"

    if site_root:
        site_root.mkdir(parents=True, exist_ok=True)
        pdf_manifest = read_json(site_root / "sources" / "pdf_manifest.json", [])
        layout = site_layout(site_root)
        raw_status = _raw_source_status(layout)
        raw_ready = _raw_sources_ready(raw_status)

    if st.session_state.get("run_id") and site_id:
        status, pages, events = _load_scrape_runtime(site_id, st.session_state["run_id"], max_events=1500)
        status = status or {}
        raw_pages = pages if isinstance(pages, list) else []
        summary = derive_run_summary(status=status, pages=raw_pages, selected_count=len(selected_url_strings))
        run_state_label = summary.state
    elif selected_url_strings:
        run_state_label = "ready"

    st.markdown("Source Inventory")
    i1, i2, i3, i4 = st.columns(4)
    i1.metric("Website URLs", f"{len(selected_url_strings):,} selected")
    i2.metric("PDF documents", f"{len(pdf_manifest):,} uploaded")
    i3.metric("Prepared sources", "ready" if raw_ready else "not ready")
    i4.metric("Last refreshed", last_refreshed)

    next_action = _source_next_action(
        selected_url_count=len(selected_url_strings),
        pdf_count=len(pdf_manifest),
        run_state=run_state_label,
        raw_ready=raw_ready,
    )
    st.markdown("Next Action")
    st.info(next_action)

    st.markdown("Add Sources")
    url_panel, doc_panel = st.columns(2)
    with url_panel:
        st.markdown("Website URLs")
        st.caption("Refreshing discovery is additive: newly found sitemap URLs are merged with existing/manual URLs.")
        if st.button("Refresh Sitemap URLs", disabled=not st.session_state["site_url"], type="primary"):
            result = discover_site_urls(st.session_state["site_url"])
            refreshed_rows = _to_discovered_rows(result.urls)
            merged = {
                row.get("url"): row
                for row in st.session_state.get("discovered", [])
                if isinstance(row, dict) and row.get("url")
            }
            for row in refreshed_rows:
                if isinstance(row, dict) and row.get("url"):
                    merged[row["url"]] = row
            st.session_state["discovered"] = list(merged.values())
            st.session_state["selected_df"] = pd.DataFrame(st.session_state["discovered"])
            write_json(_discovered_json_path(st.session_state["site_id"]), st.session_state["discovered"])
            _save_app_state()
            discovered_rows_for_summary = st.session_state["discovered"]
            source_count = len(
                {
                    row.get("source_sitemap")
                    for row in discovered_rows_for_summary
                    if isinstance(row, dict) and row.get("source_sitemap")
                }
            )
            last_refreshed = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            st.info("\n".join(result.notes) if result.notes else "Discovery completed.")

        st.session_state["manual_urls"] = st.text_area(
            "Paste official links",
            value=st.session_state["manual_urls"],
            height=110,
            placeholder="https://admissions.example.edu/...\n/registrar/...",
        )
        _save_app_state()
        if st.button("Add URLs", type="secondary"):
            items = apply_manual_urls(st.session_state["site_url"], st.session_state["manual_urls"].splitlines())
            merged = {row.get("url"): row for row in st.session_state.get("discovered", []) if isinstance(row, dict) and row.get("url")}
            accepted = 0
            excluded = 0
            for item in items:
                row = item.to_dict()
                if row.get("excluded_reason"):
                    excluded += 1
                else:
                    accepted += 1
                merged[item.url] = row
            st.session_state["discovered"] = list(merged.values())
            st.session_state["selected_df"] = pd.DataFrame(st.session_state["discovered"])
            write_json(_discovered_json_path(st.session_state["site_id"]), st.session_state["discovered"])
            _save_app_state()
            st.success(f"Accepted {accepted:,} URL(s). Excluded {excluded:,} off-domain URL(s).")

        st.markdown("Add One URL To Knowledge Base")
        one_url = st.text_input(
            "URL to scrape, compile, and index",
            value="",
            placeholder="https://example.edu/admissions/deadlines",
            key="manual_one_url_pipeline_input",
        )
        if st.button(
            "Scrape + Inject",
            type="primary",
            disabled=not site_id or not one_url.strip(),
            key="manual_one_url_pipeline_run",
        ):
            with st.spinner("Scraping one URL and injecting it into the knowledge base..."):
                try:
                    pipeline_result = run_manual_url_pipeline(
                        site_root=site_root,
                        site_url=st.session_state.get("site_url", ""),
                        url=one_url.strip(),
                    )
                except Exception as exc:
                    st.error(f"One URL pipeline failed: {exc}")
                else:
                    if pipeline_result.get("status") == "rejected":
                        st.warning(f"URL rejected: {pipeline_result.get('reason')}")
                    else:
                        st.session_state["run_id"] = str(pipeline_result.get("run_id") or "")
                        st.session_state["last_run_by_site"][site_id] = st.session_state["run_id"]
                        _save_app_state()
                        st.success("URL scraped, compiled into the wiki, and indexed for query.")
                        render_metric_strip(
                            [
                                {"label": "Raw Ready", "value": f"{int((pipeline_result.get('raw_report') or {}).get('counts', {}).get('ready', 0)):,}"},
                                {"label": "Wiki Pages", "value": f"{int((pipeline_result.get('wiki_report') or {}).get('pages_created', 0)) + int((pipeline_result.get('wiki_report') or {}).get('pages_updated', 0)):,}"},
                                {"label": "Raw Docs", "value": f"{int((pipeline_result.get('index_report') or {}).get('raw_index_count', 0)):,}"},
                                {"label": "Wiki Docs", "value": f"{int((pipeline_result.get('index_report') or {}).get('wiki_index_count', 0)):,}"},
                            ]
                        )

    if not site_id:
        st.info("Create or open a workspace first.")
    else:
        pdf_dir = site_root / "sources" / "pdf_uploads"
        pdf_manifest_path = site_root / "sources" / "pdf_manifest.json"
        ingest_dir = site_root / "sources" / "pdf_ingest"
        pages_dir = site_root / "sources" / "pdf_pages"
        source_rows = _read_jsonl_rows(ingest_dir / "pdf_sources.jsonl")
        chunk_rows = _read_jsonl_rows(ingest_dir / "pdf_chunks.jsonl")
        quarantine_rows = _read_jsonl_rows(ingest_dir / "pdf_quarantine.jsonl")
        page_rows = []
        for pages_index in sorted(pages_dir.glob("*/pages.json")) if pages_dir.exists() else []:
            payload = read_json(pages_index, [])
            if isinstance(payload, list):
                page_rows.extend([row for row in payload if isinstance(row, dict)])
        sources_by_path = {str(row.get("path") or ""): row for row in source_rows}
        pdf_metrics = _summarize_pdf_rows(source_rows, page_rows, chunk_rows, quarantine_rows)
        if pdf_manifest and source_rows:
            changed = False
            for row in pdf_manifest:
                source = sources_by_path.get(str(row.get("path") or ""))
                if source:
                    row["status"] = "extracted" if source.get("accepted") else "quarantined"
                    row["page_count"] = source.get("page_count")
                    changed = True
            if changed:
                write_json(pdf_manifest_path, pdf_manifest)

        with doc_panel:
            st.markdown("Documents")
            uploaded_pdfs = st.file_uploader(
                "Upload PDFs",
                type=["pdf"],
                accept_multiple_files=True,
                key="choose_pdf_uploads",
            )
            if uploaded_pdfs:
                upload_signature = _pdf_upload_signature(uploaded_pdfs)
                if upload_signature and st.session_state.get("last_pdf_upload_signature") != upload_signature:
                    st.session_state["last_pdf_upload_signature"] = upload_signature
                    pdf_dir.mkdir(parents=True, exist_ok=True)
                    existing = {row.get("path"): row for row in pdf_manifest if isinstance(row, dict)}
                    for uploaded in uploaded_pdfs:
                        target = pdf_dir / _safe_uploaded_filename(uploaded.name)
                        target.write_bytes(uploaded.getbuffer())
                        existing[str(target)] = {
                            "name": uploaded.name,
                            "path": str(target),
                            "size_bytes": int(target.stat().st_size),
                            "added_at": datetime.now(timezone.utc).isoformat(),
                            "status": "extracting",
                        }
                    pdf_manifest = sorted(existing.values(), key=lambda row: row.get("name", ""))
                    write_json(pdf_manifest_path, pdf_manifest)
                    _start_pdf_extraction_job(site_root, pdf_manifest)
                    _render_pdf_live_status_loop(site_root)

            pdf_status = _read_pdf_extraction_status(site_root)
            if pdf_manifest:
                st.caption(f"{len(pdf_manifest):,} PDF document(s) uploaded.")
                queue_summary = _summarize_pdf_manifest_queue(pdf_manifest)
                if pdf_status.get("state") == "running":
                    _render_pdf_live_status_loop(site_root)
                else:
                    if pdf_status.get("state") == "complete":
                        st.success(
                            f"PDF extraction complete: {int(pdf_status.get('pages_done') or 0):,} page(s), "
                            f"{int(pdf_status.get('chunks') or 0):,} search chunks, "
                            f"{int(pdf_status.get('review') or 0):,} needing review."
                        )
                    elif pdf_status.get("state") == "interrupted":
                        st.warning("Previous PDF extraction was interrupted. Click Extract / Re-extract PDFs to restart with page-by-page progress.")
                    elif pdf_status.get("state") in {"failed", "parser_unavailable"}:
                        st.error(f"PDF extraction failed: {pdf_status.get('error') or 'unknown error'}")
                    if source_rows or chunk_rows or quarantine_rows:
                        _render_pdf_extraction_metrics(
                            pdfs_done=pdf_metrics["accepted"],
                            pdfs_total=len(pdf_manifest),
                            pages_done=pdf_metrics["pages_done"],
                            pages_total=queue_summary["pages"] if not queue_summary["unknown_pages"] else None,
                            chunks=pdf_metrics["chunks"],
                            review=pdf_metrics["quarantine"],
                        )
                        st.caption(f"{pdf_metrics['page_artifacts']:,} page artifact(s) prepared for the knowledge base.")
                        if pdf_metrics["unknown_page_sources"]:
                            st.caption(f"{pdf_metrics['unknown_page_sources']:,} extracted PDF(s) did not report a page count.")
                if st.button(
                    "Extract / Re-extract PDFs",
                    type="secondary",
                    key="extract_uploaded_pdfs_now",
                    disabled=pdf_status.get("state") == "running",
                ):
                    _start_pdf_extraction_job(site_root, pdf_manifest)
                    _render_pdf_live_status_loop(site_root)
            else:
                st.info("Upload PDFs to include documents in the source set.")

        if source_rows or chunk_rows or quarantine_rows:
            st.divider()
            st.markdown("Prepared Sources")
            prepared_cols = st.columns(3)
            prepared_cols[0].metric("Extracted documents", f"{len(source_rows):,}")
            prepared_cols[1].metric("Search chunks", f"{len(chunk_rows):,}")
            prepared_cols[2].metric("Needs review", f"{len(quarantine_rows):,}")

if active_tab == WORKFLOW_TABS[2]:
    st.subheader("Runs")
    runs_site_id = st.session_state.get("site_id", "")
    runs_selected_url_strings = _selected_url_strings_from_state()
    runs_run_id = st.session_state.get("run_id", "")
    runs_status = {}
    runs_pages = []
    runs_summary = None
    runs_status_stale = False
    runs_elapsed_label = "n/a"
    runs_eta_label = "n/a"
    runs_all_page_rows = []
    runs_pages_df = pd.DataFrame()
    runs_has_live_runner = bool(runs_run_id and runs_site_id and runner.has_live_run(runs_site_id, runs_run_id))
    if runs_run_id and runs_site_id:
        runs_status, loaded_pages, _runs_events = _load_scrape_runtime(runs_site_id, runs_run_id, max_events=1500)
        runs_status = runs_status or {}
        runs_pages = loaded_pages if isinstance(loaded_pages, list) else []
        runs_summary = derive_run_summary(
            status=runs_status,
            pages=runs_pages,
            selected_count=len(runs_selected_url_strings),
        )
        runs_status_stale = runs_summary.state in {"running", "pausing", "initializing"} and not runs_has_live_runner

    runs_operator_run = build_operator_run_status(
        state=runs_summary.state if runs_summary else ("ready" if runs_selected_url_strings else "none"),
        done=int(runs_summary.done) if runs_summary else 0,
        total=int(runs_summary.total) if runs_summary else len(runs_selected_url_strings),
        running=int(runs_summary.running) if runs_summary else 0,
        failed=int(runs_summary.failed) if runs_summary else 0,
        queued=int(runs_summary.queued) if runs_summary else len(runs_selected_url_strings),
        has_live_runner=runs_has_live_runner,
    )
    render_status_band(
        title="Scrape run",
        subtitle=runs_operator_run.message,
        status_label=runs_operator_run.state_label,
        tone=runs_operator_run.attention_level,
        action_label=runs_operator_run.primary_action,
    )
    st.markdown("Current Run")
    if not runs_site_id:
        st.info("Create or open a workspace first.")
    else:
        with st.container(key="runs_control_panel"):
            runs_controls = st.columns([1.05, 1.35, 0.9, 0.85, 0.85, 0.9, 1.55], gap="small", vertical_alignment="bottom")
            runs_concurrency = runs_controls[0].number_input(
                "Concurrency",
                min_value=1,
                max_value=16,
                value=int(st.session_state.get("scrape_concurrency", 10)),
                step=1,
                key="runs_scrape_concurrency",
            )
            st.session_state["scrape_concurrency"] = int(runs_concurrency)
            if runs_controls[1].button("Start New Scrape", type="primary", use_container_width=True, key="runs_start_new_scrape"):
                selected_urls = _rows_to_discovered_urls(st.session_state["selected_df"].to_dict("records"))
                selected_urls = [
                    item
                    for item in selected_urls
                    if (urlparse(item.url.strip()).scheme in {"http", "https"} and urlparse(item.url.strip()).netloc)
                ]
                if not selected_urls:
                    st.session_state["scrape_status_message"] = "No URLs selected. Add selected URLs before starting a scrape."
                    st.error("No URLs selected. Add selected URLs before starting a scrape.")
                else:
                    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
                    st.session_state["run_id"] = run_id
                    st.session_state["last_run_by_site"][runs_site_id] = run_id
                    _save_app_state()
                    st.session_state["scrape_status_message"] = "Starting new scrape run..."
                    with st.spinner("Starting new scrape run..."):
                        runner.start(
                            runs_site_id,
                            run_id,
                            selected_urls,
                            concurrency=int(runs_concurrency),
                            browser_mode=st.session_state.get("scrape_browser_mode", "none"),
                            lightpanda_cdp_url=st.session_state.get("lightpanda_cdp_url", ""),
                        )
                    st.session_state["scrape_status_message"] = f"Started scrape for {len(selected_urls):,} selected URLs."
                    st.success(f"Started scrape for {len(selected_urls):,} selected URLs.")
                    st.rerun()
            if runs_controls[2].button("Resume", disabled=not st.session_state["run_id"], use_container_width=True, key="runs_resume_scrape"):
                live_run = runner.has_live_run(runs_site_id, st.session_state["run_id"])
                resumed = runner.resume(
                    runs_site_id,
                    st.session_state["run_id"],
                    concurrency=int(runs_concurrency),
                    browser_mode=st.session_state.get("scrape_browser_mode", "none"),
                    lightpanda_cdp_url=st.session_state.get("lightpanda_cdp_url", ""),
                )
                if not resumed and live_run:
                    runner.unpause(runs_site_id, st.session_state["run_id"])
                    st.session_state["scrape_status_message"] = "Continuing paused in-memory run..."
                elif resumed:
                    st.session_state["scrape_status_message"] = "Resuming saved run from disk state..."
                else:
                    st.session_state["scrape_status_message"] = "No resumable pages were found for this run."
                st.rerun()
            if runs_controls[3].button("Pause", disabled=not st.session_state["run_id"], use_container_width=True, key="runs_pause_scrape"):
                runner.pause(runs_site_id, st.session_state["run_id"])
                st.session_state["scrape_status_message"] = "Pausing after in-flight pages finish..."
                st.rerun()
            if runs_controls[4].button("Cancel", disabled=not st.session_state["run_id"], use_container_width=True, key="runs_cancel_scrape"):
                runner.cancel(runs_site_id, st.session_state["run_id"])
                st.session_state["scrape_status_message"] = "Cancel requested. Stopping after in-flight pages finish..."
                st.rerun()
            if runs_controls[5].button("Refresh", use_container_width=True, key="runs_refresh"):
                st.rerun()
            runs_autorefresh = runs_controls[6].checkbox("Auto-refresh", value=False, key="runs_autorefresh")
            if runs_autorefresh and st_autorefresh is None:
                runs_controls[6].caption("Install `streamlit-autorefresh` for live auto-refresh. Use Refresh for now.")
            active_run_id = str(st.session_state.get("run_id") or "none")
            active_run_label_short = active_run_id if len(active_run_id) <= 46 else f"{active_run_id[:24]}…{active_run_id[-12:]}"
            st.markdown(
                "<div class=\"run-meta-line\">"
                f"<span class=\"run-meta-pill\">Selected URLs <strong>{len(runs_selected_url_strings):,}</strong></span>"
                f"<span class=\"run-meta-pill\">Active run <code title=\"{escape(active_run_id, quote=True)}\">{escape(active_run_label_short, quote=True)}</code></span>"
                "</div>",
                unsafe_allow_html=True,
            )

        if st.session_state["run_id"] and runs_summary:
            if runs_status_stale:
                runs_status["state"] = "stopped"
                runs_summary = derive_run_summary(
                    status=runs_status,
                    pages=runs_pages,
                    selected_count=len(runs_selected_url_strings),
                )
            runs_done = runs_summary.done
            runs_queued = runs_summary.queued
            runs_started_at = pd.to_datetime(runs_status.get("started_at"), errors="coerce", utc=True)
            runs_elapsed_seconds = 0.0
            if pd.notna(runs_started_at):
                runs_elapsed_seconds = max((datetime.now(timezone.utc) - runs_started_at.to_pydatetime()).total_seconds(), 0.0)
            runs_eta_seconds = (
                runs_queued / (runs_done / runs_elapsed_seconds)
                if runs_elapsed_seconds > 0 and runs_done > 0
                else None
            )
            runs_elapsed_label = f"{runs_elapsed_seconds/60.0:.1f} min" if runs_elapsed_seconds > 0 else "n/a"
            runs_eta_label = f"{runs_eta_seconds/60.0:.1f} min" if runs_eta_seconds is not None else "n/a"

            runs_page_rows_by_url: dict[str, dict] = {}
            for row in runs_pages:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or "").strip()
                if url:
                    runs_page_rows_by_url[url] = dict(row)
            for url in runs_selected_url_strings:
                if url not in runs_page_rows_by_url:
                    runs_page_rows_by_url[url] = {
                        "url": url,
                        "status": "queued",
                        "attempt": 0,
                        "worker_id": None,
                        "fetch_mode": None,
                        "http_status": None,
                        "failure_reason": None,
                        "started_at": None,
                        "finished_at": None,
                    }
            runs_all_page_rows = list(runs_page_rows_by_url.values())
            runs_pages_df = pd.DataFrame(runs_all_page_rows)
            if not runs_pages_df.empty:
                runs_pages_df["started_at"] = pd.to_datetime(runs_pages_df.get("started_at"), errors="coerce", utc=True)
                runs_pages_df["finished_at"] = pd.to_datetime(runs_pages_df.get("finished_at"), errors="coerce", utc=True)
                runs_pages_df["duration_sec"] = (
                    (runs_pages_df["finished_at"] - runs_pages_df["started_at"]).dt.total_seconds()
                ).round(2)
                runs_pages_df["duration_sec"] = runs_pages_df["duration_sec"].fillna(0.0)
                runs_pages_df["status"] = runs_pages_df.get("status", pd.Series(dtype=str)).fillna("queued").astype(str)
                attempt_series = runs_pages_df["attempt"] if "attempt" in runs_pages_df.columns else pd.Series(0, index=runs_pages_df.index)
                runs_pages_df["attempt"] = pd.to_numeric(attempt_series, errors="coerce").fillna(0).astype(int)
                runs_pages_df["updated_at"] = runs_pages_df["finished_at"].fillna(runs_pages_df["started_at"])
                runs_pages_df["updated_at_str"] = runs_pages_df["updated_at"].dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                runs_pages_df["updated_at_str"] = runs_pages_df["updated_at_str"].fillna("pending")
                status_rank = {"running": 0, "failed": 1, "success": 2, "cancelled": 3, "queued": 4}
                runs_pages_df["status_rank"] = runs_pages_df["status"].map(lambda s: status_rank.get(str(s).lower(), 5))

            runs_message = st.session_state.get("scrape_status_message")
            if runs_message and runs_summary.state not in {"completed", "cancelled", "failed"}:
                st.status(runs_message, state="running", expanded=False)
            progress_total = runs_summary.total if runs_summary.total > 0 else 1
            progress_done = min(runs_summary.success + runs_summary.failed, progress_total)
            st.progress(progress_done / progress_total, text=runs_summary.progress_label)
            r1, r2, r3, r4, r5 = st.columns(5)
            r1.metric("State", runs_summary.state)
            r2.metric("Markdown saved", f"{runs_summary.success:,}")
            r3.metric("Failed", f"{runs_summary.failed:,}")
            r4.metric("Remaining", f"{runs_summary.remaining:,}")
            r5.metric("ETA", runs_eta_label)
            impact_cols = st.columns(4)
            pages_per_min = (runs_summary.done / (runs_elapsed_seconds / 60.0)) if runs_elapsed_seconds > 0 else 0.0
            impact_cols[0].metric("Queued", f"{runs_summary.queued:,}")
            impact_cols[1].metric("Running", f"{runs_summary.running:,}")
            impact_cols[2].metric("Elapsed", runs_elapsed_label)
            impact_cols[3].metric("Pages / min", f"{pages_per_min:.1f}")
            if runs_status_stale:
                st.warning("This run is paused in the UI. Resume it to continue from saved progress.")

            with st.expander("Page outcomes", expanded=False):
                st.caption("Content Inspector")
                running_pages = latest_pages_by_status(runs_all_page_rows, "running", limit=8)
                if running_pages:
                    st.caption("Running")
                    running_df = pd.DataFrame(running_pages)
                    st.dataframe(
                        running_df[[c for c in ["url", "worker_id", "fetch_mode", "attempt", "started_at"] if c in running_df.columns]],
                        use_container_width=True,
                        hide_index=True,
                    )

                successful_pages = latest_pages_by_status(runs_all_page_rows, "success", limit=10)
                if successful_pages:
                    st.caption("Recently scraped")
                    recent_preview_rows = []
                    for row in successful_pages:
                        url = str(row.get("url") or "")
                        href = build_scraped_page_preview_href(
                            site_id=runs_site_id,
                            run_id=st.session_state["run_id"],
                            url=url,
                        )
                        source_path = _url_path_label(url, max_chars=110)
                        path_title = source_path.strip("/") or "Home"
                        title = str(row.get("title") or path_title or "Untitled page")
                        recent_preview_rows.append(
                            {
                                "Title": title[:120],
                                "Status": str(row.get("status") or "success"),
                                "Source path": source_path,
                                "Source URL": url,
                                "Scraped timestamp": str(row.get("finished_at") or row.get("started_at") or "unknown"),
                                "Preview URL": href,
                            }
                        )
                    recent_preview_df = pd.DataFrame(recent_preview_rows)
                    st.dataframe(
                        recent_preview_df[["Title", "Status", "Source path", "Scraped timestamp", "Preview URL"]],
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Preview URL": st.column_config.LinkColumn("Preview", display_text="Preview"),
                        },
                    )

                failed_pages = latest_pages_by_status(runs_all_page_rows, "failed", limit=10)
                if failed_pages:
                    st.caption("Failures")
                    failed_df = pd.DataFrame(failed_pages)
                    st.dataframe(
                        failed_df[[c for c in ["url", "failure_reason", "http_status", "attempt", "finished_at"] if c in failed_df.columns]],
                        use_container_width=True,
                        hide_index=True,
                    )

                st.markdown("#### All Pages")
                if runs_pages_df.empty:
                    st.info("Run initializing. Waiting for queue state to be published.")
                else:
                    f1, f2, f3, f4, f5 = st.columns([1.5, 1.4, 2.4, 1.4, 1.2])
                    status_options = sorted(runs_pages_df["status"].dropna().astype(str).unique().tolist())
                    default_statuses = ["running"] if "running" in status_options else []
                    selected_statuses = f1.multiselect(
                        "Status filter",
                        options=status_options,
                        default=default_statuses,
                        key="runs_live_status_filter",
                    )
                    slow_threshold = f2.number_input("Slow threshold (sec)", min_value=0, max_value=600, value=10, step=1)
                    url_query = f3.text_input("URL contains", value="", key="runs_live_url_query")
                    latest_only = f4.checkbox("Latest only", value=False, key="runs_live_latest_only")
                    wide_table = f5.checkbox("Wide table", value=True, key="runs_live_wide_table")

                    visible_df = runs_pages_df.copy()
                    if selected_statuses:
                        visible_df = visible_df[visible_df["status"].isin(selected_statuses)]
                    if url_query.strip():
                        visible_df = visible_df[
                            visible_df["url"].astype(str).str.contains(url_query.strip(), case=False, na=False, regex=False)
                        ]
                    visible_df["is_slow"] = visible_df["duration_sec"] >= float(slow_threshold)
                    if latest_only:
                        visible_df = visible_df.sort_values(
                            ["status_rank", "updated_at"], ascending=[True, False], na_position="last"
                        ).head(250)
                    else:
                        visible_df = visible_df.sort_values(
                            ["status_rank", "updated_at", "url"], ascending=[True, False, True], na_position="last"
                        )

                    if visible_df.empty:
                        st.info("No pages match the current filters.")
                    else:
                        table_df = visible_df[
                            [
                                c
                                for c in [
                                    "status",
                                    "url",
                                    "worker_id",
                                    "fetch_mode",
                                    "http_status",
                                    "failure_reason",
                                    "attempt",
                                    "duration_sec",
                                    "is_slow",
                                    "updated_at_str",
                                ]
                                if c in visible_df.columns
                            ]
                        ]
                        if wide_table:
                            page_size = int(st.selectbox("Rows per page", options=[100, 250, 500, 1000], index=1, key="runs_live_page_size"))
                            _render_paginated_df(table_df, key_prefix="runs_live_pages", default_page_size=page_size)
                        else:
                            _render_paginated_df(table_df, key_prefix="runs_live_pages", default_page_size=100)
                        waiting_for_first = bool(runs_summary.total > 0 and runs_summary.done == 0)
                        if waiting_for_first:
                            st.caption("Waiting for first page completion. Queue and worker activity are live.")

            _schedule_live_refresh(
                key="runs_live_autorefresh_tick",
                enabled=runs_autorefresh,
                active=runs_summary.state in {"running", "pausing", "paused", "initializing"},
                interval_seconds=1.0,
            )
        else:
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Total", f"{len(runs_selected_url_strings):,}")
            r2.metric("Queued", f"{len(runs_selected_url_strings):,}")
            r3.metric("Running", "0")
            r4.metric("State", "ready")
            st.progress(0.0, text="No active run")
            if runs_selected_url_strings:
                st.info(f"Ready to scrape {len(runs_selected_url_strings):,} selected URL(s).")
            else:
                st.info("No selected URLs yet.")
if active_tab == WORKFLOW_TABS[3]:
    st.subheader("Documents")
    site_id = st.session_state.get("site_id", "")
    if not site_id:
        st.info("Create or open a workspace first.")
    else:
        layout = site_layout(DATA_ROOT / "sites" / site_id)
        raw_status = _raw_source_status(layout)
        source_rows = _compact_source_rows(raw_status["rows"], layout)
        if source_rows:
            docs_df = pd.DataFrame(source_rows)
            available_groups = []
            if (docs_df["kind"] == "web").any():
                available_groups.append("Scraped URLs")
            if (docs_df["kind"] == "pdf").any():
                available_groups.append("PDF pages")
            if (~docs_df["kind"].isin(["web", "pdf"])).any():
                available_groups.append("Other documents")
            if not available_groups:
                available_groups = ["Other documents"]

            group_counts = {
                "Scraped URLs": int((docs_df["kind"] == "web").sum()),
                "PDF pages": int((docs_df["kind"] == "pdf").sum()),
                "Other documents": int((~docs_df["kind"].isin(["web", "pdf"])).sum()),
            }
            documents_group_key = "documents_source_group"
            documents_previous_group_key = "documents_previous_source_group"
            if st.session_state.get(documents_group_key) not in available_groups:
                st.session_state[documents_group_key] = available_groups[0]
            previous_group = st.session_state.get(documents_previous_group_key, st.session_state[documents_group_key])

            with st.container(border=True, key="documents_review_shell"):
                toolbar_left, toolbar_middle, toolbar_right = st.columns([1.0, 1.05, 1.35])
                source_group = toolbar_left.segmented_control(
                    "Choose source type",
                    options=available_groups,
                    format_func=lambda group: f"{group} ({group_counts.get(str(group), 0):,})",
                    key=documents_group_key,
                ) or available_groups[0]
                if source_group != previous_group:
                    st.session_state[documents_previous_group_key] = source_group
                    st.session_state["documents_filter"] = ""
                else:
                    st.session_state[documents_previous_group_key] = source_group

                group_docs = _documents_for_group(docs_df, str(source_group))
                with toolbar_middle:
                    selected_category = _document_category_selector(group_docs, source_group=str(source_group))
                doc_query = toolbar_right.text_input(
                    _document_search_label(str(source_group)),
                    value="",
                    placeholder=_document_search_placeholder(str(source_group)),
                    key="documents_filter",
                )

                visible_docs = group_docs.copy()
                if selected_category != "__all__" and "category_key" in visible_docs.columns:
                    visible_docs = visible_docs[visible_docs["category_key"] == selected_category]
                if doc_query.strip():
                    visible_docs = _filter_document_rows_by_search(visible_docs, doc_query, str(source_group))
                visible_docs = _sort_document_rows(visible_docs)

                source_col, preview_col = st.columns([0.95, 1.45], gap="large")
                with source_col:
                    st.subheader("Sources")
                    entry_label = "pages" if str(source_group) == "PDF pages" else "sources"
                    st.markdown(
                        f'<div class="document-preview-countline">{len(visible_docs):,} {entry_label} · index view</div>',
                        unsafe_allow_html=True,
                    )
                    if visible_docs.empty:
                        st.info("No sources match the current filter.")
                        selected_row = None
                    else:
                        selected_row = _document_source_picker(visible_docs, source_group=str(source_group))
                with preview_col:
                    st.subheader("Preview")
                    st.caption("Markdown preview")
                    if selected_row:
                        selected_source_id = str(selected_row.get("source_id") or "")
                        preview_loading_key = f"documents_loading_source_{_widget_key_token(str(source_group))}"
                        is_loading_preview = bool(
                            selected_source_id and st.session_state.get(preview_loading_key) == selected_source_id
                        )

                        def render_selected_preview() -> None:
                            preview_text, preview_error = _read_source_markdown(layout, str(selected_row["markdown"] or ""))
                            if preview_error:
                                st.warning(preview_error)
                            else:
                                _render_markdown_preview(
                                    preview_text,
                                    selected_row.get("title"),
                                    source_label=selected_row.get("display_path") or _document_source_subtitle(selected_row, str(source_group)),
                                )

                        if is_loading_preview:
                            with st.spinner("Loading selected source…"):
                                render_selected_preview()
                            st.session_state.pop(preview_loading_key, None)
                        else:
                            render_selected_preview()
                    else:
                        st.info("Choose a source to preview rendered Markdown.")
            render_operator_details(
                "Operator Details",
                {"Registry path:": str(layout.registry_path)},
                expanded=False,
            )
        else:
            st.info("Normalize scraped pages, PDFs, or tabular files to populate document rows.")


if active_tab == WORKFLOW_TABS[4]:
    st.subheader("Wiki")
    site_id = st.session_state.get("site_id", "")
    if not site_id:
        st.info("Create or open a workspace first.")
    else:
        layout = site_layout(DATA_ROOT / "sites" / site_id)
        raw_status = _raw_source_status(layout)
        raw_sources_ready = _raw_sources_ready(raw_status)
        wiki_status = _load_wiki_status(layout, raw_status)
        pending_by_kind = wiki_status.get("pending_source_count_by_kind") or {}
        pending_pdf_sources = int(pending_by_kind.get("pdf") or 0)
        pending_web_sources = int(pending_by_kind.get("web") or 0)
        pending_other_sources = max(int(wiki_status.get("pending_source_count") or 0) - pending_pdf_sources - pending_web_sources, 0)
        wiki_primary_action = _wiki_primary_action_label(wiki_status)
        wiki_tone = "ready" if _wiki_ready(wiki_status) else "warning"
        render_status_band(
            title="Wiki build",
            subtitle="Keep generated wiki pages synchronized with prepared web, PDF, and document sources.",
            status_label=str(wiki_status["job_status"]).replace("-", " ").title(),
            tone=wiki_tone,
            action_label=wiki_primary_action if raw_sources_ready else "Prepare documents",
        )

        if not raw_sources_ready:
            st.warning("Blocked: prepare source documents before building the LLM Wiki.")

        selected_wiki_runtime = "python"
        st.caption("Wiki builder runtime: `Python deterministic` — runs the local non-interactive wiki builder directly in tmux.")
        source_cols = st.columns(5)
        source_cols[0].metric("Sources Ready", f"{int(wiki_status.get('source_count') or 0):,}")
        source_cols[1].metric("Sources Waiting", f"{int(wiki_status.get('pending_source_count') or 0):,}")
        source_cols[2].metric("PDF Waiting", f"{pending_pdf_sources:,}")
        source_cols[3].metric("Web Waiting", f"{pending_web_sources:,}")
        source_cols[4].metric("Changed", f"{int(wiki_status.get('changed_source_count') or 0):,}")
        if pending_other_sources:
            st.caption(f"Other source types waiting: `{pending_other_sources:,}`")

        build_col, update_col = st.columns([1, 1])
        build_disabled = not raw_sources_ready
        update_disabled = not raw_sources_ready or int(wiki_status.get("pending_source_count") or 0) <= 0
        if build_col.button("Build Wiki", type="primary", disabled=build_disabled, key="build_llm_wiki"):
            launch_result = launch_wiki_builder(layout.site_root, runner=tmux_runner, resume=False, rebuild=True, runtime=selected_wiki_runtime)
            if launch_result.get("ok"):
                launch_runtime = launch_result.get("runtime", selected_wiki_runtime)
                st.session_state["wiki_build_launch_notice"] = {
                    "tmux_session": launch_result["session_name"],
                    "report_path": launch_result["report_path"],
                    "runtime": launch_runtime,
                }
                st.success("Started wiki build.")
                st.caption(f"Runtime: `{launch_runtime}`")
                st.rerun()
            else:
                st.error(launch_result.get("error") or "Failed to start LLM Wiki builder.")
        if update_col.button("Update Wiki", type="primary", disabled=update_disabled, key="update_llm_wiki"):
            launch_result = launch_wiki_builder(layout.site_root, runner=tmux_runner, resume=True, runtime=selected_wiki_runtime)
            if launch_result.get("ok"):
                launch_runtime = launch_result.get("runtime", selected_wiki_runtime)
                st.session_state["wiki_build_launch_notice"] = {
                    "tmux_session": launch_result["session_name"],
                    "report_path": launch_result["report_path"],
                    "runtime": launch_runtime,
                }
                st.success("Started wiki update.")
                st.caption(f"Runtime: `{launch_runtime}`")
                st.rerun()
            else:
                st.error(launch_result.get("error") or "Failed to start LLM Wiki update.")
        wiki_job_state = str(wiki_status.get("job_status") or "").lower()
        wiki_agent_active = wiki_job_state in {"running", "queued", "starting", "initializing"}
        if wiki_agent_active:
            st.info("Wiki builder is running. This page auto-refreshes while activity is in progress.")
        _schedule_live_refresh(
            key="wiki_agent_activity_autorefresh_tick",
            enabled=True,
            active=wiki_agent_active,
            interval_seconds=1.0,
        )

        w1, w2, w3, w4 = st.columns(4)
        w1.metric("Job Status", wiki_status["job_status"])
        w2.metric("Pages Created", f"{wiki_status['pages_created']:,}")
        w3.metric("Pages Updated", f"{wiki_status['pages_updated']:,}")
        w4.metric("Review Queue", f"{wiki_status['review_queue_count']:,}")
        st.caption(f"Last progress update: `{wiki_status['last_progress'] or 'not reported'}`")
        display_wiki_runtime = str(wiki_status.get("runtime") or selected_wiki_runtime)
        st.caption(f"Runtime: `{display_wiki_runtime}`")
        st.metric("Integrated Sources", f"{wiki_status['integrated_sources']:,}")
        with st.container(border=True, key="wiki_build_activity"):
            st.markdown("### Build activity")
            activity_cols = st.columns(4)
            activity_cols[0].metric("Runtime", display_wiki_runtime)
            activity_cols[1].metric("State", wiki_status["job_status"])
            activity_cols[2].metric("Sources", f"{wiki_status['integrated_sources']:,}")
            activity_cols[3].metric("Pages", f"{wiki_status['pages_created'] + wiki_status['pages_updated']:,}")
            wiki_log_tail = _tail_text(Path(wiki_status["log_path"]), max_lines=8)
            if wiki_log_tail:
                with st.expander("Latest builder log", expanded=wiki_agent_active):
                    st.code(wiki_log_tail[-4000:], language="markdown")
            else:
                st.caption("Build log output will appear after the wiki builder starts.")
        st.markdown("### Generated Markdown")
        wiki_markdown_files = _list_wiki_markdown_files(layout.wiki_dir)
        if wiki_markdown_files:
            wiki_records = _wiki_markdown_records(wiki_markdown_files)
            wiki_list_col, wiki_preview_col = st.columns([0.95, 1.45], gap="large")
            with wiki_list_col:
                st.subheader("Wiki pages")
                wiki_query = st.text_input(
                    "Search wiki pages",
                    value="",
                    placeholder="Title, section, or path",
                    key="wiki_markdown_filter",
                )
                visible_wiki_records = _filter_wiki_markdown_records(wiki_records, wiki_query)
                st.markdown(
                    f'<div class="document-preview-countline">{len(visible_wiki_records):,} pages · index view</div>',
                    unsafe_allow_html=True,
                )
                if visible_wiki_records:
                    selected_wiki_record = _wiki_markdown_picker(visible_wiki_records)
                else:
                    st.info("No wiki pages match the current search.")
                    selected_wiki_record = None

            with wiki_preview_col:
                st.subheader("Preview")
                if selected_wiki_record:
                    selected_wiki_file = str(selected_wiki_record.get("path") or "")
                    wiki_loading_key = "wiki_loading_markdown_file"
                    is_loading_wiki_preview = bool(
                        selected_wiki_file and st.session_state.get(wiki_loading_key) == selected_wiki_file
                    )

                    def render_wiki_markdown_preview() -> None:
                        selected_markdown, selected_markdown_error = _read_wiki_markdown(layout, selected_wiki_file)
                        if selected_markdown_error:
                            st.warning(selected_markdown_error)
                            return
                        page_metadata = _parse_markdown_frontmatter(selected_markdown)
                        if page_metadata:
                            meta_cols = st.columns(4)
                            meta_cols[0].metric("Sources", f"{len(page_metadata.get('source_ids') or []):,}")
                            meta_cols[1].metric("Audience", ", ".join(page_metadata.get("audiences") or ["general"])[:80])
                            meta_cols[2].metric("Intent", ", ".join(page_metadata.get("intents") or ["explore"])[:80])
                            meta_cols[3].metric("Owner", str(page_metadata.get("canonical_owner") or selected_wiki_file)[:80])
                            citations = page_metadata.get("source_paths") or []
                            if citations:
                                st.caption("Citations: " + ", ".join(f"`{item}`" for item in citations[:8]))
                        with st.container(border=True, key="wiki_markdown_preview"):
                            st.markdown(
                                _rewrite_wiki_markdown_links(
                                    _strip_temp_clipboard_images(_strip_markdown_frontmatter(selected_markdown)),
                                    current_rel_path=selected_wiki_file,
                                    site_id=site_id,
                                )
                            )

                    if is_loading_wiki_preview:
                        with st.spinner("Loading selected wiki page…"):
                            render_wiki_markdown_preview()
                        st.session_state.pop(wiki_loading_key, None)
                    else:
                        render_wiki_markdown_preview()
                else:
                    st.info("Choose a wiki page to preview generated Markdown.")
        else:
            st.info("Generated Markdown files will appear after the wiki build creates `wiki/*.md` artifacts.")


if active_tab == WORKFLOW_TABS[5]:
    st.subheader("Embeddings")
    site_id = st.session_state.get("site_id", "")
    if not site_id:
        st.info("Create or open a workspace first.")
    else:
        layout = site_layout(DATA_ROOT / "sites" / site_id)
        raw_status = _raw_source_status(layout)
        wiki_status = _load_wiki_status(layout, raw_status)
        embedding_status = _load_embedding_status(layout)
        raw_ready = _raw_sources_ready(raw_status)
        wiki_ready = _wiki_ready(wiki_status)
        can_build_index = raw_ready and wiki_ready

        render_status_band(
            title="Wiki and source index",
            subtitle="Embeds generated wiki pages plus the underlying source documents into the local LLM Wiki index.",
            status_label=str(embedding_status["index_health"]).replace("_", " ").title(),
            tone="ready" if embedding_status["index_health"] == "ready" else "warning",
            action_label="Build embeddings" if can_build_index else "Build wiki first",
        )
        if not raw_ready:
            st.warning("Blocked: prepare source documents before building embeddings.")
        elif not wiki_ready:
            st.warning("Blocked: build the LLM Wiki before embedding/indexing.")

        build_index_col, refresh_index_col = st.columns([1, 1])
        if build_index_col.button("Build / Rebuild Embeddings", type="primary", disabled=not can_build_index, key="build_llm_wiki_index"):
            with st.spinner("Building LLM Wiki index..."):
                try:
                    index_report = build_llm_wiki_index(layout.site_root)
                except Exception as exc:
                    st.error(f"Embedding build failed: {exc}")
                else:
                    st.success(
                        f"Indexed {int(index_report.get('raw_index_count') or 0):,} raw document chunk(s) and "
                        f"{int(index_report.get('wiki_index_count') or 0):,} wiki chunk(s)."
                    )
                    st.rerun()
        if refresh_index_col.button("Refresh Embedding Status", key="refresh_embedding_status"):
            st.rerun()

        e1, e2, e3, e4, e5 = st.columns(5)
        e1.metric("Raw Docs", f"{embedding_status['raw_index_count']:,}")
        e2.metric("Wiki Docs", f"{embedding_status['wiki_index_count']:,}")
        e3.metric("Changed Docs", f"{embedding_status['changed_document_count']:,}")
        e4.metric("Reranker", "ready" if embedding_status["reranker_ready"] else "not ready")
        e5.metric("Index Health", embedding_status["index_health"])
        latest_embedding_report = embedding_status.get("latest_report") or {}
        embedding_meta = latest_embedding_report.get("embedding") if isinstance(latest_embedding_report, dict) else {}
        reranker_meta = latest_embedding_report.get("reranker") if isinstance(latest_embedding_report, dict) else {}
        detail_rows = [
            {"Metric": "Embedding provider", "Value": str((embedding_meta or {}).get("provider") or "n/a")},
            {"Metric": "Embedding model", "Value": str((embedding_meta or {}).get("model") or "n/a")},
            {"Metric": "Vector dimensions", "Value": str((embedding_meta or {}).get("vector_dimensions") or "n/a")},
            {"Metric": "Reranker provider", "Value": str((reranker_meta or {}).get("provider") or "n/a")},
            {"Metric": "Reranker model", "Value": str((reranker_meta or {}).get("model") or "n/a")},
            {"Metric": "Last build time", "Value": embedding_status.get("last_build_time") or "n/a"},
        ]
        st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)
if active_tab == WORKFLOW_TABS[6]:
    st.subheader("Metrics")
    st.caption("Request and cost metrics are estimated from recorded run/site events plus configured provider pricing.")
    if not st.session_state.get("site_id"):
        st.info("Select or create a site first.")
    else:
        site_root = DATA_ROOT / "sites" / st.session_state["site_id"]
        run_choices = sorted([d.name for d in site_root.iterdir() if d.is_dir() and d.name != "meta"]) if site_root.exists() else []
        real_run_choices = [name for name in run_choices if _is_real_scrape_run(st.session_state["site_id"], name)]
        if not real_run_choices:
            st.info("No scrape runs are available yet. Start a scrape to populate metrics.")
        else:
            model_map = {m.get("id"): m for m in st.session_state.get("openrouter_models", [])}
            tavily_per_call = float(st.session_state.get("tavily_cost_per_call_usd", 0.0))
            ollama_in_per_m = float(st.session_state.get("ollama_input_per_m_usd", 0.0))
            ollama_out_per_m = float(st.session_state.get("ollama_output_per_m_usd", 0.0))

            st.markdown("### Metrics To Date")
            window_label = st.selectbox(
                "Date range",
                options=["Last 7 days", "Last 30 days", "Last 3 months", "Last 6 months", "Last year", "All time"],
                index=1,
                key="metrics_to_date_window",
                help="Filters run-level rollups by run start time.",
            )
            run_metric_rows = [
                _build_run_metrics_row(
                    site_id=st.session_state["site_id"],
                    run_id=run_name,
                    site_root=site_root,
                    model_map=model_map,
                    tavily_per_call=tavily_per_call,
                    ollama_in_per_m=ollama_in_per_m,
                    ollama_out_per_m=ollama_out_per_m,
                )
                for run_name in real_run_choices
            ]
            metrics_df = pd.DataFrame(run_metric_rows)
            if metrics_df.empty:
                st.info("No run metrics are available for this site yet.")
            else:
                metrics_df["run_ts"] = pd.to_datetime(metrics_df["run_ts"], errors="coerce", utc=True)
                window_start = _metrics_window_start(window_label)
                filtered_metrics_df = metrics_df if window_start is None else metrics_df[metrics_df["run_ts"].isna() | (metrics_df["run_ts"] >= window_start)]
                filtered_metrics_df = filtered_metrics_df.copy()
                if filtered_metrics_df.empty:
                    st.info(f"No runs match {window_label.lower()}.")
                else:
                    total_done = int(filtered_metrics_df["done_pages"].sum())
                    total_scraped = int(filtered_metrics_df["scraped_pages"].sum())
                    total_failed = int(filtered_metrics_df["failed_pages"].sum())
                    total_elapsed_min = float(filtered_metrics_df["elapsed_min"].sum())
                    success_rate = (total_scraped / total_done * 100.0) if total_done > 0 else 0.0
                    aggregate_ppm = (total_done / total_elapsed_min) if total_elapsed_min > 0 else 0.0
                    render_metric_strip(
                        [
                            {"label": "Runs", "value": _fmt_compact_number(float(len(filtered_metrics_df)))},
                            {"label": "Selected URLs", "value": _fmt_compact_number(float(filtered_metrics_df["selected_urls"].sum()))},
                            {"label": "Scraped Pages", "value": _fmt_compact_number(float(total_scraped))},
                            {"label": "Failed Pages", "value": _fmt_compact_number(float(total_failed))},
                        ]
                    )
                    render_metric_strip(
                        [
                            {"label": "Success Rate", "value": f"{success_rate:.1f}%"},
                            {"label": "Pages / Min", "value": f"{aggregate_ppm:.2f}"},
                            {"label": "Provider Requests", "value": _fmt_compact_number(float(filtered_metrics_df["provider_requests"].sum()))},
                            {"label": "Est. Cost", "value": _fmt_usd(float(filtered_metrics_df["cost_usd"].sum()))},
                        ]
                    )

                    usage_chart_data = _metrics_usage_chart_data(filtered_metrics_df)
                    if usage_chart_data:
                        grouped_usage = usage_chart_data["grouped"]
                        pages_long = usage_chart_data["pages_long"]
                        x_title = str(usage_chart_data["x_title"])
                        tooltip_bucket = (
                            alt.Tooltip("bucket:N", title=x_title)
                            if usage_chart_data["grain"] == "run"
                            else alt.Tooltip("bucket:T", title=x_title)
                        )
                        page_y_max = _nice_metric_axis_max(float(grouped_usage["page_total"].max()), minimum=1.0)
                        cost_max = float(grouped_usage["cost_usd"].max())
                        cost_y_max = _nice_metric_axis_max(cost_max, minimum=0.01 if cost_max < 1 else 1.0)
                        cost_format = _metric_money_axis_format(cost_y_max)
                        page_types = list(pages_long["page_type"].drop_duplicates())
                        page_colors = ["#cc785c", "#bf5c54"][: len(page_types)]
                        td1, td2 = st.columns(2)
                        td1.altair_chart(
                            alt.Chart(pages_long)
                            .mark_bar(cornerRadiusTopRight=4, cornerRadiusTopLeft=4)
                            .encode(
                                x=usage_chart_data["x_encoding"],
                                y=alt.Y(
                                    "pages:Q",
                                    title="Pages",
                                    stack=True,
                                    axis=alt.Axis(format=",.0f", tickMinStep=1, tickCount=5),
                                    scale=alt.Scale(domain=[0, page_y_max]),
                                ),
                                color=alt.Color(
                                    "page_type:N",
                                    title="Outcome",
                                    scale=alt.Scale(domain=page_types, range=page_colors),
                                ),
                                tooltip=[
                                    tooltip_bucket,
                                    alt.Tooltip("page_type:N", title="Outcome"),
                                    alt.Tooltip("pages:Q", title="Pages", format=",.0f"),
                                    alt.Tooltip("runs:Q", title="Runs", format=",.0f"),
                                ],
                            )
                            .properties(height=260, title=f"Pages by {x_title.lower()}"),
                            use_container_width=True,
                        )
                        td2.altair_chart(
                            alt.Chart(grouped_usage)
                            .mark_bar(cornerRadiusTopRight=4, cornerRadiusTopLeft=4, color="#cc785c")
                            .encode(
                                x=usage_chart_data["x_encoding"],
                                y=alt.Y(
                                    "cost_usd:Q",
                                    title="Estimated Cost (USD)",
                                    axis=alt.Axis(format=cost_format, tickCount=5),
                                    scale=alt.Scale(domain=[0, cost_y_max]),
                                ),
                                tooltip=[
                                    tooltip_bucket,
                                    alt.Tooltip("cost_usd:Q", title="Cost", format=cost_format),
                                    alt.Tooltip("provider_requests:Q", title="Provider Requests", format=",.0f"),
                                    alt.Tooltip("runs:Q", title="Runs", format=",.0f"),
                                ],
                            )
                            .properties(height=260, title=f"Cost by {x_title.lower()}"),
                            use_container_width=True,
                        )

                    per_run_display = filtered_metrics_df.sort_values("run_ts", ascending=False, na_position="last").copy()
                    per_run_display["Run"] = per_run_display["run_label"]
                    per_run_display["Selected"] = per_run_display["selected_urls"].map(lambda value: _fmt_compact_number(float(value)))
                    per_run_display["Scraped"] = per_run_display["scraped_pages"].map(lambda value: _fmt_compact_number(float(value)))
                    per_run_display["Failed"] = per_run_display["failed_pages"].map(lambda value: _fmt_compact_number(float(value)))
                    per_run_display["Cleaned"] = per_run_display["cleaned_pages"].map(lambda value: _fmt_compact_number(float(value)))
                    per_run_display["Success %"] = per_run_display["success_rate"].map(lambda value: f"{float(value):.1f}%")
                    per_run_display["Pages/min"] = per_run_display["pages_per_min"].map(lambda value: f"{float(value):.2f}")
                    per_run_display["Requests"] = per_run_display["provider_requests"].map(lambda value: _fmt_compact_number(float(value)))
                    per_run_display["Cost"] = per_run_display["cost_usd"].map(lambda value: _fmt_usd(float(value)))
                    st.caption("Per-run metrics in the selected date range")
                    st.dataframe(
                        per_run_display[["Run", "state", "Selected", "Scraped", "Failed", "Cleaned", "Success %", "Pages/min", "Requests", "Cost", "run_id"]],
                        use_container_width=True,
                        hide_index=True,
                    )

            st.markdown("### Detailed Metrics Per Run")
            load_detailed_run_metrics = st.toggle(
                "Load detailed metrics per run",
                value=False,
                key="metrics_load_run_metrics",
                help="Keep this off for the fast to-date dashboard. Turn it on when you want charts and provider events for one selected run.",
            )
            if not load_detailed_run_metrics:
                st.info("Turn this on to inspect one run's timeline, failures, provider usage, and event table.")
            else:
                latest_run = real_run_choices[-1]
                current_selected = st.session_state.get("metrics_run", "")
                selected_run = current_selected if current_selected in real_run_choices else latest_run
                metrics_run = st.selectbox(
                    "Run",
                    options=real_run_choices,
                    index=real_run_choices.index(selected_run),
                    key="metrics_run",
                    format_func=lambda run_name: f"Run {_run_human_timestamp(run_name)}",
                )
                run_root = site_root / metrics_run
                st.markdown("#### Selected Run Detail")
                run_events = load_events(run_root)
                site_events = load_events(site_root / "meta")
                trace_df = _build_trace_df(
                    run_events=run_events,
                    site_events=site_events,
                    model_map=model_map,
                    tavily_per_call=tavily_per_call,
                    ollama_in_per_m=ollama_in_per_m,
                    ollama_out_per_m=ollama_out_per_m,
                )
                pages, failures, run_status, _scrape_events = _load_run_analytics_inputs(st.session_state["site_id"], metrics_run, run_root)
                selected_urls = read_json(run_root / "selected_urls.json", [])
                cleanup_manifest = read_json(run_root / "cleanup_manifest.json", [])
                cleaned_pages = [r for r in cleanup_manifest if isinstance(r, dict) and r.get("status") == "cleaned"]
                skipped_pages = [r for r in cleanup_manifest if isinstance(r, dict) and r.get("status") == "skipped"]
                total_hint = len(selected_urls) if isinstance(selected_urls, list) else None
                page_summary = summarize_pages(pages, run_status=run_status, total_hint=total_hint)
                duration_summary = summarize_durations(pages)
                completion_df = build_completion_timeseries(pages)
                slow_pages_df = build_slowest_pages_table(pages)
                failure_summary = summarize_failures(pages, failures)
                output_summary = summarize_output_volume(pages)

                with st.container(border=True):
                    st.caption("Run Summary")
                    ra1, ra2, ra3, ra4, ra5 = st.columns(5)
                    ra1.metric("Selected URLs", _fmt_compact_number(len(selected_urls) if isinstance(selected_urls, list) else 0))
                    ra2.metric("Scraped Pages", _fmt_compact_number(int(page_summary.get("success", 0))))
                    ra3.metric("Cleaned Pages", _fmt_compact_number(len(cleaned_pages)))
                    ra4.metric("Skipped Pages", _fmt_compact_number(len(skipped_pages)))
                    ra5.metric("Failed Pages", _fmt_compact_number(int(page_summary.get("failed", 0))))
                    rb1, rb2, rb3, rb4, rb5 = st.columns(5)
                    rb1.metric("Elapsed", f"{float(page_summary.get('elapsed_sec', 0.0)) / 60.0:.1f} min")
                    rb2.metric("Pages / min", f"{float(page_summary.get('pages_per_min', 0.0)):.2f}")
                    eta_value = page_summary.get("eta_min")
                    rb3.metric("ETA", "n/a" if eta_value is None else f"{float(eta_value):.1f} min")
                    rb4.metric("P50 Duration", f"{float(duration_summary.get('p50_sec', 0.0)):.2f} s")
                    rb5.metric("P95 Duration", f"{float(duration_summary.get('p95_sec', 0.0)):.2f} s")
                    rc1, rc2, rc3 = st.columns(3)
                    rc1.metric("Markdown Bytes", _fmt_compact_number(int(output_summary.get("markdown_total_bytes", 0))))
                    rc2.metric("Raw HTML Bytes", _fmt_compact_number(int(output_summary.get("raw_html_total_bytes", 0))))
                    rc3.metric("Avg Text Length", _fmt_compact_number(float(output_summary.get("text_avg", 0.0))))

                if completion_df.empty:
                    st.info("No completed pages yet for scrape charts.")
                else:
                    cts1, cts2 = st.columns(2)
                    cts1.altair_chart(
                        alt.Chart(completion_df)
                        .mark_line(point=alt.OverlayMarkDef(size=22, filled=True))
                        .encode(x=alt.X("bucket:T", title="Time"), y=alt.Y("completed:Q", title="Pages Completed"), tooltip=["bucket:T", "completed:Q", "success:Q", "failed:Q", "cancelled:Q"])
                        .properties(height=300),
                        use_container_width=True,
                    )
                    cts2.altair_chart(
                        alt.Chart(completion_df)
                        .mark_line(point=alt.OverlayMarkDef(size=22, filled=True))
                        .encode(x=alt.X("bucket:T", title="Time"), y=alt.Y("ppm:Q", title="Pages / Minute"), tooltip=["bucket:T", "ppm:Q"])
                        .properties(height=300),
                        use_container_width=True,
                    )

                fr1, fr2, fr3 = st.columns(3)
                for target, df, title in [
                    (fr1, failure_summary["by_reason"], "Reason"),
                    (fr2, failure_summary["by_fetch_mode"], "Fetch Mode"),
                    (fr3, failure_summary["by_http_status"], "HTTP Status"),
                ]:
                    if df.empty:
                        target.info(f"No failures by {title.lower()} yet.")
                    else:
                        target.altair_chart(
                            alt.Chart(df.sort_values("count", ascending=False))
                            .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                            .encode(x=alt.X("count:Q", title="Count"), y=alt.Y("label:N", title=title, sort="-x"), tooltip=["label", "count"])
                            .properties(height=240),
                            use_container_width=True,
                        )
                if not slow_pages_df.empty:
                    st.caption("Slowest Pages")
                    st.dataframe(slow_pages_df, use_container_width=True, hide_index=True)

                st.markdown("### Provider Requests And Cost")
                if trace_df.empty:
                    st.info("No OpenRouter, Tavily, or Ollama events are recorded for this run yet.")
                else:
                    trace_df["ts"] = pd.to_datetime(trace_df.get("ts"), errors="coerce", utc=True)
                    trace_df["provider"] = trace_df.get("provider", "unknown").fillna("unknown").astype(str)
                    trace_df["operation"] = trace_df.get("operation", "unknown").fillna("unknown").astype(str)
                    trace_df["model"] = trace_df.get("model", "unknown").fillna("unknown").astype(str)
                    trace_df["prompt_tokens"] = pd.to_numeric(trace_df.get("prompt_tokens"), errors="coerce").fillna(0.0)
                    trace_df["completion_tokens"] = pd.to_numeric(trace_df.get("completion_tokens"), errors="coerce").fillna(0.0)
                    trace_df["total_tokens"] = pd.to_numeric(trace_df.get("total_tokens"), errors="coerce").fillna(trace_df["prompt_tokens"] + trace_df["completion_tokens"])
                    trace_df["cost_usd"] = pd.to_numeric(trace_df.get("cost_usd"), errors="coerce").fillna(0.0)
                    billable_trace = trace_df[~trace_df.get("is_summary", pd.Series(False, index=trace_df.index)).fillna(False).astype(bool)].copy()
                    provider_counts = billable_trace.groupby("provider", as_index=False).size().rename(columns={"size": "requests"}).sort_values("requests", ascending=False)
                    model_counts = billable_trace.groupby(["provider", "model"], as_index=False).size().rename(columns={"size": "requests"}).sort_values("requests", ascending=False)
                    operation_counts = billable_trace.groupby(["provider", "operation"], as_index=False).size().rename(columns={"size": "requests"}).sort_values("requests", ascending=False)
                    cost_by_provider = billable_trace.groupby("provider", as_index=False)["cost_usd"].sum().sort_values("cost_usd", ascending=False)
                    token_ts = billable_trace.dropna(subset=["ts"]).copy()
                    if not token_ts.empty:
                        token_ts["bucket"] = token_ts["ts"].dt.floor("min")
                        token_ts = token_ts.groupby(["bucket", "provider"], as_index=False)[["prompt_tokens", "completion_tokens", "total_tokens", "cost_usd"]].sum()

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Provider Requests", _fmt_compact_number(float(len(billable_trace))))
                    m2.metric("OpenRouter", _fmt_compact_number(float((billable_trace["provider"] == "openrouter").sum())))
                    m3.metric("Tavily", _fmt_compact_number(float((billable_trace["provider"] == "tavily").sum())))
                    m4.metric("Ollama", _fmt_compact_number(float((billable_trace["provider"] == "ollama").sum())))

                    p1, p2 = st.columns(2)
                    p1.altair_chart(
                        alt.Chart(provider_counts)
                        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                        .encode(x=alt.X("requests:Q", title="Requests"), y=alt.Y("provider:N", title="Provider", sort="-x"), tooltip=["provider", "requests"])
                        .properties(height=260),
                        use_container_width=True,
                    )
                    p2.altair_chart(
                        alt.Chart(cost_by_provider)
                        .mark_arc(innerRadius=45)
                        .encode(theta=alt.Theta("cost_usd:Q", title="Estimated Cost"), color=alt.Color("provider:N", title="Provider"), tooltip=["provider", "cost_usd"])
                        .properties(height=260),
                        use_container_width=True,
                    )
                    p3, p4 = st.columns(2)
                    p3.altair_chart(
                        alt.Chart(model_counts.head(30))
                        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                        .encode(x=alt.X("requests:Q", title="Requests"), y=alt.Y("model:N", title="Model", sort="-x"), color=alt.Color("provider:N", title="Provider"), tooltip=["provider", "model", "requests"])
                        .properties(height=360),
                        use_container_width=True,
                    )
                    p4.altair_chart(
                        alt.Chart(operation_counts.head(30))
                        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                        .encode(x=alt.X("requests:Q", title="Requests"), y=alt.Y("operation:N", title="Operation", sort="-x"), color=alt.Color("provider:N", title="Provider"), tooltip=["provider", "operation", "requests"])
                        .properties(height=360),
                        use_container_width=True,
                    )
                    if token_ts.empty:
                        st.info("No token or cost time series data yet.")
                    else:
                        t1, t2 = st.columns(2)
                        t1.altair_chart(
                            alt.Chart(token_ts)
                            .mark_area(opacity=0.7)
                            .encode(x=alt.X("bucket:T", title="Time"), y=alt.Y("total_tokens:Q", title="Tokens"), color=alt.Color("provider:N", title="Provider"), tooltip=["bucket:T", "provider", "total_tokens"])
                            .properties(height=300),
                            use_container_width=True,
                        )
                        t2.altair_chart(
                            alt.Chart(token_ts)
                            .mark_line(point=alt.OverlayMarkDef(size=18, filled=True))
                            .encode(x=alt.X("bucket:T", title="Time"), y=alt.Y("cost_usd:Q", title="Estimated Cost (USD)"), color=alt.Color("provider:N", title="Provider"), tooltip=["bucket:T", "provider", "cost_usd"])
                            .properties(height=300),
                            use_container_width=True,
                        )
                    with st.expander("Provider event table", expanded=False):
                        st.dataframe(
                            billable_trace[[c for c in ["ts", "provider", "operation", "model", "status", "prompt_tokens", "completion_tokens", "total_tokens", "latency_ms", "cost_usd"] if c in billable_trace.columns]],
                            use_container_width=True,
                            hide_index=True,
                        )
if active_tab == WORKFLOW_TABS[7]:
    st.subheader("Settings")
    st.caption("Configure local providers, models, scraping, retrieval, and research.")

    status_cols = st.columns(4)
    status_cols[0].metric("OpenRouter", "set" if st.session_state.get("openrouter_api_key") else "missing")
    status_cols[1].metric("Scraper", st.session_state.get("scrape_browser_mode", "none"))
    status_cols[2].metric("Concurrency", int(st.session_state.get("scrape_concurrency", 10)))
    status_cols[3].metric("Vector", "on" if st.session_state.get("zvec_enabled", True) else "off")

    settings_tabs = st.tabs(["Keys", "LLM", "Scraping", "Indexing", "Research"])

    with settings_tabs[0]:
        st.caption("API keys are stored locally in `.env`.")
        with st.container(border=True):
            st.markdown("**OpenRouter**")
            or1, or2 = st.columns([3, 1])
            openrouter_key = or1.text_input(
                "OPENROUTER_API_KEY",
                value=st.session_state.get("openrouter_api_key", ""),
                type="password",
                label_visibility="collapsed",
                placeholder="sk-or-...",
                help="Used for URL reasoning, graph labeling, and Q&A when selected.",
            )
            if or2.button("Save", key="save_openrouter_key", use_container_width=True):
                _save_env_key(ENV_PATH, "OPENROUTER_API_KEY", openrouter_key.strip())
                st.session_state["openrouter_api_key"] = openrouter_key.strip()
                os.environ["OPENROUTER_API_KEY"] = openrouter_key.strip()
                _save_app_state()
                st.success("Saved OpenRouter key")

        with st.container(border=True):
            st.markdown("**Tavily**")
            tav1, tav2 = st.columns([3, 1])
            tavily_key = tav1.text_input(
                "TAVILY_API_KEY",
                value=st.session_state.get("tavily_api_key", ""),
                type="password",
                label_visibility="collapsed",
                placeholder="tvly-...",
                help="Optional. Used for university map research and failed-source recovery when enabled.",
            )
            if tav2.button("Save", key="save_tavily_key", use_container_width=True):
                _save_env_key(ENV_PATH, "TAVILY_API_KEY", tavily_key.strip())
                st.session_state["tavily_api_key"] = tavily_key.strip()
                _save_app_state()
                st.success("Saved Tavily key")

    with settings_tabs[1]:
        st.caption("Choose providers and models per LLM task.")
        with st.container(border=True):
            st.markdown("**Model endpoints**")
            st.session_state["ollama_base_url"] = _normalize_ollama_base_url(
                st.text_input("Ollama base URL", value=st.session_state.get("ollama_base_url", OLLAMA_BASE_URL), key="settings_ollama_base_url")
            )

        with st.expander("URL reasoning", expanded=True):
            tr1, tr2, tr3 = st.columns([1, 1.5, 1.5])
            current_url_provider = st.session_state.get("url_reasoning_provider", "openrouter")
            st.session_state["url_reasoning_provider"] = tr1.selectbox(
                "Provider",
                options=["openrouter", "ollama"],
                index=["openrouter", "ollama"].index(current_url_provider) if current_url_provider in {"openrouter", "ollama"} else 0,
                key="url_reasoning_provider_select",
            )
            st.session_state["url_reasoning_openrouter_model"] = tr2.text_input(
                "OpenRouter model",
                value=st.session_state.get("url_reasoning_openrouter_model")
                or st.session_state.get("url_reasoning_model")
                or st.session_state.get("default_or_model", "deepseek/deepseek-v4-flash"),
                key="settings_url_reasoning_openrouter_model",
            )
            st.session_state["url_reasoning_ollama_model"] = tr3.text_input(
                "Ollama model",
                value=st.session_state.get("url_reasoning_ollama_model") or st.session_state.get("ollama_model") or "qwen2.5:3b",
                key="settings_url_reasoning_ollama_model",
            )

        with st.expander("Wiki enrichment", expanded=False):
            tg1, tg2, tg3 = st.columns([1, 1.5, 1.5])
            current_graph_provider = st.session_state.get("graph_enrichment_provider", "openrouter")
            st.session_state["graph_enrichment_provider"] = tg1.selectbox(
                "Provider",
                options=["openrouter", "ollama"],
                index=["openrouter", "ollama"].index(current_graph_provider) if current_graph_provider in {"openrouter", "ollama"} else 0,
                help="Provider for optional wiki maintenance/enrichment jobs.",
                key="graph_enrichment_provider_select",
            )
            st.session_state["graph_enrichment_openrouter_model"] = tg2.text_input(
                "OpenRouter model",
                value=st.session_state.get("graph_enrichment_openrouter_model") or st.session_state.get("graphify_model", "openai/gpt-4.1-mini"),
                key="settings_graph_enrichment_openrouter_model",
            )
            st.session_state["graph_enrichment_ollama_model"] = tg3.text_input(
                "Ollama model",
                value=st.session_state.get("graph_enrichment_ollama_model") or st.session_state.get("ollama_model") or "qwen2.5:3b",
                key="settings_graph_enrichment_ollama_model",
            )

        with st.expander("Wiki Q&A", expanded=False):
            ta1, ta2, ta3 = st.columns([1, 1.5, 1.5])
            current_answer_provider = st.session_state.get("graph_answer_provider", "openrouter")
            st.session_state["graph_answer_provider"] = ta1.selectbox(
                "Provider",
                options=["openrouter", "ollama"],
                index=["openrouter", "ollama"].index(current_answer_provider) if current_answer_provider in {"openrouter", "ollama"} else 0,
                key="graph_answer_provider_select",
            )
            st.session_state["graph_answer_openrouter_model"] = ta2.text_input(
                "OpenRouter model",
                value=st.session_state.get("graph_answer_openrouter_model") or st.session_state.get("default_or_model", "deepseek/deepseek-v4-flash"),
                key="settings_graph_answer_openrouter_model",
            )
            st.session_state["graph_answer_ollama_model"] = ta3.text_input(
                "Ollama model",
                value=st.session_state.get("graph_answer_ollama_model") or st.session_state.get("ollama_model") or "qwen2.5:3b",
                key="settings_graph_answer_ollama_model",
            )

    with settings_tabs[2]:
        st.caption("Bulk scraping stays lightweight by default. Browser fallback is opt-in.")
        with st.container(border=True):
            s1, s2 = st.columns([1, 1])
            st.session_state["scrape_concurrency"] = int(
                s1.number_input(
                    "Scrape concurrency",
                    min_value=1,
                    max_value=16,
                    value=int(st.session_state.get("scrape_concurrency", 4)),
                    step=1,
                    key="settings_scrape_concurrency",
                )
            )
            browser_options = ["none", "lightpanda"]
            current_browser = st.session_state.get("scrape_browser_mode", "none")
            st.session_state["scrape_browser_mode"] = s2.selectbox(
                "Browser fallback",
                options=browser_options,
                index=browser_options.index(current_browser) if current_browser in browser_options else 0,
                help="none = lightweight HTTP only. lightpanda = external Lightpanda CDP endpoint. Chrome/Chromium is not used.",
                key="settings_scrape_browser_mode",
            )
            st.session_state["lightpanda_cdp_url"] = st.text_input(
                "Lightpanda CDP URL",
                value=st.session_state.get("lightpanda_cdp_url", ""),
                placeholder="ws://127.0.0.1:9222",
                help="Used only when Browser fallback is lightpanda.",
                key="settings_lightpanda_cdp_url",
            )

    with settings_tabs[3]:
        st.caption("Search/index settings used after scraping and graph build.")
        with st.container(border=True):
            st.markdown("**Embeddings**")
            e1, e2 = st.columns([1, 2])
            st.session_state["embedding_enabled"] = e1.toggle(
                "Enabled", value=bool(st.session_state.get("embedding_enabled", True)), key="settings_embedding_enabled"
            )
            st.session_state["embedding_model"] = e2.text_input(
                "Model", value=st.session_state.get("embedding_model", "nomic-embed-text:latest"), key="settings_embedding_model"
            )
        with st.container(border=True):
            st.markdown("**Zvec**")
            z1, z2, z3 = st.columns([1, 2, 2])
            st.session_state["zvec_enabled"] = z1.toggle(
                "Enabled", value=bool(st.session_state.get("zvec_enabled", True)), key="settings_zvec_enabled"
            )
            st.session_state["zvec_index_path"] = z2.text_input(
                "Index path", value=st.session_state.get("zvec_index_path", ""), placeholder="data/sites/<site>/zvec", key="settings_zvec_index_path"
            )
            st.session_state["zvec_collection"] = z3.text_input(
                "Collection", value=st.session_state.get("zvec_collection", "university_wiki"), key="settings_zvec_collection"
            )

    with settings_tabs[4]:
        st.caption("Optional external research/recovery features.")
        with st.container(border=True):
            st.session_state["use_tavily_for_map"] = st.toggle(
                "Use Tavily for university map", value=bool(st.session_state.get("use_tavily_for_map", False)), key="settings_use_tavily_for_map"
            )

    st.divider()
    if st.button("Save All Settings", type="primary", use_container_width=True):
        if st.session_state.get("lightpanda_cdp_url", "").strip():
            _save_env_key(ENV_PATH, "LIGHTPANDA_CDP_URL", st.session_state.get("lightpanda_cdp_url", "").strip())
            os.environ["LIGHTPANDA_CDP_URL"] = st.session_state.get("lightpanda_cdp_url", "").strip()
        os.environ["SCRAPE_BROWSER_MODE"] = st.session_state.get("scrape_browser_mode", "none")
        _save_app_state()
        st.success("Settings saved.")
