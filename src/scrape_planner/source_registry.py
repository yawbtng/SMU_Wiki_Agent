from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse
from uuid import uuid4


REGISTRY_STATUSES = {"ready", "failed", "needs-review"}
CHANGE_STATES = {"new", "unchanged", "changed", "failed", "needs-review"}
COUNT_KEYS = ("new", "unchanged", "changed", "ready", "failed", "needs-review")


@dataclass(frozen=True)
class RegistryMergeResult:
    rows: list[dict[str, Any]]
    counts: dict[str, int]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def checksum_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def checksum_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stable_source_id(source_kind: str, original_url_or_path: str) -> str:
    kind = _clean_token(source_kind or "source")
    identity = _normalize_identity(original_url_or_path)
    digest = hashlib.sha1(f"{kind}:{identity}".encode("utf-8")).hexdigest()[:16]
    return f"{kind}_{digest}"


def build_source_row(
    *,
    source_kind: str,
    title: str,
    original_url: str,
    original_path: str,
    markdown_path: str,
    metadata_path: str,
    checksum: str,
    parser: str,
    status: str,
    now: str | None = None,
    source_id: str | None = None,
    wiki_status: str = "pending",
    error_reason: str = "",
    diagnostic_path: str = "",
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timestamp = now or utc_now_iso()
    normalized_status = _normalize_status(status)
    identity = original_url or original_path or title or markdown_path
    row = {
        "source_id": source_id or stable_source_id(source_kind, identity),
        "source_kind": str(source_kind or "unknown"),
        "title": str(title or identity or "Untitled source"),
        "original_url": str(original_url or ""),
        "original_path": str(original_path or ""),
        "markdown_path": str(markdown_path or ""),
        "metadata_path": str(metadata_path or ""),
        "checksum": str(checksum or ""),
        "parser": str(parser or ""),
        "status": normalized_status,
        "change_state": _change_state_for_status(normalized_status),
        "first_seen_at": timestamp,
        "last_seen_at": timestamp,
        "last_changed_at": timestamp,
        "wiki_status": str(wiki_status or "pending"),
        "wiki_integrated_at": "",
        "wiki_page_paths": [],
        "error_reason": str(error_reason or ""),
        "diagnostic_path": str(diagnostic_path or ""),
        "provenance": provenance or {},
    }
    return row


def read_registry_rows(path: Path) -> list[dict[str, Any]]:
    if not Path(path).exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("source_id"):
            rows.append(_with_defaults(value, now=""))
    return sorted(_dedupe_by_source_id(rows).values(), key=lambda row: str(row.get("source_id") or ""))


def write_registry_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deduped = _dedupe_by_source_id(rows)
    ordered = [deduped[key] for key in sorted(deduped)]
    payload = "".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in ordered)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(path)


def merge_registry_rows(path: Path, incoming_rows: list[dict[str, Any]], *, now: str | None = None) -> RegistryMergeResult:
    timestamp = now or utc_now_iso()
    existing = {str(row.get("source_id")): row for row in read_registry_rows(path)}
    incoming = _dedupe_by_source_id([_with_defaults(row, now=timestamp) for row in incoming_rows])
    counts = {key: 0 for key in COUNT_KEYS}

    for source_id in sorted(incoming):
        new_row = incoming[source_id]
        previous = existing.get(source_id)
        merged = _merge_one(previous, new_row, now=timestamp)
        existing[source_id] = merged
        _increment_counts(counts, merged)

    rows = [existing[key] for key in sorted(existing)]
    write_registry_rows(path, rows)
    return RegistryMergeResult(rows=rows, counts=counts)


