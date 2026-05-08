from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

_LOCK = Lock()


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, indent=2, ensure_ascii=True)
    with _LOCK:
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=True) + "\n"
    with _LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
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


def write_run_status(run_root: Path, status: dict[str, Any]) -> None:
    _write_json_atomic(run_root / "run_status.json", status)


def read_run_status(run_root: Path) -> dict[str, Any]:
    path = run_root / "run_status.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def append_run_event(run_root: Path, event: dict[str, Any]) -> None:
    _append_jsonl(run_root / "events.jsonl", event)


def read_run_events(run_root: Path, limit: int | None = None) -> list[dict[str, Any]]:
    events = _read_jsonl(run_root / "events.jsonl")
    if limit is None or limit <= 0:
        return events
    return events[-limit:]


def upsert_page_state(run_root: Path, page: dict[str, Any]) -> None:
    _append_jsonl(run_root / "pages.jsonl", page)


def read_page_states(run_root: Path) -> list[dict[str, Any]]:
    rows = _read_jsonl(run_root / "pages.jsonl")
    pages_by_url: dict[str, dict[str, Any]] = {}
    for row in rows:
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        pages_by_url[url] = row
    return list(pages_by_url.values())
