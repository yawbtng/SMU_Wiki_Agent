from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
try:
    from streamlit_autorefresh import st_autorefresh
except Exception:
    st_autorefresh = None

from src.scrape_planner.failure_classifier import classify_failure
from src.scrape_planner.local_cleanup import CleanupRunner, ollama_available
from src.scrape_planner.markdown_graph import (
    answer_context as graph_answer_context,
    build_graph as build_markdown_graph,
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
from src.scrape_planner.observability import load_events
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
from src.scrape_planner.ui_scrape_realtime import (
    build_scraped_page_preview_href,
    derive_run_summary,
    is_safe_route_part,
    latest_pages_by_status,
    resolve_scraped_markdown_preview,
)
from src.scrape_planner.ui_navigation import WORKFLOW_TABS

ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / "data"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
ENV_PATH = ROOT / ".env"
APP_STATE_PATH = DATA_ROOT / "app_state.json"
PI_PROMPT_TEMPLATE_PATH = ROOT / "prompts" / "pi_url_selection_prompt.md"
DOCUMENT_WIKI_SKILL_PATH = ROOT / ".pi" / "skills" / "document-wiki-ingest" / "SKILL.md"
GRAPHIFY_DEFAULT_BIN = "/private/tmp/graphify-venv/bin/graphify"


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
        "url_reasoning_provider": "openrouter",
        "url_reasoning_openrouter_model": "deepseek/deepseek-v4-flash",
        "url_reasoning_ollama_model": "qwen2.5:3b",
        "graph_enrichment_provider": "ollama",
        "graph_answer_provider": "openrouter",
        "scrape_concurrency": 10,
        "embedding_enabled": True,
        "embedding_model": "nomic-embed-text:latest",
        "zvec_enabled": True,
        "zvec_index_path": "",
        "zvec_collection": "university_wiki",
        "use_tavily_for_map": False,
        "use_tavily_for_retry": False,
        "tavily_cost_per_call_usd": 0.0,
        "ollama_input_per_m_usd": 0.0,
        "ollama_output_per_m_usd": 0.0,
        "selector_chat": [],
        "last_selection_payload": {},
        "pi_binary": "",
        "tmux_binary": "",
        "graphify_binary": "",
        "graphify_provider": "openrouter",
        "graphify_model": "openai/gpt-4.1-mini",
        "graphify_max_files": 0,
        "graphify_token_budget": 60000,
        "graphify_timeout_sec": 900,
        "graphify_query": "",
        "graphify_path_from": "",
        "graphify_path_to": "",
        "graphify_explain": "",
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


def _detect_graphify_binary() -> str:
    configured = os.getenv("GRAPHIFY_BIN", "").strip()
    if configured:
        return configured
    if Path(GRAPHIFY_DEFAULT_BIN).exists():
        return GRAPHIFY_DEFAULT_BIN
    found = shutil.which("graphify")
    return found or GRAPHIFY_DEFAULT_BIN


def _safe_graph_input_name(url: str, fallback: str) -> str:
    parsed = urlparse(url or "")
    raw = parsed.path.strip("/") or parsed.netloc or fallback
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-").lower()
    return f"{slug or fallback}.md"


def _raw_markdown_files(run_root: Path) -> list[Path]:
    raw_dir = run_root / "markdown"
    if not raw_dir.exists():
        return []
    return sorted([p for p in raw_dir.glob("*.md") if p.is_file()])


def _graph_is_real_scrape_run(run_name: str) -> bool:
    if run_name.startswith("pi_url_"):
        return False
    run_dir = DATA_ROOT / "sites" / st.session_state.get("site_id", "") / run_name
    scrape_markers = [
        "selected_urls.json",
        "scrape_manifest.json",
        "run_status.json",
        "pages.jsonl",
        "events.jsonl",
        "failures.json",
    ]
    return (run_dir / "markdown").exists() and any((run_dir / marker).exists() for marker in scrape_markers)


def _run_human_timestamp(run_name: str) -> str:
    match = re.match(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", run_name)
    if not match:
        return run_name
    year, month, day, hour, minute, second = match.groups()
    return f"{year}-{month}-{day} {hour}:{minute}:{second} UTC"


def _prepare_graphify_raw_input(
    run_root: Path,
    graph_root: Path,
    max_files: int,
) -> tuple[Path | None, str | None, int]:
    raw_files = _raw_markdown_files(run_root)
    if not raw_files:
        return None, "No raw markdown files found for this run.", 0

    if max_files <= 0 or max_files >= len(raw_files):
        return run_root / "markdown", None, len(raw_files)

    selected = sorted(raw_files)[:max_files]
    input_dir = graph_root / "raw-input"
    if input_dir.exists():
        shutil.rmtree(input_dir)
    input_dir.mkdir(parents=True, exist_ok=True)

    used_names: set[str] = set()
    for idx, src in enumerate(selected, start=1):
        base_name = src.name
        if base_name in used_names:
            base_name = f"{Path(base_name).stem}-{idx}.md"
        used_names.add(base_name)
        (input_dir / base_name).symlink_to(src.resolve())

    return input_dir, None, len(selected)


def _run_graphify_for_raw_markdown(
    *,
    run_root: Path,
    graphify_bin: str,
    provider: str,
    model: str,
    max_files: int,
    token_budget: int,
    max_output_tokens: int,
    timeout_sec: int,
) -> dict:
    graphify_bin = graphify_bin.strip() or _detect_graphify_binary()
    graph_root = run_root / "graphify-raw"
    input_dir, prep_error, selected_count = _prepare_graphify_raw_input(
        run_root,
        graph_root,
        max_files,
    )
    if prep_error or input_dir is None:
        return {"ok": False, "error": prep_error or "Unable to prepare Graphify input."}

    env = os.environ.copy()
    backend = "ollama"
    provider = (provider or "ollama").strip().lower()
    if provider == "openrouter":
        backend = "openai"
        openrouter_key = st.session_state.get("openrouter_api_key") or env.get("OPENROUTER_API_KEY", "")
        if not openrouter_key:
            return {"ok": False, "error": "OPENROUTER_API_KEY is missing. Save it in Settings first."}
        env["OPENAI_API_KEY"] = str(openrouter_key).strip()
        env["GRAPHIFY_OPENAI_BASE_URL"] = "https://openrouter.ai/api/v1"
        env["OPENAI_BASE_URL"] = "https://openrouter.ai/api/v1"
        env["GRAPHIFY_OPENAI_MODEL"] = model
    else:
        env["OLLAMA_MODEL"] = model
        env.setdefault("OLLAMA_API_KEY", "local")
    env["GRAPHIFY_MAX_OUTPUT_TOKENS"] = str(max_output_tokens)

    extract_cmd = [
        graphify_bin,
        "extract",
        str(input_dir),
        "--backend",
        backend,
        "--model",
        model,
        "--token-budget",
        str(token_budget),
        "--max-concurrency",
        "1",
        "--api-timeout",
        str(timeout_sec),
        "--out",
        str(graph_root),
    ]
    try:
        extract_result = subprocess.run(
            extract_cmd,
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except FileNotFoundError:
        return {"ok": False, "error": f"Graphify binary not found: {graphify_bin}"}
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "error": f"Graphify timed out after {timeout_sec} seconds.",
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }

    if extract_result.returncode != 0:
        return {
            "ok": False,
            "error": "Graphify extraction failed.",
            "stdout": extract_result.stdout,
            "stderr": extract_result.stderr,
        }

    cluster_cmd = [graphify_bin, "cluster-only", str(graph_root)]
    cluster_result = subprocess.run(cluster_cmd, cwd=str(ROOT), env=env, capture_output=True, text=True)
    if cluster_result.returncode != 0:
        return {
            "ok": False,
            "error": "Graphify graph render failed.",
            "stdout": extract_result.stdout + "\n" + cluster_result.stdout,
            "stderr": extract_result.stderr + "\n" + cluster_result.stderr,
        }

    label_result = _label_graphify_communities(graphify_bin, graph_root, input_dir)
    graph_out = graph_root / "graphify-out"
    return {
        "ok": True,
        "selected_count": selected_count,
        "graph_root": str(graph_root),
        "graph_html": str(graph_out / "graph.html"),
        "graph_json": str(graph_out / "graph.json"),
        "graph_report": str(graph_out / "GRAPH_REPORT.md"),
        "stdout": extract_result.stdout + "\n" + cluster_result.stdout + "\n" + str(label_result.get("stdout") or ""),
        "stderr": extract_result.stderr + "\n" + cluster_result.stderr + "\n" + str(label_result.get("stderr") or ""),
    }


def _run_graphify_lookup(graphify_bin: str, mode: str, args: list[str], graph_json: Path, budget: int = 2000) -> dict:
    graphify_bin = graphify_bin.strip() or _detect_graphify_binary()
    if not graph_json.exists():
        return {"ok": False, "error": f"Graph JSON not found: {graph_json}"}
    cmd = [graphify_bin, mode, *args, "--graph", str(graph_json)]
    if mode == "query":
        cmd.extend(["--budget", str(budget)])
    try:
        result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        return {"ok": False, "error": f"Graphify binary not found: {graphify_bin}"}
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "error": "Graphify lookup timed out.", "stdout": exc.stdout or "", "stderr": exc.stderr or ""}
    return {
        "ok": result.returncode == 0,
        "error": "" if result.returncode == 0 else f"Graphify {mode} failed.",
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _label_graphify_communities(graphify_bin: str, graph_root: Path, input_path: Path) -> dict:
    graphify_bin = graphify_bin.strip() or _detect_graphify_binary()
    graphify_python = Path(graphify_bin).with_name("python")
    if not graphify_python.exists():
        graphify_python = Path(sys.executable)
    script = r'''
import json
import re
from collections import Counter
from pathlib import Path

from graphify.analyze import suggest_questions
from graphify.build import build_from_json
from graphify.cluster import score_all
from graphify.export import to_html
from graphify.report import generate

graph_root = Path(__import__("sys").argv[1])
input_path = __import__("sys").argv[2]
graph_out = graph_root / "graphify-out"
graph_json = graph_out / "graph.json"
analysis_path = graph_out / ".graphify_analysis.json"

graph_data = json.loads(graph_json.read_text(encoding="utf-8"))
analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
G = build_from_json(graph_data)
communities = {int(k): v for k, v in analysis.get("communities", {}).items()}
cohesion = {int(k): v for k, v in analysis.get("cohesion", {}).items()}

node_data = {node_id: data for node_id, data in G.nodes(data=True)}
stop = {
    "and", "the", "for", "with", "from", "into", "this", "that", "page", "pages",
    "program", "programs", "office", "services", "service", "student", "students",
    "smu", "southern", "methodist", "university", "document", "documents", "pdf",
    "www", "edu", "html", "https", "http", "department", "departments", "academic",
    "academics", "school", "college", "center", "centers", "information", "resources",
    "resource", "about", "home", "menu", "item", "redirect",
}

def words(text):
    out = []
    for w in re.findall(r"[A-Za-z][A-Za-z0-9]+", str(text).lower()):
        digit_ratio = sum(ch.isdigit() for ch in w) / max(len(w), 1)
        if len(w) > 2 and w not in stop and digit_ratio < 0.25:
            out.append(w)
    return out

def title_from_tokens(tokens):
    cleaned = []
    for token, _count in tokens:
        if token not in cleaned:
            cleaned.append(token)
        if len(cleaned) >= 4:
            break
    if not cleaned:
        return ""
    return " ".join(t.upper() if len(t) <= 4 else t.title() for t in cleaned)

labels = {}
for cid, members in communities.items():
    counter = Counter()
    first_label = ""
    for node_id in members:
        data = node_data.get(node_id, {})
        label = str(data.get("label") or node_id)
        if not first_label and label:
            first_label = label
        source_url = str(data.get("source_url") or "")
        counter.update(words(label))
        counter.update(words(source_url.replace("/", " ")))
    label = title_from_tokens(counter.most_common(12))
    if not label:
        label = first_label[:60] if first_label else f"Community {cid}"
    labels[cid] = label

(graph_out / ".graphify_labels.json").write_text(
    json.dumps({str(k): v for k, v in labels.items()}, indent=2, ensure_ascii=False),
    encoding="utf-8",
)

detection = {}
detect_path = graph_out / ".graphify_detect.json"
if detect_path.exists():
    detection = json.loads(detect_path.read_text(encoding="utf-8"))
detection.setdefault("total_files", len({str(data.get("source_file") or "") for _node_id, data in G.nodes(data=True) if data.get("source_file")}))
detection.setdefault("total_words", 0)
detection.setdefault("files", {})
tokens = analysis.get("tokens", {})
questions = suggest_questions(G, communities, labels)
report = generate(
    G,
    communities,
    cohesion or score_all(G, communities),
    labels,
    analysis.get("gods", []),
    analysis.get("surprises", []),
    detection,
    {"input": tokens.get("input", 0), "output": tokens.get("output", 0)},
    input_path,
    suggested_questions=questions,
)
(graph_out / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")
to_html(G, communities, str(graph_out / "graph.html"), community_labels=labels)
print(json.dumps({"labels": {str(k): v for k, v in labels.items()}}, ensure_ascii=False))
'''
    try:
        result = subprocess.run(
            [str(graphify_python), "-c", script, str(graph_root), str(input_path)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": result.returncode == 0,
        "error": "" if result.returncode == 0 else "Community labeling failed.",
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


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


def _safe_uploaded_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name or "document.pdf")).strip(".-")
    return cleaned[:160] or "document.pdf"


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


def _schedule_live_refresh(*, key: str, enabled: bool, active: bool, interval_seconds: float = 1.0) -> None:
    if not enabled or not active:
        return
    if st_autorefresh is not None:
        st_autorefresh(interval=max(250, int(interval_seconds * 1000)), key=key)


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


def _render_cleanup_direct_preview() -> None:
    cleanup_preview_param = str(st.query_params.get("cleanup_preview", "") or "").strip()
    if not cleanup_preview_param:
        return

    raw_path = Path(unquote(cleanup_preview_param))
    preview_path = raw_path if raw_path.is_absolute() else (ROOT / raw_path)
    try:
        resolved_path = preview_path.resolve()
        data_root = DATA_ROOT.resolve()
        is_allowed = resolved_path == data_root or data_root in resolved_path.parents
    except Exception:
        resolved_path = preview_path
        is_allowed = False

    st.title("Cleaned Page Preview")
    st.caption(f"File: `{resolved_path}`")
    if not is_allowed:
        st.error("Preview blocked because the file is outside this project's data directory.")
    elif not resolved_path.exists():
        st.error("Preview file not found. The cleanup manifest may point at a stale path.")
    else:
        st.markdown(resolved_path.read_text(encoding="utf-8", errors="replace"))

    if st.button("Back to Cleanup Results"):
        if "cleanup_preview" in st.query_params:
            del st.query_params["cleanup_preview"]
        st.rerun()
    st.stop()


def _render_scraped_page_preview() -> None:
    if str(st.query_params.get("view", "") or "").strip() != "scraped_page":
        return

    site_id = str(st.query_params.get("site_id", "") or "").strip()
    run_id = str(st.query_params.get("run_id", "") or "").strip()
    slug = str(st.query_params.get("page_slug", "") or "").strip()

    st.title("Scraped Page Preview")
    if not site_id or not run_id or not slug:
        st.error("Preview link is missing site, run, or page information.")
        st.stop()
    if not is_safe_route_part(site_id) or not is_safe_route_part(run_id):
        st.error("Preview link contains invalid site or run information.")
        st.stop()

    run_root = _run_root(site_id, run_id)
    preview = resolve_scraped_markdown_preview(run_root, slug)
    if preview.url:
        st.caption(f"Source: {preview.url}")
    st.caption(f"Run: `{run_id}`")

    meta_cols = st.columns(3)
    meta_cols[0].metric("HTTP", preview.http_status if preview.http_status is not None else "n/a")
    meta_cols[1].metric("Fetch Mode", preview.fetch_mode or "n/a")
    meta_cols[2].metric("Text Length", preview.text_length if preview.text_length is not None else "n/a")

    if not preview.ready:
        st.info(preview.message)
        st.stop()

    st.divider()
    st.markdown(preview.markdown)
    st.stop()


st.set_page_config(page_title="Scrapling Scrape Planner", layout="wide")
_apply_compact_ui_styles()
_render_cleanup_direct_preview()
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
store = _get_store()
runner = _get_runner()
cleanup_runner = _get_cleanup_runner()
terminal_skill_runner = _get_terminal_skill_runner()
tmux_runner = _get_tmux_runner()

st.title("Scrape Pipeline")
st.caption("Setup -> Discover -> PDF Sources -> Scrape -> Graph.")

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
    st.subheader("Setup")
    if active_ws:
        discovered_count = len(st.session_state.get("discovered") or read_json(_discovered_json_path(st.session_state["site_id"]), []))
        selected_df_for_setup = st.session_state.get("selected_df", pd.DataFrame())
        selected_count = 0
        if isinstance(selected_df_for_setup, pd.DataFrame) and not selected_df_for_setup.empty:
            selected_count = int(selected_df_for_setup["selected"].fillna(False).sum()) if "selected" in selected_df_for_setup.columns else len(selected_df_for_setup)
        next_hint = "Refresh sitemap URLs"
        if discovered_count and not selected_count:
            next_hint = "Add PDF sources"
        elif selected_count and not st.session_state.get("run_id"):
            next_hint = "Start Scrape"
        elif st.session_state.get("run_id"):
            next_hint = "Clean or Review latest run"

        s1, s2, s3, s4 = st.columns([1.1, 1.8, 1, 1])
        s1.metric("Workspace", active_ws.get("name", "Workspace"))
        s2.metric("Site", active_ws.get("url") or st.session_state.get("site_url") or "not set")
        s3.metric("Discovered", f"{discovered_count:,}")
        s4.metric("Selected", f"{selected_count:,}")
        st.info(f"Next: {next_hint}")
        if st.session_state.get("run_id"):
            st.caption(f"Active run: `{st.session_state['run_id']}`")
    else:
        st.warning("No active workspace selected. Go back to the workspace list and open one.")

with tabs[1]:
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

    d1, d2, d3 = st.columns(3)
    d1.metric("Discovered URLs", f"{len(discovered_rows_for_summary):,}")
    d2.metric("Sitemap Sources", f"{source_count:,}")
    d3.metric("Last Refreshed", last_refreshed)

    st.write("Add URLs")
    st.session_state["manual_urls"] = st.text_area("Paste official links", value=st.session_state["manual_urls"], height=110, placeholder="https://admissions.example.edu/...\n/registrar/...")
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

    if discovered_rows_for_summary:
        host_counts = pd.Series([urlparse(str(row.get("url") or "")).netloc.lower() for row in discovered_rows_for_summary if isinstance(row, dict)]).value_counts().head(12)
        if not host_counts.empty:
            st.caption("Top hosts")
            st.dataframe(host_counts.rename_axis("host").reset_index(name="urls"), use_container_width=True, hide_index=True)

with tabs[2]:
    site_id = st.session_state.get("site_id", "")
    if not site_id:
        st.info("Create or open a workspace first.")
    else:
        site_root = DATA_ROOT / "sites" / site_id
        site_root.mkdir(parents=True, exist_ok=True)
        pdf_dir = site_root / "sources" / "pdf_uploads"
        pdf_manifest_path = site_root / "sources" / "pdf_manifest.json"
        pdf_manifest = read_json(pdf_manifest_path, [])

        st.subheader("PDF Sources")
        st.caption("Upload PDFs for Docling parsing and Zvec embedding. URL selection is disabled.")

        uploaded_pdfs = st.file_uploader(
            "Add PDFs for embedding",
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
            st.success(f"Saved {len(uploaded_pdfs):,} PDF(s).")

        c1, c2 = st.columns([1, 2])
        c1.metric("PDF Sources", f"{len(pdf_manifest):,}")
        c2.info("Ready for Docling parsing and Zvec embedding.")

        if pdf_manifest:
            display_rows = [
                {
                    "name": row.get("name", ""),
                    "size_bytes": row.get("size_bytes", 0),
                    "status": row.get("status", ""),
                    "path": row.get("path", ""),
                    "added_at": row.get("added_at", ""),
                }
                for row in pdf_manifest
                if isinstance(row, dict)
            ]
            st.dataframe(pd.DataFrame(display_rows), use_container_width=True, hide_index=True)
        else:
            st.info("Upload one or more PDFs to prepare them for embedding.")

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
        st.session_state.setdefault("scrape_status_message", "")

        c1, c2, c3, c4, c5, c6, c7 = st.columns([1, 1, 1, 1, 1, 1, 2.2])
        concurrency = c3.number_input(
            "Concurrency",
            min_value=1,
            max_value=16,
            value=int(st.session_state.get("scrape_concurrency", 10)),
            step=1,
        )
        st.session_state["scrape_concurrency"] = int(concurrency)
        if c1.button("Start New Scrape", type="primary"):
            selected_urls = _rows_to_discovered_urls(st.session_state["selected_df"].to_dict("records"))
            valid_selected_urls = []
            for item in selected_urls:
                parsed_url = urlparse(item.url.strip())
                if parsed_url.scheme in {"http", "https"} and parsed_url.netloc:
                    valid_selected_urls.append(item)
            selected_urls = valid_selected_urls
            if not selected_urls:
                st.session_state["scrape_status_message"] = "No URLs selected. Add selected URLs before starting a scrape."
                st.error("No URLs selected. Add selected URLs before starting a scrape.")
            else:
                run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
                st.session_state["run_id"] = run_id
                st.session_state["last_run_by_site"][st.session_state["site_id"]] = run_id
                _save_app_state()
                st.session_state["scrape_status_message"] = "Starting new scrape run..."
                with st.spinner("Starting new scrape run..."):
                    runner.start(
                        st.session_state["site_id"],
                        run_id,
                        selected_urls,
                        concurrency=int(concurrency),
                    )
                st.session_state["scrape_status_message"] = f"Started scrape for {len(selected_urls):,} selected URLs."
                st.success(f"Started scrape for {len(selected_urls):,} selected URLs.")
                st.rerun()
        if c4.button("Pause", disabled=not st.session_state["run_id"]):
            runner.pause(st.session_state["site_id"], st.session_state["run_id"])
            st.session_state["scrape_status_message"] = "Pausing after in-flight pages finish..."
            st.rerun()
        if c5.button("Resume Current Run", disabled=not st.session_state["run_id"]):
            resumed = runner.resume(
                st.session_state["site_id"],
                st.session_state["run_id"],
                concurrency=int(concurrency),
            )
            if not resumed:
                runner.unpause(st.session_state["site_id"], st.session_state["run_id"])
            st.session_state["scrape_status_message"] = "Continuing from last saved page state..."
            st.rerun()
        if c2.button("Cancel", disabled=not st.session_state["run_id"]):
            runner.cancel(st.session_state["site_id"], st.session_state["run_id"])
            st.session_state["scrape_status_message"] = "Cancel requested. Stopping after in-flight pages finish..."
            st.rerun()
        if c6.button("Refresh", use_container_width=True):
            st.rerun()
        autorefresh = c7.checkbox("Auto-refresh every 1s", value=False)
        if autorefresh and st_autorefresh is None:
            c7.caption("Install `streamlit-autorefresh` to enable this without blocking. Use Refresh for now.")
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
            raw_pages = pages if isinstance(pages, list) else []
            summary = derive_run_summary(status=status, pages=raw_pages, selected_count=len(selected_url_strings))
            if summary.state in {"completed", "cancelled", "failed"}:
                st.session_state.pop("scrape_status_message", None)
            status_message = st.session_state.get("scrape_status_message")
            if status_message:
                st.status(status_message, state="running", expanded=False)
            run_state = summary.state
            total = summary.total
            done = summary.done
            queued = summary.queued
            started_at = pd.to_datetime(status.get("started_at"), errors="coerce", utc=True)
            elapsed_seconds = 0.0
            if pd.notna(started_at):
                elapsed_seconds = max((datetime.now(timezone.utc) - started_at.to_pydatetime()).total_seconds(), 0.0)
            throughput = (done / elapsed_seconds * 60.0) if elapsed_seconds > 0 else 0.0
            eta_seconds = (queued / (done / elapsed_seconds)) if elapsed_seconds > 0 and done > 0 else None
            elapsed_label = f"{elapsed_seconds/60.0:.1f} min" if elapsed_seconds > 0 else "n/a"
            eta_label = f"{eta_seconds/60.0:.1f} min" if eta_seconds is not None else "n/a"

            page_rows_by_url: dict[str, dict] = {}
            for row in raw_pages:
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
            all_page_rows = list(page_rows_by_url.values())
            pages_df = pd.DataFrame(all_page_rows)
            if not pages_df.empty:
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

            st.subheader("Live Scrape")
            progress_total = summary.total if summary.total > 0 else 1
            progress_done = min(summary.success + summary.failed, progress_total)
            st.progress(progress_done / progress_total, text=summary.progress_label)
            k1, k2, k3, k4, k5, k6 = st.columns(6)
            k1.metric("State", summary.state)
            k2.metric("Running", f"{summary.running:,}")
            k3.metric("Success", f"{summary.success:,}")
            k4.metric("Failed", f"{summary.failed:,}")
            k5.metric("Remaining", f"{summary.remaining:,}")
            k6.metric("Queued", f"{summary.queued:,}")
            if summary.state in {"initializing", "running"} and summary.done == 0:
                with st.spinner("Preparing queue and waiting for first scraped page..."):
                    st.info("Workers are starting. The latest scraped pages will appear here automatically.")
            elif summary.state == "pausing":
                st.warning("Pausing after in-flight pages finish...")
            elif summary.state == "paused":
                st.info(
                    f"Paused with {summary.success:,} complete and {summary.remaining:,} remaining. "
                    "Resume Current Run will continue unfinished pages."
                )
            elif summary.state == "completed":
                st.success("Scrape run completed.")
            hdr1, hdr2, hdr3 = st.columns([3, 2, 2])
            hdr1.caption(f"Current URL: `{status.get('current_url') or 'pending initialization'}`")
            hdr2.caption(f"Elapsed: `{elapsed_label}`")
            hdr3.caption(f"ETA: `{eta_label}`")

            st.subheader("Current Activity")
            running_pages = latest_pages_by_status(all_page_rows, "running", limit=8)
            if running_pages:
                running_df = pd.DataFrame(running_pages)
                st.dataframe(
                    running_df[[c for c in ["url", "worker_id", "fetch_mode", "attempt", "started_at"] if c in running_df.columns]],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No pages are running right now. The queue may be waiting, paused, or already complete.")

            st.subheader("Recently Scraped")
            successful_pages = latest_pages_by_status(all_page_rows, "success", limit=10)
            if successful_pages:
                preview_links = []
                for row in successful_pages:
                    url = str(row.get("url") or "")
                    href = build_scraped_page_preview_href(
                        site_id=st.session_state["site_id"],
                        run_id=st.session_state["run_id"],
                        url=url,
                    )
                    preview_links.append(
                        f'<a href="{escape(href, quote=True)}" target="_blank">Open preview</a> '
                        f'<span>{escape(url)}</span>'
                    )
                st.markdown("<br>".join(preview_links), unsafe_allow_html=True)
            else:
                st.info("Successful pages will appear here as soon as markdown is saved.")

            st.subheader("Current Failures")
            failed_pages = latest_pages_by_status(all_page_rows, "failed", limit=10)
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
                if pages_df.empty:
                    st.info("Run initializing. Waiting for queue state to be published.")
                else:
                    f1, f2, f3, f4 = st.columns([2, 2, 3, 2])
                    status_options = sorted(pages_df["status"].dropna().astype(str).unique().tolist())
                    default_statuses = ["running"] if "running" in status_options else []
                    selected_statuses = f1.multiselect(
                        "Status filter",
                        options=status_options,
                        default=default_statuses,
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

            # V1 keeps scrape focused on progress, current URL, counts, and quick retry.

            _schedule_live_refresh(
                key="scrape_live_autorefresh_tick",
                enabled=autorefresh,
                active=run_state in {"running", "pausing", "paused", "initializing"},
                interval_seconds=1.0,
            )
        else:
            st.subheader("Run Health")
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Total", f"{len(selected_url_strings):,}")
            k2.metric("Queued", f"{len(selected_url_strings):,}")
            k3.metric("Running", "0")
            k4.metric("State", "ready")
            if selected_url_strings:
                st.info(f"Ready to scrape {len(selected_url_strings):,} selected URL(s).")
            else:
                st.info("No selected URLs yet.")

if st.session_state.get("_show_legacy_cleanup_ui", False):
    cleanup_site_id = st.session_state.get("site_id", "")
    cleanup_run_id = _resolve_active_run_id(cleanup_site_id, st.session_state.get("run_id", ""))
    if cleanup_run_id and cleanup_run_id != st.session_state.get("run_id", ""):
        st.session_state["run_id"] = cleanup_run_id
        st.session_state.setdefault("last_run_by_site", {})[cleanup_site_id] = cleanup_run_id

    if cleanup_site_id and cleanup_run_id:
        root = _run_root(cleanup_site_id, cleanup_run_id)
        st.subheader("Clean")
        st.caption("Clean scraped content into wiki-ready markdown. Provider settings live in Settings.")

        cleanup_provider = st.session_state.get("cleanup_provider", "openrouter")
        provider_label = "OpenRouter" if cleanup_provider == "openrouter" else "Ollama"
        cleanup_model = st.session_state.get("default_or_model", "deepseek/deepseek-v4-flash") if cleanup_provider == "openrouter" else st.session_state.get("ollama_model", "qwen2.5:1.5b")
        st.metric("Cleanup Provider", f"{provider_label} / {cleanup_model}")
        st.session_state["ollama_base_url"] = _normalize_ollama_base_url(st.session_state.get("ollama_base_url", OLLAMA_BASE_URL))
        ollama_url = st.session_state["ollama_base_url"]
        max_tokens = 2048
        think_enabled = False
        concurrency = int(st.session_state.get("cleanup_concurrency", 1))
        available = bool(st.session_state.get("openrouter_api_key")) if cleanup_provider == "openrouter" else ollama_available(ollama_url)
        cleanup_active = cleanup_runner.is_active(cleanup_site_id, cleanup_run_id)
        c1, c2, c3 = st.columns(3)
        if cleanup_provider == "openrouter" and not available:
            st.warning("Save `OPENROUTER_API_KEY` in Settings before starting OpenRouter cleanup.")
        if c1.button("Start Cleaning", type="primary", disabled=(not available) or cleanup_active):
            cleanup_runner.start(
                site_id=cleanup_site_id,
                run_id=cleanup_run_id,
                run_root=root,
                model=st.session_state["default_or_model"] if cleanup_provider == "openrouter" else st.session_state["ollama_model"],
                base_url=ollama_url,
                max_tokens=int(max_tokens),
                concurrency=int(concurrency),
                think=bool(think_enabled),
                provider=cleanup_provider,
                openrouter_api_key=st.session_state.get("openrouter_api_key", "").strip(),
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
                model=st.session_state["default_or_model"] if cleanup_provider == "openrouter" else st.session_state["ollama_model"],
                base_url=ollama_url,
                max_tokens=int(max_tokens),
                concurrency=int(concurrency),
                think=bool(think_enabled),
                provider=cleanup_provider,
                openrouter_api_key=st.session_state.get("openrouter_api_key", "").strip(),
            )
            st.success("Cleanup resume requested.")
        auto_refresh_cleanup = st.checkbox("Auto-refresh queue", value=False)
        if auto_refresh_cleanup and st_autorefresh is None:
            st.caption("Install `streamlit-autorefresh` to enable this without blocking. Use Refresh for now.")


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
            st.subheader("Progress")
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
            st.subheader("Currently Running")
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
            k4.metric("Skipped / Failed", int((qdf["status"] == "skipped").sum()) + int((qdf["status"] == "failed").sum()))
        # Full cleanup queue and raw events are intentionally omitted from the V1 UI.

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

        # Tavily retry and Claude plan controls are omitted from V1.

        _schedule_live_refresh(
            key="cleanup_live_autorefresh_tick",
            enabled=auto_refresh_cleanup,
            active=bool(cleanup_status and cleanup_status.get("state") == "running"),
            interval_seconds=1.5,
        )
    else:
        st.info("Complete a scrape run first.")

if st.session_state.get("_show_legacy_review_ui", False):
    st.subheader("Review")
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
            cleanup_manifest = read_json(run_root / "cleanup_manifest.json", [])
            cleaned_pages = [r for r in cleanup_manifest if isinstance(r, dict) and r.get("status") == "cleaned"]
            skipped_pages = [r for r in cleanup_manifest if isinstance(r, dict) and r.get("status") == "skipped"]
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
                rc1, rc2, rc3, rc4 = st.columns(4)
                rc1.metric("Markdown Bytes", _fmt_compact_number(int(output_summary.get("markdown_total_bytes", 0))))
                rc2.metric("Raw HTML Bytes", _fmt_compact_number(int(output_summary.get("raw_html_total_bytes", 0))))
                rc3.metric("Avg Text Length", _fmt_compact_number(float(output_summary.get("text_avg", 0.0))))
                rc4.metric("Avg Cleanup Duration", "see trace")

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
                    pd.to_numeric(trace_df["cost_usd"], errors="coerce")
                    if "cost_usd" in trace_df.columns
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
                    pd.to_numeric(full_df["cost_usd"], errors="coerce")
                    if not full_df.empty and "cost_usd" in full_df.columns
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

                    if "cost_usd" in trace_df.columns:
                        cost_df = trace_df.groupby("provider", as_index=False)["cost_usd"].sum()
                        cost_df = cost_df[cost_df["cost_usd"] > 0].sort_values("cost_usd", ascending=False)
                        st.caption("Where estimated LLM/tool cost was incurred across providers.")
                        if cost_df.empty:
                            st.info("No non-zero provider cost recorded for this run.")
                        elif len(cost_df) == 1:
                            row = cost_df.iloc[0]
                            st.metric("Cost Concentration", str(row["provider"]), f"${float(row['cost_usd']):.4f}")
                        elif len(cost_df) <= 4:
                            bars = (
                                alt.Chart(cost_df)
                                .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                                .encode(
                                    x=alt.X("cost_usd:Q", title=None, axis=alt.Axis(grid=False, ticks=False, labels=False)),
                                    y=alt.Y("provider:N", title="Provider", sort="-x"),
                                    tooltip=["provider", "cost_usd"],
                                )
                            )
                            labels = bars.mark_text(align="left", dx=5).encode(
                                text=alt.Text("cost_usd:Q", format=".4f")
                            )
                            st.altair_chart((bars + labels).properties(height=190), use_container_width=True)
                        else:
                            st.altair_chart(
                                alt.Chart(cost_df)
                                .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                                .encode(
                                    x=alt.X("cost_usd:Q", title="Estimated Cost (USD)"),
                                    y=alt.Y("provider:N", title="Provider", sort="-x"),
                                    tooltip=["provider", "cost_usd"],
                                )
                                .properties(height=260),
                                use_container_width=True,
                            )

                else:
                    st.info("No trace events for this run yet.")

with tabs[4]:
    st.subheader("Knowledge Graph")
    if not st.session_state.get("site_id"):
        st.info("Select or create a site first.")
    else:
        site_root = DATA_ROOT / "sites" / st.session_state["site_id"]
        graph_run_choices = sorted([d.name for d in site_root.iterdir() if d.is_dir() and d.name != "meta"]) if site_root.exists() else []
        graph_real_runs = [name for name in graph_run_choices if _graph_is_real_scrape_run(name)]
        if not graph_real_runs:
            st.info("No raw markdown run is available yet. Scrape pages first, then build the graph.")
        else:
            latest_graph_run = graph_real_runs[-1]
            current_graph_run = st.session_state.get("graph_run", "")
            selected_graph_run = current_graph_run if current_graph_run in graph_real_runs else latest_graph_run
            selected_graph_index = graph_real_runs.index(selected_graph_run)
            graph_run = st.selectbox(
                "Run",
                options=graph_real_runs,
                index=selected_graph_index,
                key="graph_run",
                format_func=lambda run_name: f"Run {_run_human_timestamp(run_name)}",
            )
            graph_run_root = site_root / graph_run
            graph_dir = knowledge_graph_dir(graph_run_root)
            stats = load_graph_stats(graph_run_root)
            raw_files = _raw_markdown_files(graph_run_root)
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
                    graph = build_markdown_graph(graph_run_root, st.session_state["site_id"], graph_run)
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
                "Use Build Deterministic Graph for the real retrieval graph. The old Graphify runner is no longer the primary graph path."
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
                    page_options = [page.get("id") for page in pages]
                    p1, p2, p3 = st.columns([1.5, 1.5, 1])
                    from_page = p1.selectbox("From page", options=page_options, index=0 if page_options else None, key="kg_path_from")
                    to_page = p2.selectbox("To page", options=page_options, index=min(1, len(page_options) - 1) if page_options else None, key="kg_path_to")
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
with tabs[5]:
    st.subheader("Settings")
    st.caption("One place for keys, providers, models, embeddings, and vector search.")

    st.write("Providers")
    or1, or2 = st.columns([2, 1])
    openrouter_key = or1.text_input(
        "OPENROUTER_API_KEY",
        value=st.session_state.get("openrouter_api_key", ""),
        type="password",
        help="Saved locally to .env in this project.",
    )
    if or2.button("Save OpenRouter Key", use_container_width=True):
        _save_env_key(ENV_PATH, "OPENROUTER_API_KEY", openrouter_key.strip())
        st.session_state["openrouter_api_key"] = openrouter_key.strip()
        os.environ["OPENROUTER_API_KEY"] = openrouter_key.strip()
        _save_app_state()
        st.success("Saved OpenRouter key")

    tav1, tav2 = st.columns([2, 1])
    tavily_key = tav1.text_input(
        "TAVILY_API_KEY",
        value=st.session_state.get("tavily_api_key", ""),
        type="password",
        help="Optional. Used for university map research and failed-source recovery when enabled.",
    )
    if tav2.button("Save Tavily Key", use_container_width=True):
        _save_env_key(ENV_PATH, "TAVILY_API_KEY", tavily_key.strip())
        st.session_state["tavily_api_key"] = tavily_key.strip()
        _save_app_state()
        st.success("Saved Tavily key")

    st.write("Task Providers")
    tr1, tr2, tr3 = st.columns([1, 1.5, 1.5])
    current_url_provider = st.session_state.get("url_reasoning_provider", "openrouter")
    st.session_state["url_reasoning_provider"] = tr1.selectbox(
        "URL reasoning",
        options=["openrouter", "ollama"],
        index=["openrouter", "ollama"].index(current_url_provider) if current_url_provider in {"openrouter", "ollama"} else 0,
    )
    st.session_state["url_reasoning_openrouter_model"] = tr2.text_input(
        "URL OpenRouter model",
        value=st.session_state.get("url_reasoning_openrouter_model")
        or st.session_state.get("url_reasoning_model")
        or st.session_state.get("default_or_model", "deepseek/deepseek-v4-flash"),
    )
    st.session_state["url_reasoning_ollama_model"] = tr3.text_input(
        "URL Ollama model",
        value=st.session_state.get("url_reasoning_ollama_model") or st.session_state.get("ollama_model") or "qwen2.5:3b",
    )

    tg1, tg2, tg3 = st.columns([1, 1.5, 1.5])
    current_graph_provider = st.session_state.get("graph_enrichment_provider", "ollama")
    st.session_state["graph_enrichment_provider"] = tg1.selectbox(
        "Graph enrichment",
        options=["deterministic", "openrouter", "ollama"],
        index=["deterministic", "openrouter", "ollama"].index(current_graph_provider)
        if current_graph_provider in {"deterministic", "openrouter", "ollama"}
        else 2,
        help="Deterministic graph is the primary path. Provider applies only to optional semantic enrichment.",
    )
    st.session_state["graph_enrichment_openrouter_model"] = tg2.text_input(
        "Graph OpenRouter model",
        value=st.session_state.get("graph_enrichment_openrouter_model") or st.session_state.get("graphify_model", "openai/gpt-4.1-mini"),
    )
    st.session_state["graph_enrichment_ollama_model"] = tg3.text_input(
        "Graph Ollama model",
        value=st.session_state.get("graph_enrichment_ollama_model") or st.session_state.get("ollama_model") or "qwen2.5:3b",
    )

    ta1, ta2, ta3 = st.columns([1, 1.5, 1.5])
    current_answer_provider = st.session_state.get("graph_answer_provider", "openrouter")
    st.session_state["graph_answer_provider"] = ta1.selectbox(
        "Graph Q&A",
        options=["openrouter", "ollama"],
        index=["openrouter", "ollama"].index(current_answer_provider) if current_answer_provider in {"openrouter", "ollama"} else 0,
    )
    st.session_state["graph_answer_openrouter_model"] = ta2.text_input(
        "Q&A OpenRouter model",
        value=st.session_state.get("graph_answer_openrouter_model") or st.session_state.get("default_or_model", "deepseek/deepseek-v4-flash"),
    )
    st.session_state["graph_answer_ollama_model"] = ta3.text_input(
        "Q&A Ollama model",
        value=st.session_state.get("graph_answer_ollama_model") or st.session_state.get("ollama_model") or "qwen2.5:3b",
    )

    st.write("Runtime")
    o1, o2 = st.columns(2)
    st.session_state["ollama_base_url"] = _normalize_ollama_base_url(o1.text_input("Ollama base URL", value=st.session_state.get("ollama_base_url", OLLAMA_BASE_URL)))
    st.session_state["scrape_concurrency"] = int(o2.number_input("Scrape concurrency", min_value=1, max_value=16, value=int(st.session_state.get("scrape_concurrency", 4)), step=1))

    st.write("Embeddings")
    e1, e2 = st.columns([1, 2])
    st.session_state["embedding_enabled"] = e1.toggle("Embeddings", value=bool(st.session_state.get("embedding_enabled", True)))
    st.session_state["embedding_model"] = e2.text_input("Embedding model", value=st.session_state.get("embedding_model", "nomic-embed-text:latest"))

    st.write("Zvec")
    z1, z2, z3 = st.columns([1, 2, 2])
    st.session_state["zvec_enabled"] = z1.toggle("Zvec", value=bool(st.session_state.get("zvec_enabled", True)))
    st.session_state["zvec_index_path"] = z2.text_input("Index path", value=st.session_state.get("zvec_index_path", ""), placeholder="data/sites/<site>/zvec")
    st.session_state["zvec_collection"] = z3.text_input("Collection", value=st.session_state.get("zvec_collection", "university_wiki"))

    st.write("Research")
    r1, r2 = st.columns(2)
    st.session_state["use_tavily_for_map"] = r1.toggle("Use Tavily for university map", value=bool(st.session_state.get("use_tavily_for_map", False)))
    st.session_state["use_tavily_for_retry"] = r2.toggle("Use Tavily for failed retries", value=bool(st.session_state.get("use_tavily_for_retry", False)))

    if st.button("Save Settings", type="primary"):
        _save_app_state()
        st.success("Settings saved.")
