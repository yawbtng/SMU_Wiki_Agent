from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_contracts import (
    APP_STATE_DEFAULTS,
    AppStateContract,
    DiscoveredURLContract,
    IndexStatusContract,
    MCPStatusContract,
    RawSourceRowContract,
    RunStatusContract,
    SelectedURLContract,
    WikiStatusContract,
    WorkspaceContract,
)
from ..runtime.run_persistence import read_run_status
from ..core.site_layout import SiteLayout, site_layout, site_root_for
from ..sources.source_registry import read_registry_rows
from ..wiki.stepper_status import (
    load_embedding_status,
    load_mcp_status,
    load_wiki_agent_status,
    load_wiki_status,
    raw_source_status,
)
from ..core.storage import read_json, write_json


def _run_root(data_root: Path, site_id: str, run_id: str) -> Path:
    return site_root_for(data_root, site_id) / str(run_id)


def _site_layout(data_root: Path, site_id: str) -> SiteLayout:
    return site_layout(site_root_for(data_root, site_id))


def _is_scalar_stringish(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _normalize_string(value: Any, default: str = "") -> str:
    if isinstance(value, str):
        return value
    if _is_scalar_stringish(value) and value is not None:
        return str(value)
    return default


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return _normalize_string(value, "")


def _normalize_int(value: Any, default: int = 0, *, minimum: int | None = None, maximum: int | None = None) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        result = value
    elif isinstance(value, float):
        result = int(value)
    elif isinstance(value, str) and value.strip():
        try:
            result = int(value.strip())
        except ValueError:
            return default
    else:
        return default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _normalize_float(value: Any, default: float = 0.0, *, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str) and value.strip():
        try:
            result = float(value.strip())
        except ValueError:
            return default
    else:
        return default
    if minimum is not None:
        result = max(minimum, result)
    return result


def _normalize_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 0:
            return False
        if value == 1:
            return True
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"", "0", "false", "f", "no", "n", "off"}:
            return False
        if normalized in {"1", "true", "t", "yes", "y", "on"}:
            return True
        return default
    return default


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _normalize_string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, item in value.items():
        if not _is_scalar_stringish(key) or not _is_scalar_stringish(item) or key is None or item is None:
            continue
        normalized[str(key)] = str(item)
    return normalized


def _normalize_browser_mode(value: Any, default: str = "none") -> str:
    normalized = _normalize_string(value, default).strip().lower()
    return "lightpanda" if normalized == "lightpanda" else "none"


def _normalize_workspace_rows(value: Any) -> list[WorkspaceContract]:
    if not isinstance(value, list):
        return []
    rows: list[WorkspaceContract] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        if "id" in item:
            normalized["id"] = _normalize_string(item.get("id"))
        if "name" in item:
            normalized["name"] = _normalize_string(item.get("name"))
        if "url" in item:
            normalized["url"] = _normalize_string(item.get("url"))
        rows.append(normalized)
    return rows


