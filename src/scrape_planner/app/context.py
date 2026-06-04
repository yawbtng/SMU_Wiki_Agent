from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, MutableMapping

from .repositories import AppStateRepository, SiteArtifactRepository, SiteStatusReadModel


class SessionAdapter:
    def __init__(self, state: MutableMapping[str, Any]) -> None:
        self._state = state

    def __contains__(self, key: object) -> bool:
        return key in self._state

    def __getitem__(self, key: str) -> Any:
        return self._state[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._state[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._state.get(key, default)

    def setdefault(self, key: str, default: Any) -> Any:
        return self._state.setdefault(key, default)


@dataclass(frozen=True)
class AppContext:
    data_root: Path
    session: SessionAdapter
    app_state: AppStateRepository
    site_artifacts: SiteArtifactRepository
    site_status: SiteStatusReadModel
