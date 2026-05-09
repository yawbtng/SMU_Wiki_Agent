from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote

import altair as alt
import pandas as pd
import streamlit as st

from src.scrape_planner.failure_classifier import classify_failure
from src.scrape_planner.llm_orchestrator import (
    choose_top_urls_with_openrouter,
    explain_url_selection_with_openrouter,
    fetch_ollama_models,
    fetch_openrouter_models,
    pull_ollama_model,
)
from src.scrape_planner.local_cleanup import CleanupRunner, ollama_available
from src.scrape_planner.models import DiscoveredURL
from src.scrape_planner.observability import append_event, load_events, summarize_events
from src.scrape_planner.run_persistence import read_page_states, read_run_events, read_run_status
from src.scrape_planner.run_analytics import (
    build_completion_timeseries,
    build_slowest_pages_table,
    summarize_durations,
    summarize_failures,
    summarize_output_volume,
    summarize_pages,
)
from src.scrape_planner.scrape_worker import ScrapeRunner
from src.scrape_planner.sitemap_discovery import apply_manual_urls, discover_site_urls, normalize_site_url
from src.scrape_planner.state import RunStateStore
from src.scrape_planner.storage import persist_discovered, read_json, write_json
from src.scrape_planner.tavily_retry import retry_failed_with_tavily
from src.scrape_planner.terminal_skill_runner import TerminalSkillRunner
from src.scrape_planner.tmux_runner import TmuxRunner
from src.scrape_planner.ui_claude_plan import render_claude_plan_section
from src.scrape_planner.ui_navigation import WORKFLOW_TABS

ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / "data"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
ENV_PATH = ROOT / ".env"
APP_STATE_PATH = DATA_ROOT / "app_state.json"
PI_PROMPT_TEMPLATE_PATH = ROOT / "prompts" / "pi_url_selection_prompt.md"


def _site_slug(url: str) -> str:
    return normalize_site_url(url).replace("https://", "").replace("http://", "").replace("/", "_")


def _detect_pi_binary() -> str:
    for candidate in ("pi", "pi-agent", "pi_agent"):
        found = shutil.which(candidate)
        if found:
            return found
    local_candidate = Path.home() / ".local" / "bin" / "pi"
    if local_candidate.exists():
        return str(local_candidate)
    return "pi"


def _detect_tmux_binary() -> str:
    for candidate in ("tmux", "/opt/homebrew/bin/tmux", "/usr/local/bin/tmux"):
        found = shutil.which(candidate) if "/" not in candidate else (candidate if Path(candidate).exists() else "")
        if found:
            return str(found)
    return "tmux"


