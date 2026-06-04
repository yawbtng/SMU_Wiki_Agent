from __future__ import annotations

import json
import shlex
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.scrape_planner.app.tmux_settings import refresh_app_state_cache
from src.scrape_planner.core.storage import write_json
from src.scrape_planner.infra.tmux_runner import TmuxRunner
from src.scrape_planner.infra.tmux_session_shell import build_managed_session_shell, grace_seconds, sanitize_tmux_session_name
from src.scrape_planner.infra.tmux_session_lifecycle import reconcile_expired_tmux_sessions


def test_build_managed_session_shell_archives_sleeps_and_exits() -> None:
    shell = build_managed_session_shell("echo hi", "/tmp/work", archive_path="/tmp/wiki.log", grace=1800)

    assert "tee /tmp/wiki.log" in shell
    assert "sleep 1800" in shell
    assert "exit $code" in shell
    assert "exec /bin/zsh -l" not in shell


def test_build_managed_session_shell_exports_app_state_api_keys(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    write_json(
        data_root / "app_state.json",
        {
            "openrouter_api_key": "fake-openrouter-key",
            "tavily_api_key": "fake-tavily-key",
            "embedding_model": "openai/text-embedding-3-large",
        },
    )
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_EMBED_MODEL", raising=False)
    refresh_app_state_cache()

    shell = build_managed_session_shell("echo hi", str(tmp_path / "work"), grace=0)

    assert f"export OPENROUTER_API_KEY={shlex.quote('fake-openrouter-key')}" in shell
    assert f"export TAVILY_API_KEY={shlex.quote('fake-tavily-key')}" in shell
    assert f"export OPENROUTER_EMBED_MODEL={shlex.quote('openai/text-embedding-3-large')}" in shell


def test_build_managed_session_shell_skips_app_state_exports_when_env_set(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    write_json(
        data_root / "app_state.json",
        {"openrouter_api_key": "fake-openrouter-key"},
    )
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-openrouter-key")
    refresh_app_state_cache()

    shell = build_managed_session_shell("echo hi", str(tmp_path / "work"), grace=0)

    assert "export OPENROUTER_API_KEY=" not in shell


def test_sanitize_tmux_session_name_replaces_dots() -> None:
    assert sanitize_tmux_session_name("wiki-www.smu.edu-20260602-095604") == "wiki-www_smu_edu-20260602-095604"


def test_grace_seconds_defaults_to_thirty_minutes(monkeypatch) -> None:
    monkeypatch.delenv("TMUX_SESSION_GRACE_SECONDS", raising=False)
    assert grace_seconds() == 1800


def test_grace_seconds_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("TMUX_SESSION_GRACE_SECONDS", "600")
    assert grace_seconds() == 600


def test_tmux_runner_start_resolves_grace_without_shadowing(monkeypatch) -> None:
    class Ok:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(TmuxRunner, "session_exists", lambda self, name, tmux_bin=None: False)
    monkeypatch.setattr(TmuxRunner, "_run", lambda self, args, tmux_bin=None: Ok())

    result = TmuxRunner().start("wiki-test-site", "echo hi", "/tmp/work", grace_seconds=600)

    assert result["ok"] is True
    assert result["tmux_grace_seconds"] == 600


def test_reconcile_kills_expired_completed_sessions(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    archives = reports / "tmux-archives"
    reports.mkdir()
    archives.mkdir()
    finished = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    report_path = reports / "wiki-build-latest.json"
    report_path.write_text(
        json.dumps(
            {
                "status": "complete",
                "job_status": "complete",
                "tmux_session": "wiki-site-20260522-101112",
                "updated_at": finished,
                "job_finished_at": finished,
            }
        ),
        encoding="utf-8",
    )

    class FakeRunner:
        def __init__(self) -> None:
            self.killed: list[str] = []
            self._sessions = {"wiki-site-20260522-101112"}

        def available(self) -> bool:
            return True

        def session_exists(self, name: str) -> bool:
            return name in self._sessions

        def capture(self, name: str, lines: int = 5000) -> str:
            return f"pane output for {name}\n"

        def kill(self, name: str):
            self._sessions.discard(name)
            self.killed.append(name)
            return {"ok": True}

    runner = FakeRunner()
    actions = reconcile_expired_tmux_sessions(reports, runner=runner, grace=1800)

    assert len(actions) == 1
    assert actions[0]["session"] == "wiki-site-20260522-101112"
    assert actions[0]["killed"] is True
    assert runner.killed == ["wiki-site-20260522-101112"]
    assert (archives / "wiki-site-20260522-101112.log").exists()


def test_archive_site_tmux_session_reconciles_running_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.scrape_planner.webapp.tmux_sessions import archive_site_tmux_session_payload

    data_root = tmp_path / "data"
    site_root = data_root / "sites" / "demo.edu"
    reports = site_root / "wiki" / "reports"
    reports.mkdir(parents=True)
    report_path = reports / "wiki-build-latest.json"
    write_json(
        report_path,
        {
            "status": "running",
            "job_status": "running",
            "tmux_session": "wiki-demo.edu-test",
        },
    )

    class FakeRunner:
        def available(self) -> bool:
            return True

        def session_exists(self, name: str) -> bool:
            return True

        def capture(self, name: str, lines: int = 5000) -> str:
            return "pane output"

        def kill(self, name: str):
            return {"ok": True}

    monkeypatch.setattr("src.scrape_planner.webapp.tmux_sessions.TmuxRunner", FakeRunner)
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))

    payload = archive_site_tmux_session_payload("demo.edu", "wiki-demo.edu-test", site_root_fn=lambda _site_id: site_root)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert payload["killed"] is True
    assert report["job_status"] == "archived"
    assert report["status"] == "archived"
