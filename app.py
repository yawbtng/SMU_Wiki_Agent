from __future__ import annotations

import json
import os
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import altair as alt
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
try:
    from streamlit_autorefresh import st_autorefresh
except Exception:
    st_autorefresh = None

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
    load_mcp_status as _stepper_load_mcp_status,
    load_wiki_status as _stepper_load_wiki_status,
    raw_source_status as _stepper_raw_source_status,
    raw_sources_ready as _stepper_raw_sources_ready,
    read_jsonl_rows as _stepper_read_jsonl_rows,
    wiki_ready as _stepper_wiki_ready,
)
from src.scrape_planner.storage import persist_discovered, read_json, write_json
from src.scrape_planner.tmux_runner import TmuxRunner
from src.scrape_planner.llm_wiki_builder import launch_wiki_builder
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

ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / "data"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
ENV_PATH = ROOT / ".env"
APP_STATE_PATH = DATA_ROOT / "app_state.json"


def _site_slug(url: str) -> str:
    return normalize_site_url(url).replace("https://", "").replace("http://", "").replace("/", "_")


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
    return DATA_ROOT / "sites" / site_id / run_id


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


def _read_jsonl_rows(path: Path) -> list[dict]:
    return _stepper_read_jsonl_rows(path)


def _raw_source_status(layout) -> dict:
    return _stepper_raw_source_status(layout)


def _raw_sources_ready(raw_status: dict) -> bool:
    return _stepper_raw_sources_ready(raw_status)


def _load_wiki_status(layout, raw_status: dict) -> dict:
    return _stepper_load_wiki_status(layout, raw_status)


def _wiki_ready(wiki_status: dict) -> bool:
    return _stepper_wiki_ready(wiki_status)


def _load_embedding_status(layout) -> dict:
    return _stepper_load_embedding_status(layout)


def _load_mcp_status(layout) -> dict:
    return _stepper_load_mcp_status(layout)


def _merge_jsonl_rows_app(path: Path, rows: list[dict], *, key: str) -> None:
    existing = {str(row.get(key)): row for row in _read_jsonl_rows(path) if row.get(key)}
    for row in rows:
        if row.get(key):
            existing[str(row.get(key))] = row
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in existing.values()), encoding="utf-8")


def _extract_uploaded_pdfs_to_site_sources(site_root: Path, pdf_manifest: list[dict]) -> dict:
    paths = [Path(str(row.get("path"))) for row in pdf_manifest if isinstance(row, dict) and row.get("path")]
    result = ingest_pdfs(paths, PdfIngestConfig(page_markdown_dir=site_root / "sources" / "pdf_pages"))
    out_dir = site_root / "sources" / "pdf_ingest"
    _merge_jsonl_rows_app(out_dir / "pdf_sources.jsonl", [row.to_dict() for row in result.sources], key="pdf_source_id")
    _merge_jsonl_rows_app(out_dir / "pdf_chunks.jsonl", [row.to_dict() for row in result.chunks], key="chunk_id")
    _merge_jsonl_rows_app(out_dir / "pdf_quarantine.jsonl", [row.to_dict() for row in result.quarantine], key="pdf_source_id")
    return {
        "sources": len(result.sources),
        "accepted": len([row for row in result.sources if row.accepted]),
        "chunks": len(result.chunks),
        "quarantine": len(result.quarantine),
        "output_dir": str(out_dir),
    }


def _render_pdf_parser_unavailable_error(exc: PdfParserUnavailableError) -> None:
    st.error(
        "PDF extraction is unavailable until Docling is installed. "
        "Install `requirements-pdf.txt` in this environment, then try extraction again."
    )
    st.caption(f"Parser setup detail: `{exc}`")


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
    return DATA_ROOT / "sites" / site_id / "discovered_urls.json"


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
    return read_json(
        APP_STATE_PATH,
        {
            "active_workspace_id": "",
            "workspaces": [],
            "last_site_url": "",
            "last_site_id": "",
            "last_run_id": "",
            "last_run_by_site": {},
            "manual_urls": "",
            "ollama_model": "",
            "llm_provider": "openrouter",
            "ollama_base_url": OLLAMA_BASE_URL,
            "site_history": [],
        },
    )


def _save_app_state() -> None:
    write_json(
        APP_STATE_PATH,
        {
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
            "scrape_browser_mode": st.session_state.get("scrape_browser_mode", "none"),
            "lightpanda_cdp_url": st.session_state.get("lightpanda_cdp_url", ""),
            "embedding_enabled": bool(st.session_state.get("embedding_enabled", True)),
            "embedding_model": st.session_state.get("embedding_model", "nomic-embed-text:latest"),
            "zvec_enabled": bool(st.session_state.get("zvec_enabled", True)),
            "zvec_index_path": st.session_state.get("zvec_index_path", ""),
            "zvec_collection": st.session_state.get("zvec_collection", "university_wiki"),
            "use_tavily_for_map": bool(st.session_state.get("use_tavily_for_map", False)),
            "tavily_cost_per_call_usd": float(st.session_state.get("tavily_cost_per_call_usd", 0.0)),
            "ollama_input_per_m_usd": float(st.session_state.get("ollama_input_per_m_usd", 0.0)),
            "ollama_output_per_m_usd": float(st.session_state.get("ollama_output_per_m_usd", 0.0)),
        },
    )


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
    discovered_path = _discovered_json_path(site_id)
    rows = read_json(discovered_path, [])
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
    _merge_rows(read_json(run_root / "pages.jsonl", []))
    failures = read_json(run_root / "failures.json", [])
    run_status = read_json(run_root / "run_status.json", {})
    scrape_events = read_json(run_root / "events.jsonl", [])

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


