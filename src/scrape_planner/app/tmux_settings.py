from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from ..core.data_root import repo_root, resolve_data_root
from ..core.storage import read_json
from .artifact_contracts import APP_STATE_DEFAULTS, AppStateContract
from .repositories import _normalize_app_state_payload

DEFAULT_GRACE_SECONDS = 30 * 60
DEFAULT_ARCHIVE_SUBDIR = "wiki/reports/tmux-archives"
VALID_WIKI_RUNTIMES = frozenset({"pi", "python"})


def app_state_path() -> Path:
    return resolve_data_root(repo_root()) / "app_state.json"


@lru_cache(maxsize=1)
def load_app_state() -> AppStateContract:
    defaults: AppStateContract = {**APP_STATE_DEFAULTS}
    payload = read_json(app_state_path(), {})
    return _normalize_app_state_payload(payload, defaults)


def refresh_app_state_cache() -> None:
    load_app_state.cache_clear()


def tmux_session_grace_seconds(*, override: int | None = None) -> int:
    if override is not None:
        return max(0, int(override))
    raw = os.environ.get("TMUX_SESSION_GRACE_SECONDS", "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    payload = read_json(app_state_path(), {})
    if isinstance(payload, dict) and "tmux_session_grace_seconds" in payload:
        stored = payload.get("tmux_session_grace_seconds")
        if isinstance(stored, int) and not isinstance(stored, bool):
            return max(0, stored)
        if isinstance(stored, str) and stored.strip().isdigit():
            return max(0, int(stored.strip()))
    return DEFAULT_GRACE_SECONDS


def wiki_builder_runtime(*, override: str | None = None) -> str:
    if override:
        normalized = _normalize_wiki_runtime(override)
        if normalized in VALID_WIKI_RUNTIMES:
            return normalized
    stored = _normalize_wiki_runtime(str(load_app_state().get("wiki_builder_runtime") or "pi"))
    return stored if stored in VALID_WIKI_RUNTIMES else "pi"


def wiki_skip_pi(*, override: bool | None = None) -> bool:
    if override is not None:
        return bool(override)
    return bool(load_app_state().get("wiki_skip_pi"))


def tmux_archive_sessions(*, override: bool | None = None) -> bool:
    if override is not None:
        return bool(override)
    value = load_app_state().get("tmux_archive_sessions")
    return True if value is None else bool(value)


def tmux_reconcile_expired_sessions(*, override: bool | None = None) -> bool:
    if override is not None:
        return bool(override)
    value = load_app_state().get("tmux_reconcile_expired_sessions")
    return True if value is None else bool(value)


def pi_cmd(*, override: str | None = None) -> str:
    if override:
        return str(override).strip() or "pi"
    stored = str(load_app_state().get("pi_cmd") or "pi").strip()
    return stored or "pi"


def tmux_archive_subdir(*, override: str | None = None) -> str:
    if override:
        return str(override).strip() or DEFAULT_ARCHIVE_SUBDIR
    stored = str(load_app_state().get("tmux_archive_subdir") or DEFAULT_ARCHIVE_SUBDIR).strip()
    return stored or DEFAULT_ARCHIVE_SUBDIR


def _normalize_wiki_runtime(value: str) -> str:
    normalized = str(value or "pi").strip().lower().replace("_", "-")
    if normalized in {"python", "deterministic"}:
        return "python"
    if normalized in {"pi", "ralph-pi", ""}:
        return "pi"
    return normalized
