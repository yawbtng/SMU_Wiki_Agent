from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4


def ensure_run_dirs(base: Path) -> dict[str, Path]:
    paths = {
        "base": base,
        "raw_html": base / "raw_html",
        "markdown": base / "markdown",
        "metadata": base / "metadata",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    tmp_path.replace(path)


def write_json(path: Path, data: Any) -> None:
    write_json_atomic(path, data)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        line = json.dumps(row, ensure_ascii=True) + "\n"
    except TypeError as exc:
        raise ValueError(f"jsonl payload is not serializable for {path}: {exc}") from exc
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        try:
            value, _idx = decoder.raw_decode(text.lstrip())
            return value
        except json.JSONDecodeError:
            return default
