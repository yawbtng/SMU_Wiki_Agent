from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_demo_workspace_seed_is_present() -> None:
    seed = ROOT / "fixtures" / "demo-workspace"
    site_root = seed / "sites" / "codex.test.edu"
    assert site_root.is_dir()
    assert (site_root / "wiki" / "pages" / "admissions.md").is_file()
    assert (site_root / "indexes" / "llm_wiki_manifest.json").is_file()


def test_bootstrap_data_seeds_empty_target(tmp_path: Path) -> None:
    target = tmp_path / "data"
    env = {**os.environ, "DEMO_WORKSPACE_SEED": str(ROOT / "fixtures" / "demo-workspace")}
    subprocess.run(
        ["bash", str(ROOT / "scripts" / "bootstrap-data.sh"), str(target)],
        check=True,
        cwd=ROOT,
        env=env,
    )
    site_root = target / "sites" / "codex.test.edu"
    assert site_root.is_dir()
    app_state = json.loads((target / "app_state.json").read_text(encoding="utf-8"))
    assert app_state["active_workspace_id"] == "codex.test.edu"


def test_bootstrap_data_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "data"
    env = {**os.environ, "DEMO_WORKSPACE_SEED": str(ROOT / "fixtures" / "demo-workspace")}
    for _ in range(2):
        subprocess.run(
            ["bash", str(ROOT / "scripts" / "bootstrap-data.sh"), str(target)],
            check=True,
            cwd=ROOT,
            env=env,
        )
    assert len(list((target / "sites").iterdir())) == 1


def test_docker_entrypoint_bootstraps_seed() -> None:
    entrypoint = (ROOT / "scripts" / "docker-entrypoint.sh").read_text(encoding="utf-8")
    assert "bootstrap-data.sh" in entrypoint
    assert "fixtures/demo-workspace" in entrypoint