def _normalize_app_state_payload(payload: Any, defaults: AppStateContract) -> AppStateContract:
    merged: AppStateContract = dict(defaults)
    if not isinstance(payload, dict):
        return merged

    normalized = {str(key): value for key, value in payload.items() if not str(key).startswith("ollama_") and str(key) not in {"ollama_model", "ollama_base_url"}}
    normalized["active_workspace_id"] = _normalize_string(payload.get("active_workspace_id"), defaults.get("active_workspace_id", ""))
    normalized["workspaces"] = _normalize_workspace_rows(payload.get("workspaces"))
    normalized["last_site_url"] = _normalize_string(payload.get("last_site_url"), defaults.get("last_site_url", ""))
    normalized["last_site_id"] = _normalize_string(payload.get("last_site_id"), defaults.get("last_site_id", ""))
    normalized["last_run_id"] = _normalize_string(payload.get("last_run_id"), defaults.get("last_run_id", ""))
    normalized["last_run_by_site"] = _normalize_string_mapping(payload.get("last_run_by_site"))
    normalized["manual_urls"] = _normalize_string(payload.get("manual_urls"), defaults.get("manual_urls", ""))
    normalized["llm_provider"] = "openrouter"
    normalized["scrape_browser_mode"] = _normalize_browser_mode(payload.get("scrape_browser_mode"), defaults.get("scrape_browser_mode", "none"))
    normalized["lightpanda_cdp_url"] = _normalize_string(payload.get("lightpanda_cdp_url"), defaults.get("lightpanda_cdp_url", ""))
    normalized["site_history"] = _normalize_string_list(payload.get("site_history"))
    normalized["openrouter_api_key"] = _normalize_string(payload.get("openrouter_api_key"), defaults.get("openrouter_api_key", ""))
    normalized["tavily_api_key"] = _normalize_string(payload.get("tavily_api_key"), defaults.get("tavily_api_key", ""))
    normalized["default_or_model"] = _normalize_string(payload.get("default_or_model"), defaults.get("default_or_model", ""))
    normalized["default_llm_cap"] = _normalize_int(payload.get("default_llm_cap"), int(defaults.get("default_llm_cap") or 150), minimum=1)
    normalized["default_llm_batch_size"] = _normalize_int(
        payload.get("default_llm_batch_size"),
        int(defaults.get("default_llm_batch_size") or 250),
        minimum=1,
    )
    normalized["default_llm_sleep_sec"] = _normalize_float(
        payload.get("default_llm_sleep_sec"),
        float(defaults.get("default_llm_sleep_sec") or 0.0),
        minimum=0.0,
    )
    normalized["url_reasoning_provider"] = "openrouter"
    normalized["url_reasoning_openrouter_model"] = _normalize_string(
        payload.get("url_reasoning_openrouter_model"),
        defaults.get("url_reasoning_openrouter_model", ""),
    )
    normalized["graph_enrichment_provider"] = "openrouter"
    normalized["graph_enrichment_openrouter_model"] = _normalize_string(
        payload.get("graph_enrichment_openrouter_model"),
        defaults.get("graph_enrichment_openrouter_model", ""),
    )
    normalized["graph_answer_provider"] = "openrouter"
    normalized["graph_answer_openrouter_model"] = _normalize_string(
        payload.get("graph_answer_openrouter_model"),
        defaults.get("graph_answer_openrouter_model", ""),
    )
    normalized["scrape_concurrency"] = _normalize_int(payload.get("scrape_concurrency"), int(defaults.get("scrape_concurrency") or 4), minimum=1, maximum=16)
    normalized["embedding_enabled"] = _normalize_bool(payload.get("embedding_enabled"), bool(defaults.get("embedding_enabled", True)))
    normalized["embedding_model"] = _normalize_string(payload.get("embedding_model"), defaults.get("embedding_model", "openai/text-embedding-3-small"))
    normalized["zvec_enabled"] = _normalize_bool(payload.get("zvec_enabled"), bool(defaults.get("zvec_enabled", True)))
    normalized["zvec_index_path"] = _normalize_string(payload.get("zvec_index_path"), defaults.get("zvec_index_path", ""))
    normalized["zvec_collection"] = _normalize_string(payload.get("zvec_collection"), defaults.get("zvec_collection", "university_wiki"))
    normalized["use_tavily_for_map"] = _normalize_bool(payload.get("use_tavily_for_map"), bool(defaults.get("use_tavily_for_map", False)))
    normalized["tavily_cost_per_call_usd"] = _normalize_float(
        payload.get("tavily_cost_per_call_usd"),
        float(defaults.get("tavily_cost_per_call_usd") or 0.0),
        minimum=0.0,
    )
    normalized["tmux_session_grace_seconds"] = _normalize_int(
        payload.get("tmux_session_grace_seconds"),
        int(defaults.get("tmux_session_grace_seconds") or 1800),
        minimum=0,
    )
    runtime = _normalize_string(payload.get("wiki_builder_runtime"), defaults.get("wiki_builder_runtime", "pi")).lower()
    normalized["wiki_builder_runtime"] = "python" if runtime in {"python", "deterministic"} else "pi"
    normalized["wiki_skip_pi"] = _normalize_bool(payload.get("wiki_skip_pi"), bool(defaults.get("wiki_skip_pi")))
    normalized["tmux_archive_sessions"] = _normalize_bool(
        payload.get("tmux_archive_sessions"),
        bool(defaults.get("tmux_archive_sessions", True)),
    )
    normalized["tmux_reconcile_expired_sessions"] = _normalize_bool(
        payload.get("tmux_reconcile_expired_sessions"),
        bool(defaults.get("tmux_reconcile_expired_sessions", True)),
    )
    normalized["pi_cmd"] = _normalize_string(payload.get("pi_cmd"), defaults.get("pi_cmd", "pi")).strip() or "pi"
    normalized["tmux_archive_subdir"] = _normalize_string(
        payload.get("tmux_archive_subdir"),
        defaults.get("tmux_archive_subdir", "wiki/reports/tmux-archives"),
    )
    merged.update(normalized)
    return merged


