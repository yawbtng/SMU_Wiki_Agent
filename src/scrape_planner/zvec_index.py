from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests

from .pdf_ingest import PdfIngestConfig, ingest_pdfs
from .storage import read_json, write_json


@dataclass(frozen=True)
class IndexDoc:
    source_kind: str
    source_id: str
    title: str
    url: str
    path: str
    text: str


def ollama_embed(text: str, *, model: str, base_url: str) -> list[float]:
    payload = {"model": model, "prompt": text}
    resp = requests.post(f"{base_url.rstrip('/')}/api/embeddings", json=payload, timeout=120)
    if resp.status_code == 404:
        resp = requests.post(f"{base_url.rstrip('/')}/api/embed", json={"model": model, "input": text}, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    if "embedding" in data:
        return [float(v) for v in data["embedding"]]
    embeddings = data.get("embeddings") or []
    if embeddings:
        return [float(v) for v in embeddings[0]]
    raise ValueError("ollama embedding response did not include an embedding")


def chunks(text: str, *, chunk_chars: int = 1800, overlap: int = 200) -> list[str]:
    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not cleaned:
        return []
    out: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + chunk_chars)
        chunk = cleaned[start:end].strip()
        if chunk:
            out.append(chunk)
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return out


def load_index_docs(run_root: Path, *, ingest_uploaded_pdfs: bool = True) -> list[IndexDoc]:
    run_root = run_root.resolve()
    docs: list[IndexDoc] = []
    docs.extend(_load_raw_scrape_docs(run_root))
    docs.extend(_load_wiki_docs(run_root))
    docs.extend(_load_pdf_chunk_docs(run_root, ingest_uploaded_pdfs=ingest_uploaded_pdfs))
    return _dedupe_docs(docs)


def build_zvec_index(
    run_root: Path,
    *,
    db_path: Path | None = None,
    model: str = "nomic-embed-text:latest",
    ollama_base_url: str = "http://localhost:11434",
    chunk_chars: int = 1800,
    embed_fn: Callable[[str], list[float]] | None = None,
) -> dict[str, Any]:
    try:
        import zvec
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "zvec is not installed. Use Python 3.10+ and install optional dependencies with: "
            "pip install -r requirements-mcp.txt. "
            f"Error: {exc}"
        ) from exc

    run_root = run_root.resolve()
    db_path = (db_path or (run_root / "zvec_index")).resolve()
    docs = load_index_docs(run_root)
    if not docs:
        raise ValueError(f"No raw scrape, wiki, or PDF docs found under {run_root}")

    embed = embed_fn or (lambda text: ollama_embed(text, model=model, base_url=ollama_base_url))
    first_text = docs[0].text[:chunk_chars]
    first_embedding = embed(first_text)
    schema = _create_schema(zvec, dimension=len(first_embedding))
    collection = zvec.create_and_open(path=str(db_path), schema=schema)

    zdocs = []
    count = 0
    by_kind: dict[str, int] = {}
    for doc in docs:
        by_kind[doc.source_kind] = by_kind.get(doc.source_kind, 0) + 1
        for idx, chunk in enumerate(chunks(doc.text, chunk_chars=chunk_chars), start=1):
            embedding = first_embedding if count == 0 else embed(chunk)
            doc_id = hashlib.sha1(f"{doc.source_kind}:{doc.source_id}:{idx}".encode("utf-8")).hexdigest()
            zdocs.append(
                zvec.Doc(
                    id=doc_id,
                    vectors={"embedding": embedding},
                    fields={
                        "text": chunk,
                        "title": doc.title,
                        "url": doc.url,
                        "path": doc.path,
                        "source_kind": doc.source_kind,
                        "source_id": doc.source_id,
                    },
                )
            )
            count += 1
            if len(zdocs) >= 64:
                _write_docs(collection, zdocs)
                zdocs = []
    if zdocs:
        _write_docs(collection, zdocs)
    collection.optimize()

    out = {
        "db_path": str(db_path),
        "docs": len(docs),
        "chunks": count,
        "docs_by_kind": by_kind,
        "embedding_model": model,
        "dimension": len(first_embedding),
    }
    write_json(run_root / "zvec_index_manifest.json", out)
    return out


def _load_raw_scrape_docs(run_root: Path) -> list[IndexDoc]:
    manifest = read_json(run_root / "scrape_manifest.json", [])
    docs: list[IndexDoc] = []
    for row in manifest if isinstance(manifest, list) else []:
        if not isinstance(row, dict) or row.get("status") != "success":
            continue
        path = Path(str(row.get("markdown_path") or ""))
        if not path.exists():
            continue
        url = str(row.get("url") or "")
        docs.append(
            IndexDoc(
                source_kind="raw_scrape",
                source_id=_stable_source_id("raw_scrape", str(path), url),
                title=_title_from_path_or_url(path, url),
                url=url,
                path=str(path),
                text=path.read_text(encoding="utf-8", errors="replace"),
            )
        )
    return docs


