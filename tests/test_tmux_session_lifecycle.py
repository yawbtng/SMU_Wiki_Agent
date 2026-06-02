from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.scrape_planner.infra.tmux_runner import TmuxRunner
from src.scrape_planner.infra.tmux_session_shell import build_managed_session_shell, grace_seconds, sanitize_tmux_session_name
from src.scrape_planner.infra.tmux_session_lifecycle import reconcile_expired_tmux_sessions


def test_build_managed_session_shell_archives_sleeps_and_exits() -> None:
    shell = build_managed_session_shell("echo hi", "/tmp/work", archive_path="/tmp/wiki.log", grace=1800)

    assert "tee /tmp/wiki.log" in shell
    assert "sleep 1800" in shell
    assert "exit $code" in shell
    assert "exec /bin/zsh -l" not in shell


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
