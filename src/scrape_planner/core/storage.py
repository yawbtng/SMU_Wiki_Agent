from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import DiscoveredURL


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


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")
    tmp_path.replace(path)


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


def persist_discovered(path: Path, discovered: list[DiscoveredURL]) -> None:
    write_json(path, [asdict(item) for item in discovered])
