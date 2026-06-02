from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..app import APP_STATE_DEFAULTS
from ..app.repositories import AppStateRepository, SiteArtifactRepository, SiteStatusReadModel
from ..runtime.agent_run_metrics import AgentRunMetricsRepository
from ..core.data_root import resolve_data_root
from ..wiki.stepper_status import read_jsonl_rows
from ..infra.tmux_runner import TmuxRunner

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def data_root() -> Path:
    return resolve_data_root(PROJECT_ROOT)


def app_state_path() -> Path:
    return data_root() / "app_state.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "items"):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    return value


def read_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def read_jsonl_tail(path: Path, limit: int = 200) -> list[dict[str, Any]]:
    rows = read_jsonl_rows(path)
    return rows[-limit:] if limit > 0 else rows


def site_root(site_id: str) -> Path:
    safe = site_id.strip().strip("/")
    if not safe or ".." in safe or "/" in safe:
        raise HTTPException(status_code=400, detail="invalid site_id")
    return data_root() / "sites" / safe


def run_root(site_id: str, run_id: str) -> Path:
    safe = run_id.strip().strip("/")
    if not safe or ".." in safe or "/" in safe:
        raise HTTPException(status_code=400, detail="invalid run_id")
    return site_root(site_id) / safe


def reports_dir(site_id: str) -> Path:
    return site_root(site_id) / "wiki" / "reports"


def artifact_repo() -> SiteArtifactRepository:
    return SiteArtifactRepository(data_root())


def status_model() -> SiteStatusReadModel:
    return SiteStatusReadModel(data_root())


def state_repo() -> AppStateRepository:
    return AppStateRepository(app_state_path(), defaults={**APP_STATE_DEFAULTS})


def metrics_repo() -> AgentRunMetricsRepository:
    return AgentRunMetricsRepository(data_root())


def mcp_runner() -> TmuxRunner:
    return TmuxRunner()