def _load_wiki_docs(run_root: Path) -> list[IndexDoc]:
    wiki_root = run_root / "wiki"
    docs: list[IndexDoc] = []
    if not wiki_root.exists():
        return docs
    for path in sorted(wiki_root.rglob("*.md")):
        docs.append(
            IndexDoc(
                source_kind="wiki",
                source_id=_stable_source_id("wiki", str(path), ""),
                title=path.stem,
                url="",
                path=str(path),
                text=path.read_text(encoding="utf-8", errors="replace"),
            )
        )
    return docs


def _load_pdf_chunk_docs(run_root: Path, *, ingest_uploaded_pdfs: bool) -> list[IndexDoc]:
    if ingest_uploaded_pdfs:
        _materialize_uploaded_pdf_chunks(run_root)
    chunks_path = run_root / "s05" / "pdf_chunks.jsonl"
    source_rows = {
        str(row.get("pdf_source_id")): row
        for row in _read_jsonl(run_root / "s05" / "pdf_sources.jsonl")
        if isinstance(row, dict)
    }
    docs: list[IndexDoc] = []
    for row in _read_jsonl(chunks_path):
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        source_id = str(row.get("pdf_source_id") or "")
        source = source_rows.get(source_id, {})
        path = str(source.get("path") or "")
        title = Path(path).name if path else f"PDF {source_id}"
        docs.append(
            IndexDoc(
                source_kind="pdf",
                source_id=str(row.get("chunk_id") or _stable_source_id("pdf", source_id, text[:80])),
                title=title,
                url="",
                path=path,
                text=text,
            )
        )
    return docs


def _materialize_uploaded_pdf_chunks(run_root: Path) -> None:
    sources_root = run_root.parent / "sources"
    pre_extracted = sources_root / "pdf_ingest"
    s05 = run_root / "s05"
    if (pre_extracted / "pdf_sources.jsonl").exists() or (pre_extracted / "pdf_chunks.jsonl").exists():
        _merge_jsonl(s05 / "pdf_sources.jsonl", _read_jsonl(pre_extracted / "pdf_sources.jsonl"), key="pdf_source_id")
        _merge_jsonl(s05 / "pdf_chunks.jsonl", _read_jsonl(pre_extracted / "pdf_chunks.jsonl"), key="chunk_id")
        _merge_jsonl(s05 / "pdf_quarantine.jsonl", _read_jsonl(pre_extracted / "pdf_quarantine.jsonl"), key="pdf_source_id")
        return

    manifest_path = sources_root / "pdf_manifest.json"
    manifest = read_json(manifest_path, [])
    paths = [row.get("path") for row in manifest if isinstance(row, dict) and row.get("path")]
    if not paths:
        return
    result = ingest_pdfs([Path(str(path)) for path in paths], PdfIngestConfig())
    _merge_jsonl(s05 / "pdf_sources.jsonl", [row.to_dict() for row in result.sources], key="pdf_source_id")
    _merge_jsonl(s05 / "pdf_chunks.jsonl", [row.to_dict() for row in result.chunks], key="chunk_id")
    _merge_jsonl(s05 / "pdf_quarantine.jsonl", [row.to_dict() for row in result.quarantine], key="pdf_source_id")


def _create_schema(zvec: Any, *, dimension: int) -> Any:
    return zvec.CollectionSchema(
        name="smu_wiki",
        fields=[
            zvec.FieldSchema(name="text", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(name="title", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(name="url", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(name="path", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(name="source_kind", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(name="source_id", data_type=zvec.DataType.STRING),
        ],
        vectors=[
            zvec.VectorSchema(
                name="embedding",
                data_type=zvec.DataType.VECTOR_FP32,
                dimension=dimension,
                index_param=zvec.HnswIndexParam(metric_type=zvec.MetricType.COSINE),
            )
        ],
    )


def _write_docs(collection: Any, docs: list[Any]) -> None:
    collection.upsert(docs) if hasattr(collection, "upsert") else collection.insert(docs)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=True) + "\n" for row in rows), encoding="utf-8")


def _merge_jsonl(path: Path, rows: list[dict[str, Any]], *, key: str) -> None:
    merged = {str(row.get(key) or ""): row for row in _read_jsonl(path) if row.get(key)}
    for row in rows:
        row_key = str(row.get(key) or "")
        if row_key:
            merged[row_key] = row
    _write_jsonl(path, list(merged.values()))


def _dedupe_docs(docs: list[IndexDoc]) -> list[IndexDoc]:
    seen: set[tuple[str, str]] = set()
    out: list[IndexDoc] = []
    for doc in docs:
        key = (doc.source_kind, doc.source_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(doc)
    return out


def _stable_source_id(*parts: str) -> str:
    return hashlib.sha1(":".join(parts).encode("utf-8")).hexdigest()


def _title_from_path_or_url(path: Path, url: str) -> str:
    parsed = url.rsplit("/", 1)[-1].strip() if url else ""
    return parsed or path.stem