def _apply_compact_ui_styles() -> None:
    st.markdown(
        """
        <style>
        html, body, [class*="st-"], [data-testid="stAppViewContainer"] {
            font-size: 13px;
        }
        .main .block-container {
            padding-top: 1.2rem;
            padding-bottom: 1.6rem;
            max-width: 100%;
        }
        h1 {
            font-size: 1.45rem !important;
            line-height: 1.2 !important;
            margin-bottom: 0.35rem !important;
        }
        h2, h3 {
            font-size: 1.02rem !important;
            line-height: 1.25 !important;
            margin-top: 0.8rem !important;
            margin-bottom: 0.35rem !important;
        }
        p, label, .stMarkdown, .stCaption, [data-testid="stMarkdownContainer"] {
            font-size: 0.82rem !important;
            line-height: 1.35 !important;
        }
        [data-testid="stMetric"] {
            padding: 0.15rem 0;
        }
        [data-testid="stMetricLabel"] p {
            font-size: 0.72rem !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.08rem !important;
            line-height: 1.15 !important;
        }
        button, input, textarea, select, [role="tab"] {
            font-size: 0.8rem !important;
        }
        [data-testid="stDataFrame"] {
            font-size: 0.78rem !important;
        }
        div[data-testid="stExpander"] details summary p {
            font-size: 0.82rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_scraped_page_preview() -> None:
    if str(st.query_params.get("view", "") or "").strip() != "scraped_page":
        return

    site_id = str(st.query_params.get("site_id", "") or "").strip()
    run_id = str(st.query_params.get("run_id", "") or "").strip()
    slug = str(st.query_params.get("page_slug", "") or "").strip()

    st.subheader("Scraped page preview")
    st.link_button("Back to Runs", "./")
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
    preview_title = first_heading or Path(preview.url or slug).name or "Untitled scraped page"

    st.markdown(f"### {preview_title}")
    st.caption(f"Source URL: `{preview.url or 'Not recorded'}`")
    st.caption(f"Run id: `{run_id}`")
    st.caption(f"Page slug: `{slug}`")

    meta_cols = st.columns(4)
    meta_cols[0].metric("Scrape status", "Ready" if preview.ready else "Missing")
    meta_cols[1].metric("HTTP status", preview.http_status if preview.http_status is not None else "n/a")
    meta_cols[2].metric("Fetch mode", preview.fetch_mode or "n/a")
    meta_cols[3].metric("Text length", preview.text_length if preview.text_length is not None else "n/a")

    expected_markdown_path = preview.path or (run_root / "markdown" / f"{slug}.md")
    metadata_summary_rows = [
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

st.title("LLM Wiki Pipeline")
st.caption("Overview -> Sources -> Runs -> Corpus -> Wiki -> Retrieval -> Settings.")

if not st.session_state.get("active_workspace_id"):
    st.subheader("Workspaces")
    st.caption("Create a workspace for each university, then open it to use the full pipeline UI.")

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
            with st.container(border=True):
                st.markdown(f"**{ws.get('name','Unnamed University')}**")
                st.caption(f"{ws.get('url','')}")
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
        st.info("No workspaces yet. Add one above.")
    st.stop()

active_ws = next((w for w in st.session_state.get("workspaces", []) if w.get("id") == st.session_state.get("active_workspace_id")), None)
if active_ws:
    top1, top2 = st.columns([3, 1])
    top1.caption(f"Workspace: {active_ws.get('name')} ({active_ws.get('url')})")
    if top2.button("Back to Workspaces"):
        st.session_state["active_workspace_id"] = ""
        _save_app_state()
        st.rerun()

tabs = st.tabs(WORKFLOW_TABS)

with tabs[0]:
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

with tabs[1]:
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
        if st.button("Refresh Sitemap URLs", disabled=not st.session_state["site_url"], type="primary"):
            result = discover_site_urls(st.session_state["site_url"])
            st.session_state["discovered"] = _to_discovered_rows(result.urls)
            st.session_state["selected_df"] = pd.DataFrame(st.session_state["discovered"])
            persist_discovered(_discovered_json_path(st.session_state["site_id"]), result.urls)
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
                        "status": "ready_for_docling_zvec",
                    }
                pdf_manifest = sorted(existing.values(), key=lambda row: row.get("name", ""))
                write_json(pdf_manifest_path, pdf_manifest)
                with st.spinner("Extracting uploaded PDFs..."):
                    try:
                        pdf_summary = _extract_uploaded_pdfs_to_site_sources(site_root, pdf_manifest)
                    except PdfParserUnavailableError as exc:
                        _render_pdf_parser_unavailable_error(exc)
                    else:
                        st.success(
                            f"Saved and extracted {len(uploaded_pdfs):,} PDF(s): "
                            f"{pdf_summary['chunks']:,} search chunk(s), {pdf_summary['quarantine']:,} needing review."
                        )
            if pdf_manifest:
                st.caption(f"{len(pdf_manifest):,} PDF document(s) uploaded.")
                if st.button("Extract / Re-extract PDFs", type="secondary", key="extract_uploaded_pdfs_now"):
                    with st.spinner("Extracting PDFs with PyPDF/Docling..."):
                        try:
                            pdf_summary = _extract_uploaded_pdfs_to_site_sources(site_root, pdf_manifest)
                        except PdfParserUnavailableError as exc:
                            _render_pdf_parser_unavailable_error(exc)
                        else:
                            st.success(
                                f"Extraction complete: {pdf_summary['chunks']:,} search chunks, {pdf_summary['quarantine']:,} needing review."
                            )
                            st.rerun()
            else:
                st.info("Upload PDFs to include documents in the source set.")

        if source_rows or chunk_rows or quarantine_rows:
            st.divider()
            st.markdown("Prepared Sources")
            prepared_cols = st.columns(3)
            prepared_cols[0].metric("Extracted documents", f"{len(source_rows):,}")
            prepared_cols[1].metric("Search chunks", f"{len(chunk_rows):,}")
            prepared_cols[2].metric("Needs review", f"{len(quarantine_rows):,}")

with tabs[2]:
    st.subheader("Runs")
    runs_site_id = st.session_state.get("site_id", "")
    runs_selected_url_strings = _selected_url_strings_from_state()
    runs_run_id = st.session_state.get("run_id", "")
    runs_discovered_path = _discovered_json_path(runs_site_id)
    runs_discovered_rows = st.session_state.get("discovered") or (read_json(runs_discovered_path, []) if runs_site_id else [])
    runs_source_count = len(
        {
            row.get("source_sitemap")
            for row in runs_discovered_rows
            if isinstance(row, dict) and row.get("source_sitemap")
        }
    )
    runs_last_refreshed = "never"
    if runs_discovered_path.exists():
        runs_last_refreshed = datetime.fromtimestamp(
            runs_discovered_path.stat().st_mtime,
            tz=timezone.utc,
        ).strftime("%Y-%m-%d %H:%M UTC")

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
        runs_cols = st.columns([1, 1, 1, 1])
        runs_settings = st.columns([1, 1, 2])
        runs_concurrency = runs_settings[0].number_input(
            "Concurrency",
            min_value=1,
            max_value=16,
            value=int(st.session_state.get("scrape_concurrency", 10)),
            step=1,
            key="runs_scrape_concurrency",
        )
        st.session_state["scrape_concurrency"] = int(runs_concurrency)
        if runs_cols[0].button("Start New Scrape", type="primary", key="runs_start_new_scrape"):
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
        if runs_cols[1].button("Resume", disabled=not st.session_state["run_id"], key="runs_resume_scrape"):
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
        if runs_cols[2].button("Pause", disabled=not st.session_state["run_id"], key="runs_pause_scrape"):
            runner.pause(runs_site_id, st.session_state["run_id"])
            st.session_state["scrape_status_message"] = "Pausing after in-flight pages finish..."
            st.rerun()
        if runs_cols[3].button("Cancel", disabled=not st.session_state["run_id"], key="runs_cancel_scrape"):
            runner.cancel(runs_site_id, st.session_state["run_id"])
            st.session_state["scrape_status_message"] = "Cancel requested. Stopping after in-flight pages finish..."
            st.rerun()
        if runs_settings[1].button("Refresh", use_container_width=True, key="runs_refresh"):
            st.rerun()
        runs_autorefresh = runs_settings[2].checkbox("Auto-refresh every 1s", value=False, key="runs_autorefresh")
        if runs_autorefresh and st_autorefresh is None:
            runs_settings[2].caption("Install `streamlit-autorefresh` to enable this without blocking. Use Refresh for now.")
        st.caption(
            f"Selected URLs: `{len(runs_selected_url_strings):,}`   |   Active run: `{st.session_state.get('run_id') or 'none'}`"
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
            r2.metric("Success", f"{runs_summary.success:,}")
            r3.metric("Failed", f"{runs_summary.failed:,}")
            r4.metric("Remaining", f"{runs_summary.remaining:,}")
            r5.metric("ETA", runs_eta_label)
            if runs_status_stale:
                st.warning("This run is paused in the UI. Resume it to continue from saved progress.")

            with st.expander("Website discovery details", expanded=False):
                d1, d2, d3 = st.columns(3)
                d1.metric("Discovered URLs", f"{len(runs_discovered_rows):,}")
                d2.metric("Sitemap sources", f"{runs_source_count:,}")
                d3.metric("Last refreshed", runs_last_refreshed)
                if runs_discovered_rows:
                    host_counts = pd.Series(
                        [
                            urlparse(str(row.get("url") or "")).netloc.lower()
                            for row in runs_discovered_rows
                            if isinstance(row, dict)
                        ]
                    ).value_counts().head(12)
                    if not host_counts.empty:
                        st.dataframe(host_counts.rename_axis("host").reset_index(name="urls"), use_container_width=True, hide_index=True)

            with st.expander("Scrape activity details", expanded=True):
                st.caption(f"Current URL: `{runs_status.get('current_url') or 'pending initialization'}`")
                st.caption(f"Elapsed: `{runs_elapsed_label}`")
                st.caption(f"ETA: `{runs_eta_label}`")
                st.caption("Current activity")
                running_pages = latest_pages_by_status(runs_all_page_rows, "running", limit=8)
                if running_pages:
                    running_df = pd.DataFrame(running_pages)
                    st.dataframe(
                        running_df[[c for c in ["url", "worker_id", "fetch_mode", "attempt", "started_at"] if c in running_df.columns]],
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("No pages are running right now. The queue may be waiting, paused, or already complete.")

                st.caption("Recently scraped")
                successful_pages = latest_pages_by_status(runs_all_page_rows, "success", limit=10)
                if successful_pages:
                    st.markdown("#### Content Inspector")
                    st.caption("Compact preview actions for recently scraped pages.")
                    recent_preview_rows = []
                    for row in successful_pages:
                        url = str(row.get("url") or "")
                        href = build_scraped_page_preview_href(
                            site_id=runs_site_id,
                            run_id=st.session_state["run_id"],
                            url=url,
                        )
                        parsed_url = urlparse(url)
                        title = str(row.get("title") or parsed_url.path.strip("/") or parsed_url.netloc or "Untitled page")
                        recent_preview_rows.append(
                            {
                                "Title": title[:120],
                                "Status": str(row.get("status") or "success"),
                                "Source URL": url,
                                "Scraped timestamp": str(row.get("finished_at") or row.get("started_at") or "unknown"),
                                "Preview URL": href,
                            }
                        )
                    st.dataframe(
                        pd.DataFrame(recent_preview_rows),
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Preview URL": st.column_config.LinkColumn("Preview", display_text="Preview"),
                        },
                    )
                else:
                    st.info("Successful pages will appear here as soon as markdown is saved.")

                st.caption("Current failures")
                failed_pages = latest_pages_by_status(runs_all_page_rows, "failed", limit=10)
                if failed_pages:
                    failed_df = pd.DataFrame(failed_pages)
                    st.dataframe(
                        failed_df[[c for c in ["url", "failure_reason", "http_status", "attempt", "finished_at"] if c in failed_df.columns]],
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("No failed pages in this run yet.")

                with st.expander("All pages and filters", expanded=False):
                    if runs_pages_df.empty:
                        st.info("Run initializing. Waiting for queue state to be published.")
                    else:
                        f1, f2, f3, f4 = st.columns([2, 2, 3, 2])
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
                        latest_only = f4.checkbox("Show latest activity only", value=False, key="runs_live_latest_only")

                        visible_df = runs_pages_df.copy()
                        if selected_statuses:
                            visible_df = visible_df[visible_df["status"].isin(selected_statuses)]
                        if url_query.strip():
                            visible_df = visible_df[
                                visible_df["url"].astype(str).str.contains(url_query.strip(), case=False, na=False)
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
                            _render_paginated_df(
                                visible_df[
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
                                ],
                                key_prefix="runs_live_pages",
                                default_page_size=100,
                            )
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
            with st.expander("Website discovery details", expanded=False):
                d1, d2, d3 = st.columns(3)
                d1.metric("Discovered URLs", f"{len(runs_discovered_rows):,}")
                d2.metric("Sitemap sources", f"{runs_source_count:,}")
                d3.metric("Last refreshed", runs_last_refreshed)

with tabs[3]:
    st.subheader("Corpus")
    site_id = st.session_state.get("site_id", "")
    if not site_id:
        st.info("Create or open a workspace first.")
    else:
        layout = site_layout(DATA_ROOT / "sites" / site_id)
        corpus_ingest_dir = layout.site_root / "sources" / "pdf_ingest"
        corpus_pages_dir = layout.site_root / "sources" / "pdf_pages"
        chunk_rows = _read_jsonl_rows(corpus_ingest_dir / "pdf_chunks.jsonl")
        quarantine_rows = _read_jsonl_rows(corpus_ingest_dir / "pdf_quarantine.jsonl")
        page_rows = []
        for pages_index in sorted(corpus_pages_dir.glob("*/pages.json")) if corpus_pages_dir.exists() else []:
            payload = read_json(pages_index, [])
            if isinstance(payload, list):
                page_rows.extend([row for row in payload if isinstance(row, dict)])

        raw_status = _raw_source_status(layout)
        counts_by_status = raw_status["by_status"]

        latest_report_path = raw_status.get("latest_report_path")
        render_metric_strip(
            [
                {"label": "PDF Pages", "value": f"{len(page_rows):,}"},
                {"label": "Search Chunks", "value": f"{len(chunk_rows):,}"},
                {"label": "PDF Review", "value": f"{len(quarantine_rows):,}"},
                {"label": "Raw Sources", "value": f"{len(raw_status['rows']):,}"},
                {"label": "Raw Ready", "value": f"{int(counts_by_status.get('ready', 0)):,}"},
            ]
        )

        quality_sample_rows = [row for row in chunk_rows[:50] if isinstance(row, dict)]
        quality_summary = build_chunk_quality_summary(quality_sample_rows)
        st.markdown("### Chunk quality")
        render_metric_strip(
            [
                {"label": "Sampled chunks", "value": f"{quality_summary.total:,}"},
                {"label": "Good", "value": f"{quality_summary.good_count:,}"},
                {"label": "Needs review", "value": f"{quality_summary.needs_review_count:,}"},
                {"label": "Poor", "value": f"{quality_summary.poor_count:,}"},
                {
                    "label": "Ready state",
                    "value": "Ready for retrieval" if quality_summary.ready_for_retrieval else "Needs review",
                },
            ]
        )
        if quality_summary.total:
            st.caption(
                "Top flags: "
                + (", ".join(quality_summary.top_flags) if quality_summary.top_flags else "none")
            )
        else:
            st.caption("Unknown chunk quality. Next action: inspect sample chunks after PDF extraction.")

        render_operator_details(
            "Operator Details",
            {
                "Registry path:": str(layout.registry_path),
                "Latest report path:": str(latest_report_path or ""),
            },
        )
        if latest_report_path:
            with st.expander("Latest normalization report", expanded=False):
                st.json(raw_status.get("latest_report") or {})
        else:
            st.warning("Missing prerequisite: raw data sources have not been normalized yet.")

        with st.expander("PDF extraction", expanded=bool(page_rows)):
            p1, p2, p3 = st.columns(3)
            p1.metric("Pages extracted", f"{len(page_rows):,}")
            p2.metric("Search chunks", f"{len(chunk_rows):,}")
            p3.metric("Needs review", f"{len(quarantine_rows):,}")
            if pdf_manifest:
                display_rows = [
                    {
                        "name": row.get("name", ""),
                        "size_bytes": row.get("size_bytes", 0),
                        "status": row.get("status", ""),
                        "page_count": row.get("page_count", ""),
                        "path": row.get("path", ""),
                        "added_at": row.get("added_at", ""),
                    }
                    for row in pdf_manifest
                    if isinstance(row, dict)
                ]
                st.dataframe(pd.DataFrame(display_rows), use_container_width=True, hide_index=True)
                with st.expander("Page-by-page markdown", expanded=bool(page_rows)):
                    if page_rows:
                        page_preview_options = [
                            row for row in page_rows
                            if isinstance(row, dict)
                            and str(row.get("markdown_path") or "").strip()
                            and row.get("page_number") is not None
                        ]
                        preview_cols = st.columns(3)
                        preview_cols[0].metric("Previewable pages", f"{len(page_preview_options):,}")
                        preview_cols[1].metric(
                            "Parsers",
                            ", ".join(sorted({str(row.get("parser") or "") for row in page_preview_options if row.get("parser")})) or "n/a",
                        )
                        preview_cols[2].metric(
                            "Largest page",
                            f"{max((int(row.get('char_count') or 0) for row in page_preview_options), default=0):,} chars",
                        )
                        if page_preview_options:
                            preview_by_page_number = {
                                int(row.get("page_number")): row
                                for row in page_preview_options
                                if str(row.get("page_number") or "").isdigit()
                            }
                            preview_page_numbers = sorted(preview_by_page_number)
                            current_preview_page = int(
                                st.session_state.get("pdf_page_preview_number")
                                or preview_page_numbers[0]
                            )
                            if current_preview_page not in preview_by_page_number:
                                current_preview_page = preview_page_numbers[0]
                            selected_page_number = int(
                                st.number_input(
                                    "Page number",
                                    min_value=preview_page_numbers[0],
                                    max_value=preview_page_numbers[-1],
                                    value=current_preview_page,
                                    step=1,
                                    key="pdf_page_preview_number",
                                )
                            )
                            selected_page = preview_by_page_number.get(selected_page_number, preview_by_page_number[preview_page_numbers[0]])
                            markdown_path = str(selected_page.get("markdown_path") or "").strip()
                            detail_cols = st.columns(3)
                            detail_cols[0].caption(f"Parser: `{str(selected_page.get('parser') or 'n/a')}`")
                            detail_cols[1].caption(f"Chars: `{int(selected_page.get('char_count') or 0):,}`")
                            detail_cols[2].caption(f"File: `{Path(markdown_path).name}`")

                            action_cols = st.columns([1, 1, 4])
                            if action_cols[0].button("Load preview", key="load_pdf_preview", type="secondary"):
                                st.session_state["pdf_page_markdown_preview_path"] = markdown_path
                                st.session_state["pdf_page_markdown_preview_text"] = _load_markdown_preview(markdown_path, max_chars=12000)
                            if hasattr(st, "dialog") and action_cols[1].button(
                                "Open dialog",
                                key="open_pdf_preview_dialog",
                                type="secondary",
                            ):
                                _open_page_markdown_dialog(markdown_path)

                            preview_target_path = str(st.session_state.get("pdf_page_markdown_preview_path") or "").strip()
                            preview_text = str(st.session_state.get("pdf_page_markdown_preview_text") or "")
                            if preview_target_path == markdown_path and preview_text:
                                st.markdown("---")
                                st.markdown(preview_text)
                            elif preview_target_path == markdown_path:
                                st.warning("Could not load markdown preview from this path.")
                            else:
                                st.caption("Preview is loaded on demand to keep this screen responsive during large runs.")
                        else:
                            st.warning("No previewable page markdown files were found yet.")
                    else:
                        st.warning("No page markdown files yet. Click Extract / Re-extract PDFs.")
                with st.expander("PDF review queue", expanded=bool(quarantine_rows)):
                    if quarantine_rows:
                        st.dataframe(pd.DataFrame(quarantine_rows), use_container_width=True, hide_index=True)
                    else:
                        st.success("No PDFs need review.")
            else:
                st.info("Upload one or more PDFs to extract them for embedding.")

        st.markdown("### Content Inspector")
        st.caption("Preview extracted pages and chunks before trusting them for wiki or retrieval.")
        with st.expander("Embedding chunks", expanded=False):
            if chunk_rows:
                for idx, row in enumerate([item for item in chunk_rows[:20] if isinstance(item, dict)]):
                    source_title = _chunk_source_title(row)
                    quality = classify_chunk_row(row)
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2.5, 1.2, 1.3])
                        c1.markdown(f"**{source_title}**")
                        c2.caption(f"Quality: `{quality.quality}`")
                        c3.caption(f"Chars: `{quality.char_count:,}`")
                        st.caption(f"Source: `{_chunk_source_location(row)}`")
                        st.caption(f"Section path/context: `{quality.context_label}`")
                        st.caption(
                            "Flags: `"
                            + (", ".join(quality.flags) if quality.flags else "none")
                            + "`"
                        )
                        st.caption(f"Reason: {quality.reason}")
                        text_sample = str(row.get("text") or "").strip()
                        if text_sample:
                            st.text_area(
                                "Chunk text",
                                value=text_sample[:1200],
                                height=140,
                                disabled=True,
                                key=f"corpus_chunk_text_{idx}",
                            )
                        else:
                            st.warning("This chunk has no text.")
            else:
                st.warning("No chunks extracted yet. Click Extract / Re-extract PDFs.")

        if raw_status["rows"]:
            rows = raw_status["rows"][:1000]
            rows_by_kind: dict[str, list[dict]] = {}
            for row in rows:
                kind = str(row.get("source_kind") or "unknown").strip().lower()
                rows_by_kind.setdefault(kind, []).append(row)

            pdf_rows = rows_by_kind.get("pdf", [])
            web_rows = rows_by_kind.get("web", [])
            other_rows = [row for kind, kind_rows in rows_by_kind.items() if kind not in {"pdf", "web"} for row in kind_rows]

            pdf_page_count = 0
            pdf_pages_dir = layout.site_root / "sources" / "pdf_pages"
            if pdf_pages_dir.exists():
                pdf_page_count = len([path for path in pdf_pages_dir.rglob("*.md") if path.is_file()])
            raw_markdown_count = 0
            if layout.raw_sources_dir.exists():
                raw_markdown_count = len([path for path in layout.raw_sources_dir.rglob("*.md") if path.is_file()])

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Total Sources", f"{len(rows):,}")
            m2.metric("Web Sources", f"{len(web_rows):,}")
            m3.metric("PDF Sources", f"{len(pdf_rows):,}")
            m4.metric("PDF Pages Extracted", f"{pdf_page_count:,}")
            m5.metric("Raw Markdown Files", f"{raw_markdown_count:,}")

            c_web, c_pdf, c_other = st.columns(3)
            c_web.metric("Web Ready/Failed", f"{sum(1 for r in web_rows if str(r.get('status') or '') == 'ready')}/{sum(1 for r in web_rows if str(r.get('status') or '') == 'failed')}")
            c_pdf.metric("PDF Ready/Failed", f"{sum(1 for r in pdf_rows if str(r.get('status') or '') == 'ready')}/{sum(1 for r in pdf_rows if str(r.get('status') or '') == 'failed')}")
            c_other.metric("Other Sources", f"{len(other_rows):,}")

            st.markdown("### PDF Sources")
            if pdf_rows:
                for row in pdf_rows[:80]:
                    source_id = str(row.get("source_id") or "")
                    title = str(row.get("title") or source_id or "Untitled PDF")
                    status = str(row.get("status") or "unknown")
                    parser = str(row.get("parser") or "")
                    markdown_path = str(row.get("markdown_path") or "")
                    metadata_path = str(row.get("metadata_path") or "")
                    error_reason = str(row.get("error_reason") or "")
                    page_count = ""
                    if metadata_path:
                        metadata_abs = layout.site_root / metadata_path
                        if metadata_abs.exists():
                            metadata = read_json(metadata_abs, {})
                            page_count = str(metadata.get("page_count") or "")
                    with st.container(border=True):
                        p1, p2, p3, p4 = st.columns([2.6, 1.1, 1.0, 1.3])
                        p1.markdown(f"**{title}**")
                        p2.caption(f"Status: `{status}`")
                        p3.caption(f"Parser: `{parser or 'n/a'}`")
                        p4.caption(f"Pages: `{page_count or 'n/a'}`")
                        st.caption(f"Source ID: `{source_id}`")
                        if error_reason:
                            st.warning(error_reason)
                        a1, a2, a3 = st.columns([1, 1, 2.5])
                        if a1.button("Preview", key=f"pdf_card_preview_{source_id}"):
                            preview_path = str((layout.site_root / markdown_path) if markdown_path else "")
                            if preview_path and hasattr(st, "dialog"):
                                _open_page_markdown_dialog(preview_path)
                        if a2.button("Metadata", key=f"pdf_card_metadata_{source_id}"):
                            st.session_state["raw_source_metadata_id"] = source_id
                        a3.caption(f"Markdown: `{markdown_path or 'n/a'}`")
            else:
                st.info("No PDF sources found yet.")

            st.markdown("### Web Sources")
            if web_rows:
                for row in web_rows[:120]:
                    source_id = str(row.get("source_id") or "")
                    title = str(row.get("title") or source_id or "Untitled web source")
                    status = str(row.get("status") or "unknown")
                    original_url = str(row.get("original_url") or "")
                    markdown_path = str(row.get("markdown_path") or "")
                    change_state = str(row.get("change_state") or "")
                    error_reason = str(row.get("error_reason") or "")
                    with st.container(border=True):
                        w1, w2, w3 = st.columns([2.8, 1.2, 1.3])
                        w1.markdown(f"**{title}**")
                        w2.caption(f"Status: `{status}`")
                        w3.caption(f"Change: `{change_state or 'n/a'}`")
                        if original_url:
                            st.caption(f"URL: `{original_url}`")
                        st.caption(f"Source ID: `{source_id}`")
                        if error_reason:
                            st.warning(error_reason)
                        a1, a2, a3 = st.columns([1, 1, 2.5])
                        if a1.button("Preview", key=f"web_card_preview_{source_id}"):
                            preview_path = str((layout.site_root / markdown_path) if markdown_path else "")
                            if preview_path and hasattr(st, "dialog"):
                                _open_page_markdown_dialog(preview_path)
                        if a2.button("Metadata", key=f"web_card_metadata_{source_id}"):
                            st.session_state["raw_source_metadata_id"] = source_id
                        a3.caption(f"Markdown: `{markdown_path or 'n/a'}`")
            else:
                st.info("No web sources found yet.")

            selected_meta_id = str(st.session_state.get("raw_source_metadata_id") or "")
            if selected_meta_id:
                selected_row = next((row for row in rows if str(row.get("source_id") or "") == selected_meta_id), None)
                if selected_row:
                    with st.expander(f"Metadata: {selected_meta_id}", expanded=True):
                        st.json(selected_row)
        else:
            st.info("Normalize scraped pages, PDFs, or tabular files to populate `raw_sources/registry.jsonl`.")

with tabs[4]:
    st.subheader("Wiki")
    site_id = st.session_state.get("site_id", "")
    if not site_id:
        st.info("Create or open a workspace first.")
    else:
        layout = site_layout(DATA_ROOT / "sites" / site_id)
        raw_status = _raw_source_status(layout)
        raw_sources_ready = _raw_sources_ready(raw_status)
        wiki_status = _load_wiki_status(layout, raw_status)

        if not raw_sources_ready:
            st.warning("Missing prerequisite: normalize raw data sources before building the LLM Wiki.")

        build_col, refresh_col = st.columns([1, 1])
        if build_col.button("Build LLM Wiki", type="primary", disabled=not raw_sources_ready, key="build_llm_wiki"):
            launch_result = launch_wiki_builder(layout.site_root, runner=tmux_runner, resume=True, runtime="pi")
            if launch_result.get("ok"):
                st.success(f"Started tmux session `{launch_result['session_name']}`.")
                st.caption(f"Report path: `{launch_result['report_path']}`")
                st.caption(f"Runtime: `{launch_result.get('runtime', 'python')}`")
            else:
                st.error(launch_result.get("error") or "Failed to start LLM Wiki builder.")
        if refresh_col.button("Refresh Wiki Status", key="refresh_llm_wiki_status"):
            st.rerun()

        w1, w2, w3, w4 = st.columns(4)
        w1.metric("Job Status", wiki_status["job_status"])
        w2.metric("Pages Created", f"{wiki_status['pages_created']:,}")
        w3.metric("Pages Updated", f"{wiki_status['pages_updated']:,}")
        w4.metric("Review Queue", f"{wiki_status['review_queue_count']:,}")
        st.caption(f"tmux session: `{wiki_status['tmux_session']}`")
        st.caption(f"Log path: `{wiki_status['log_path']}`")
        st.caption(f"Last progress update: `{wiki_status['last_progress'] or 'not reported'}`")
        st.caption(f"Wiki index: `{wiki_status['index_path']}`")
        st.caption(f"Review queue: `{wiki_status['review_queue_path']}`")
        st.metric("Integrated Sources", f"{wiki_status['integrated_sources']:,}")

        live_col1, live_col2 = st.columns([1, 1.2])
        live_logs = live_col1.checkbox("Auto-refresh live logs (1s)", value=False, key="wiki_live_logs_autorefresh")
        show_tmux = live_col2.checkbox("Include tmux pane output", value=True, key="wiki_live_tmux_output")
        _schedule_live_refresh(
            key="wiki_live_logs_tick",
            enabled=live_logs,
            active=bool(wiki_status.get("job_status", "").lower() in {"running", "started", "pending"}),
            interval_seconds=1.0,
        )

        wiki_log_text = _tail_text(Path(wiki_status["log_path"]), max_lines=120)
        tmux_text = tmux_runner.capture(str(wiki_status["tmux_session"]), lines=120) if show_tmux else ""
        with st.expander("Live wiki build logs", expanded=True):
            st.caption("Streaming latest wiki log and tmux pane output.")
            st.markdown("**wiki/log.md (tail)**")
            st.code(wiki_log_text or "(no wiki log yet)", language="text")
            if show_tmux:
                st.markdown("**tmux pane (tail)**")
                st.code(tmux_text or "(no tmux output yet)", language="text")

        latest_report_path = wiki_status.get("latest_report_path")
        if latest_report_path:
            st.caption(f"Latest wiki report: `{latest_report_path}`")
            with st.expander("Latest wiki report", expanded=False):
                st.json(wiki_status.get("latest_report") or {})
        else:
            st.info("Wiki build reports will appear under `wiki/reports/` after the builder runs.")

with tabs[5]:
    st.subheader("Retrieval")
    site_id = st.session_state.get("site_id", "")
    if site_id:
        layout = site_layout(DATA_ROOT / "sites" / site_id)
        raw_status = _raw_source_status(layout)
        wiki_status = _load_wiki_status(layout, raw_status)
        embedding_status = _load_embedding_status(layout)
        wiki_ready = _wiki_ready(wiki_status)
        if not _raw_sources_ready(raw_status):
            st.warning("Missing prerequisite: normalize raw data sources before embedding and reranking.")
        elif not wiki_ready:
            st.warning("Missing prerequisite: build the LLM Wiki before embedding and reranking.")

        e1, e2, e3, e4, e5 = st.columns(5)
        e1.metric("Raw Index", f"{embedding_status['raw_index_count']:,}")
        e2.metric("Wiki Index", f"{embedding_status['wiki_index_count']:,}")
        e3.metric("Changed Docs", f"{embedding_status['changed_document_count']:,}")
        e4.metric("Reranker", "ready" if embedding_status["reranker_ready"] else "not ready")
        e5.metric("Index Health", embedding_status["index_health"])
        if embedding_status["last_build_time"]:
            st.caption(f"Last build time: `{embedding_status['last_build_time']}`")
        if embedding_status.get("latest_report_path"):
            st.caption(f"Latest embedding report: `{embedding_status['latest_report_path']}`")
            with st.expander("Latest embedding/rerank status", expanded=False):
                st.json(embedding_status.get("latest_report") or {})
        else:
            st.info("Embedding and reranker reports will appear under `indexes/` after the index build runs.")
    st.divider()
    st.markdown("### Knowledge Graph")
    site_id = st.session_state.get("site_id", "")
    if not site_id:
        st.info("Select or create a site first.")
    else:
        site_root = DATA_ROOT / "sites" / site_id
        graph_run_choices = sorted([d.name for d in site_root.iterdir() if d.is_dir() and d.name != "meta"]) if site_root.exists() else []
        graph_real_runs = [name for name in graph_run_choices if _is_real_scrape_run(site_id, name)]
        if not graph_real_runs:
            st.info("No raw markdown run is available yet. Scrape pages first, then build the graph.")
        else:
            latest_graph_run = graph_real_runs[-1]
            current_graph_run = st.session_state.get("graph_run", "")
            selected_graph_run = current_graph_run if current_graph_run in graph_real_runs else latest_graph_run
            selected_graph_index = graph_real_runs.index(selected_graph_run)
            graph_run = st.selectbox(
                "Graph run",
                options=graph_real_runs,
                index=selected_graph_index,
                key="graph_run",
                format_func=lambda run_name: f"Run {_run_human_timestamp(run_name)}",
            )
            graph_run_root = site_root / graph_run
            graph_dir = knowledge_graph_dir(graph_run_root)
            stats = load_graph_stats(graph_run_root)
            raw_files = discover_raw_markdown_files(graph_run_root)
            raw_count = len(raw_files)
            page_count = int(stats.get("page_nodes") or 0)
            unit_count = int(stats.get("unit_nodes") or 0)
            edge_count = int(stats.get("edges") or 0)
            status_label = "ready" if stats.get("status") == "ready" else "missing"
            if stats.get("counts_match") is False:
                status_label = "count mismatch"

            g1, g2, g3, g4, g5 = st.columns([1, 1, 1, 1, 1.4])
            g1.metric("Raw Files", f"{raw_count:,}")
            g2.metric("Page Nodes", f"{page_count:,}")
            g3.metric("Units", f"{unit_count:,}")
            g4.metric("Edges", f"{edge_count:,}")
            g5.metric("Graph Status", status_label)
            st.caption(f"Primary retrieval graph: `{graph_dir / 'graph.json'}`")

            b1, b2, b3, b4 = st.columns([1.4, 1.6, 1.2, 2.8])
            if b1.button("Build Deterministic Graph", type="primary", key="build_deterministic_kg"):
                try:
                    graph = build_markdown_graph(graph_run_root, site_id, graph_run)
                    st.success(
                        f"Built graph with {graph['counts']['page_nodes']:,} page nodes and {graph['counts']['edges']:,} edges."
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(f"Graph build failed: {exc}")

            selected_unit_for_enrich = b2.selectbox(
                "Semantic enrichment unit",
                options=[row.get("unit_key") for row in graph_list_units(graph_run_root) if row.get("page_count", 0) > 0] or [""],
                help="Optional bounded enrichment merged into knowledge_graph/graph.json. Deterministic graph does not require it.",
                key="semantic_enrichment_unit",
            )
            if b3.button("Rebuild Query Index", disabled=stats.get("status") != "ready", key="rebuild_kg_query_index"):
                try:
                    st.json(rebuild_graph_query_index(graph_run_root))
                except Exception as exc:
                    st.error(f"Query index rebuild failed: {exc}")
            b4.caption(
                "Use Build Deterministic Graph for the real retrieval graph. Optional semantic enrichment can add concept edges after the deterministic build."
            )
            if st.button(
                "Run Semantic Enrichment for Selected Unit",
                disabled=stats.get("status") != "ready" or not selected_unit_for_enrich,
                key="run_semantic_enrichment_unit",
            ):
                try:
                    st.json(run_graphify_enrichment_for_unit(graph_run_root, str(selected_unit_for_enrich)))
                    st.rerun()
                except Exception as exc:
                    st.error(f"Semantic enrichment failed: {exc}")

            if stats.get("status") != "ready":
                st.info("Build the deterministic graph to enable inspection and retrieval controls.")
            else:
                dist = load_unit_distribution(graph_run_root)
                no_unit = load_pages_without_unit_tags(graph_run_root)
                orphaned = load_graph_orphan_pages(graph_run_root)
                tags = load_graph_tags(graph_run_root)
                edges = load_graph_edges(graph_run_root)
                pages = load_graph_page_nodes(graph_run_root)

                st.caption("Coverage")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Tagged Pages", f"{len({t.get('page_id') for t in tags}):,}")
                c2.metric("Pages Without Unit", f"{len(no_unit):,}")
                c3.metric("Orphan Pages", f"{len(orphaned):,}")
                c4.metric("Graph Count Match", "yes" if stats.get("counts_match") else "no")

                left, right = st.columns([1.2, 1])
                with left:
                    st.caption("Unit Distribution")
                    if dist:
                        st.dataframe(pd.DataFrame(dist), use_container_width=True, hide_index=True)
                    else:
                        st.info("No unit tags found.")
                with right:
                    st.caption("Edge Types")
                    edge_counts = pd.DataFrame(
                        [{"type": key, "count": val} for key, val in Counter([edge.get("type") for edge in edges]).items()]
                    ).sort_values("count", ascending=False)
                    st.dataframe(edge_counts, use_container_width=True, hide_index=True)

                with st.expander("Pages without unit tags", expanded=False):
                    if no_unit:
                        st.dataframe(
                            pd.DataFrame(no_unit)[[c for c in ["id", "title", "source_url", "path"] if c in no_unit[0]]],
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.success("Every page has at least one unit tag.")
                with st.expander("Orphan pages and isolated nodes", expanded=False):
                    if orphaned:
                        st.dataframe(
                            pd.DataFrame(orphaned)[[c for c in ["id", "title", "source_url", "path"] if c in orphaned[0]]],
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.success("No orphan pages.")

                inspect_tabs = st.tabs(["Query", "Path", "Explain", "Knowledge Graph HTML"])
                with inspect_tabs[0]:
                    st.markdown("#### Ask the markdown graph")
                    unit_options = [""] + [str(row.get("unit_key")) for row in graph_list_units(graph_run_root) if row.get("page_count", 0) > 0]
                    graph_query = st.text_area(
                        "Ask a question",
                        value="I-20 international students",
                        height=90,
                        key="kg_query",
                        help="This queries the deterministic raw-markdown graph and returns source markdown evidence for the LLM.",
                    )
                    q1, q2, q3 = st.columns([1.6, 1, 1])
                    graph_unit = q1.selectbox("Unit filter", options=unit_options, index=0, key="kg_query_unit")
                    graph_limit = int(q2.number_input("Page result limit", min_value=1, max_value=50, value=10, key="kg_query_limit"))
                    context_budget = int(q3.number_input("Evidence budget", min_value=1000, max_value=50000, value=12000, step=1000, key="kg_context_budget"))
                    ask_col, search_col = st.columns([1, 1])
                    ask_clicked = ask_col.button("Ask Graph / Get Evidence", type="primary", key="kg_build_context")
                    search_clicked = search_col.button("Search Matching Pages", key="kg_search_pages")
                    if ask_clicked:
                        context = graph_answer_context(graph_run_root, graph_query, unit=graph_unit or None, budget_chars=context_budget)
                        st.success(f"Found {len(context.get('evidence', []))} evidence item(s), {context.get('used_chars', 0)} chars.")
                        for item in context.get("evidence", []):
                            with st.container(border=True):
                                st.markdown(f"**{item.get('title') or item.get('page_id')}**")
                                st.caption(f"{item.get('source_url')} | `{item.get('path')}`")
                                st.code(item.get("markdown_excerpt", ""), language="markdown")
                        with st.expander("Raw MCP-style answer_context payload", expanded=False):
                            st.json({k: v for k, v in context.items() if k != "evidence"})
                    if search_clicked:
                        results = graph_search_pages(graph_run_root, graph_query, unit=graph_unit or None, limit=graph_limit)
                        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
                with inspect_tabs[1]:
                    page_options = [page.get("id") for page in pages if page.get("id")]
                    safe_page_options = page_options or [""]
                    p1, p2, p3 = st.columns([1.5, 1.5, 1])
                    from_page = p1.selectbox("From page", options=safe_page_options, index=0, key="kg_path_from")
                    to_page = p2.selectbox("To page", options=safe_page_options, index=min(1, len(safe_page_options) - 1), key="kg_path_to")
                    depth = int(p3.number_input("Depth", min_value=1, max_value=4, value=1, key="kg_traverse_depth"))
                    if st.button("Traverse From Page", disabled=not from_page, key="kg_traverse"):
                        st.json(graph_traverse_from_page(graph_run_root, str(from_page), depth=depth))
                    if st.button("Shortest Path", disabled=not from_page or not to_page, key="kg_shortest_path"):
                        st.json(graph_shortest_path(graph_run_root, str(from_page), str(to_page)))
                with inspect_tabs[2]:
                    selected_unit = st.selectbox("Unit pages", options=unit_options, key="kg_explain_unit")
                    if selected_unit:
                        rows = graph_get_unit_pages(graph_run_root, selected_unit, limit=200)
                        st.dataframe(
                            pd.DataFrame(rows)[[c for c in ["id", "title", "source_url", "path"] if rows and c in rows[0]]],
                            use_container_width=True,
                            hide_index=True,
                        )
                    with st.expander("Build status JSON", expanded=False):
                        st.json(read_json(graph_dir / "build_status.json", {}))
                with inspect_tabs[3]:
                    graph_html = graph_dir / "graph.html"
                    if graph_html.exists():
                        st.caption(f"Rendered from `{graph_html}`. This is the deterministic knowledge graph summary.")
                        components.html(graph_html.read_text(encoding="utf-8", errors="replace"), height=650, scrolling=True)
                    else:
                        st.info("HTML graph view will appear after build.")
    st.divider()
    st.markdown("### Run Metrics")
    if not st.session_state.get("site_id"):
        st.info("Select or create a site first.")
    else:
        site_root = DATA_ROOT / "sites" / st.session_state["site_id"]
        run_choices = sorted([d.name for d in site_root.iterdir() if d.is_dir() and d.name != "meta"]) if site_root.exists() else []
        real_run_choices = [name for name in run_choices if _is_real_scrape_run(st.session_state["site_id"], name)]
        if not real_run_choices:
            st.info("No scrape runs are available yet. Start a scrape to populate metrics.")
        else:
            latest_run = real_run_choices[-1]
            current_selected = st.session_state.get("metrics_run", "")
            selected_run = current_selected if current_selected in real_run_choices else latest_run
            selected_index = real_run_choices.index(selected_run)
            metrics_run = st.selectbox(
                "Run",
                options=real_run_choices,
                index=selected_index,
                key="metrics_run",
                format_func=lambda run_name: f"Run {_run_human_timestamp(run_name)}",
            )
            run_root = site_root / metrics_run
            run_events = load_events(run_root)
            site_events = load_events(site_root / "meta")
            model_map = {m.get("id"): m for m in st.session_state.get("openrouter_models", [])}
            tavily_per_call = float(st.session_state.get("tavily_cost_per_call_usd", 0.0))
            ollama_in_per_m = float(st.session_state.get("ollama_input_per_m_usd", 0.0))
            ollama_out_per_m = float(st.session_state.get("ollama_output_per_m_usd", 0.0))
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

            def _fmt_compact_number(value: float) -> str:
                val = float(value)
                abs_val = abs(val)
                if abs_val >= 1_000_000_000:
                    return f"{val/1_000_000_000:.1f}B"
                if abs_val >= 1_000_000:
                    return f"{val/1_000_000:.1f}M"
                if abs_val >= 1_000:
                    return f"{val/1_000:.1f}K"
                return f"{int(val)}" if val.is_integer() else f"{val:.1f}"

            st.caption("Run Summary")
            with st.container(border=True):
                ra1, ra2, ra3, ra4, ra5 = st.columns(5)
                ra1.metric("Selected URLs", _fmt_compact_number(len(selected_urls) if isinstance(selected_urls, list) else 0))
                ra2.metric("Scraped Pages", _fmt_compact_number(int(page_summary.get("success", 0))))
                ra3.metric("Cleaned Pages", _fmt_compact_number(len(cleaned_pages)))
                ra4.metric("Skipped Pages", _fmt_compact_number(len(skipped_pages)))
                ra5.metric("Failed Pages", _fmt_compact_number(int(page_summary.get("failed", 0))))

                st.write("")
                st.caption("Performance")
                rb1, rb2, rb3, rb4, rb5 = st.columns(5)
                rb1.metric("Elapsed", f"{float(page_summary.get('elapsed_sec', 0.0)) / 60.0:.1f} min")
                rb2.metric("Pages / min", f"{float(page_summary.get('pages_per_min', 0.0)):.2f}")
                eta_value = page_summary.get("eta_min")
                rb3.metric("ETA", "—" if eta_value is None else f"{float(eta_value):.1f} min")
                rb4.metric("P50 Duration", f"{float(duration_summary.get('p50_sec', 0.0)):.2f} s")
                rb5.metric("P95 Duration", f"{float(duration_summary.get('p95_sec', 0.0)):.2f} s")

                st.write("")
                st.caption("Content Volume")
                rc1, rc2, rc3 = st.columns(3)
                rc1.metric("Markdown Bytes", _fmt_compact_number(int(output_summary.get("markdown_total_bytes", 0))))
                rc2.metric("Raw HTML Bytes", _fmt_compact_number(int(output_summary.get("raw_html_total_bytes", 0))))
                rc3.metric("Avg Text Length", _fmt_compact_number(float(output_summary.get("text_avg", 0.0))))

            with st.container(border=True):
                st.caption("Scrape Analytics Charts")
                if completion_df.empty:
                    st.info("No completed pages yet for run-level scrape analytics.")
                else:
                    cts1, cts2 = st.columns(2)
                    cts1.altair_chart(
                        alt.Chart(completion_df)
                        .mark_line(point=alt.OverlayMarkDef(size=22, filled=True))
                        .encode(
                            x=alt.X("bucket:T", title="Time"),
                            y=alt.Y("completed:Q", title="Pages Completed"),
                            tooltip=["bucket:T", "completed:Q", "success:Q", "failed:Q", "cancelled:Q"],
                        )
                        .properties(height=300),
                        use_container_width=True,
                    )
                    cts2.altair_chart(
                        alt.Chart(completion_df)
                        .mark_line(point=alt.OverlayMarkDef(size=22, filled=True))
                        .encode(
                            x=alt.X("bucket:T", title="Time"),
                            y=alt.Y("ppm:Q", title="Pages / Minute"),
                            tooltip=["bucket:T", "ppm:Q"],
                        )
                        .properties(height=300),
                        use_container_width=True,
                    )

                st.write("")
                fr1, fr2, fr3 = st.columns(3)
                by_reason_df = failure_summary["by_reason"]
                by_fetch_mode_df = failure_summary["by_fetch_mode"]
                by_http_status_df = failure_summary["by_http_status"]
                if by_reason_df.empty:
                    fr1.info("No failures by reason yet.")
                else:
                    fr1.altair_chart(
                        alt.Chart(by_reason_df.sort_values("count", ascending=False))
                        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                        .encode(
                            x=alt.X("count:Q", title="Count"),
                            y=alt.Y("label:N", title="Reason", sort="-x"),
                            tooltip=["label", "count"],
                        )
                        .properties(height=240),
                        use_container_width=True,
                    )
                if by_fetch_mode_df.empty:
                    fr2.info("No failures by fetch mode yet.")
                else:
                    fr2.altair_chart(
                        alt.Chart(by_fetch_mode_df.sort_values("count", ascending=False))
                        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                        .encode(
                            x=alt.X("count:Q", title="Count"),
                            y=alt.Y("label:N", title="Fetch Mode", sort="-x"),
                            tooltip=["label", "count"],
                        )
                        .properties(height=240),
                        use_container_width=True,
                    )
                if by_http_status_df.empty:
                    fr3.info("No failures by HTTP status yet.")
                else:
                    fr3.altair_chart(
                        alt.Chart(by_http_status_df.sort_values("count", ascending=False))
                        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                        .encode(
                            x=alt.X("count:Q", title="Count"),
                            y=alt.Y("label:N", title="HTTP Status", sort="-x"),
                            tooltip=["label", "count"],
                        )
                        .properties(height=240),
                        use_container_width=True,
                    )

                if not slow_pages_df.empty:
                    st.caption("Slowest Pages")
                    st.dataframe(slow_pages_df, use_container_width=True, hide_index=True)

            with st.container(border=True):
                st.caption("OpenRouter LLM Metrics")
                openrouter_trace = trace_df[
                    (trace_df["provider"].fillna("").astype(str) == "openrouter")
                    & (~trace_df.get("is_summary", pd.Series(False, index=trace_df.index)).fillna(False).astype(bool))
                ].copy() if not trace_df.empty else pd.DataFrame()
                if openrouter_trace.empty:
                    st.info("No non-summary OpenRouter calls recorded for this run yet.")
                else:
                    openrouter_trace["ts"] = pd.to_datetime(openrouter_trace.get("ts"), errors="coerce", utc=True)
                    openrouter_trace = openrouter_trace.dropna(subset=["ts"]).copy()
                    openrouter_trace["operation"] = openrouter_trace.get("operation", "unknown").fillna("unknown").astype(str)
                    openrouter_trace["model"] = openrouter_trace.get("model", "unknown").fillna("unknown").astype(str)
                    openrouter_trace["prompt_tokens"] = pd.to_numeric(openrouter_trace.get("prompt_tokens"), errors="coerce").fillna(0.0)
                    openrouter_trace["completion_tokens"] = pd.to_numeric(openrouter_trace.get("completion_tokens"), errors="coerce").fillna(0.0)
                    openrouter_trace["total_tokens"] = pd.to_numeric(openrouter_trace.get("total_tokens"), errors="coerce").fillna(
                        openrouter_trace["prompt_tokens"] + openrouter_trace["completion_tokens"]
                    )
                    openrouter_trace["latency_ms"] = pd.to_numeric(openrouter_trace.get("latency_ms"), errors="coerce")
                    openrouter_trace["cost_usd"] = pd.to_numeric(openrouter_trace.get("cost_usd"), errors="coerce").fillna(0.0)

                    llm_calls_ts = build_llm_calls_timeseries(trace_df)
                    llm_tokens_ts = build_llm_token_timeseries(trace_df)
                    llm_model_counts = build_llm_model_counts(trace_df)
                    llm_latency = build_llm_latency_table(trace_df)
                    llm_cost_by_operation = build_llm_cost_breakdown(trace_df, group_by="operation")
                    llm_cost_by_model = build_llm_cost_breakdown(trace_df, group_by="model")
                    llm_operation_counts = (
                        llm_calls_ts.groupby("operation", as_index=False)["calls"].sum().sort_values("calls", ascending=False)
                        if not llm_calls_ts.empty
                        else pd.DataFrame(columns=["operation", "calls"])
                    )
                    llm_p95_latency = float(llm_latency["latency_ms"].quantile(0.95)) if not llm_latency.empty else 0.0

                    l1, l2, l3, l4 = st.columns(4)
                    l1.metric("OpenRouter Calls", _fmt_compact_number(len(openrouter_trace)))
                    l2.metric("Prompt Tokens", _fmt_compact_number(float(openrouter_trace["prompt_tokens"].sum())))
                    l3.metric("Completion Tokens", _fmt_compact_number(float(openrouter_trace["completion_tokens"].sum())))
                    l4.metric("P95 Latency", f"{llm_p95_latency:.1f} ms")

                    gt1, gt2 = st.columns(2)
                    if llm_calls_ts.empty:
                        gt1.info("No call timeline data yet.")
                    else:
                        gt1.altair_chart(
                            alt.Chart(llm_calls_ts)
                            .mark_line(point=alt.OverlayMarkDef(size=18, filled=True))
                            .encode(
                                x=alt.X("bucket:T", title="Time"),
                                y=alt.Y("calls:Q", title="Calls"),
                                color=alt.Color("operation:N", title="Operation"),
                                tooltip=["bucket:T", "operation", "calls"],
                            )
                            .properties(height=280),
                            use_container_width=True,
                        )
                    if llm_operation_counts.empty:
                        gt2.info("No operation breakdown yet.")
                    else:
                        gt2.altair_chart(
                            alt.Chart(llm_operation_counts)
                            .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                            .encode(
                                x=alt.X("calls:Q", title="Calls"),
                                y=alt.Y("operation:N", title="Operation", sort="-x"),
                                tooltip=["operation", "calls"],
                            )
                            .properties(height=280),
                            use_container_width=True,
                        )

                    gt3, gt4 = st.columns(2)
                    if llm_model_counts.empty:
                        gt3.info("No model mix data yet.")
                    else:
                        gt3.altair_chart(
                            alt.Chart(llm_model_counts)
                            .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                            .encode(
                                x=alt.X("calls:Q", title="Calls"),
                                y=alt.Y("model:N", title="Model", sort="-x"),
                                tooltip=["model", "calls"],
                            )
                            .properties(height=300),
                            use_container_width=True,
                        )
                    if llm_tokens_ts.empty:
                        gt4.info("No token timeline data yet.")
                    else:
                        token_long = llm_tokens_ts.melt(
                            id_vars=["bucket"],
                            value_vars=["prompt_tokens", "completion_tokens"],
                            var_name="token_type",
                            value_name="tokens",
                        )
                        gt4.altair_chart(
                            alt.Chart(token_long)
                            .mark_area(opacity=0.7)
                            .encode(
                                x=alt.X("bucket:T", title="Time"),
                                y=alt.Y("tokens:Q", title="Tokens"),
                                color=alt.Color("token_type:N", title="Token Type"),
                                tooltip=["bucket:T", "token_type", "tokens"],
                            )
                            .properties(height=300),
                            use_container_width=True,
                        )

                    gt5, gt6 = st.columns(2)
                    gt5.altair_chart(
                        alt.Chart(openrouter_trace)
                        .mark_bar()
                        .encode(
                            x=alt.X("total_tokens:Q", bin=alt.Bin(maxbins=20), title="Total Tokens / Call"),
                            y=alt.Y("count():Q", title="Calls"),
                            tooltip=[alt.Tooltip("count():Q", title="Calls")],
                        )
                        .properties(height=280),
                        use_container_width=True,
                    )
                    latency_ts = openrouter_trace.dropna(subset=["latency_ms"]).sort_values("ts")
                    if latency_ts.empty:
                        gt6.info("No latency timeline yet.")
                    else:
                        gt6.altair_chart(
                            alt.Chart(latency_ts)
                            .mark_line(point=alt.OverlayMarkDef(size=18, filled=True, opacity=0.6))
                            .encode(
                                x=alt.X("ts:T", title="Time"),
                                y=alt.Y("latency_ms:Q", title="Latency (ms)"),
                                color=alt.Color("operation:N", title="Operation"),
                                tooltip=["ts:T", "operation", "model", "latency_ms", "status"],
                            )
                            .properties(height=280),
                            use_container_width=True,
                        )

                    gt7, gt8 = st.columns(2)
                    if llm_latency.empty:
                        gt7.info("No latency distribution yet.")
                    else:
                        gt7.altair_chart(
                            alt.Chart(llm_latency)
                            .mark_boxplot(extent="min-max")
                            .encode(
                                x=alt.X("operation:N", title="Operation"),
                                y=alt.Y("latency_ms:Q", title="Latency (ms)"),
                                color=alt.Color("operation:N", legend=None),
                                tooltip=["operation", "model", "latency_ms"],
                            )
                            .properties(height=300),
                            use_container_width=True,
                        )
                    cost_long = pd.concat(
                        [
                            llm_cost_by_operation.rename(columns={"operation": "label"}).assign(dimension="operation"),
                            llm_cost_by_model.rename(columns={"model": "label"}).assign(dimension="model"),
                        ],
                        ignore_index=True,
                    )
                    if cost_long.empty:
                        gt8.info("No non-zero OpenRouter cost data yet.")
                    else:
                        gt8.altair_chart(
                            alt.Chart(cost_long)
                            .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                            .encode(
                                x=alt.X("cost_usd:Q", title="Estimated Cost (USD)"),
                                y=alt.Y("label:N", title="Operation / Model", sort="-x"),
                                color=alt.Color("dimension:N", title="Breakdown"),
                                tooltip=["dimension", "label", "cost_usd"],
                            )
                            .properties(height=300),
                            use_container_width=True,
                        )
    st.divider()
    st.markdown("### MCP Readiness")
    site_id = st.session_state.get("site_id", "")
    if not site_id:
        st.info("Create or open a workspace first.")
    else:
        layout = site_layout(DATA_ROOT / "sites" / site_id)
        raw_status = _raw_source_status(layout)
        wiki_status = _load_wiki_status(layout, raw_status)
        embedding_status = _load_embedding_status(layout)
        mcp_status = _load_mcp_status(layout)
        if not _raw_sources_ready(raw_status):
            st.warning("Missing prerequisite: normalize raw data sources before MCP query setup.")
        elif not _wiki_ready(wiki_status):
            st.warning("Missing prerequisite: build the LLM Wiki before MCP query setup.")
        elif embedding_status["index_health"] != "ready":
            st.warning("Missing prerequisite: build healthy raw/wiki indexes before MCP query setup.")
        elif not mcp_status["server_available"]:
            st.warning("MCP server implementation is pending. Query setup stays unavailable until a real server module is present.")
        else:
            st.success("MCP query prerequisites are ready.")

        m1, m2 = st.columns(2)
        m1.metric("Index Health", mcp_status["index_health"])
        m2.metric("Server", "configured" if mcp_status["server_available"] else "pending")
        if mcp_status["server_command"]:
            st.caption("Server command")
            st.code(mcp_status["server_command"], language="bash")
            st.caption("Codex MCP config snippet")
            st.json(mcp_status["config_snippet"])
        else:
            st.caption("Expected MCP command once implemented")
            st.code(mcp_status["expected_server_command"], language="bash")
        if mcp_status.get("latest_report_path"):
            st.caption(f"Latest MCP report: `{mcp_status['latest_report_path']}`")

with tabs[6]:
    st.subheader("Settings")
    st.caption("Configure only what you need. Advanced knobs are grouped to reduce clutter.")

    status_cols = st.columns(4)
    status_cols[0].metric("OpenRouter", "set" if st.session_state.get("openrouter_api_key") else "missing")
    status_cols[1].metric("Scraper", st.session_state.get("scrape_browser_mode", "none"))
    status_cols[2].metric("Concurrency", int(st.session_state.get("scrape_concurrency", 10)))
    status_cols[3].metric("Vector", "on" if st.session_state.get("zvec_enabled", True) else "off")

    settings_tabs = st.tabs(["🔑 Keys", "🤖 LLM", "🕷 Scraping", "🔎 Retrieval", "🧪 Research"])

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

        with st.expander("Graph enrichment", expanded=False):
            tg1, tg2, tg3 = st.columns([1, 1.5, 1.5])
            current_graph_provider = st.session_state.get("graph_enrichment_provider", "openrouter")
            st.session_state["graph_enrichment_provider"] = tg1.selectbox(
                "Provider",
                options=["deterministic", "openrouter", "ollama"],
                index=["deterministic", "openrouter", "ollama"].index(current_graph_provider)
                if current_graph_provider in {"deterministic", "openrouter", "ollama"}
                else 1,
                help="URL graph artifacts are secondary support. Provider applies only to optional semantic enrichment.",
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

        with st.expander("Graph Q&A", expanded=False):
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
