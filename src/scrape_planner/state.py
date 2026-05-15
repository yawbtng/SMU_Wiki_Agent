from __future__ import annotations

import json
import threading
from collections import defaultdict
from typing import Any

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    redis = None


class _MemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, str] = {}
        self._lists: dict[str, list[str]] = defaultdict(list)

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._values.get(key)

    def set(self, key: str, value: str) -> None:
        with self._lock:
            self._values[key] = value

    def delete(self, key: str) -> None:
        with self._lock:
            self._values.pop(key, None)
            self._lists.pop(key, None)

    def rpush(self, key: str, value: str) -> None:
        with self._lock:
            self._lists[key].append(value)

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        with self._lock:
            data = self._lists.get(key, [])
            if end == -1:
                return data[start:]
            return data[start : end + 1]


class RunStateStore:
    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        self._mem = _MemoryStore()
        self._client: "redis.Redis | None" = None
        try:
            if redis is None:
                raise RuntimeError("redis dependency unavailable")
            client = redis.Redis.from_url(redis_url, decode_responses=True)
            client.ping()
            self._client = client
        except Exception:
            self._client = None

    def _get(self, key: str) -> str | None:
        if self._client is None:
            return self._mem.get(key)
        return self._client.get(key)

    def _set(self, key: str, value: str) -> None:
        if self._client is None:
            self._mem.set(key, value)
            return
        self._client.set(key, value)

    def _delete(self, key: str) -> None:
        if self._client is None:
            self._mem.delete(key)
            return
        self._client.delete(key)

    def _rpush(self, key: str, value: str) -> None:
        if self._client is None:
            self._mem.rpush(key, value)
            return
        self._client.rpush(key, value)

    def _lrange(self, key: str, start: int, end: int) -> list[str]:
        if self._client is None:
            return self._mem.lrange(key, start, end)
        return self._client.lrange(key, start, end)

    def set_status(self, site_id: str, run_id: str, payload: dict[str, Any]) -> None:
        self._set(f"site:{site_id}:run:{run_id}:status", json.dumps(payload))

    def get_status(self, site_id: str, run_id: str) -> dict[str, Any]:
        raw = self._get(f"site:{site_id}:run:{run_id}:status")
        return json.loads(raw) if raw else {}

    def push_event(self, site_id: str, run_id: str, payload: dict[str, Any]) -> None:
        self._rpush(f"site:{site_id}:run:{run_id}:events", json.dumps(payload))

    def get_events(self, site_id: str, run_id: str, max_items: int = 200) -> list[dict[str, Any]]:
        raw_events = self._lrange(f"site:{site_id}:run:{run_id}:events", -max_items, -1)
        return [json.loads(item) for item in raw_events]

    def set_pages(self, site_id: str, run_id: str, payload: list[dict[str, Any]]) -> None:
        self._set(f"site:{site_id}:run:{run_id}:pages", json.dumps(payload))

    def get_pages(self, site_id: str, run_id: str) -> list[dict[str, Any]]:
        raw = self._get(f"site:{site_id}:run:{run_id}:pages")
        return json.loads(raw) if raw else []

    def set_cancel(self, site_id: str, run_id: str, value: bool) -> None:
        self._set(f"site:{site_id}:run:{run_id}:cancel", "1" if value else "0")

    def get_cancel(self, site_id: str, run_id: str) -> bool:
        return self._get(f"site:{site_id}:run:{run_id}:cancel") == "1"

    def set_pause(self, site_id: str, run_id: str, value: bool) -> None:
        self._set(f"site:{site_id}:run:{run_id}:pause", "1" if value else "0")

    def get_pause(self, site_id: str, run_id: str) -> bool:
        return self._get(f"site:{site_id}:run:{run_id}:pause") == "1"

    def clear_run(self, site_id: str, run_id: str) -> None:
        self._delete(f"site:{site_id}:run:{run_id}:status")
        self._delete(f"site:{site_id}:run:{run_id}:events")
        self._delete(f"site:{site_id}:run:{run_id}:pages")
        self._delete(f"site:{site_id}:run:{run_id}:cancel")
        self._delete(f"site:{site_id}:run:{run_id}:pause")

    def set_cleanup_status(self, site_id: str, run_id: str, payload: dict[str, Any]) -> None:
        self._set(f"site:{site_id}:run:{run_id}:cleanup:status", json.dumps(payload))

    def get_cleanup_status(self, site_id: str, run_id: str) -> dict[str, Any]:
        raw = self._get(f"site:{site_id}:run:{run_id}:cleanup:status")
        return json.loads(raw) if raw else {}

    def set_cleanup_items(self, site_id: str, run_id: str, payload: list[dict[str, Any]]) -> None:
        self._set(f"site:{site_id}:run:{run_id}:cleanup:items", json.dumps(payload))

    def get_cleanup_items(self, site_id: str, run_id: str) -> list[dict[str, Any]]:
        raw = self._get(f"site:{site_id}:run:{run_id}:cleanup:items")
        return json.loads(raw) if raw else []

    def push_cleanup_event(self, site_id: str, run_id: str, payload: dict[str, Any]) -> None:
        self._rpush(f"site:{site_id}:run:{run_id}:cleanup:events", json.dumps(payload))

    def get_cleanup_events(self, site_id: str, run_id: str, max_items: int = 200) -> list[dict[str, Any]]:
        raw_events = self._lrange(f"site:{site_id}:run:{run_id}:cleanup:events", -max_items, -1)
        return [json.loads(item) for item in raw_events]

    def set_cleanup_cancel(self, site_id: str, run_id: str, value: bool) -> None:
        self._set(f"site:{site_id}:run:{run_id}:cleanup:cancel", "1" if value else "0")

    def get_cleanup_cancel(self, site_id: str, run_id: str) -> bool:
        return self._get(f"site:{site_id}:run:{run_id}:cleanup:cancel") == "1"

    def clear_cleanup_run(self, site_id: str, run_id: str) -> None:
        self._delete(f"site:{site_id}:run:{run_id}:cleanup:status")
        self._delete(f"site:{site_id}:run:{run_id}:cleanup:items")
        self._delete(f"site:{site_id}:run:{run_id}:cleanup:events")
        self._delete(f"site:{site_id}:run:{run_id}:cleanup:cancel")
