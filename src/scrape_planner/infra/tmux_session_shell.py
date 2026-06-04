from __future__ import annotations

import shlex
from pathlib import Path

DEFAULT_GRACE_SECONDS = 30 * 60


def sanitize_tmux_session_name(name: str) -> str:
    """Match tmux session naming: dots and other punctuation become underscores."""
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(name or "").strip())


def grace_seconds(value: int | None = None) -> int:
    from ..app.tmux_settings import tmux_session_grace_seconds

    return tmux_session_grace_seconds(override=value)


def build_managed_session_shell(
    command: str,
    workdir: str,
    *,
    archive_path: Path | str | None = None,
    grace: int | None = None,
) -> str:
    """Run command, tee output to archive, wait grace period, then exit (no interactive shell)."""
    from ..app.tmux_settings import build_app_state_env_exports

    grace_value = grace_seconds(grace)
    workdir_q = shlex.quote(workdir)
    path_prefix = "export PATH=/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
    env_exports = build_app_state_env_exports()
    env_prefix = " && ".join(env_exports)
    if archive_path:
        archive_q = shlex.quote(str(archive_path))
        run = f"set -o pipefail; {command} 2>&1 | tee {archive_q}; code=$?"
        archive_msg = f'echo "[tmux-runner] log archived to {archive_path}"'
    else:
        run = f"{command}; code=$?"
        archive_msg = ""
    tail = ['echo "[tmux-runner] command exited with code $code"']
    if archive_msg:
        tail.append(archive_msg)
    if grace_value > 0:
        tail.append(f'echo "[tmux-runner] session closes in {grace_value}s"')
        tail.append(f"sleep {grace_value}")
    tail.append("exit $code")
    setup = [f"cd {workdir_q}", path_prefix]
    if env_prefix:
        setup.append(env_prefix)
    setup.append(run)
    inner = " && ".join(setup) + "; " + "; ".join(tail)
    return f"/bin/zsh -lic {shlex.quote(inner)}"
