from __future__ import annotations

import json
import os
import hashlib
import shutil
import time
from pathlib import Path
from typing import Any

from ..core.site_layout import site_layout

COLLECTION_NAME = "llm_wiki_documents"
VECTOR_FIELD = "embedding"
COLLECTION_DIRNAME = "zvec_llm_wiki"
MANIFEST_FILENAME = "zvec_llm_wiki_manifest.json"


class ZvecStoreUnavailable(RuntimeError):
    """Raised when the zvec dense store cannot be opened or queried."""


def zvec_collection_path(site_root: Path) -> Path:
    return site_layout(Path(site_root)).indexes_dir / COLLECTION_DIRNAME


def zvec_manifest_path(site_root: Path) -> Path:
    return site_layout(Path(site_root)).indexes_dir / MANIFEST_FILENAME


def zvec_ready(site_root: Path) -> dict[str, Any]:
    path = zvec_collection_path(site_root)
    manifest_path = zvec_manifest_path(site_root)
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            manifest = payload
    ready = bool(manifest.get("ready")) and path.exists()
    return {
        "backend": "zvec",
        "ready": ready,
        "path": str(path),
        "manifest_path": str(manifest_path),
        "collection": COLLECTION_NAME,
        "documents": int(manifest.get("documents") or 0),
        "vector_dimensions": int(manifest.get("vector_dimensions") or 0),
        "error": "" if ready else str(manifest.get("error") or "zvec_collection_missing"),
    }


def replace_zvec_documents(
    site_root: Path,
    rows: list[dict[str, Any]],
    *,
    dimensions: int,
    zvec_module: Any | None = None,
) -> dict[str, Any]:
    layout = site_layout(Path(site_root))
    target = zvec_collection_path(layout.site_root)
    manifest_path = zvec_manifest_path(layout.site_root)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    vector_rows = [_zvec_row(row, dimensions=dimensions) for row in rows]
    vector_rows = [row for row in vector_rows if row is not None]
    if rows and len(vector_rows) != len(rows):
        raise ZvecStoreUnavailable("not all index rows have dense vectors with the expected dimensions")
    if not vector_rows:
        _remove_managed_path(target, layout.indexes_dir)
        manifest = _manifest(
            target,
            manifest_path,
            documents=0,
            dimensions=dimensions,
            ready=False,
            error="empty_index",
        )
        _write_json(manifest_path, manifest)
        return manifest

    zvec = zvec_module or _load_zvec_module()
    temp_path = target.with_name(f"{target.name}.tmp-{os.getpid()}-{int(time.time() * 1000)}")
    _remove_managed_path(temp_path, layout.indexes_dir)
    try:
        schema = _create_schema(zvec, dimensions=dimensions)
        collection = zvec.create_and_open(path=str(temp_path), schema=schema)
        _insert_documents(collection, zvec, vector_rows)
        if hasattr(collection, "optimize"):
            collection.optimize()
        _close_collection(collection)
        _replace_managed_path(temp_path, target, layout.indexes_dir)
    except Exception as exc:
        _remove_managed_path(temp_path, layout.indexes_dir)
        if isinstance(exc, ZvecStoreUnavailable):
            raise
        raise ZvecStoreUnavailable(f"zvec build failed: {exc}") from exc

    manifest = _manifest(
        target,
        manifest_path,
        documents=len(vector_rows),
        dimensions=dimensions,
        ready=True,
        error="",
    )
    _write_json(manifest_path, manifest)
    return manifest


def query_zvec_documents(
    site_root: Path,
    vector: list[float],
    *,
    top_k: int,
    zvec_module: Any | None = None,
) -> list[dict[str, Any]]:
    path = zvec_collection_path(site_root)
    if not path.exists():
        raise ZvecStoreUnavailable(f"zvec collection missing at {path}")
    zvec = zvec_module or _load_zvec_module()
    try:
        collection = _open_collection(path, zvec)
        result = collection.query(vectors=zvec.VectorQuery(field_name=VECTOR_FIELD, vector=vector), topk=int(top_k))
    except Exception as exc:
        raise ZvecStoreUnavailable(f"zvec query failed: {exc}") from exc
    return _format_results(result)


def _load_zvec_module() -> Any:
    try:
        import zvec
    except Exception as exc:
        raise ZvecStoreUnavailable("zvec is not installed. Install MCP/vector dependencies with requirements-mcp.txt.") from exc
    return zvec