def _normalize_discovered_row(row: Any) -> DiscoveredURLContract | None:
    if not isinstance(row, dict):
        return None
    normalized = dict(row)
    if "url" in row:
        normalized["url"] = _normalize_string(row.get("url"))
    if "source_sitemap" in row:
        normalized["source_sitemap"] = _normalize_string(row.get("source_sitemap"))
    if "lastmod" in row:
        normalized["lastmod"] = _normalize_optional_string(row.get("lastmod"))
    if "path_category" in row:
        normalized["path_category"] = _normalize_string(row.get("path_category"))
    if "content_type_guess" in row:
        normalized["content_type_guess"] = _normalize_string(row.get("content_type_guess"))
    if "excluded_reason" in row:
        normalized["excluded_reason"] = _normalize_optional_string(row.get("excluded_reason"))
    if "selected" in row:
        normalized["selected"] = _normalize_bool(row.get("selected"))
    return normalized


def _normalize_discovered_rows_payload(payload: Any) -> list[DiscoveredURLContract]:
    if not isinstance(payload, list):
        return []
    rows: list[DiscoveredURLContract] = []
    for item in payload:
        normalized = _normalize_discovered_row(item)
        if normalized is not None:
            rows.append(normalized)
    return rows


class AppStateRepository:
    def __init__(self, path: Path, *, defaults: AppStateContract | None = None) -> None:
        self.path = Path(path)
        self.defaults = dict(defaults or APP_STATE_DEFAULTS)

    def load(self) -> AppStateContract:
        payload = read_json(self.path, {})
        return _normalize_app_state_payload(payload, self.defaults)

    def save(self, payload: dict[str, Any]) -> None:
        write_json(self.path, _normalize_app_state_payload(payload, self.defaults))
        try:
            from .tmux_settings import refresh_app_state_cache

            refresh_app_state_cache()
        except ImportError:
            pass


class SiteArtifactRepository:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root)

    def site_root(self, site_id: str) -> Path:
        return site_root_for(self.data_root, site_id)

    def run_root(self, site_id: str, run_id: str) -> Path:
        return _run_root(self.data_root, site_id, run_id)

    def discovered_path(self, site_id: str) -> Path:
        return self.site_root(site_id) / "discovered_urls.json"

    def selected_urls_path(self, site_id: str, run_id: str) -> Path:
        return self.run_root(site_id, run_id) / "selected_urls.json"

    def load_discovered_rows(self, site_id: str) -> list[DiscoveredURLContract]:
        payload = read_json(self.discovered_path(site_id), [])
        return _normalize_discovered_rows_payload(payload)

    def save_discovered_rows(self, site_id: str, rows: list[dict[str, Any]]) -> None:
        write_json(self.discovered_path(site_id), rows)

    def load_selected_url_rows(self, site_id: str, run_id: str) -> list[SelectedURLContract]:
        payload = read_json(self.selected_urls_path(site_id, run_id), [])
        return _normalize_discovered_rows_payload(payload)

    def load_run_status(self, site_id: str, run_id: str) -> RunStatusContract:
        payload = read_run_status(self.run_root(site_id, run_id))
        return payload if isinstance(payload, dict) else {}

    def load_raw_source_rows(self, site_id: str) -> list[RawSourceRowContract]:
        return read_registry_rows(_site_layout(self.data_root, site_id).registry_path)


class SiteStatusReadModel:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root)

    def layout(self, site_id: str) -> SiteLayout:
        return _site_layout(self.data_root, site_id)

    def load_raw_source_status(self, site_id: str) -> dict[str, Any]:
        return raw_source_status(self.layout(site_id))

    def load_wiki_status(self, site_id: str) -> WikiStatusContract:
        layout = self.layout(site_id)
        return load_wiki_status(layout, raw_source_status(layout))

    def load_index_status(self, site_id: str) -> IndexStatusContract:
        return load_embedding_status(self.layout(site_id))

    def load_mcp_status(self, site_id: str) -> MCPStatusContract:
        return load_mcp_status(self.layout(site_id))

    def load_wiki_agent_status(self, site_id: str) -> dict[str, Any]:
        layout = self.layout(site_id)
        return load_wiki_agent_status(layout.wiki_dir / "reports")
