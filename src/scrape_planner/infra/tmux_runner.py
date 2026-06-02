from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .tmux_session_shell import build_managed_session_shell, grace_seconds as resolve_grace_seconds


def _run_tmux(args: list[str]) -> subprocess.CompletedProcess[str]:
    bin_path = shutil.which("tmux")
    if not bin_path:
        return subprocess.CompletedProcess(args=["tmux", *args], returncode=127, stdout="", stderr="tmux not found in PATH")
    return subprocess.run([bin_path, *args], capture_output=True, text=True)


class TmuxRunner:
    def _resolve_tmux(self, tmux_bin: str | None = None) -> str | None:
        if tmux_bin:
            return tmux_bin
        return shutil.which("tmux")

    def _run(self, args: list[str], tmux_bin: str | None = None) -> subprocess.CompletedProcess[str]:
        bin_path = self._resolve_tmux(tmux_bin)
        if not bin_path:
            return subprocess.CompletedProcess(args=["tmux", *args], returncode=127, stdout="", stderr="tmux not found in PATH")
        return subprocess.run([bin_path, *args], capture_output=True, text=True)

    def session_exists(self, name: str, tmux_bin: str | None = None) -> bool:
        r = self._run(["has-session", "-t", name], tmux_bin=tmux_bin)
        return r.returncode == 0

    def list_sessions(self, tmux_bin: str | None = None) -> list[str]:
        r = self._run(["list-sessions", "-F", "#{session_name}"], tmux_bin=tmux_bin)
        if r.returncode != 0:
            return []
        return [line.strip() for line in r.stdout.splitlines() if line.strip()]

    def available(self, tmux_bin: str | None = None) -> bool:
        return self._resolve_tmux(tmux_bin) is not None

    def start(
        self,
        name: str,
        command: str,
        workdir: str,
        tmux_bin: str | None = None,
        *,
        archive_path: Path | str | None = None,
        grace_seconds: int | None = None,
    ) -> dict[str, Any]:
        if self.session_exists(name, tmux_bin=tmux_bin):
            return {"ok": False, "error": f"Session `{name}` already exists."}
        if archive_path:
            Path(archive_path).parent.mkdir(parents=True, exist_ok=True)
        shell_command = build_managed_session_shell(
            command,
            workdir,
            archive_path=archive_path,
            grace=grace_seconds,
        )
        r = self._run(["new-session", "-d", "-s", name, shell_command], tmux_bin=tmux_bin)
        if r.returncode != 0:
            return {
                "ok": False,
                "error": r.stderr.strip() or "Failed to start tmux session.",
                "command": shell_command,
            }
        return {
            "ok": True,
            "command": shell_command,
            "tmux_archive_path": str(archive_path) if archive_path else "",
            "tmux_grace_seconds": resolve_grace_seconds(grace_seconds),
        }

    def start_shell(self, name: str, workdir: str, tmux_bin: str | None = None) -> dict[str, Any]:
        if self.session_exists(name, tmux_bin=tmux_bin):
            return {"ok": False, "error": f"Session `{name}` already exists."}
        wrapped = (
            f"cd {shlex.quote(workdir)} && "
            "export PATH=/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH && "
            "exec /bin/zsh -l"
        )
        r = self._run(["new-session", "-d", "-s", name, "/bin/zsh", "-lic", wrapped], tmux_bin=tmux_bin)
        if r.returncode != 0:
            return {"ok": False, "error": r.stderr.strip() or "Failed to start tmux shell."}
        return {"ok": True}

    def capture(self, name: str, lines: int = 200, tmux_bin: str | None = None) -> str:
        r = self._run(["capture-pane", "-p", "-S", f"-{lines}", "-t", name], tmux_bin=tmux_bin)
        if r.returncode != 0:
            return r.stderr.strip() or ""
        return r.stdout

    def send_line(self, name: str, text: str, tmux_bin: str | None = None) -> dict[str, Any]:
        r = self._run(["send-keys", "-t", name, text, "Enter"], tmux_bin=tmux_bin)
        return {"ok": r.returncode == 0, "error": r.stderr.strip() if r.returncode != 0 else ""}

    def press_enter(self, name: str, tmux_bin: str | None = None) -> dict[str, Any]:
        r = self._run(["send-keys", "-t", name, "C-m"], tmux_bin=tmux_bin)
        return {"ok": r.returncode == 0, "error": r.stderr.strip() if r.returncode != 0 else ""}

    def send_ctrl_c(self, name: str, tmux_bin: str | None = None) -> dict[str, Any]:
        r = self._run(["send-keys", "-t", name, "C-c"], tmux_bin=tmux_bin)
        return {"ok": r.returncode == 0, "error": r.stderr.strip() if r.returncode != 0 else ""}

    def kill(self, name: str, tmux_bin: str | None = None) -> dict[str, Any]:
        r = self._run(["kill-session", "-t", name], tmux_bin=tmux_bin)
        return {"ok": r.returncode == 0, "error": r.stderr.strip() if r.returncode != 0 else ""}
