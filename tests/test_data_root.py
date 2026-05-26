import ast
from pathlib import Path

from src.scrape_planner.data_root import resolve_data_root


def test_env_data_root_override_wins(tmp_path: Path):
    project_root = tmp_path / "repo"
    configured = tmp_path / "configured-data"
    project_root.mkdir()

    assert resolve_data_root(project_root, {"ULTRA_FAST_RAG_DATA_ROOT": str(configured)}) == configured.resolve()


def test_local_populated_data_root_wins(tmp_path: Path):
    project_root = tmp_path / "repo"
    local_data = project_root / "data"
    (local_data / "sites").mkdir(parents=True)

    assert resolve_data_root(project_root, {}) == local_data.resolve()


def test_worktree_reuses_populated_main_checkout_data(tmp_path: Path):
    main_root = tmp_path / "main" / "ultra-fast-rag"
    worktree_root = tmp_path / "worktrees" / "9733" / "ultra-fast-rag"
    main_data = main_root / "data"
    gitdir = main_root / ".git" / "worktrees" / "ultra-fast-rag5"

    (main_data / "sites" / "www.smu.edu").mkdir(parents=True)
    gitdir.mkdir(parents=True)
    worktree_root.mkdir(parents=True)
    (worktree_root / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")

    assert resolve_data_root(worktree_root, {}) == main_data.resolve()


def test_unpopulated_worktree_uses_local_data_when_main_has_no_data(tmp_path: Path):
    main_root = tmp_path / "main" / "ultra-fast-rag"
    worktree_root = tmp_path / "worktrees" / "9733" / "ultra-fast-rag"
    gitdir = main_root / ".git" / "worktrees" / "ultra-fast-rag5"

    gitdir.mkdir(parents=True)
    worktree_root.mkdir(parents=True)
    (worktree_root / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")

    assert resolve_data_root(worktree_root, {}) == (worktree_root / "data").resolve()


def test_app_py_keeps_local_data_root_assignment_for_this_wave() -> None:
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"))

    data_root_assign = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "DATA_ROOT" for target in node.targets)
    )

    assert isinstance(data_root_assign.value, ast.BinOp)
    assert isinstance(data_root_assign.value.op, ast.Div)
    assert isinstance(data_root_assign.value.left, ast.Name)
    assert data_root_assign.value.left.id == "ROOT"
    assert isinstance(data_root_assign.value.right, ast.Constant)
    assert data_root_assign.value.right.value == "data"
