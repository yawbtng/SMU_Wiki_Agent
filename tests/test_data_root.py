from __future__ import annotations

from pathlib import Path


def _clean_env(monkeypatch) -> None:
    monkeypatch.delenv("SCRAPE_PLANNER_DATA_ROOT", raising=False)
    monkeypatch.delenv("ULTRA_FAST_RAG_DATA_ROOT", raising=False)
    monkeypatch.delenv("SCRAPE_PLANNER_DATA_ROOT_STRICT", raising=False)


def test_resolve_data_root_prefers_populated_sibling_when_explicit_empty(tmp_path: Path, monkeypatch) -> None:
    from src.scrape_planner.core.data_root import resolve_data_root

    _clean_env(monkeypatch)
    project = tmp_path / "webapp"
    sibling = tmp_path / "sibling"
    empty = tmp_path / "empty-data"
    (sibling / "data" / "sites" / "demo.edu").mkdir(parents=True)
    empty.mkdir()
    project.mkdir()

    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(empty))
    resolved = resolve_data_root(project)
    assert resolved == (sibling / "data").resolve()


def test_resolve_data_root_uses_local_populated_data(tmp_path: Path, monkeypatch) -> None:
    from src.scrape_planner.core.data_root import resolve_data_root

    _clean_env(monkeypatch)
    project = tmp_path / "repo"
    (project / "data" / "sites" / "demo.edu").mkdir(parents=True)

    assert resolve_data_root(project) == (project / "data").resolve()


def test_resolve_data_root_honors_strict_empty_explicit(tmp_path: Path, monkeypatch) -> None:
    from src.scrape_planner.core.data_root import resolve_data_root

    _clean_env(monkeypatch)
    project = tmp_path / "repo"
    project.mkdir()
    empty = tmp_path / "configured-empty"
    empty.mkdir()

    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(empty))
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT_STRICT", "1")
    assert resolve_data_root(project) == empty.resolve()


def test_empty_sites_dir_is_not_populated(tmp_path: Path) -> None:
    from src.scrape_planner.core.data_root import _looks_populated_data_root

    root = tmp_path / "data"
    (root / "sites").mkdir(parents=True)
    assert _looks_populated_data_root(root) is False

    (root / "sites" / "demo.edu").mkdir()
    assert _looks_populated_data_root(root) is True
