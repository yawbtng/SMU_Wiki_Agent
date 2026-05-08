from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import read_json, write_json


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_event(run_root: Path, event: dict[str, Any]) -> None:
    path = run_root / "observability_events.json"
    events = read_json(path, [])
    payload = {"ts": now_iso()}
    payload.update(event)
    events.append(payload)
    write_json(path, events)


def load_events(run_root: Path) -> list[dict[str, Any]]:
    return read_json(run_root / "observability_events.json", [])


def summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(events)
    by_provider: dict[str, int] = {}
    by_status: dict[str, int] = {}
    latency_samples = []
    for e in events:
        provider = e.get("provider", "unknown")
        status = e.get("status", "unknown")
        by_provider[provider] = by_provider.get(provider, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
        if isinstance(e.get("latency_ms"), (int, float)):
            latency_samples.append(float(e["latency_ms"]))
    avg_latency = sum(latency_samples) / len(latency_samples) if latency_samples else 0.0
    return {
        "total_calls": total,
        "by_provider": by_provider,
        "by_status": by_status,
        "avg_latency_ms": round(avg_latency, 2),
    }

