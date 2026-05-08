from __future__ import annotations

import shlex
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TerminalSkillRunner:
    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._logs: list[str] = []
        self._max_logs = 2000
        self._started_at: str | None = None
        self._paused = False
        self._command = ""
        self._workdir = ""

    def _append_log(self, line: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._lock:
            self._logs.append(f"[{ts}] {line.rstrip()}")
            if len(self._logs) > self._max_logs:
                self._logs = self._logs[-self._max_logs :]

    def _reader(self) -> None:
        proc = self._process
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                self._append_log(line)
        except Exception as exc:
            self._append_log(f"Reader error: {exc}")
        finally:
            rc = proc.poll()
            self._append_log(f"Process exited with code {rc}")

    def start(
        self,
        command: str,
        *,
        workdir: str | None = None,
        env: dict[str, str] | None = None,
        use_shell: bool = False,
    ) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise RuntimeError("A terminal skill job is already running.")

        cwd = str(Path(workdir).resolve()) if workdir else None
        if use_shell:
            proc = subprocess.Popen(
                ["/bin/zsh", "-lic", command],
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        else:
            args = shlex.split(command)
            proc = subprocess.Popen(
                args,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        with self._lock:
            self._process = proc
            self._reader_thread = threading.Thread(target=self._reader, daemon=True)
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._paused = False
            self._command = command
            self._workdir = cwd or ""
            self._logs = []
        self._append_log(f"Started: {command}")
        if cwd:
            self._append_log(f"Working directory: {cwd}")
        self._reader_thread.start()

    def pause(self) -> None:
        with self._lock:
            proc = self._process
        if proc is None or proc.poll() is not None:
            return
        proc.send_signal(signal.SIGSTOP)
        with self._lock:
            self._paused = True
        self._append_log("Paused via SIGSTOP")

    def resume(self) -> None:
        with self._lock:
            proc = self._process
        if proc is None or proc.poll() is not None:
            return
        proc.send_signal(signal.SIGCONT)
        with self._lock:
            self._paused = False
        self._append_log("Resumed via SIGCONT")

    def cancel(self) -> None:
        with self._lock:
            proc = self._process
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        deadline = time.time() + 5
        while time.time() < deadline and proc.poll() is None:
            time.sleep(0.1)
        if proc.poll() is None:
            proc.kill()
        with self._lock:
            self._paused = False
        self._append_log("Cancelled by user")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            proc = self._process
            return {
                "running": bool(proc is not None and proc.poll() is None),
                "paused": self._paused,
                "pid": None if proc is None else proc.pid,
                "returncode": None if proc is None else proc.poll(),
                "started_at": self._started_at,
                "command": self._command,
                "workdir": self._workdir,
                "logs": list(self._logs),
            }
