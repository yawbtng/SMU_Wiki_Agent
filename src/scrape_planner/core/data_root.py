from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


DATA_ROOT_ENV_VARS = ("ULTRA_FAST_RAG_DATA_ROOT", "SCRAPE_PLANNER_DATA_ROOT")


def repo_root() -> Path:
    """Return the repository root (directory containing start.sh and src/)."""
    path = Path(__file__).resolve()
    for parent in path.parents:
        if (parent / "start.sh").is_file() and (parent / "src").is_dir():
            return parent
    return path.parents[3]


def resolve_data_root(project_root: Path, env: Mapping[str, str] | None = None) -> Path:
    """Return the artifact data directory for this checkout."""
    env = env or os.environ
    explicit = _explicit_data_root(env)

    if explicit is not None:
        if _looks_populated_data_root(explicit) or env.get("SCRAPE_PLANNER_DATA_ROOT_STRICT") == "1":
            return explicit

    root = project_root.resolve()
    for candidate in _data_root_candidates(root, explicit):
        if _looks_populated_data_root(candidate):
            return candidate

    if explicit is not None:
        return explicit
    return root / "data"


def _explicit_data_root(env: Mapping[str, str]) -> Path | None:
    for key in DATA_ROOT_ENV_VARS:
        configured = str(env.get(key, "")).strip()
        if configured:
            return Path(configured).expanduser().resolve()
    return None


def _data_root_candidates(project_root: Path, explicit: Path | None) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []

    def add(path: Path) -> None:
        resolved = path.expanduser().resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        ordered.append(resolved)

    add(project_root / "data")
    main_root = _main_worktree_root(project_root)
    if main_root and main_root != project_root:
        add(main_root / "data")
    for sibling_data in _sibling_worktree_data_roots(project_root):
        add(sibling_data)
    if explicit is not None:
        add(explicit)
    return ordered


def _looks_populated_data_root(path: Path) -> bool:
    sites = path / "sites"
    if sites.is_dir():
        for entry in sites.iterdir():
            if entry.is_dir() or entry.is_symlink():
                return True
    app_state = path / "app_state.json"
    return app_state.is_file() and app_state.stat().st_size > 2


def _sibling_worktree_data_roots(project_root: Path) -> list[Path]:
    parent = project_root.parent
    if not parent.is_dir():
        return []
    roots: list[Path] = []
    for sibling in sorted(parent.iterdir()):
        if not sibling.is_dir() or sibling.resolve() == project_root.resolve():
            continue
        data_path = sibling / "data"
        if data_path.is_dir():
            roots.append(data_path)
    return roots


def _main_worktree_root(project_root: Path) -> Path | None:
    git_file = project_root / ".git"
    if not git_file.is_file():
        return None

    try:
        content = git_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    prefix = "gitdir:"
    if not content.startswith(prefix):
        return None

    raw_gitdir = content[len(prefix) :].strip()
    gitdir = Path(raw_gitdir)
    if not gitdir.is_absolute():
        gitdir = (project_root / gitdir).resolve()

    if gitdir.parent.name == "worktrees" and gitdir.parent.parent.name == ".git":
        return gitdir.parent.parent.parent.resolve()

    return None