def _create_schema(zvec: Any, *, dimensions: int) -> Any:
    return zvec.CollectionSchema(
        name=COLLECTION_NAME,
        fields=[
            zvec.FieldSchema(name="id", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(name="corpus", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(name="source_kind", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(name="source_id", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(name="source_ids", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(name="path", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(name="title", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(name="checksum", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(name="text", data_type=zvec.DataType.STRING),
        ],
        vectors=[
            zvec.VectorSchema(
                name=VECTOR_FIELD,
                data_type=zvec.DataType.VECTOR_FP32,
                dimension=dimensions,
                index_param=zvec.HnswIndexParam(metric_type=zvec.MetricType.COSINE),
            )
        ],
    )


def _zvec_row(row: dict[str, Any], *, dimensions: int) -> dict[str, Any] | None:
    vector = row.get("embedding_vector")
    if not isinstance(vector, list) or len(vector) != dimensions:
        return None
    doc_id = str(row.get("id") or "")
    if not doc_id:
        return None
    return {
        "id": doc_id,
        "zvec_id": _zvec_doc_id(doc_id),
        "vector": [float(value) for value in vector],
        "fields": {
            "id": _zvec_string(doc_id),
            "corpus": _zvec_string(row.get("corpus") or ""),
            "source_kind": _zvec_string(row.get("source_kind") or ""),
            "source_id": _zvec_string(row.get("source_id") or ""),
            "source_ids": _zvec_string(json.dumps([str(value) for value in row.get("source_ids", []) or [] if str(value)], ensure_ascii=True)),
            "path": _zvec_string(row.get("path") or ""),
            "title": _zvec_string(row.get("title") or ""),
            "checksum": _zvec_string(row.get("checksum") or ""),
            "text": _zvec_string(row.get("text") or ""),
        },
    }


def _insert_documents(collection: Any, zvec: Any, rows: list[dict[str, Any]]) -> None:
    batch: list[Any] = []
    for row in rows:
        batch.append(zvec.Doc(id=row["zvec_id"], fields=row["fields"], vectors={VECTOR_FIELD: row["vector"]}))
        if len(batch) >= 128:
            _write_batch(collection, batch)
            batch = []
    if batch:
        _write_batch(collection, batch)


def _write_batch(collection: Any, batch: list[Any]) -> None:
    if hasattr(collection, "upsert"):
        collection.upsert(batch)
    elif hasattr(collection, "insert"):
        collection.insert(batch)
    elif hasattr(collection, "add_documents"):
        collection.add_documents(batch)
    else:
        raise ZvecStoreUnavailable("zvec collection does not expose upsert, insert, or add_documents")


def _open_collection(path: Path, zvec: Any) -> Any:
    if hasattr(zvec, "open"):
        return zvec.open(path=str(path))
    return zvec.create_and_open(path=str(path), schema=None)


def _format_results(result: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in result or []:
        doc = getattr(item, "doc", item)
        fields = getattr(doc, "fields", {}) or {}
        score = getattr(item, "score", None)
        source_ids = _source_ids(fields.get("source_ids"))
        rows.append(
            {
                "id": str(fields.get("id") or getattr(doc, "id", "") or ""),
                "score": _float_score(score),
                "corpus": str(fields.get("corpus") or ""),
                "source_kind": str(fields.get("source_kind") or ""),
                "source_id": str(fields.get("source_id") or ""),
                "source_ids": source_ids,
                "path": str(fields.get("path") or ""),
                "title": str(fields.get("title") or ""),
                "checksum": str(fields.get("checksum") or ""),
                "text": str(fields.get("text") or ""),
            }
        )
    return rows


def _source_ids(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item)]
        return [value]
    return []


def _float_score(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _zvec_doc_id(value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8", errors="replace")).hexdigest()
    return f"d{digest}"


def _zvec_string(value: Any) -> str:
    text = str(value or "").encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    return "".join(char if char in {"\n", "\r", "\t"} or 32 <= ord(char) != 127 else " " for char in text)


def _manifest(
    path: Path,
    manifest_path: Path,
    *,
    documents: int,
    dimensions: int,
    ready: bool,
    error: str,
) -> dict[str, Any]:
    return {
        "backend": "zvec",
        "ready": bool(ready),
        "path": str(path),
        "manifest_path": str(manifest_path),
        "collection": COLLECTION_NAME,
        "documents": int(documents),
        "vector_dimensions": int(dimensions),
        "error": str(error or ""),
        "built_at_ms": int(time.time() * 1000),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp_path, path)


def _replace_managed_path(temp_path: Path, target: Path, indexes_dir: Path) -> None:
    _assert_managed_path(temp_path, indexes_dir)
    _assert_managed_path(target, indexes_dir)
    _remove_managed_path(target, indexes_dir)
    os.replace(temp_path, target)


def _remove_managed_path(path: Path, indexes_dir: Path) -> None:
    _assert_managed_path(path, indexes_dir)
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _assert_managed_path(path: Path, indexes_dir: Path) -> None:
    root = indexes_dir.resolve()
    try:
        resolved = path.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ZvecStoreUnavailable(f"refusing to modify unmanaged zvec path: {path}") from exc
    if not path.name.startswith(COLLECTION_DIRNAME):
        raise ZvecStoreUnavailable(f"refusing to modify unexpected zvec path: {path}")


def _close_collection(collection: Any) -> None:
    close = getattr(collection, "close", None)
    if callable(close):
        close()