def _merge_one(previous: dict[str, Any] | None, incoming: dict[str, Any], *, now: str) -> dict[str, Any]:
    status = _normalize_status(str(incoming.get("status") or "ready"))
    incoming["status"] = status
    if status in {"failed", "needs-review"}:
        merged = dict(incoming)
        if previous:
            merged["first_seen_at"] = previous.get("first_seen_at") or incoming.get("first_seen_at") or now
            merged["wiki_status"] = previous.get("wiki_status") or incoming.get("wiki_status") or "pending"
            merged["wiki_integrated_at"] = previous.get("wiki_integrated_at") or ""
            merged["wiki_page_paths"] = previous.get("wiki_page_paths") or []
        merged["last_seen_at"] = now
        merged["last_changed_at"] = incoming.get("last_changed_at") or now
        merged["change_state"] = "failed" if status == "failed" else "needs-review"
        return _with_defaults(merged, now=now)

    if previous is None:
        merged = dict(incoming)
        merged["first_seen_at"] = incoming.get("first_seen_at") or now
        merged["last_seen_at"] = now
        merged["last_changed_at"] = incoming.get("last_changed_at") or now
        merged["change_state"] = "new"
        merged["wiki_status"] = incoming.get("wiki_status") or "pending"
        return _with_defaults(merged, now=now)

    previous_checksum = str(previous.get("checksum") or "")
    incoming_checksum = str(incoming.get("checksum") or "")
    if previous_checksum == incoming_checksum:
        merged = dict(previous)
        merged["last_seen_at"] = now
        merged["change_state"] = "unchanged"
        return _with_defaults(merged, now=now)

    merged = dict(incoming)
    merged["first_seen_at"] = previous.get("first_seen_at") or incoming.get("first_seen_at") or now
    merged["last_seen_at"] = now
    merged["last_changed_at"] = now
    merged["previous_checksum"] = previous_checksum
    merged["change_state"] = "changed"
    merged["wiki_status"] = "pending"
    merged["wiki_integrated_at"] = previous.get("wiki_integrated_at") or ""
    merged["wiki_page_paths"] = previous.get("wiki_page_paths") or []
    return _with_defaults(merged, now=now)


def _increment_counts(counts: dict[str, int], row: dict[str, Any]) -> None:
    state = str(row.get("change_state") or "")
    status = str(row.get("status") or "")
    if state in counts:
        counts[state] += 1
    if status in counts and status != state:
        counts[status] += 1


def _with_defaults(row: dict[str, Any], *, now: str) -> dict[str, Any]:
    timestamp = now or utc_now_iso()
    status = _normalize_status(str(row.get("status") or "ready"))
    state = str(row.get("change_state") or _change_state_for_status(status))
    if state not in CHANGE_STATES:
        state = _change_state_for_status(status)
    out = dict(row)
    out.setdefault("source_id", stable_source_id(str(out.get("source_kind") or "source"), _row_identity(out)))
    out.setdefault("source_kind", "unknown")
    out.setdefault("title", "Untitled source")
    out.setdefault("original_url", "")
    out.setdefault("original_path", "")
    out.setdefault("markdown_path", "")
    out.setdefault("metadata_path", "")
    out.setdefault("checksum", "")
    out.setdefault("parser", "")
    out["status"] = status
    out["change_state"] = state
    out.setdefault("first_seen_at", timestamp)
    out.setdefault("last_seen_at", timestamp)
    out.setdefault("last_changed_at", timestamp)
    out.setdefault("wiki_status", "pending")
    out.setdefault("wiki_integrated_at", "")
    out.setdefault("wiki_page_paths", [])
    out.setdefault("error_reason", "")
    out.setdefault("diagnostic_path", "")
    out.setdefault("provenance", {})
    return out


def _dedupe_by_source_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        source_id = str(row.get("source_id") or "")
        if source_id:
            deduped[source_id] = row
    return deduped


def _normalize_status(status: str) -> str:
    normalized = str(status or "ready").strip().lower().replace("_", "-")
    return normalized if normalized in REGISTRY_STATUSES else "needs-review"


def _change_state_for_status(status: str) -> str:
    if status == "failed":
        return "failed"
    if status == "needs-review":
        return "needs-review"
    return "new"


def _normalize_identity(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path or "/"
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        return urlunparse((scheme, netloc, path, "", parsed.query, ""))
    return raw


def _row_identity(row: dict[str, Any]) -> str:
    return str(row.get("original_url") or row.get("original_path") or row.get("markdown_path") or row.get("title") or "")


def _clean_token(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "source"))
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "source"
