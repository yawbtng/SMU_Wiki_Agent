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
from ..run_persistence import read_run_status
from ..site_layout import SiteLayout, site_layout
from ..source_registry import read_registry_rows
from ..stepper_status import (
    load_embedding_status,
    load_mcp_status,
    load_wiki_status,
    raw_source_status,
)
from ..storage import read_json, write_json


def _site_root(data_root: Path, site_id: str) -> Path:
    return Path(data_root) / "sites" / str(site_id)


def _run_root(data_root: Path, site_id: str, run_id: str) -> Path:
    return _site_root(data_root, site_id) / str(run_id)


def _site_layout(data_root: Path, site_id: str) -> SiteLayout:
    return site_layout(_site_root(data_root, site_id))


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

    normalized = dict(payload)
    normalized["active_workspace_id"] = _normalize_string(payload.get("active_workspace_id"), defaults.get("active_workspace_id", ""))
    normalized["workspaces"] = _normalize_workspace_rows(payload.get("workspaces"))
    normalized["last_site_url"] = _normalize_string(payload.get("last_site_url"), defaults.get("last_site_url", ""))
    normalized["last_site_id"] = _normalize_string(payload.get("last_site_id"), defaults.get("last_site_id", ""))
    normalized["last_run_id"] = _normalize_string(payload.get("last_run_id"), defaults.get("last_run_id", ""))
    normalized["last_run_by_site"] = _normalize_string_mapping(payload.get("last_run_by_site"))
    normalized["manual_urls"] = _normalize_string(payload.get("manual_urls"), defaults.get("manual_urls", ""))
    normalized["ollama_model"] = _normalize_string(payload.get("ollama_model"), defaults.get("ollama_model", ""))
    normalized["llm_provider"] = _normalize_string(payload.get("llm_provider"), defaults.get("llm_provider", "openrouter"))
    normalized["ollama_base_url"] = _normalize_string(payload.get("ollama_base_url"), defaults.get("ollama_base_url", ""))
    normalized["site_history"] = _normalize_string_list(payload.get("site_history"))
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
        write_json(self.path, payload)


class SiteArtifactRepository:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root)

    def site_root(self, site_id: str) -> Path:
        return _site_root(self.data_root, site_id)

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
