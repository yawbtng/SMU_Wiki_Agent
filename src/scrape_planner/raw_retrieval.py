from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from .run_persistence import _append_jsonl, _write_json_atomic

INDEX_VERSION = "raw-lexical-v1"
TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass
class RawSourceRecord:
    source_id: str
    url: str
    path: str
    content_hash: str


@dataclass
class ChunkRow:
    chunk_id: str
    source_id: str
    url: str
    path: str
    content_hash: str
    text: str


@dataclass
class IndexManifest:
    version: str
    source_ledger_hash: str
    source_count: int
    chunk_count: int
    term_count: int


@dataclass
class QueryRequest:
    query: str
    max_results: int = 5
    max_candidates: int = 200
    snippet_chars: int = 280


@dataclass
class QueryEvidenceRow:
    source_id: str
    url: str
    path: str
    chunk_id: str
    score: float
    snippet: str


@dataclass
class QueryResponse:
    status: Literal["ok", "missing_index", "stale_index"]
    reason: str | None
    evidence: list[QueryEvidenceRow]
    metadata: dict[str, Any]


def _normalize_source_rows(rows: list[dict[str, Any]]) -> tuple[list[RawSourceRecord], list[dict[str, Any]]]:
    records: list[RawSourceRecord] = []
    invalid: list[dict[str, Any]] = []
    for row in rows:
        source_id = str(row.get("source_id") or "").strip()
        url = str(row.get("url") or "").strip()
        path = str(row.get("path") or "").strip()
        content_hash = str(row.get("content_hash") or "").strip()
        if not source_id or not url or not path:
            invalid.append({"row": row, "reason": "missing_source_id_url_or_path"})
            continue
        if not content_hash:
            p = Path(path)
            if not p.exists():
                invalid.append({"row": row, "reason": "missing_content_hash_and_unreadable_path"})
                continue
            content_hash = hashlib.sha1(p.read_text(encoding="utf-8", errors="ignore").encode("utf-8")).hexdigest()
        records.append(RawSourceRecord(source_id=source_id, url=url, path=path, content_hash=content_hash))
    return records, invalid


def _source_fingerprint(records: list[RawSourceRecord]) -> str:
    ledger = [{"source_id": r.source_id, "path": r.path, "content_hash": r.content_hash} for r in sorted(records, key=lambda x: x.source_id)]
    return hashlib.sha1(json.dumps(ledger, sort_keys=True).encode("utf-8")).hexdigest()


def _chunk_text(text: str, *, chunk_chars: int = 1600, overlap: int = 200) -> list[str]:
    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + chunk_chars)
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def build_raw_index(index_root: Path, source_rows: list[dict[str, Any]], *, chunk_chars: int = 1600, overlap: int = 200) -> dict[str, Any]:
    records, invalid_rows = _normalize_source_rows(source_rows)
    postings: dict[str, dict[str, int]] = {}
    chunk_rows: list[ChunkRow] = []

    for record in records:
        path = Path(record.path)
        if not path.exists():
            invalid_rows.append({"source_id": record.source_id, "path": record.path, "reason": "path_not_found"})
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for idx, chunk in enumerate(_chunk_text(text, chunk_chars=chunk_chars, overlap=overlap), start=1):
            chunk_id = f"{record.source_id}:{idx}"
            row = ChunkRow(
                chunk_id=chunk_id,
                source_id=record.source_id,
                url=record.url,
                path=record.path,
                content_hash=record.content_hash,
                text=chunk,
            )
            chunk_rows.append(row)
            tf: dict[str, int] = {}
            for tok in _tokenize(chunk):
                tf[tok] = tf.get(tok, 0) + 1
            for term, count in tf.items():
                postings.setdefault(term, {})[chunk_id] = count

    index_root.mkdir(parents=True, exist_ok=True)
    chunks_path = index_root / "raw_chunks.jsonl"
    if chunks_path.exists():
        chunks_path.unlink()
    for row in chunk_rows:
        _append_jsonl(chunks_path, asdict(row))

    _write_json_atomic(index_root / "raw_postings.json", postings)

    manifest = IndexManifest(
        version=INDEX_VERSION,
        source_ledger_hash=_source_fingerprint(records),
        source_count=len(records),
        chunk_count=len(chunk_rows),
        term_count=len(postings),
    )
    _write_json_atomic(index_root / "raw_index_manifest.json", asdict(manifest))

    build_report = {
        "status": "ok",
        "manifest": asdict(manifest),
        "invalid_sources": invalid_rows,
    }
    _write_json_atomic(index_root / "raw_index_build_report.json", build_report)
    return build_report


