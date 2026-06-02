from __future__ import annotations

from typing import Any, Dict, List

from typing_extensions import NotRequired, TypedDict


class WorkspaceContract(TypedDict, total=False):
    id: str
    name: str
    url: str


class DiscoveredURLContract(TypedDict, total=False):
    url: str
    source_sitemap: str
    lastmod: str | None
    path_category: str
    content_type_guess: str
    excluded_reason: str | None
    selected: bool


SelectedURLContract = DiscoveredURLContract


class RunStatusContract(TypedDict, total=False):
    state: str
    status: str
    site_id: str
    run_id: str
    total: int
    queued: int
    running: int
    done: int
    failed: int
    started_at: str
    finished_at: str
    updated_at: str
    error: str


class RawSourceRowContract(TypedDict, total=False):
    source_id: str
    source_kind: str
    title: str
    original_url: str
    original_path: str
    markdown_path: str
    metadata_path: str
    checksum: str
    parser: str
    status: str
    change_state: str
    first_seen_at: str
    last_seen_at: str
    last_changed_at: str
    wiki_status: str
    wiki_integrated_at: str
    wiki_page_paths: List[str]
    error_reason: str
    diagnostic_path: str
    provenance: Dict[str, Any]


class WikiStatusContract(TypedDict, total=False):
    tmux_session: str
    log_path: str
    job_status: str
    last_progress: str
    pages_created: int
    pages_updated: int
    integrated_sources: int
    review_queue_count: int
    latest_report_path: NotRequired[object]
    latest_report: Dict[str, Any]
    index_path: NotRequired[object]
    review_queue_path: NotRequired[object]


class IndexStatusContract(TypedDict, total=False):
    raw_index_count: int
    wiki_index_count: int
    last_build_time: str
    reranker_ready: bool
    changed_document_count: int
    index_health: str
    latest_report_path: NotRequired[object]
    latest_report: Dict[str, Any]


class MCPStatusContract(TypedDict, total=False):
    server_command: str
    expected_server_command: str
    server_available: bool
    config_snippet: Dict[str, Any]
    index_health: str
    latest_report_path: NotRequired[object]
    latest_report: Dict[str, Any]


class AppStateContract(TypedDict, total=False):
    active_workspace_id: str
    workspaces: List[WorkspaceContract]
    last_site_url: str
    last_site_id: str
    last_run_id: str
    last_run_by_site: Dict[str, str]
    manual_urls: str
    ollama_model: str
    llm_provider: str
    ollama_base_url: str
    scrape_browser_mode: str
    lightpanda_cdp_url: str
    site_history: List[str]
    tavily_api_key: str
    default_or_model: str
    default_llm_cap: int
    default_llm_batch_size: int
    default_llm_sleep_sec: float
    url_reasoning_provider: str
    url_reasoning_openrouter_model: str
    url_reasoning_ollama_model: str
    graph_enrichment_provider: str
    graph_enrichment_openrouter_model: str
    graph_enrichment_ollama_model: str
    graph_answer_provider: str
    graph_answer_openrouter_model: str
    graph_answer_ollama_model: str
    scrape_concurrency: int
    embedding_enabled: bool
    embedding_model: str
    zvec_enabled: bool
    zvec_index_path: str
    zvec_collection: str
    use_tavily_for_map: bool
    tavily_cost_per_call_usd: float
    ollama_input_per_m_usd: float
    ollama_output_per_m_usd: float
    tmux_session_grace_seconds: int
    wiki_builder_runtime: str
    wiki_skip_pi: bool
    tmux_archive_sessions: bool
    tmux_reconcile_expired_sessions: bool
    pi_cmd: str
    tmux_archive_subdir: str


APP_STATE_DEFAULTS: AppStateContract = {
    "active_workspace_id": "",
    "workspaces": [],
    "last_site_url": "",
    "last_site_id": "",
    "last_run_id": "",
    "last_run_by_site": {},
    "manual_urls": "",
    "ollama_model": "",
    "llm_provider": "openrouter",
    "ollama_base_url": "http://host.docker.internal:11434",
    "site_history": [],
    "tmux_session_grace_seconds": 1800,
    "wiki_builder_runtime": "pi",
    "wiki_skip_pi": False,
    "tmux_archive_sessions": True,
    "tmux_reconcile_expired_sessions": True,
    "pi_cmd": "pi",
    "tmux_archive_subdir": "wiki/reports/tmux-archives",
}