def _extract_json_payload_from_text(text: str):
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty JSON output")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    starts = [idx for idx in (stripped.find("["), stripped.find("{")) if idx >= 0]
    if not starts:
        raise ValueError("no JSON payload found")
    start = min(starts)
    end = max(stripped.rfind("]"), stripped.rfind("}"))
    if end <= start:
        raise ValueError("incomplete JSON payload")
    return json.loads(stripped[start : end + 1])


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
        "tavily_cost_per_call_usd": 0.0,
        "ollama_input_per_m_usd": 0.0,
        "ollama_output_per_m_usd": 0.0,
        "selector_chat": [],
        "last_selection_payload": {},
        "pi_binary": "",
        "tmux_binary": "",
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

def _get_cleanup_runner() -> CleanupRunner:
    if "cleanup_runner" not in st.session_state:
        st.session_state["cleanup_runner"] = CleanupRunner(_get_store())
    return st.session_state["cleanup_runner"]


def _get_terminal_skill_runner() -> TerminalSkillRunner:
    if "terminal_skill_runner" not in st.session_state:
        st.session_state["terminal_skill_runner"] = TerminalSkillRunner()
    return st.session_state["terminal_skill_runner"]


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


def _safe_read_json(path_value: object) -> tuple[dict | list | None, Path | None, str | None]:
    try:
        raw = str(path_value or "").strip()
        if not raw:
            return None, None, "No metadata path recorded."
        path = Path(raw)
        if not path.exists():
            return None, path, "Metadata file not found."
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload, path, None
    except Exception as exc:
        return None, None, f"Failed to read metadata JSON: {exc}"


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


def _next_retry_run_id(source_run_id: str, site_id: str) -> str:
    base = f"{source_run_id}-retry-"
    site_root = DATA_ROOT / "sites" / site_id
    idx = 1
    while (site_root / f"{base}{idx:02d}").exists():
        idx += 1
    return f"{base}{idx:02d}"


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
            "site_history": st.session_state.get("site_history", []),
            "tavily_api_key": st.session_state.get("tavily_api_key", ""),
            "default_or_model": st.session_state.get("default_or_model", "deepseek/deepseek-v4-flash"),
            "default_llm_cap": int(st.session_state.get("default_llm_cap", 150)),
            "default_llm_batch_size": int(st.session_state.get("default_llm_batch_size", 250)),
            "default_llm_sleep_sec": float(st.session_state.get("default_llm_sleep_sec", 0.0)),
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
        if ollama_available(url):
            return url
    return _normalize_ollama_base_url(current_value)


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


st.set_page_config(page_title="Scrapling Scrape Planner", layout="wide")
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
store = _get_store()
runner = _get_runner()
cleanup_runner = _get_cleanup_runner()
terminal_skill_runner = _get_terminal_skill_runner()
tmux_runner = _get_tmux_runner()

st.title("Scrapling Scrape Planner")
st.caption("Discover sitemap URLs, select pages, scrape with failure visibility, clean with local LLM, and build wiki inputs.")

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
    st.subheader("Workspace Dashboard")
    if active_ws:
        st.caption("You are inside this workspace. Use the tabs above to discover, select, scrape, clean, and inspect metrics.")
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Workspace", active_ws.get("name", "Workspace"))
        d2.metric("Site ID", st.session_state.get("site_id") or "not_set")
        discovered_count = len(st.session_state.get("discovered") or read_json(_discovered_json_path(st.session_state["site_id"]), []))
        d3.metric("Discovered URLs", f"{discovered_count:,}")
        d4.metric("Active Run", st.session_state.get("run_id") or "none")
        st.info("Next step: go to `Discover` to refresh sitemap URLs, then `Select` to score and choose important URLs before scraping.")
    else:
        st.warning("No active workspace selected. Go back to the workspace list and open one.")

    with st.expander("Advanced: change active site URL", expanded=False):
        st.warning("Only use this if you intentionally want this workspace to point at a different root URL.")
        if st.session_state["site_history"]:
            options = [""] + st.session_state["site_history"]
            current_url = st.session_state.get("site_url", "")
            idx = options.index(current_url) if current_url in options else 0
            recent = st.selectbox("Recent Sites", options=options, index=idx)
            if recent and recent != st.session_state.get("site_url", ""):
                st.session_state["site_url"] = recent
                st.session_state["site_id"] = _site_slug(recent)
                st.session_state["run_id"] = st.session_state["last_run_by_site"].get(st.session_state["site_id"], "")
                _hydrate_site_workspace(st.session_state["site_id"])
                _save_app_state()
                st.rerun()
        site_input = st.text_input("Website root URL", value=st.session_state["site_url"], placeholder="https://example.com")
        if st.button("Update Active Site", type="secondary"):
            normalized = normalize_site_url(site_input)
            st.session_state["site_url"] = normalized
            st.session_state["site_id"] = _site_slug(normalized)
            st.session_state["run_id"] = st.session_state["last_run_by_site"].get(st.session_state["site_id"], "")
            _hydrate_site_workspace(st.session_state["site_id"])
            st.session_state["site_history"] = [normalized] + [u for u in st.session_state["site_history"] if u != normalized]
            st.session_state["site_history"] = st.session_state["site_history"][:50]
            (DATA_ROOT / "sites" / st.session_state["site_id"]).mkdir(parents=True, exist_ok=True)
            _save_app_state()
            st.success(f"Active site updated: {normalized}")

    with st.expander("Manage workspaces", expanded=False):
        st.caption("Workspace creation/deletion is hidden here so the active workflow stays focused.")
        with st.form("new_workspace_form_inside_active", clear_on_submit=True):
            c1, c2 = st.columns(2)
            ws_name = c1.text_input("University Name", placeholder="Southern Methodist University")
            ws_url = c2.text_input("Website URL", placeholder="https://www.smu.edu")
            submitted = st.form_submit_button("+ Add Workspace")
            if submitted and ws_name.strip() and ws_url.strip():
                normalized = normalize_site_url(ws_url.strip())
                ws_id = _site_slug(normalized)
                new_ws = {"id": ws_id, "name": ws_name.strip(), "url": normalized}
                existing = [w for w in st.session_state["workspaces"] if w.get("id") != ws_id]
                st.session_state["workspaces"] = [new_ws] + existing
                (DATA_ROOT / "sites" / ws_id).mkdir(parents=True, exist_ok=True)
                _save_app_state()
                st.rerun()
        for ws in st.session_state.get("workspaces", []):
            with st.container(border=True):
                st.markdown(f"**{ws.get('name','Unnamed University')}**")
                st.caption(ws.get("url", ""))
                c1, c2 = st.columns(2)
                is_current = ws.get("id") == st.session_state.get("active_workspace_id")
                if c1.button("Open Workspace" if not is_current else "Current Workspace", key=f"manage_open_ws_{ws.get('id')}", disabled=is_current):
                    st.session_state["active_workspace_id"] = ws.get("id", "")
                    st.session_state["site_url"] = ws.get("url", "")
                    st.session_state["site_id"] = ws.get("id", "")
                    st.session_state["run_id"] = st.session_state.get("last_run_by_site", {}).get(ws.get("id", ""), "")
                    _hydrate_site_workspace(st.session_state["site_id"])
                    _save_app_state()
                    st.rerun()
                if c2.button("Delete Workspace", key=f"manage_del_ws_{ws.get('id')}", disabled=is_current):
                    st.session_state["workspaces"] = [w for w in st.session_state["workspaces"] if w.get("id") != ws.get("id")]
                    _save_app_state()
                    st.rerun()

with tabs[1]:
    st.write("Sitemap discovery from robots.txt and common sitemap paths.")
    if st.button("Discover Sitemap URLs", disabled=not st.session_state["site_url"], type="primary"):
        result = discover_site_urls(st.session_state["site_url"])
        st.session_state["discovered"] = _to_discovered_rows(result.urls)
        st.session_state["selected_df"] = pd.DataFrame(st.session_state["discovered"])
        persist_discovered(_discovered_json_path(st.session_state["site_id"]), result.urls)
        _save_app_state()
        st.info("\n".join(result.notes) if result.notes else "Discovery completed.")

    st.write("Manual URL add (one per line)")
    st.session_state["manual_urls"] = st.text_area("Manual URLs", value=st.session_state["manual_urls"], height=120)
    _save_app_state()
    if st.button("Add Manual URLs"):
        items = apply_manual_urls(st.session_state["site_url"], st.session_state["manual_urls"].splitlines())
        merged = {row["url"]: row for row in st.session_state["discovered"]}
        for item in items:
            merged[item.url] = item.to_dict()
        st.session_state["discovered"] = list(merged.values())
        st.session_state["selected_df"] = pd.DataFrame(st.session_state["discovered"])
        _save_app_state()

    if st.session_state["discovered"]:
        st.dataframe(pd.DataFrame(st.session_state["discovered"]), use_container_width=True)
    else:
        st.warning("No URLs discovered yet.")

with tabs[2]:
    if not st.session_state["discovered"]:
        disk_rows = read_json(_discovered_json_path(st.session_state["site_id"]), [])
        if disk_rows:
            st.session_state["discovered"] = disk_rows
            st.session_state["selected_df"] = pd.DataFrame(disk_rows)
    if st.session_state["discovered"]:
        df = pd.DataFrame(st.session_state["discovered"])
        score_file = DATA_ROOT / "sites" / st.session_state["site_id"] / "selected_urls_llm.json"
        if not st.session_state.get("last_selection_payload") and score_file.exists():
            try:
                st.session_state["last_selection_payload"] = read_json(score_file, {})
            except Exception:
                pass
        st.write("Selection stage runs in a live terminal session and imports JSON scores when done.")

        with st.expander("Terminal", expanded=True):
            discovered_path = _discovered_json_path(st.session_state["site_id"])
            scored_out_path = DATA_ROOT / "sites" / st.session_state["site_id"] / "selected_urls_llm.json"
            prompt_path = DATA_ROOT / "sites" / st.session_state["site_id"] / "pi_url_selection_prompt.md"
            batch_dir = DATA_ROOT / "sites" / st.session_state["site_id"] / "pi_url_batches"
            master_instruction_path = DATA_ROOT / "sites" / st.session_state["site_id"] / "pi_url_scoring_master.md"
            if not st.session_state.get("tmux_binary"):
                st.session_state["tmux_binary"] = _detect_tmux_binary()
            if not st.session_state.get("pi_binary"):
                st.session_state["pi_binary"] = _detect_pi_binary()
            if "pi_prompt_template" not in st.session_state:
                if PI_PROMPT_TEMPLATE_PATH.exists():
                    st.session_state["pi_prompt_template"] = PI_PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
                else:
                    st.session_state["pi_prompt_template"] = "{DISCOVERED_URLS_JSON}"

            st.caption(f"{len(df):,} discovered URLs ready for scoring.")
            with st.expander("Prompt", expanded=False):
                st.session_state["pi_prompt_template"] = st.text_area(
                    "Scoring prompt template",
                    value=st.session_state["pi_prompt_template"],
                    height=260,
                    key="pi_prompt_template_input",
                    label_visibility="collapsed",
                )
                if st.button("Save Prompt Template"):
                    PI_PROMPT_TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
                    PI_PROMPT_TEMPLATE_PATH.write_text(st.session_state["pi_prompt_template"], encoding="utf-8")
                    st.success(f"Saved prompt template to {PI_PROMPT_TEMPLATE_PATH}")

            with st.expander("Advanced Paths", expanded=False):
                st.session_state["pi_binary"] = st.text_input(
                    "Agent binary",
                    value=st.session_state.get("pi_binary", ""),
                    key="pi_binary_input",
                    help="Example: /Users/abhsheno/.local/bin/pi",
                )
                st.session_state["tmux_binary"] = st.text_input(
                    "tmux binary",
                    value=st.session_state.get("tmux_binary", ""),
                    key="tmux_binary_input",
                    help="Example: /opt/homebrew/bin/tmux",
                )
                st.session_state["pi_tmux_session_name"] = st.text_input(
                    "tmux session",
                    value=st.session_state.get("pi_tmux_session_name", "pi-url-scorer"),
                    key="pi_tmux_session_name_input",
                )
                st.session_state["pi_batch_size"] = int(
                    st.number_input(
                        "URLs per agent call",
                        min_value=25,
                        max_value=1000,
                        value=int(st.session_state.get("pi_batch_size", 250)),
                        step=25,
                    )
                )
                st.text_input("Output file", value=str(scored_out_path), disabled=True)

            tmux_bin = st.session_state.get("tmux_binary", "").strip() or None
            tmux_name = st.session_state.get("pi_tmux_session_name", "pi-url-scorer")
            tmux_available = tmux_runner.available(tmux_bin=tmux_bin)
            tmux_exists = tmux_available and tmux_runner.session_exists(tmux_name, tmux_bin=tmux_bin)

            def _build_scoring_instructions() -> str:
                discovered_payload = read_json(discovered_path, [])
                batch_size = int(st.session_state.get("pi_batch_size", 250))
                batch_dir.mkdir(parents=True, exist_ok=True)
                for old_file in batch_dir.glob("*"):
                    if old_file.is_file():
                        old_file.unlink()
                batches = [
                    discovered_payload[idx : idx + batch_size]
                    for idx in range(0, len(discovered_payload), batch_size)
                ]
                for idx, batch in enumerate(batches, start=1):
                    prompt_text = st.session_state["pi_prompt_template"].replace(
                        "{DISCOVERED_URLS_JSON}",
                        pd.DataFrame(batch).to_json(orient="records", force_ascii=True),
                    )
                    (batch_dir / f"batch_{idx:04d}.prompt.md").write_text(prompt_text, encoding="utf-8")
                prompt_text = st.session_state["pi_prompt_template"].replace(
                    "{DISCOVERED_URLS_JSON}",
                    f"Split into {len(batches)} batch prompt files under {batch_dir}",
                )
                prompt_path.parent.mkdir(parents=True, exist_ok=True)
                prompt_path.write_text(prompt_text, encoding="utf-8")
                master = (
                    "# URL Scoring Terminal Task\n\n"
                    "You are running inside an interactive tmux session launched by the Streamlit UI.\n"
                    "Work visibly: briefly announce which batch you are processing, then write strict JSON outputs.\n\n"
                    "## Task\n"
                    f"Process every batch prompt file in: `{batch_dir}`\n"
                    "For each `batch_####.prompt.md`, read the file, follow its instructions exactly, and write only the JSON array output to:\n"
                    "`batch_####.prompt.output.json` in the same directory.\n\n"
                    "## Rules\n"
                    "- Do not paste large JSON into the terminal.\n"
                    "- Do not use network search unless the batch prompt explicitly asks for it.\n"
                    "- Keep going batch by batch until all prompt files have matching `.output.json` files.\n"
                    "- If a batch fails, write a short error note to `batch_####.error.txt` and continue.\n"
                    "- Final response in the terminal should say how many batch outputs were written.\n\n"
                    "## Import\n"
                    f"When finished, the UI will import all `*.output.json` files from `{batch_dir}`.\n"
                )
                master_instruction_path.write_text(master, encoding="utf-8")
                return str(master_instruction_path)

            action_1, action_2, action_3, action_4, action_5 = st.columns([1, 1, 1, 1, 1])
            if action_1.button("Build Prompt", type="secondary"):
                instruction_file = _build_scoring_instructions()
                st.session_state["pi_agent_command"] = instruction_file
                st.success("Prompt built.")

            def _start_scoring_session() -> None:
                if not tmux_available:
                    st.error("tmux not found. Set the tmux binary path in Advanced Paths.")
                    return
                instruction_file = _build_scoring_instructions()
                st.session_state["pi_agent_command"] = instruction_file
                pi_bin = st.session_state.get("pi_binary", "").strip() or "pi"
                res = tmux_runner.start_shell(tmux_name, str(ROOT), tmux_bin=tmux_bin)
                if not res.get("ok"):
                    st.error(res.get("error", "Failed to start scoring."))
                else:
                    tmux_runner.send_line(tmux_name, pi_bin, tmux_bin=tmux_bin)
                    time.sleep(0.8)
                    tmux_runner.send_line(
                        tmux_name,
                        f"Read and execute the full task from this file: {instruction_file}",
                        tmux_bin=tmux_bin,
                    )
                    st.success("Scoring started.")

            if action_2.button("Start Scoring", type="primary", disabled=tmux_exists):
                try:
                    _start_scoring_session()
                except Exception as exc:
                    st.error(f"Could not start scoring: {exc}")

            if action_3.button("Stop", disabled=not tmux_exists):
                res = tmux_runner.kill(tmux_name, tmux_bin=tmux_bin)
                if not res.get("ok"):
                    st.error(res.get("error", "Failed to stop scoring."))
                else:
                    st.warning("Scoring stopped.")
                    st.rerun()

            if action_4.button("Restart", disabled=not tmux_available):
                if tmux_exists:
                    tmux_runner.kill(tmux_name, tmux_bin=tmux_bin)
                try:
                    _start_scoring_session()
                except Exception as exc:
                    st.error(f"Could not restart scoring: {exc}")

            batch_outputs_available = batch_dir.exists() and any(batch_dir.glob("batch_*.output.json"))
            if action_5.button("Import Scores", disabled=not batch_outputs_available):
                batch_outputs = sorted(batch_dir.glob("batch_*.output.json")) if batch_dir.exists() else []
                if not scored_out_path.exists() and not batch_outputs:
                    st.error(f"Output file not found: {scored_out_path}")
                else:
                    try:
                        if batch_outputs:
                            merged_batch_rows = []
                            failed_outputs = []
                            for output_file in batch_outputs:
                                try:
                                    payload_part = _extract_json_payload_from_text(output_file.read_text(encoding="utf-8"))
                                    if isinstance(payload_part, list):
                                        merged_batch_rows.extend(payload_part)
                                    elif isinstance(payload_part, dict) and isinstance(payload_part.get("scored_urls"), list):
                                        merged_batch_rows.extend(payload_part["scored_urls"])
                                    else:
                                        failed_outputs.append(output_file.name)
                                except Exception:
                                    failed_outputs.append(output_file.name)
                            if failed_outputs:
                                st.warning(f"Skipped {len(failed_outputs)} batch outputs that were not valid JSON.")
                            pi_payload = merged_batch_rows
                        else:
                            pi_payload = _extract_json_payload_from_text(scored_out_path.read_text(encoding="utf-8"))
                        if isinstance(pi_payload, list):
                            pi_scored = [
                                {
                                    "url": row.get("url"),
                                    "score": int(round(float(row.get("final_score", row.get("score", 0))))),
                                    "reason": row.get("selected_reason", row.get("reason", "")),
                                    "student_value": row.get("relevance_score", row.get("student_value")),
                                    "freshness": row.get("freshness_score", row.get("freshness")),
                                    "source_quality": None,
                                    "scrape_value": None,
                                }
                                for row in pi_payload
                                if isinstance(row, dict) and row.get("url")
                            ]
                            pi_payload = {
                                "selection_method": "pi_prompt_array",
                                "default_threshold": 70,
                                "scored_urls": pi_scored,
                                "selected_urls": [
                                    {
                                        "url": row.get("url"),
                                        "reason": row.get("reason", ""),
                                        "priority": int(row.get("score") or 0),
                                    }
                                    for row in pi_scored
                                    if int(row.get("score") or 0) >= 70
                                ],
                            }
                        else:
                            pi_scored = pi_payload.get("scored_urls", []) if isinstance(pi_payload, dict) else []
                        if not pi_scored:
                            st.error("No `scored_urls` found in Pi output JSON.")
                        else:
                            pi_df = pd.DataFrame(pi_scored)
                            merge_cols = [
                                col
                                for col in [
                                    "url",
                                    "score",
                                    "reason",
                                    "student_value",
                                    "freshness",
                                    "source_quality",
                                    "scrape_value",
                                ]
                                if col in pi_df.columns
                            ]
                            replace_cols = [c for c in merge_cols if c != "url" and c in df.columns]
                            if replace_cols:
                                df = df.drop(columns=replace_cols)
                            df = df.merge(pi_df[merge_cols], on="url", how="left")
                            threshold = int(pi_payload.get("default_threshold", 70))
                            df["selected"] = df["score"].fillna(0).astype(int) >= threshold
                            st.session_state["score_threshold"] = threshold
                            st.session_state["llm_selected"] = [
                                {
                                    "url": row["url"],
                                    "reason": row.get("reason", ""),
                                    "priority": int(row.get("score") or 0),
                                }
                                for row in pi_scored
                                if int(row.get("score") or 0) >= threshold
                            ]
                            st.session_state["last_selection_payload"] = pi_payload
                            write_json(scored_out_path, pi_payload)
                            st.session_state["discovered"] = df.to_dict("records")
                            st.session_state["selected_df"] = df
                            _save_app_state()
                            st.success(
                                f"Imported Pi output: {len(pi_scored)} scored URLs. "
                                f"Auto-selected score >= {threshold}."
                            )
                    except Exception as exc:
                        st.error(f"Failed to import Pi output: {exc}")

            state_label = "live terminal" if tmux_exists else "idle"
            status_cols = st.columns([1, 1, 4])
            status_cols[0].caption(f"Console status: {state_label}")
            if status_cols[1].button("Refresh Terminal", disabled=not tmux_exists):
                st.rerun()
            if tmux_exists:
                st.code(tmux_runner.capture(tmux_name, lines=300, tmux_bin=tmux_bin), language="text")
                send_col, send_btn_col, kill_col = st.columns([6, 1.2, 1.4])
                tmux_input = send_col.text_input(
                    "Terminal input",
                    value="",
                    key="pi_tmux_send_input",
                    placeholder="Type a follow-up or correction for the live agent...",
                    label_visibility="collapsed",
                )
                if send_btn_col.button("Send", use_container_width=True):
                    res = tmux_runner.send_line(tmux_name, tmux_input, tmux_bin=tmux_bin)
                    if not res.get("ok"):
                        st.error(res.get("error", "Failed to send input."))
                if kill_col.button("Kill", use_container_width=True):
                    res = tmux_runner.kill(tmux_name, tmux_bin=tmux_bin)
                    if not res.get("ok"):
                        st.error(res.get("error", "Failed to kill session."))
                    else:
                        st.warning("Session killed.")
                        st.rerun()
            elif not tmux_available:
                st.warning("tmux is not available. Open Advanced Paths and set `/opt/homebrew/bin/tmux`.")

        selected_payload = st.session_state.get("last_selection_payload", {})
        if selected_payload:
            st.subheader("Selected URLs")
            st.caption(f"Selection method: `{selected_payload.get('selection_method', 'unknown')}`")
            scored_rows = selected_payload.get("scored_urls", [])
            if scored_rows:
                threshold = st.slider(
                    "Select URLs with score >= threshold",
                    min_value=0,
                    max_value=100,
                    value=int(st.session_state.get("score_threshold", selected_payload.get("default_threshold", 70))),
                    step=5,
                )
                st.session_state["score_threshold"] = threshold
                score_lookup = {row["url"]: row for row in scored_rows if row.get("url")}
                df["score"] = df["url"].map(lambda url: int((score_lookup.get(url) or {}).get("score") or 0))
                df["reason"] = df["url"].map(lambda url: (score_lookup.get(url) or {}).get("reason", ""))
                df["student_value"] = df["url"].map(lambda url: (score_lookup.get(url) or {}).get("student_value"))
                df["freshness"] = df["url"].map(lambda url: (score_lookup.get(url) or {}).get("freshness"))
                df["source_quality"] = df["url"].map(lambda url: (score_lookup.get(url) or {}).get("source_quality"))
                df["scrape_value"] = df["url"].map(lambda url: (score_lookup.get(url) or {}).get("scrape_value"))
                df["selected"] = df["score"] >= threshold
                st.session_state["discovered"] = df.to_dict("records")
                st.session_state["selected_df"] = df
                visible_df = (
                    df[df["selected"]]
                    .sort_values(["score", "freshness"], ascending=[False, False])
                    .reset_index(drop=True)
                )
                metric_1, metric_2, metric_3, metric_4 = st.columns(4)
                metric_1.metric("Scored URLs", f"{len(scored_rows):,}")
                metric_2.metric("Shown", f"{len(visible_df):,}")
                metric_3.metric("Avg Score", f"{float(df['score'].fillna(0).mean()):.1f}")
                metric_4.metric("Threshold", threshold)
                display_cols = [
                    col
                    for col in ["score", "url", "reason", "student_value", "freshness", "source_quality", "scrape_value"]
                    if col in visible_df.columns
                ]
                _render_paginated_df(
                    visible_df[display_cols],
                    key_prefix="selected_scored_urls",
                    default_page_size=100,
                )
            else:
                st.info("No scored URLs yet. Run Terminal scoring or import scores.")
        else:
            st.subheader("URLs")
            st.dataframe(df, use_container_width=True)
    else:
        st.info("Discover or add manual URLs first.")

with tabs[3]:
    if not st.session_state["site_id"]:
        st.info("Create site workspace first.")
    else:
        selected_rows = st.session_state.get("selected_df", pd.DataFrame())
        if isinstance(selected_rows, pd.DataFrame) and not selected_rows.empty:
            if "selected" in selected_rows.columns:
                selected_url_rows = selected_rows[selected_rows["selected"] == True]  # noqa: E712
            else:
                selected_url_rows = selected_rows
            selected_url_strings = selected_url_rows.get("url", pd.Series(dtype=str)).dropna().astype(str).tolist()
        else:
            selected_url_strings = []
        selected_url_strings = [u for u in selected_url_strings if u.strip()]
        selected_url_set = set(selected_url_strings)

        c1, c2, c3, c4, c5, c6, c7 = st.columns([1, 1, 1, 1, 1, 1, 2.2])
        concurrency = c3.number_input("Concurrency", min_value=1, max_value=16, value=4, step=1)
        if c1.button("Start Run", type="primary"):
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
            st.session_state["run_id"] = run_id
            st.session_state["last_run_by_site"][st.session_state["site_id"]] = run_id
            _save_app_state()
            selected_urls = _rows_to_discovered_urls(st.session_state["selected_df"].to_dict("records"))
            if not selected_urls:
                st.error("No URLs selected. Lower the score threshold or select rows before starting a scrape.")
            else:
                runner.start(
                    st.session_state["site_id"],
                    run_id,
                    selected_urls,
                    concurrency=int(concurrency),
                )
                st.success(f"Started scrape for {len(selected_urls):,} selected URLs.")
                st.rerun()
        if c4.button("Pause Run", disabled=not st.session_state["run_id"]):
            runner.pause(st.session_state["site_id"], st.session_state["run_id"])
        if c5.button("Resume Run", disabled=not st.session_state["run_id"]):
            resumed = runner.resume(
                st.session_state["site_id"],
                st.session_state["run_id"],
                concurrency=int(concurrency),
            )
            if resumed:
                st.success("Resumed unfinished queued/cancelled pages for this run.")
            else:
                runner.unpause(st.session_state["site_id"], st.session_state["run_id"])
        if c2.button("Cancel Run", disabled=not st.session_state["run_id"]):
            runner.cancel(st.session_state["site_id"], st.session_state["run_id"])
        if c6.button("Refresh", use_container_width=True):
            st.rerun()
        autorefresh = c7.checkbox("Auto-refresh every 1s", value=True)
        st.caption(
            f"Selected URLs: `{len(selected_url_strings):,}`   |   Active run: `{st.session_state.get('run_id') or 'none'}`"
        )

        if st.session_state["run_id"]:
            status, pages, events = _load_scrape_runtime(
                st.session_state["site_id"],
                st.session_state["run_id"],
                max_events=1500,
            )
            status = status or {}
            run_state = str(status.get("state") or "initializing")
            success = int(status.get("success") or 0)
            failed = int(status.get("failed") or 0)
            cancelled = int(status.get("cancelled") or 0)
            running_count = int(status.get("running") or 0)
            total = int(status.get("total") or 0)
            if total <= 0:
                total = len(selected_url_strings)
            done = success + failed + cancelled
            queued = int(status.get("queued") or max(total - done - running_count, 0))
            started_at = pd.to_datetime(status.get("started_at"), errors="coerce", utc=True)
            elapsed_seconds = 0.0
            if pd.notna(started_at):
                elapsed_seconds = max((datetime.now(timezone.utc) - started_at.to_pydatetime()).total_seconds(), 0.0)
            throughput = (done / elapsed_seconds * 60.0) if elapsed_seconds > 0 else 0.0
            eta_seconds = (queued / (done / elapsed_seconds)) if elapsed_seconds > 0 and done > 0 else None
            elapsed_label = f"{elapsed_seconds/60.0:.1f} min" if elapsed_seconds > 0 else "n/a"
            eta_label = f"{eta_seconds/60.0:.1f} min" if eta_seconds is not None else "n/a"

            st.subheader("Run Health")
            k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
            k1.metric("Total", f"{total:,}")
            k2.metric("Queued", f"{queued:,}")
            k3.metric("Running", f"{running_count:,}")
            k4.metric("Success", f"{success:,}")
            k5.metric("Failed", f"{failed:,}")
            k6.metric("Cancelled", f"{cancelled:,}")
            k7.metric("Pages/Min", f"{throughput:.1f}")
            hdr1, hdr2, hdr3, hdr4 = st.columns([2, 3, 2, 2])
            hdr1.caption(f"State: `{run_state}`")
            hdr2.caption(f"Current URL: `{status.get('current_url') or 'pending initialization'}`")
            hdr3.caption(f"Elapsed: `{elapsed_label}`")
            hdr4.caption(f"ETA: `{eta_label}`")

            page_rows_by_url: dict[str, dict] = {}
            if isinstance(pages, list):
                for row in pages:
                    if not isinstance(row, dict):
                        continue
                    url = str(row.get("url") or "").strip()
                    if not url:
                        continue
                    page_rows_by_url[url] = dict(row)
            for url in selected_url_strings:
                if url not in page_rows_by_url:
                    page_rows_by_url[url] = {
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
            pages_df = pd.DataFrame(list(page_rows_by_url.values()))

            failed_urls_current = [
                str(row.get("url") or "").strip()
                for row in page_rows_by_url.values()
                if str(row.get("status") or "").lower() == "failed" and str(row.get("url") or "").strip()
            ]
            failed_urls_current = sorted(set(failed_urls_current))

            st.subheader("Retry Failed URLs")
            if not failed_urls_current:
                st.info("No failed URLs yet. When failures appear, retry actions will show up here immediately.")
            else:
                st.caption(
                    f"{len(failed_urls_current):,} failed URL(s) in this run. "
                    "Use Quick Retry for immediate reruns or Advanced Triage below for filtered/selected retries."
                )
                quick_retry_cols = st.columns([1.3, 1.3, 2.4])

                def _start_quick_retry(urls_for_retry: list[str], reason_scope: str) -> None:
                    retry_run_id = _next_retry_run_id(st.session_state["run_id"], st.session_state["site_id"])
                    retry_urls = [
                        DiscoveredURL(
                            url=url,
                            source_sitemap="retry",
                            path_category="retry",
                            selected=True,
                        )
                        for url in urls_for_retry
                    ]
                    retry_root = _run_root(st.session_state["site_id"], retry_run_id)
                    write_json(
                        retry_root / "retry_source.json",
                        {
                            "source_run_id": st.session_state["run_id"],
                            "source_site_id": st.session_state["site_id"],
                            "retry_reason_scope": reason_scope,
                            "urls": urls_for_retry,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    runner.start(
                        st.session_state["site_id"],
                        retry_run_id,
                        retry_urls,
                        concurrency=int(concurrency),
                    )
                    st.session_state["run_id"] = retry_run_id
                    st.session_state["last_run_by_site"][st.session_state["site_id"]] = retry_run_id
                    _save_app_state()
                    st.success(f"Started retry run `{retry_run_id}` with {len(urls_for_retry):,} failed URL(s).")
                    st.rerun()

                if quick_retry_cols[0].button("Quick Retry All Failed", use_container_width=True):
                    _start_quick_retry(failed_urls_current, reason_scope="quick_all_failed")

                tavily_quick_disabled = not bool(st.session_state.get("tavily_api_key"))
                if quick_retry_cols[1].button(
                    "Quick Tavily Retry",
                    use_container_width=True,
                    disabled=tavily_quick_disabled,
                ):
                    run_root = _run_root(st.session_state["site_id"], st.session_state["run_id"])
                    updated_pages, summary = retry_failed_with_tavily(
                        run_root=run_root,
                        pages=list(page_rows_by_url.values()),
                        tavily_api_key=st.session_state["tavily_api_key"],
                        extract_depth="basic",
                        fmt="markdown",
                        target_urls=failed_urls_current,
                        source_run_id=st.session_state["run_id"],
                    )
                    store.set_pages(st.session_state["site_id"], st.session_state["run_id"], updated_pages)
                    store.set_status(
                        st.session_state["site_id"],
                        st.session_state["run_id"],
                        {
                            **status,
                            "success": sum(1 for p in updated_pages if str(p.get("status") or "").lower() == "success"),
                            "failed": sum(1 for p in updated_pages if str(p.get("status") or "").lower() == "failed"),
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    st.success("Quick Tavily retry completed.")
                    st.json(summary)
                    st.rerun()
                if tavily_quick_disabled:
                    quick_retry_cols[2].info("Set `TAVILY_API_KEY` in Settings to enable quick Tavily retry.")
                else:
                    quick_retry_cols[2].caption("Advanced, filtered, and selected retries are available in `Advanced Failure Triage` below.")

            st.subheader("Queue / Activity")
            if pages_df.empty:
                st.info("Run initializing. Waiting for queue state to be published.")
            else:
                pages_df["started_at"] = pd.to_datetime(pages_df.get("started_at"), errors="coerce", utc=True)
                pages_df["finished_at"] = pd.to_datetime(pages_df.get("finished_at"), errors="coerce", utc=True)
                pages_df["duration_sec"] = ((pages_df["finished_at"] - pages_df["started_at"]).dt.total_seconds()).round(2)
                pages_df["duration_sec"] = pages_df["duration_sec"].fillna(0.0)
                pages_df["status"] = pages_df.get("status", pd.Series(dtype=str)).fillna("queued").astype(str)
                attempt_series = pages_df["attempt"] if "attempt" in pages_df.columns else pd.Series(0, index=pages_df.index)
                pages_df["attempt"] = pd.to_numeric(attempt_series, errors="coerce").fillna(0).astype(int)
                pages_df["updated_at"] = pages_df["finished_at"].fillna(pages_df["started_at"])
                pages_df["updated_at_str"] = pages_df["updated_at"].dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                pages_df["updated_at_str"] = pages_df["updated_at_str"].fillna("pending")
                status_rank = {"running": 0, "failed": 1, "success": 2, "cancelled": 3, "queued": 4}
                pages_df["status_rank"] = pages_df["status"].map(lambda s: status_rank.get(str(s).lower(), 5))

                f1, f2, f3, f4 = st.columns([2, 2, 3, 2])
                status_options = sorted(pages_df["status"].dropna().astype(str).unique().tolist())
                selected_statuses = f1.multiselect(
                    "Status filter",
                    options=status_options,
                    default=status_options,
                    key="scrape_live_status_filter",
                )
                slow_threshold = f2.number_input("Slow threshold (sec)", min_value=0, max_value=600, value=10, step=1)
                url_query = f3.text_input("URL contains", value="", key="scrape_live_url_query")
                latest_only = f4.checkbox("Show latest activity only", value=False, key="scrape_live_latest_only")

                visible_df = pages_df.copy()
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
                        key_prefix="scrape_live_pages",
                        default_page_size=100,
                    )
                    waiting_for_first = bool(total > 0 and done == 0)
                    if waiting_for_first:
                        st.caption("Waiting for first page completion. Queue and worker activity are live.")

            st.subheader("Live Event Timeline")
            log_controls = st.columns([2, 2, 2])
            show_latest = int(
                log_controls[0].number_input("Show latest events", min_value=20, max_value=1500, value=200, step=20)
            )
            event_filter = log_controls[1].text_input("Filter event name", value="", key="event_name_filter")
            only_current = log_controls[2].checkbox("Current URL only", value=False, key="event_current_only")
            events_df = pd.DataFrame(events or [])
            if events_df.empty:
                st.info("No events yet. Run initializing.")
            else:
                if event_filter.strip() and "event" in events_df.columns:
                    events_df = events_df[
                        events_df["event"].astype(str).str.contains(event_filter.strip(), case=False, na=False)
                    ]
                if only_current and status.get("current_url") and "url" in events_df.columns:
                    events_df = events_df[events_df["url"] == status.get("current_url")]
                if "ts" in events_df.columns:
                    events_df["ts_dt"] = pd.to_datetime(events_df["ts"], errors="coerce", utc=True)
                    events_df = events_df.sort_values("ts_dt", ascending=False, na_position="last")
                    events_df["ts_readable"] = events_df["ts_dt"].dt.strftime("%Y-%m-%d %H:%M:%S UTC").fillna("n/a")
                else:
                    events_df["ts_readable"] = "n/a"
                events_df = events_df.head(show_latest)
                for _, row in events_df.iterrows():
                    with st.container(border=True):
                        line = (
                            f"`{row.get('ts_readable', 'n/a')}` "
                            f"`{row.get('event', 'event')}` "
                            f"`{row.get('status') or row.get('state') or ''}`"
                        )
                        st.markdown(line)
                        detail_bits = []
                        if row.get("url"):
                            detail_bits.append(f"url: {row.get('url')}")
                        if row.get("worker_id"):
                            detail_bits.append(f"worker: {row.get('worker_id')}")
                        if row.get("fetch_mode"):
                            detail_bits.append(f"mode: {row.get('fetch_mode')}")
                        if row.get("http_status") is not None:
                            detail_bits.append(f"http: {row.get('http_status')}")
                        reason = row.get("failure_reason") or row.get("error")
                        if reason:
                            detail_bits.append(f"reason: {str(reason)[:160]}")
                        if detail_bits:
                            st.caption(" | ".join(detail_bits))
                with st.expander("Raw events"):
                    st.dataframe(events_df, use_container_width=True)

            st.subheader("Page Inspector")
            available_urls = list(page_rows_by_url.keys())
            inspector_url = str(st.session_state.get("scrape_inspector_url") or "")
            inspector_manual = bool(st.session_state.get("scrape_inspector_manual", False))
            running_candidates = [
                str(row.get("url") or "").strip()
                for row in page_rows_by_url.values()
                if str(row.get("status") or "").lower() == "running" and str(row.get("url") or "").strip()
            ]
            running_url = running_candidates[0] if running_candidates else ""
            if not inspector_manual and running_url:
                inspector_url = running_url
            if inspector_url not in available_urls:
                inspector_manual = False
                if running_url:
                    inspector_url = running_url
                else:
                    sorted_candidates = sorted(
                        page_rows_by_url.values(),
                        key=lambda row: (
                            0 if str(row.get("status") or "").lower() == "running" else 1,
                            pd.to_datetime(
                                row.get("finished_at") or row.get("started_at"),
                                errors="coerce",
                                utc=True,
                            ).value
                            if pd.notna(pd.to_datetime(row.get("finished_at") or row.get("started_at"), errors="coerce", utc=True))
                            else -1,
                        ),
                        reverse=True,
                    )
                    inspector_url = str(sorted_candidates[0].get("url") or "") if sorted_candidates else (available_urls[0] if available_urls else "")
            st.session_state["scrape_inspector_url"] = inspector_url
            st.session_state["scrape_inspector_manual"] = inspector_manual

            selector_cols = st.columns([3, 1.3, 1.3, 2])
            selected_inspector_url = selector_cols[0].selectbox(
                "Inspect URL",
                options=available_urls,
                index=available_urls.index(inspector_url) if inspector_url in available_urls else 0,
                key="scrape_inspector_url_selector",
            )
            if selected_inspector_url != st.session_state.get("scrape_inspector_url"):
                st.session_state["scrape_inspector_manual"] = True
                st.session_state["scrape_inspector_url"] = selected_inspector_url
            if selector_cols[1].button("Follow Running", use_container_width=True):
                st.session_state["scrape_inspector_manual"] = False
                if running_url:
                    st.session_state["scrape_inspector_url"] = running_url
                st.rerun()
            if selector_cols[2].button("Reset Auto", use_container_width=True):
                st.session_state["scrape_inspector_manual"] = False
                st.rerun()
            selector_cols[3].caption(
                f"Mode: `{'manual' if st.session_state.get('scrape_inspector_manual') else 'auto-follow'}`"
            )

            selected_url = str(st.session_state.get("scrape_inspector_url") or "")
            selected_page = dict(page_rows_by_url.get(selected_url) or {})
            page_events = []
            for event in events or []:
                if not isinstance(event, dict):
                    continue
                if str(event.get("url") or "").strip() == selected_url:
                    page_events.append(event)
            page_events = sorted(
                page_events,
                key=lambda e: pd.to_datetime(e.get("ts"), errors="coerce", utc=True).value
                if pd.notna(pd.to_datetime(e.get("ts"), errors="coerce", utc=True))
                else 0,
            )
            retry_event_count = len(
                [
                    e
                    for e in page_events
                    if str(e.get("event") or "") in {"fetch_retrying_next_mode", "fetch_exception"}
                ]
            )
            preview_tabs = st.tabs(["Preview", "Markdown", "Raw HTML", "Metadata", "Events", "Failure"])

            with preview_tabs[0]:
                c_a, c_b, c_c, c_d = st.columns(4)
                c_a.metric("Status", str(selected_page.get("status") or "queued"))
                c_b.metric("Fetch Mode", str(selected_page.get("fetch_mode") or "n/a"))
                c_c.metric("HTTP", str(selected_page.get("http_status") if selected_page.get("http_status") is not None else "n/a"))
                c_d.metric("Duration (s)", f"{float(selected_page.get('duration_ms') or 0)/1000.0:.2f}")
                p1, p2, p3, p4 = st.columns(4)
                markdown_text, markdown_path, markdown_size, markdown_err = _safe_read_text(
                    selected_page.get("markdown_path"),
                    limit_chars=8000,
                )
                raw_text, raw_path, raw_size, raw_err = _safe_read_text(
                    selected_page.get("raw_html_path"),
                    limit_chars=8000,
                )
                text_len = len(markdown_text or "")
                link_count = (raw_text or "").count("href=")
                raw_len = max(len(raw_text or ""), 1)
                link_density = (link_count / raw_len) * 1000.0
                p1.metric("Markdown chars", f"{text_len:,}")
                p2.metric("Raw chars", f"{len(raw_text or ''):,}")
                p3.metric("Links (raw)", f"{link_count:,}")
                p4.metric("Link density", f"{link_density:.2f}/1k chars")
                st.caption(f"URL: `{selected_url}`")
                st.caption(f"markdown_path: `{selected_page.get('markdown_path') or 'n/a'}`")
                st.caption(f"raw_html_path: `{selected_page.get('raw_html_path') or 'n/a'}`")
                st.caption(f"metadata_path: `{selected_page.get('metadata_path') or 'n/a'}`")
                if markdown_text:
                    st.markdown(markdown_text[:4000])
                elif raw_text:
                    st.code(raw_text[:3000], language="html")
                else:
                    st.info("No preview artifact yet. Page may still be queued/running.")
                    if page_events:
                        st.caption(f"Recent events for this URL: {len(page_events)}")
                    if markdown_err:
                        st.caption(f"Markdown: {markdown_err}")
                    if raw_err:
                        st.caption(f"Raw HTML: {raw_err}")

            with preview_tabs[1]:
                md_len = st.selectbox("Preview length", options=[2000, 8000, 20000, -1], index=1, format_func=lambda v: "full" if v == -1 else f"{v:,} chars")
                md_text, md_path, md_size, md_err = _safe_read_text(
                    selected_page.get("markdown_path"),
                    limit_chars=None if md_len == -1 else int(md_len),
                )
                if md_path:
                    st.caption(f"Path: `{md_path}`")
                if md_size is not None:
                    st.caption(f"Size: `{md_size/1024.0:.1f} KB`")
                if md_err:
                    st.warning(md_err)
                elif md_text is not None:
                    st.code(md_text, language="markdown")
                else:
                    st.info("Markdown not available yet.")

            with preview_tabs[2]:
                raw_len_choice = st.selectbox("Preview length (raw)", options=[2000, 8000, 20000, -1], index=1, format_func=lambda v: "full" if v == -1 else f"{v:,} chars")
                html_text, html_path, html_size, html_err = _safe_read_text(
                    selected_page.get("raw_html_path"),
                    limit_chars=None if raw_len_choice == -1 else int(raw_len_choice),
                )
                if html_path:
                    st.caption(f"Path: `{html_path}`")
                if html_size is not None:
                    st.caption(f"Size: `{html_size/1024.0:.1f} KB`")
                if html_err:
                    st.warning(html_err)
                elif html_text is not None:
                    st.code(html_text, language="html")
                else:
                    st.info("Raw HTML not available yet.")

            with preview_tabs[3]:
                merged_metadata = dict(selected_page)
                metadata_payload, metadata_path, metadata_err = _safe_read_json(selected_page.get("metadata_path"))
                if metadata_path:
                    st.caption(f"Metadata file: `{metadata_path}`")
                if metadata_err:
                    st.caption(metadata_err)
                st.write("Page row")
                st.json(selected_page)
                if metadata_payload is not None:
                    st.write("Metadata file payload")
                    st.json(metadata_payload)
                    if isinstance(metadata_payload, dict):
                        for key, val in metadata_payload.items():
                            merged_metadata.setdefault(f"metadata.{key}", val)
                st.write("Merged view")
                st.json(merged_metadata)

            with preview_tabs[4]:
                if not page_events:
                    st.info("No events captured for this URL yet.")
                else:
                    timeline_df = pd.DataFrame(page_events)
                    if "ts" in timeline_df.columns:
                        timeline_df["ts_dt"] = pd.to_datetime(timeline_df["ts"], errors="coerce", utc=True)
                        timeline_df["ts_readable"] = timeline_df["ts_dt"].dt.strftime("%Y-%m-%d %H:%M:%S UTC").fillna("n/a")
                    important = [
                        "page_started",
                        "fetch_attempt",
                        "fetch_retrying_next_mode",
                        "fetch_exception",
                        "artifacts_saved",
                        "page_done",
                    ]
                    timeline_df = timeline_df[
                        timeline_df["event"].astype(str).isin(important)
                    ] if "event" in timeline_df.columns else timeline_df
                    _render_paginated_df(
                        timeline_df[
                            [
                                c
                                for c in [
                                    "ts_readable",
                                    "event",
                                    "status",
                                    "worker_id",
                                    "attempt",
                                    "fetch_mode",
                                    "http_status",
                                    "failure_reason",
                                    "error",
                                ]
                                if c in timeline_df.columns
                            ]
                        ],
                        key_prefix="scrape_inspector_events",
                        default_page_size=25,
                    )

            with preview_tabs[5]:
                failure_reason = selected_page.get("failure_reason") or selected_page.get("error")
                failed_status = str(selected_page.get("status") or "").lower() == "failed"
                if not failed_status and not failure_reason:
                    st.info("No failure recorded for this URL.")
                else:
                    st.error(str(failure_reason or "Failure recorded without reason"))
                    st.caption(f"HTTP status: `{selected_page.get('http_status')}`")
                    st.caption(f"Fetch mode: `{selected_page.get('fetch_mode') or 'n/a'}`")
                    st.caption(f"Attempt: `{selected_page.get('attempt') or 0}`")
                    st.caption(f"Retry-related events: `{retry_event_count}`")
                    st.write("Recommended next action")
                    st.info("Retry this URL with fallback fetch mode and inspect raw HTML artifact for partial content.")

            st.subheader("Advanced Failure Triage")
            failed_pages = [
                dict(row)
                for row in page_rows_by_url.values()
                if str(row.get("status") or "").lower() == "failed"
            ]
            if not failed_pages:
                st.info("No failed pages for this run yet.")
            else:
                failed_df = pd.DataFrame(failed_pages)
                failed_df["normalized_reason"] = failed_df.apply(
                    lambda row: _normalize_failure_reason(row.to_dict() if hasattr(row, "to_dict") else dict(row)),
                    axis=1,
                )
                http_status_series = (
                    failed_df["http_status"] if "http_status" in failed_df.columns else pd.Series(pd.NA, index=failed_df.index)
                )
                failed_df["http_status"] = pd.to_numeric(http_status_series, errors="coerce").astype("Int64")
                failed_attempt_series = (
                    failed_df["attempt"] if "attempt" in failed_df.columns else pd.Series(0, index=failed_df.index)
                )
                failed_df["attempt"] = pd.to_numeric(failed_attempt_series, errors="coerce").fillna(0).astype(int)
                failed_df["last_event_ts"] = pd.to_datetime(
                    failed_df.get("finished_at").fillna(failed_df.get("started_at")),
                    errors="coerce",
                    utc=True,
                ).dt.strftime("%Y-%m-%d %H:%M:%S UTC").fillna("n/a")
                failed_df["duration_sec"] = (
                    (
                        pd.to_datetime(failed_df.get("finished_at"), errors="coerce", utc=True)
                        - pd.to_datetime(failed_df.get("started_at"), errors="coerce", utc=True)
                    )
                    .dt.total_seconds()
                    .round(2)
                    .fillna(0.0)
                )
                failed_df["error"] = failed_df.get("error", pd.Series(dtype=str)).fillna("").astype(str)
                failed_df["selected"] = True

                reason_counts = failed_df["normalized_reason"].value_counts(dropna=False).to_dict()
                fsum1, fsum2, fsum3, fsum4 = st.columns(4)
                fsum1.metric("Failed URLs", f"{len(failed_df):,}")
                fsum2.metric("Failure Types", f"{len(reason_counts):,}")
                top_reason = max(reason_counts, key=reason_counts.get) if reason_counts else "n/a"
                fsum3.metric("Top Reason", str(top_reason))
                fsum4.metric("Max Attempts", f"{int(failed_df['attempt'].max()) if not failed_df.empty else 0}")

                st.caption("Failure groups")
                grp_df = pd.DataFrame(
                    [{"reason": key, "count": int(val)} for key, val in sorted(reason_counts.items(), key=lambda x: (-x[1], x[0]))]
                )
                st.dataframe(grp_df, use_container_width=True, hide_index=True)

                ff1, ff2, ff3, ff4 = st.columns([2, 2, 3, 2])
                reason_options = sorted(failed_df["normalized_reason"].dropna().astype(str).unique().tolist())
                selected_reasons = ff1.multiselect(
                    "Failure reason",
                    options=reason_options,
                    default=reason_options,
                    key="triage_reason_filter",
                )
                http_options = sorted(
                    [int(x) for x in failed_df["http_status"].dropna().astype(int).unique().tolist()]
                )
                selected_http = ff2.multiselect(
                    "HTTP status",
                    options=http_options,
                    default=http_options,
                    key="triage_http_filter",
                )
                url_filter = ff3.text_input("URL contains", value="", key="triage_url_filter")
                mode_options = sorted(failed_df.get("fetch_mode", pd.Series(dtype=str)).fillna("unknown").astype(str).unique().tolist())
                selected_modes = ff4.multiselect(
                    "Fetch mode",
                    options=mode_options,
                    default=mode_options,
                    key="triage_mode_filter",
                )

                triage_df = failed_df.copy()
                if selected_reasons:
                    triage_df = triage_df[triage_df["normalized_reason"].isin(selected_reasons)]
                if selected_http:
                    triage_df = triage_df[triage_df["http_status"].isin(selected_http)]
                if url_filter.strip():
                    triage_df = triage_df[triage_df["url"].astype(str).str.contains(url_filter.strip(), case=False, na=False)]
                if selected_modes:
                    triage_df = triage_df[triage_df.get("fetch_mode", pd.Series(dtype=str)).fillna("unknown").astype(str).isin(selected_modes)]

                triage_df = triage_df.sort_values(["normalized_reason", "attempt", "url"], ascending=[True, False, True])
                if triage_df.empty:
                    st.info("No failed pages match current triage filters.")
                else:
                    st.caption("Failed pages")
                    editable_df = triage_df[
                        [
                            "selected",
                            "url",
                            "normalized_reason",
                            "failure_reason",
                            "http_status",
                            "fetch_mode",
                            "attempt",
                            "duration_sec",
                            "error",
                            "last_event_ts",
                        ]
                    ].copy()
                    edited = st.data_editor(
                        editable_df,
                        use_container_width=True,
                        hide_index=True,
                        key="triage_failed_editor",
                        column_config={"selected": st.column_config.CheckboxColumn("selected", default=True)},
                        disabled=[
                            "url",
                            "normalized_reason",
                            "failure_reason",
                            "http_status",
                            "fetch_mode",
                            "attempt",
                            "duration_sec",
                            "error",
                            "last_event_ts",
                        ],
                    )
                    selected_urls = edited[edited["selected"] == True]["url"].astype(str).tolist()  # noqa: E712
                    selected_reason_for_group = st.selectbox(
                        "Retry by failure type",
                        options=reason_options,
                        index=0 if reason_options else None,
                        key="triage_retry_reason",
                    )
                    retry_cols = st.columns([1.2, 1.2, 1.2, 1.2, 2.2])
                    tavily_enabled = bool(st.session_state.get("tavily_api_key"))
                    tavily_depth = retry_cols[4].selectbox("Tavily depth", options=["basic", "advanced"], index=0, key="triage_tavily_depth")
                    tavily_fmt = retry_cols[4].selectbox("Tavily format", options=["markdown", "text"], index=0, key="triage_tavily_fmt")

                    def _start_retry_run(urls_for_retry: list[str], *, reason_scope: str) -> None:
                        if not urls_for_retry:
                            st.warning("No URLs selected for retry.")
                            return
                        retry_run_id = _next_retry_run_id(st.session_state["run_id"], st.session_state["site_id"])
                        retry_urls = [
                            DiscoveredURL(
                                url=url,
                                source_sitemap="retry",
                                path_category="retry",
                                selected=True,
                            )
                            for url in urls_for_retry
                        ]
                        retry_root = _run_root(st.session_state["site_id"], retry_run_id)
                        write_json(
                            retry_root / "retry_source.json",
                            {
                                "source_run_id": st.session_state["run_id"],
                                "source_site_id": st.session_state["site_id"],
                                "retry_reason_scope": reason_scope,
                                "urls": urls_for_retry,
                                "created_at": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                        runner.start(
                            st.session_state["site_id"],
                            retry_run_id,
                            retry_urls,
                            concurrency=int(concurrency),
                        )
                        st.session_state["run_id"] = retry_run_id
                        st.session_state["last_run_by_site"][st.session_state["site_id"]] = retry_run_id
                        _save_app_state()
                        st.success(f"Started retry run `{retry_run_id}` with {len(urls_for_retry):,} URL(s).")
                        st.rerun()

                    if retry_cols[0].button("Retry selected", use_container_width=True):
                        _start_retry_run(selected_urls, reason_scope="selected")
                    if retry_cols[1].button("Retry all failed", use_container_width=True):
                        _start_retry_run(failed_df["url"].astype(str).tolist(), reason_scope="all_failed")
                    if retry_cols[2].button("Retry by type", use_container_width=True):
                        urls_for_type = failed_df[failed_df["normalized_reason"] == selected_reason_for_group]["url"].astype(str).tolist()
                        _start_retry_run(urls_for_type, reason_scope=f"type:{selected_reason_for_group}")

                    tavily_call_count = len(selected_urls)
                    tavily_unit_cost = float(st.session_state.get("tavily_cost_per_call_usd", 0.0))
                    est_cost = tavily_call_count * tavily_unit_cost
                    st.caption(
                        f"Tavily fallback: selected `{tavily_call_count}` URL(s), "
                        f"estimated cost `${est_cost:.4f}` @ `${tavily_unit_cost:.4f}`/call."
                    )
                    if retry_cols[3].button(
                        "Retry with Tavily fallback",
                        disabled=(not tavily_enabled) or tavily_call_count == 0,
                        use_container_width=True,
                    ):
                        run_root = _run_root(st.session_state["site_id"], st.session_state["run_id"])
                        updated_pages, summary = retry_failed_with_tavily(
                            run_root=run_root,
                            pages=list(page_rows_by_url.values()),
                            tavily_api_key=st.session_state["tavily_api_key"],
                            extract_depth=tavily_depth,
                            fmt=tavily_fmt,
                            target_urls=selected_urls,
                            source_run_id=st.session_state["run_id"],
                        )
                        store.set_pages(st.session_state["site_id"], st.session_state["run_id"], updated_pages)
                        store.set_status(
                            st.session_state["site_id"],
                            st.session_state["run_id"],
                            {
                                **status,
                                "success": sum(1 for p in updated_pages if str(p.get("status") or "").lower() == "success"),
                                "failed": sum(1 for p in updated_pages if str(p.get("status") or "").lower() == "failed"),
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                        st.success("Tavily fallback retry completed.")
                        st.json(summary)
                        st.rerun()
                    if not tavily_enabled:
                        st.info("Set `TAVILY_API_KEY` in Settings to enable Tavily fallback retries.")

                    export_urls_txt = "\n".join(triage_df["url"].astype(str).tolist()) + "\n"
                    export_csv = triage_df.to_csv(index=False)
                    export_json = triage_df.to_json(orient="records", indent=2)
                    e1, e2, e3 = st.columns(3)
                    e1.download_button(
                        "Export failed URLs TXT",
                        data=export_urls_txt,
                        file_name=f"{st.session_state['run_id']}-failed-urls.txt",
                        mime="text/plain",
                        use_container_width=True,
                    )
                    e2.download_button(
                        "Export failed pages CSV",
                        data=export_csv,
                        file_name=f"{st.session_state['run_id']}-failed-pages.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )
                    e3.download_button(
                        "Export failures JSON",
                        data=export_json,
                        file_name=f"{st.session_state['run_id']}-failures.json",
                        mime="application/json",
                        use_container_width=True,
                    )

            if autorefresh and run_state in {"running", "pausing", "paused", "initializing"}:
                time.sleep(1)
                st.rerun()
        else:
            st.subheader("Run Health")
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Total", f"{len(selected_url_strings):,}")
            k2.metric("Queued", f"{len(selected_url_strings):,}")
            k3.metric("Running", "0")
            k4.metric("State", "ready")
            st.info(
                "No run yet. Select URLs and click Start Run to begin live scraping. "
                "This cockpit will show queue, activity, and timeline immediately."
            )
            st.subheader("Queue / Activity")
            if selected_url_strings:
                ready_df = pd.DataFrame({"status": ["queued"] * len(selected_url_strings), "url": selected_url_strings})
                _render_paginated_df(
                    ready_df,
                    key_prefix="scrape_ready_pages",
                    default_page_size=100,
                )
            else:
                st.info("No selected URLs yet.")
            st.subheader("Live Event Timeline")
            st.info("No events yet.")
            st.subheader("Inspector Preview")
            st.info("Start a run to populate preview-ready page activity.")

with tabs[4]:
    cleanup_site_id = st.session_state.get("site_id", "")
    cleanup_run_id = _resolve_active_run_id(cleanup_site_id, st.session_state.get("run_id", ""))
    if cleanup_run_id and cleanup_run_id != st.session_state.get("run_id", ""):
        st.session_state["run_id"] = cleanup_run_id
        st.session_state.setdefault("last_run_by_site", {})[cleanup_site_id] = cleanup_run_id

    if cleanup_site_id and cleanup_run_id:
        root = _run_root(cleanup_site_id, cleanup_run_id)
        cleanup_preview_param = str(st.query_params.get("cleanup_preview", "") or "").strip()
        if cleanup_preview_param:
            preview_path = Path(unquote(cleanup_preview_param))
            st.subheader("Direct Preview")
            st.caption(f"File: `{preview_path}`")
            if preview_path.exists():
                st.markdown(preview_path.read_text(encoding="utf-8"))
            else:
                st.error("Preview file not found.")
            if st.button("Clear Direct Preview"):
                if "cleanup_preview" in st.query_params:
                    del st.query_params["cleanup_preview"]
                st.rerun()

        st.subheader("Local Ollama Cleanup")
        model_row1, model_row2 = st.columns([1, 2])
        if model_row1.button("Fetch models from Ollama API", key="cleanup_fetch_ollama_models"):
            try:
                st.session_state["ollama_models"] = fetch_ollama_models(
                    _normalize_ollama_base_url(st.session_state.get("ollama_base_url", OLLAMA_BASE_URL))
                )
                st.success(f"Loaded {len(st.session_state.get('ollama_models', []))} models from Ollama.")
            except Exception as exc:
                st.error(f"Could not fetch models: {exc}")
        ollama_model_options = [
            str(m.get("id") or "").strip()
            for m in st.session_state.get("ollama_models", [])
            if str(m.get("id") or "").strip()
        ]
        if ollama_model_options:
            current_ollama_model = str(st.session_state.get("ollama_model") or "").strip()
            model_idx = ollama_model_options.index(current_ollama_model) if current_ollama_model in ollama_model_options else 0
            st.session_state["ollama_model"] = model_row2.selectbox(
                "Ollama model name",
                options=ollama_model_options,
                index=model_idx,
                help="Live model list from Ollama /api/tags.",
            )
        else:
            st.session_state["ollama_model"] = model_row2.text_input(
                "Ollama model name",
                value=st.session_state["ollama_model"] or "qwen2.5:1.5b",
                help="Example: qwen2.5:1.5b, llama3.2:1b, qwen2.5:3b",
            )
        st.session_state["ollama_base_url"] = st.text_input(
            "Ollama base URL", value=st.session_state.get("ollama_base_url", OLLAMA_BASE_URL)
        )
        st.session_state["ollama_base_url"] = _normalize_ollama_base_url(st.session_state["ollama_base_url"])
        ollama_url = st.session_state["ollama_base_url"]
        max_tokens = st.number_input("Max tokens per page cleanup", min_value=256, max_value=8192, value=2048, step=256)
        think_enabled = st.checkbox(
            "Enable thinking mode (slower, deeper reasoning)",
            value=False,
            help="OFF uses `think: false` with `/api/chat` for faster cleanup calls.",
        )
        concurrency = st.slider("Cleanup concurrency limit", min_value=1, max_value=8, value=1, step=1)
        available = ollama_available(ollama_url)
        st.write(f"Ollama reachable: `{available}`")
        if not available:
            if st.button("Auto-detect Ollama URL", key="cleanup_detect_ollama_url"):
                detected = _detect_reachable_ollama_url(ollama_url)
                st.session_state["ollama_base_url"] = detected
                _save_app_state()
                st.info(f"Updated Ollama base URL to `{detected}`")
                st.rerun()
        cleanup_active = cleanup_runner.is_active(cleanup_site_id, cleanup_run_id)
        c1, c2, c3 = st.columns(3)
        if c1.button("Start Cleanup Queue", type="primary", disabled=(not available) or cleanup_active):
            cleanup_runner.start(
                site_id=cleanup_site_id,
                run_id=cleanup_run_id,
                run_root=root,
                model=st.session_state["ollama_model"],
                base_url=ollama_url,
                max_tokens=int(max_tokens),
                concurrency=int(concurrency),
                think=bool(think_enabled),
            )
            st.success("Cleanup started/resumed.")
        if c2.button("Cancel Cleanup Queue", disabled=not cleanup_active):
            cleanup_runner.cancel(cleanup_site_id, cleanup_run_id)
            st.warning("Cancel requested. Current in-flight page will finish, then queue stops.")
        if c3.button("Resume Cleanup Queue", disabled=(not available) or cleanup_active):
            cleanup_runner.start(
                site_id=cleanup_site_id,
                run_id=cleanup_run_id,
                run_root=root,
                model=st.session_state["ollama_model"],
                base_url=ollama_url,
                max_tokens=int(max_tokens),
                concurrency=int(concurrency),
                think=bool(think_enabled),
            )
            st.success("Cleanup resume requested.")
        auto_refresh_cleanup = st.checkbox("Auto-refresh queue", value=True)

        with st.expander("Reset Cleanup (Start From Scratch)", expanded=False):
            st.warning("This clears cleanup artifacts for the current run only. Scraped source markdown/HTML is kept.")
            hard_reset = st.checkbox("I understand this will delete previous cleaned outputs for this run", value=False)
            if st.button("Start Fresh Cleanup", disabled=(not hard_reset) or cleanup_active):
                cleaned_dir = root / "cleaned_markdown"
                if cleaned_dir.exists():
                    shutil.rmtree(cleaned_dir, ignore_errors=True)
                for p in [root / "cleanup_manifest.json", root / "cleanup_status.json", root / "cleanup_events.jsonl"]:
                    if p.exists():
                        p.unlink(missing_ok=True)
                store.clear_cleanup_run(cleanup_site_id, cleanup_run_id)
                st.success("Cleanup state reset for this run. Click `Start Cleanup Queue` to run from scratch.")
                st.rerun()

        cleanup_status = store.get_cleanup_status(cleanup_site_id, cleanup_run_id)
        cleanup_items = store.get_cleanup_items(cleanup_site_id, cleanup_run_id)
        cleanup_events = store.get_cleanup_events(cleanup_site_id, cleanup_run_id)
        if not cleanup_status:
            cleanup_status = read_json(root / "cleanup_status.json", {})
        if not cleanup_items:
            cleanup_items = read_json(root / "cleanup_manifest.json", [])
        if not cleanup_events:
            cleanup_events = read_json(root / "cleanup_events.jsonl", [])

        if cleanup_status:
            st.subheader("Queue Status")
            st.json(cleanup_status)
            state = str(cleanup_status.get("state") or "").lower()
            if cleanup_active:
                st.info("Cleanup worker is active.")
            elif state == "cancelling":
                st.warning("Cancellation in progress. Wait a few seconds, then click `Resume Cleanup Queue`.")
            elif state == "cancelled":
                st.warning("Cleanup cancelled. Click `Resume Cleanup Queue` to continue from where it stopped.")
            elif state == "interrupted":
                st.warning("Cleanup interrupted before finishing. Click `Resume Cleanup Queue` to continue.")
            elif state == "completed":
                st.success("Cleanup completed.")
            total = int(cleanup_status.get("total") or len(cleanup_items) or 0)
            cleaned = int(cleanup_status.get("cleaned") or 0)
            failed = int(cleanup_status.get("failed") or 0)
            skipped = int(cleanup_status.get("skipped") or 0)
            done = cleaned + failed + skipped
            st.progress((done / total) if total else 0.0, text=f"Cleanup progress: {done}/{total} done")
        if cleanup_items:
            st.subheader("Realtime Queue")
            qdf = pd.DataFrame(cleanup_items)
            running_qdf = qdf[qdf["status"] == "running"].copy() if "status" in qdf.columns else pd.DataFrame()
            if running_qdf.empty:
                st.info("No files are currently running.")
            else:
                cols = [c for c in ["url", "status", "title", "source_markdown_path", "cleaned_markdown_path", "reason"] if c in running_qdf.columns]
                st.dataframe(running_qdf[cols], use_container_width=True, hide_index=True)
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Pending", int((qdf["status"] == "pending").sum()))
            k2.metric("Running", int((qdf["status"] == "running").sum()))
            k3.metric("Cleaned", int((qdf["status"] == "cleaned").sum()))
            k4.metric("Failed", int((qdf["status"] == "failed").sum()))
        if cleanup_events:
            st.subheader("Queue Events")
            st.dataframe(pd.DataFrame(cleanup_events), use_container_width=True)

        cleanup_manifest = read_json(root / "cleanup_manifest.json", cleanup_items)
        cleaned_rows = [r for r in cleanup_manifest if r.get("status") == "cleaned" and r.get("cleaned_markdown_path")]
        if cleaned_rows:
            st.subheader("Cleanup Results")
            rows_for_table = []
            for row in cleaned_rows:
                cpath = str(row.get("cleaned_markdown_path") or "")
                rows_for_table.append(
                    {
                        "title": str(row.get("title") or ""),
                        "url": str(row.get("url") or ""),
                        "tags": ", ".join(row.get("tags") or []) if isinstance(row.get("tags"), list) else str(row.get("tags") or ""),
                        "preview": f"?cleanup_preview={quote(cpath, safe='')}",
                        "cleaned_markdown_path": cpath,
                    }
                )
            cleaned_df = pd.DataFrame(rows_for_table)
            st.dataframe(
                cleaned_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "preview": st.column_config.LinkColumn("Preview Link", display_text="Open Preview"),
                    "cleaned_markdown_path": st.column_config.TextColumn("File Path"),
                },
            )
            st.caption("Use `Open Preview` to open a file in a separate tab via direct link.")
        else:
            st.info(
                "No cleanup output yet for this run. Click `Start Cleanup Queue` (or `Resume Cleanup Queue`) to generate cleaned markdown files."
            )

        st.subheader("Retry Failed URLs with Tavily")
        with st.expander("Tavily Settings", expanded=False):
            tavily_key = st.text_input(
                "TAVILY_API_KEY",
                value=st.session_state.get("tavily_api_key", ""),
                type="password",
                help="Saved locally to .env in this project.",
            )
            t1, t2 = st.columns(2)
            if t1.button("Save Tavily Key to .env"):
                _save_env_key(ENV_PATH, "TAVILY_API_KEY", tavily_key.strip())
                st.session_state["tavily_api_key"] = tavily_key.strip()
                _save_app_state()
                st.success("Saved TAVILY_API_KEY")
            if t2.button("Reload Tavily Key from .env"):
                fresh = _load_env_file(ENV_PATH).get("TAVILY_API_KEY", "")
                st.session_state["tavily_api_key"] = fresh
                st.info("Reloaded TAVILY_API_KEY from .env")

        pages_current = store.get_pages(cleanup_site_id, cleanup_run_id)
        failed_count = sum(1 for p in pages_current if p.get("status") == "failed")
        st.caption(f"Failed URLs available for Tavily retry: {failed_count}")
        td1, td2 = st.columns(2)
        tavily_depth = td1.selectbox("Tavily extract depth", options=["basic", "advanced"], index=0)
        tavily_fmt = td2.selectbox("Tavily format", options=["markdown", "text"], index=0)
        if st.button("Retry Failed with Tavily", disabled=failed_count == 0 or not st.session_state.get("tavily_api_key")):
            updated_pages, summary = retry_failed_with_tavily(
                run_root=root,
                pages=pages_current,
                tavily_api_key=st.session_state["tavily_api_key"],
                extract_depth=tavily_depth,
                fmt=tavily_fmt,
            )
            store.set_pages(cleanup_site_id, cleanup_run_id, updated_pages)
            st.success("Tavily retry completed.")
            st.json(summary)
            st.rerun()
        with st.expander("Claude Plan", expanded=False):
            render_claude_plan_section(
                run_root=root,
                site_url=st.session_state.get("site_url", ""),
                run_id=st.session_state.get("run_id", ""),
            )

        if auto_refresh_cleanup and cleanup_status and cleanup_status.get("state") == "running":
            import time

            time.sleep(1.5)
            st.rerun()
    else:
        st.info("Complete a scrape run first.")

with tabs[5]:
    st.subheader("Metrics")
    if not st.session_state.get("site_id"):
        st.info("Select or create a site first.")
    else:
        site_root = DATA_ROOT / "sites" / st.session_state["site_id"]
        run_choices = sorted([d.name for d in site_root.iterdir() if d.is_dir() and d.name != "meta"]) if site_root.exists() else []

        def _metrics_is_real_scrape_run(run_name: str) -> bool:
            if run_name.startswith("pi_url_"):
                return False
            run_dir = site_root / run_name
            scrape_markers = [
                "selected_urls.json",
                "scrape_manifest.json",
                "run_status.json",
                "pages.jsonl",
                "events.jsonl",
                "failures.json",
            ]
            return any((run_dir / marker).exists() for marker in scrape_markers)

        def _run_human_timestamp(run_name: str) -> str:
            m = re.match(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", run_name)
            if not m:
                return run_name
            y, mo, d, hh, mm, ss = m.groups()
            return f"{y}-{mo}-{d} {hh}:{mm}:{ss} UTC"

        def _run_label(run_name: str, is_real: bool) -> str:
            if not is_real:
                return f"{run_name} (non-scrape)"
            run_dir = site_root / run_name
            ts = _run_human_timestamp(run_name)
            label = f"Run {ts}"

            total_urls = None
            success_rate = None

            selected_urls = read_json(run_dir / "selected_urls.json", None)
            if isinstance(selected_urls, list):
                total_urls = len(selected_urls)

            pages = read_json(run_dir / "scrape_manifest.json", None)
            if isinstance(pages, list) and pages:
                success_count = sum(1 for p in pages if (p or {}).get("status") == "success")
                failed_count = sum(1 for p in pages if (p or {}).get("status") == "failed")
                if total_urls is None:
                    total_urls = len(pages)
                denom = success_count + failed_count
                if denom > 0:
                    success_rate = (100.0 * success_count) / float(denom)

            if total_urls is not None:
                label += f" • {int(total_urls):,} URLs"
            if success_rate is not None:
                label += f" • {success_rate:.1f}% success"
            return label

        real_run_choices = [name for name in run_choices if _metrics_is_real_scrape_run(name)]
        utility_run_choices = [name for name in run_choices if name not in real_run_choices]

        if not run_choices:
            st.info("No runs yet for this site.")
        else:
            show_utility = st.toggle("Show utility folders", value=False, key="metrics_show_utility_folders")

            # Keep utility folders available, but hidden by default for a cleaner metrics workflow.
            if show_utility:
                visible_runs = real_run_choices + utility_run_choices
            else:
                visible_runs = real_run_choices if real_run_choices else run_choices

            latest_real_run = real_run_choices[-1] if real_run_choices else ""
            default_run = latest_real_run or (visible_runs[-1] if visible_runs else "")
            current_selected = st.session_state.get("metrics_run", "")
            selected_for_index = current_selected if current_selected in visible_runs else default_run
            default_index = visible_runs.index(selected_for_index) if selected_for_index in visible_runs else 0

            selected_run = st.selectbox(
                "Run",
                options=visible_runs,
                index=default_index,
                key="metrics_run",
                format_func=lambda run_name: _run_label(run_name, run_name in real_run_choices),
            )
            if selected_run in utility_run_choices:
                w1, w2 = st.columns([4, 1])
                w1.warning("Selected folder is non-scrape utility data. Metrics may be incomplete.")
                if latest_real_run and w2.button("Use latest scrape run", key="metrics_jump_latest_scrape"):
                    st.session_state["metrics_run"] = latest_real_run
                    st.rerun()
            run_root = site_root / selected_run
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
            full_df = _build_trace_df(
                run_events=[e for r in run_choices for e in load_events(site_root / r)],
                site_events=site_events,
                model_map=model_map,
                tavily_per_call=tavily_per_call,
                ollama_in_per_m=ollama_in_per_m,
                ollama_out_per_m=ollama_out_per_m,
            )
            pages, failures, run_status, scrape_events = _load_run_analytics_inputs(st.session_state["site_id"], selected_run, run_root)
            selected_urls = read_json(run_root / "selected_urls.json", [])
            total_hint = len(selected_urls) if isinstance(selected_urls, list) else None
            processed = len(pages) if pages else 0
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

            st.caption("Scrape Run Analytics")
            with st.container(border=True):
                st.caption("Run Outcome")
                ra1, ra2, ra3, ra4, ra5 = st.columns(5)
                ra1.metric("Total URLs", _fmt_compact_number(int(page_summary.get("total", 0))))
                ra2.metric("Success", _fmt_compact_number(int(page_summary.get("success", 0))))
                ra3.metric("Failed", _fmt_compact_number(int(page_summary.get("failed", 0))))
                ra4.metric("Success Rate", f"{float(page_summary.get('success_rate', 0.0)):.1f}%")
                ra5.metric("Queued", _fmt_compact_number(int(page_summary.get("queued", 0))))

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
                rc1, rc2, rc3, rc4 = st.columns(4)
                rc1.metric("Markdown Bytes", _fmt_compact_number(int(output_summary.get("markdown_total_bytes", 0))))
                rc2.metric("Raw HTML Bytes", _fmt_compact_number(int(output_summary.get("raw_html_total_bytes", 0))))
                rc3.metric("Avg Text Length", _fmt_compact_number(float(output_summary.get("text_avg", 0.0))))
                rc4.metric("Scrape Events", _fmt_compact_number(len(scrape_events)))

            if int(page_summary.get("total", 0)) == 0 and len(trace_df) > 0:
                st.info(
                    "This run has model/system trace events but no scrape pages yet. "
                    "For scrape performance metrics, switch to a run containing `selected_urls.json` and page outputs."
                )

            with st.container(border=True):
                st.caption("Scrape Analytics Charts")
                if completion_df.empty:
                    st.info("No completed pages yet for run-level scrape analytics.")
                else:
                    st.caption("How fast pages are completing and whether throughput is accelerating or slowing over time.")
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
                st.caption("Which failure classes dominate this run and where retries should be focused first.")
                if by_reason_df.empty:
                    fr1.info("No failures by reason yet.")
                else:
                    reason_plot = by_reason_df.sort_values("count", ascending=False)
                    fr1.altair_chart(
                        alt.Chart(reason_plot)
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
                    fetch_mode_plot = by_fetch_mode_df.sort_values("count", ascending=False)
                    fr2.altair_chart(
                        alt.Chart(fetch_mode_plot)
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
                    http_status_plot = by_http_status_df.sort_values("count", ascending=False)
                    fr3.altair_chart(
                        alt.Chart(http_status_plot)
                        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                        .encode(
                            x=alt.X("count:Q", title="Count"),
                            y=alt.Y("label:N", title="HTTP Status", sort="-x"),
                            tooltip=["label", "count"],
                        )
                        .properties(height=240),
                        use_container_width=True,
                    )

                if not failure_summary["top_errors"].empty:
                    st.caption("Top Repeated Errors")
                    st.dataframe(failure_summary["top_errors"], use_container_width=True, hide_index=True)
                if not slow_pages_df.empty:
                    st.caption("Slowest Pages")
                    st.dataframe(slow_pages_df, use_container_width=True, hide_index=True)
                if not output_summary["largest_pages"].empty:
                    st.caption("Largest Pages")
                    st.dataframe(output_summary["largest_pages"], use_container_width=True, hide_index=True)

            st.write("")
            with st.container(border=True):
                st.subheader("System & Model Metrics")
                m1, m2, m3, m4, m5 = st.columns(5)
                call_count = len(trace_df)
                status_series = trace_df["status"] if "status" in trace_df.columns else pd.Series("unknown", index=trace_df.index)
                latency_series = (
                    pd.to_numeric(trace_df["latency_ms"], errors="coerce")
                    if "latency_ms" in trace_df.columns
                    else pd.Series(dtype=float, index=trace_df.index)
                )
                run_cost_series = (
                    pd.to_numeric(trace_df["estimated_cost_usd"], errors="coerce")
                    if "estimated_cost_usd" in trace_df.columns
                    else pd.Series(0.0, index=trace_df.index)
                )
                success_count = int((status_series == "success").sum()) if not trace_df.empty else 0
                success_rate = (success_count / call_count * 100.0) if call_count else 0.0
                avg_latency = float(latency_series.dropna().mean()) if not trace_df.empty and not latency_series.dropna().empty else 0.0
                p95_latency = float(latency_series.dropna().quantile(0.95)) if not trace_df.empty and not latency_series.dropna().empty else 0.0
                total_cost = float(run_cost_series.fillna(0.0).sum()) if not trace_df.empty else 0.0
                m1.metric("Calls", _fmt_compact_number(call_count))
                m2.metric("Success Rate", f"{success_rate:.1f}%")
                m3.metric("Avg Latency", f"{avg_latency:.1f} ms")
                m4.metric("P95 Latency", f"{p95_latency:.1f} ms")
                m5.metric("Run Cost (USD)", f"{total_cost:.4f}")

                agg1, agg2, agg3 = st.columns(3)
                full_cost_series = (
                    pd.to_numeric(full_df["estimated_cost_usd"], errors="coerce")
                    if not full_df.empty and "estimated_cost_usd" in full_df.columns
                    else pd.Series(0.0, index=full_df.index)
                )
                full_cost = float(full_cost_series.fillna(0.0).sum()) if not full_df.empty else 0.0
                full_calls = len(full_df)
                unique_models = int(trace_df["model"].dropna().nunique()) if not trace_df.empty and "model" in trace_df.columns else 0
                agg1.metric("Site Total Calls", _fmt_compact_number(full_calls))
                agg2.metric("Site Total Cost (USD)", f"{full_cost:.4f}")
                agg3.metric("Models Used (run)", _fmt_compact_number(unique_models))

                if not trace_df.empty:
                    provider_series = (
                        trace_df["provider"].astype(str)
                        if "provider" in trace_df.columns
                        else pd.Series("unknown", index=trace_df.index)
                    )
                    provider_counts = provider_series.value_counts().reindex(PROVIDERS, fill_value=0).reset_index()
                    provider_counts.columns = ["provider", "count"]
                    provider_nonzero = provider_counts[provider_counts["count"] > 0].copy()
                    model_series = (
                        trace_df["model"]
                        if "model" in trace_df.columns
                        else pd.Series("unknown", index=trace_df.index)
                    )
                    model_counts = model_series.fillna("unknown").astype(str).value_counts().head(15).reset_index()
                    model_counts.columns = ["model", "count"]
                    model_nonzero = model_counts[model_counts["count"] > 0].copy()
                    mc1, mc2 = st.columns(2)
                    st.caption("Who handled this run and which model/provider mix drove calls, latency, and cost.")
                    if provider_nonzero.empty:
                        mc1.info("No provider calls recorded for this run yet.")
                    elif len(provider_nonzero) == 1:
                        row = provider_nonzero.iloc[0]
                        mc1.metric("Provider Used", str(row["provider"]))
                        mc1.caption(f"Calls: `{int(row['count'])}` (100% of run)")
                    elif len(provider_nonzero) <= 4:
                        provider_nonzero = provider_nonzero.sort_values("count", ascending=False)
                        bars = (
                            alt.Chart(provider_nonzero)
                            .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                            .encode(
                                x=alt.X("count:Q", title=None, axis=alt.Axis(grid=False, ticks=False, labels=False)),
                                y=alt.Y("provider:N", title="Provider", sort="-x"),
                                tooltip=["provider", "count"],
                            )
                        )
                        labels = bars.mark_text(align="left", dx=5).encode(text=alt.Text("count:Q", format=".0f"))
                        mc1.altair_chart((bars + labels).properties(height=190), use_container_width=True)
                    else:
                        provider_nonzero = provider_nonzero.sort_values("count", ascending=False)
                        mc1.altair_chart(
                            alt.Chart(provider_nonzero)
                            .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                            .encode(
                                x=alt.X("count:Q", title="Calls"),
                                y=alt.Y("provider:N", title="Provider", sort="-x"),
                                tooltip=["provider", "count"],
                            )
                            .properties(height=260),
                            use_container_width=True,
                        )
                    if model_nonzero.empty:
                        mc2.info("No model calls recorded for this run yet.")
                    elif len(model_nonzero) == 1:
                        row = model_nonzero.iloc[0]
                        mc2.metric("Model Used", str(row["model"]))
                        mc2.caption(f"Calls: `{int(row['count'])}` (single-model run)")
                    elif len(model_nonzero) <= 4:
                        model_nonzero = model_nonzero.sort_values("count", ascending=False)
                        bars = (
                            alt.Chart(model_nonzero)
                            .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                            .encode(
                                x=alt.X("count:Q", title=None, axis=alt.Axis(grid=False, ticks=False, labels=False)),
                                y=alt.Y("model:N", title="Model", sort="-x"),
                                tooltip=["model", "count"],
                            )
                        )
                        labels = bars.mark_text(align="left", dx=5).encode(text=alt.Text("count:Q", format=".0f"))
                        mc2.altair_chart((bars + labels).properties(height=190), use_container_width=True)
                    else:
                        model_nonzero = model_nonzero.sort_values("count", ascending=False)
                        mc2.altair_chart(
                            alt.Chart(model_nonzero)
                            .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                            .encode(
                                x=alt.X("count:Q", title="Calls"),
                                y=alt.Y("model:N", title="Model", sort="-x"),
                                tooltip=["model", "count"],
                            )
                            .properties(height=260),
                            use_container_width=True,
                        )

                    latency_ts = trace_df.copy()
                    latency_ts["latency_ms"] = latency_series
                    if "ts" not in latency_ts.columns:
                        latency_ts["ts"] = pd.NaT
                    latency_ts = latency_ts.dropna(subset=["latency_ms", "ts"])
                    if not latency_ts.empty:
                        latency_ts["ts"] = pd.to_datetime(latency_ts["ts"], errors="coerce", utc=True)
                        latency_ts = latency_ts.dropna(subset=["ts"]).sort_values("ts")
                        st.caption("How request latency changed over time by provider.")
                        st.altair_chart(
                            alt.Chart(latency_ts)
                            .mark_line(point=alt.OverlayMarkDef(size=18, filled=True, opacity=0.6))
                            .encode(
                                x=alt.X("ts:T", title="Time"),
                                y=alt.Y("latency_ms:Q", title="Latency (ms)"),
                                color=alt.Color("provider:N", title="Provider"),
                                tooltip=["ts:T", "provider", "model", "latency_ms", "status"],
                            )
                            .properties(height=320),
                            use_container_width=True,
                        )

                    if "estimated_cost_usd" in trace_df.columns:
                        cost_df = trace_df.groupby("provider", as_index=False)["estimated_cost_usd"].sum()
                        cost_df = cost_df[cost_df["estimated_cost_usd"] > 0].sort_values("estimated_cost_usd", ascending=False)
                        st.caption("Where estimated LLM/tool cost was incurred across providers.")
                        if cost_df.empty:
                            st.info("No non-zero provider cost recorded for this run.")
                        elif len(cost_df) == 1:
                            row = cost_df.iloc[0]
                            st.metric("Cost Concentration", str(row["provider"]), f"${float(row['estimated_cost_usd']):.4f}")
                        elif len(cost_df) <= 4:
                            bars = (
                                alt.Chart(cost_df)
                                .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                                .encode(
                                    x=alt.X("estimated_cost_usd:Q", title=None, axis=alt.Axis(grid=False, ticks=False, labels=False)),
                                    y=alt.Y("provider:N", title="Provider", sort="-x"),
                                    tooltip=["provider", "estimated_cost_usd"],
                                )
                            )
                            labels = bars.mark_text(align="left", dx=5).encode(
                                text=alt.Text("estimated_cost_usd:Q", format=".4f")
                            )
                            st.altair_chart((bars + labels).properties(height=190), use_container_width=True)
                        else:
                            st.altair_chart(
                                alt.Chart(cost_df)
                                .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                                .encode(
                                    x=alt.X("estimated_cost_usd:Q", title="Estimated Cost (USD)"),
                                    y=alt.Y("provider:N", title="Provider", sort="-x"),
                                    tooltip=["provider", "estimated_cost_usd"],
                                )
                                .properties(height=260),
                                use_container_width=True,
                            )

                    with st.expander("Raw Events"):
                        st.dataframe(trace_df, use_container_width=True)
                else:
                    st.info("No trace events for this run yet.")

with tabs[6]:
    st.subheader("Settings")
    st.caption("Choose the default LLM provider and model for scoring/selection workflows.")
    with st.expander("Provider Credentials", expanded=False):
        or1, or2 = st.columns(2)
        openrouter_key = or1.text_input(
            "OPENROUTER_API_KEY",
            value=st.session_state.get("openrouter_api_key", ""),
            type="password",
            help="Saved locally to .env in this project.",
        )
        if or1.button("Save OpenRouter Key to .env"):
            _save_env_key(ENV_PATH, "OPENROUTER_API_KEY", openrouter_key.strip())
            st.session_state["openrouter_api_key"] = openrouter_key.strip()
            os.environ["OPENROUTER_API_KEY"] = openrouter_key.strip()
            _save_app_state()
            st.success("Saved OPENROUTER_API_KEY")
        if or2.button("Reload OpenRouter Key from .env"):
            fresh = _load_env_file(ENV_PATH).get("OPENROUTER_API_KEY", "")
            st.session_state["openrouter_api_key"] = fresh
            if fresh:
                os.environ["OPENROUTER_API_KEY"] = fresh
            st.info("Reloaded OPENROUTER_API_KEY from .env")

    pcol1, pcol2 = st.columns([1, 2])
    st.session_state["llm_provider"] = pcol1.selectbox(
        "Default LLM provider",
        options=["openrouter", "ollama"],
        index=0 if st.session_state.get("llm_provider", "openrouter") == "openrouter" else 1,
    )
    st.session_state["ollama_base_url"] = pcol2.text_input(
        "Ollama base URL",
        value=st.session_state.get("ollama_base_url", OLLAMA_BASE_URL),
        help="Ollama API base, e.g. http://localhost:11434",
    )
    st.session_state["ollama_base_url"] = _normalize_ollama_base_url(st.session_state["ollama_base_url"])

    model_options: list[str] = []
    model_help = ""
    if st.session_state["llm_provider"] == "openrouter":
        model_options = [
            str(m.get("id") or "").strip()
            for m in st.session_state.get("openrouter_models", [])
            if str(m.get("id") or "").strip()
        ]
        model_help = "Uses OpenRouter model IDs from the latest refresh."
    else:
        model_options = [
            str(m.get("id") or "").strip()
            for m in st.session_state.get("ollama_models", [])
            if str(m.get("id") or "").strip()
        ]
        model_help = "Uses locally available models returned by Ollama /api/tags."

    current_model = str(st.session_state.get("default_or_model", "deepseek/deepseek-v4-flash")).strip()
    if model_options:
        model_index = model_options.index(current_model) if current_model in model_options else 0
        st.session_state["default_or_model"] = st.selectbox(
            "Default model",
            options=model_options,
            index=model_index,
            help=model_help,
        )
    else:
        st.session_state["default_or_model"] = st.text_input(
            "Default model",
            value=current_model,
            help=f"{model_help} If cache is empty, enter model manually or refresh models below.",
        )

    s1, s2 = st.columns(2)
    st.session_state["default_llm_cap"] = int(
        s2.number_input("Default max URLs", min_value=10, max_value=5000, value=int(st.session_state.get("default_llm_cap", 150)))
    )
    st.session_state["default_llm_batch_size"] = int(
        s2.number_input("Default LLM batch size", min_value=50, max_value=600, value=int(st.session_state.get("default_llm_batch_size", 250)), step=25)
    )
    st.session_state["default_llm_sleep_sec"] = float(
        s2.number_input("Default sleep between batches (sec)", min_value=0.0, max_value=30.0, value=float(st.session_state.get("default_llm_sleep_sec", 0.0)), step=0.5)
    )

    with st.expander("Advanced Pricing", expanded=False):
        st.caption("OpenRouter cost uses model pricing from the OpenRouter model list.")
        rp1, rp2, rp3 = st.columns([1, 1, 2])
        if rp1.button("Refresh OpenRouter Models"):
            try:
                st.session_state["openrouter_models"] = fetch_openrouter_models(st.session_state.get("openrouter_api_key", "").strip())
                st.success(f"Loaded {len(st.session_state['openrouter_models'])} OpenRouter models.")
            except Exception as exc:
                st.error(f"Model refresh failed: {exc}")
        if rp2.button("Refresh Ollama Models"):
            try:
                st.session_state["ollama_models"] = fetch_ollama_models(
                    st.session_state.get("ollama_base_url", OLLAMA_BASE_URL).strip()
                )
                st.success(f"Loaded {len(st.session_state['ollama_models'])} Ollama models.")
            except Exception as exc:
                st.error(f"Ollama model refresh failed: {exc}")
        rp3.caption(
            f"Cached: OpenRouter `{len(st.session_state.get('openrouter_models', []))}` | "
            f"Ollama `{len(st.session_state.get('ollama_models', []))}`"
        )

        ollama_pull_model = st.text_input(
            "Pull model to Ollama",
            value="",
            placeholder="e.g. qwen2.5:3b",
            help="Calls Ollama /api/pull and then refreshes local model list.",
        )
        if st.button("Pull Model via Ollama API", disabled=not ollama_pull_model.strip()):
            try:
                pull_result = pull_ollama_model(
                    st.session_state.get("ollama_base_url", OLLAMA_BASE_URL).strip(),
                    ollama_pull_model.strip(),
                    stream=False,
                )
                st.session_state["ollama_models"] = fetch_ollama_models(
                    st.session_state.get("ollama_base_url", OLLAMA_BASE_URL).strip()
                )
                st.success(f"Pulled `{ollama_pull_model.strip()}`")
                st.json(pull_result)
            except Exception as exc:
                st.error(f"Ollama pull failed: {exc}")

        p1, p2, p3 = st.columns(3)
        st.session_state["tavily_cost_per_call_usd"] = float(
            p1.number_input("Tavily cost per call (USD)", min_value=0.0, value=float(st.session_state.get("tavily_cost_per_call_usd", 0.0)), step=0.001, format="%.6f")
        )
        st.session_state["ollama_input_per_m_usd"] = float(
            p2.number_input("Ollama input /1M tok (USD)", min_value=0.0, value=float(st.session_state.get("ollama_input_per_m_usd", 0.0)), step=0.01, format="%.6f")
        )
        st.session_state["ollama_output_per_m_usd"] = float(
            p3.number_input("Ollama output /1M tok (USD)", min_value=0.0, value=float(st.session_state.get("ollama_output_per_m_usd", 0.0)), step=0.01, format="%.6f")
        )
    if st.button("Save Defaults"):
        _save_app_state()
        st.success("Defaults saved.")

    st.subheader("Observability")
    if not st.session_state.get("site_id"):
        st.info("Select or create a site first to view telemetry.")
    else:
        site_root = DATA_ROOT / "sites" / st.session_state["site_id"]
        run_choices = sorted([d.name for d in site_root.iterdir() if d.is_dir() and d.name != "meta"]) if site_root.exists() else []
        if not run_choices:
            st.info("No runs yet for this site.")
        else:
            selected_run = st.selectbox("Run for observability", options=run_choices, index=len(run_choices) - 1, key="observability_run")
            run_root = site_root / selected_run
            trace_df = _build_trace_df(
                run_events=load_events(run_root),
                site_events=load_events(site_root / "meta"),
                model_map={m.get("id"): m for m in st.session_state.get("openrouter_models", [])},
                tavily_per_call=float(st.session_state.get("tavily_cost_per_call_usd", 0.0)),
                ollama_in_per_m=float(st.session_state.get("ollama_input_per_m_usd", 0.0)),
                ollama_out_per_m=float(st.session_state.get("ollama_output_per_m_usd", 0.0)),
            )
            if trace_df.empty:
                st.info("No telemetry events recorded yet for this site/run.")
            else:
                total_calls = len(trace_df)
                success_calls = int((trace_df["status"] == "success").sum())
                success_rate = (success_calls / total_calls * 100.0) if total_calls else 0.0
                lat_series = trace_df["latency_ms"].dropna()
                avg_latency = float(lat_series.mean()) if not lat_series.empty else 0.0
                p95_latency = float(lat_series.quantile(0.95)) if not lat_series.empty else 0.0
                fallback_calls = int((trace_df["status"] == "fallback").sum())
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Total Calls", total_calls)
                c2.metric("Success Rate", f"{success_rate:.1f}%")
                c3.metric("Avg Latency", f"{avg_latency:.1f} ms")
                c4.metric("P95 Latency", f"{p95_latency:.1f} ms")
                c5.metric("Fallback Calls", fallback_calls)

                prov = (
                    trace_df.groupby("provider", as_index=False)
                    .agg(
                        calls=("provider", "size"),
                        failed=("status", lambda s: int((s != "success").sum())),
                        avg_latency_ms=("latency_ms", "mean"),
                    )
                    .set_index("provider")
                    .reindex(PROVIDERS, fill_value=0)
                    .reset_index()
                )
                prov["avg_latency_ms"] = prov["avg_latency_ms"].fillna(0.0).round(1)
                st.caption("Provider Health Summary")
                st.dataframe(prov, use_container_width=True, hide_index=True)

                calls_by_provider = trace_df["provider"].value_counts().reindex(PROVIDERS, fill_value=0).reset_index()
                calls_by_provider.columns = ["provider", "calls"]
                status_by_provider = (
                    trace_df.groupby(["provider", "status"], as_index=False).size().rename(columns={"size": "calls"})
                )
                ch1, ch2 = st.columns(2)
                ch1.altair_chart(
                    alt.Chart(calls_by_provider)
                    .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
                    .encode(x=alt.X("provider:N", title="Provider"), y=alt.Y("calls:Q", title="Calls"), tooltip=["provider", "calls"])
                    .properties(height=260),
                    use_container_width=True,
                )
                ch2.altair_chart(
                    alt.Chart(status_by_provider)
                    .mark_bar()
                    .encode(
                        x=alt.X("provider:N", title="Provider"),
                        y=alt.Y("calls:Q", title="Calls"),
                        color=alt.Color("status:N", title="Status"),
                        tooltip=["provider", "status", "calls"],
                    )
                    .properties(height=260),
                    use_container_width=True,
                )

                with st.expander("Inspect Raw Events", expanded=False):
                    st.dataframe(trace_df, use_container_width=True)
