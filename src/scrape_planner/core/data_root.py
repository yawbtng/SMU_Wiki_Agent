from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


DATA_ROOT_ENV_VARS = ("ULTRA_FAST_RAG_DATA_ROOT", "SCRAPE_PLANNER_DATA_ROOT")


def repo_root() -> Path:
    """Return the repository root (directory containing app.py and src/)."""
    path = Path(__file__).resolve()
    for parent in path.parents:
        if (parent / "app.py").is_file() and (parent / "src").is_dir():
            return parent
    return path.parents[3]


def resolve_data_root(project_root: Path, env: Mapping[str, str] | None = None) -> Path:
    """Return the artifact data directory for this checkout.

    Codex worktrees do not contain ignored runtime artifacts. When a worktree is
    attached to a main checkout that already has populated `data/`, reuse that
    data root so old scrape runs remain visible without copying large artifacts.
    """
    env = env or os.environ
    for key in DATA_ROOT_ENV_VARS:
        configured = str(env.get(key, "")).strip()
        if configured:
            return Path(configured).expanduser().resolve()

    root = project_root.resolve()
    local_data = root / "data"
    if _looks_populated_data_root(local_data):
        return local_data

    main_root = _main_worktree_root(root)
    if main_root and main_root != root:
        main_data = main_root / "data"
        if _looks_populated_data_root(main_data):
            return main_data

    return local_data


def _looks_populated_data_root(path: Path) -> bool:
    return (path / "sites").exists() or (path / "app_state.json").exists()


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

    # Standard Git worktree gitdir:
    #   <main-worktree>/.git/worktrees/<worktree-name>
    if gitdir.parent.name == "worktrees" and gitdir.parent.parent.name == ".git":
        return gitdir.parent.parent.parent.resolve()

    return None