def query_raw_index(index_root: Path, source_rows: list[dict[str, Any]], request: QueryRequest) -> QueryResponse:
    manifest_path = index_root / "raw_index_manifest.json"
    postings_path = index_root / "raw_postings.json"
    chunks_path = index_root / "raw_chunks.jsonl"

    if not manifest_path.exists() or not postings_path.exists() or not chunks_path.exists():
        return QueryResponse(status="missing_index", reason="index_artifacts_missing", evidence=[], metadata={"index_root": str(index_root)})

    records, _invalid = _normalize_source_rows(source_rows)
    current_hash = _source_fingerprint(records)

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        postings = json.loads(postings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return QueryResponse(status="missing_index", reason="index_artifacts_malformed", evidence=[], metadata={"index_root": str(index_root)})

    if str(manifest.get("source_ledger_hash") or "") != current_hash:
        return QueryResponse(
            status="stale_index",
            reason="source_fingerprint_mismatch",
            evidence=[],
            metadata={"expected": current_hash, "actual": manifest.get("source_ledger_hash")},
        )

    tokens = _tokenize(request.query)
    if request.max_results <= 0:
        return QueryResponse(status="ok", reason=None, evidence=[], metadata={"bounded": True, "reason": "max_results_le_zero"})
    if not tokens:
        return QueryResponse(status="ok", reason=None, evidence=[], metadata={"bounded": True, "reason": "empty_query"})

    scores: dict[str, float] = {}
    for token in tokens:
        hits = postings.get(token) if isinstance(postings, dict) else None
        if not isinstance(hits, dict):
            continue
        for chunk_id, tf in hits.items():
            try:
                scores[str(chunk_id)] = scores.get(str(chunk_id), 0.0) + float(tf)
            except Exception:
                continue

    sorted_candidates = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    candidates_truncated = len(sorted_candidates) > request.max_candidates
    selected_candidates = sorted_candidates[: request.max_candidates]

    chunk_map: dict[str, dict[str, Any]] = {}
    for line in chunks_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and "chunk_id" in row:
            chunk_map[str(row["chunk_id"])] = row

    result_rows: list[QueryEvidenceRow] = []
    snippets_truncated = False
    for chunk_id, score in selected_candidates[: request.max_results]:
        row = chunk_map.get(chunk_id)
        if not row:
            continue
        snippet = str(row.get("text") or "").strip()
        if len(snippet) > request.snippet_chars:
            snippet = snippet[: request.snippet_chars].rstrip() + "..."
            snippets_truncated = True
        result_rows.append(
            QueryEvidenceRow(
                source_id=str(row.get("source_id") or ""),
                url=str(row.get("url") or ""),
                path=str(row.get("path") or ""),
                chunk_id=chunk_id,
                score=float(score),
                snippet=snippet,
            )
        )

    return QueryResponse(
        status="ok",
        reason=None,
        evidence=result_rows,
        metadata={
            "bounded": True,
            "candidates_truncated": candidates_truncated,
            "snippets_truncated": snippets_truncated,
            "max_results": request.max_results,
            "max_candidates": request.max_candidates,
            "snippet_chars": request.snippet_chars,
        },
    )
