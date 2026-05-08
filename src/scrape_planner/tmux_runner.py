from __future__ import annotations

import shlex
import shutil
import subprocess
from typing import Any


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

    def available(self, tmux_bin: str | None = None) -> bool:
        return self._resolve_tmux(tmux_bin) is not None

    def start(self, name: str, command: str, workdir: str, tmux_bin: str | None = None) -> dict[str, Any]:
        if self.session_exists(name, tmux_bin=tmux_bin):
            return {"ok": False, "error": f"Session `{name}` already exists."}
        wrapped = (
            f"cd {shlex.quote(workdir)} && "
            "export PATH=/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH && "
            f"{command}; "
            "code=$?; echo; echo \"[tmux-runner] command exited with code $code\"; "
            "exec /bin/zsh -l"
        )
        shell_command = f"/bin/zsh -lic {shlex.quote(wrapped)}"
        r = self._run(["new-session", "-d", "-s", name, shell_command], tmux_bin=tmux_bin)
        if r.returncode != 0:
            return {
                "ok": False,
                "error": r.stderr.strip() or "Failed to start tmux session.",
                "command": shell_command,
            }
        return {"ok": True, "command": shell_command}

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
