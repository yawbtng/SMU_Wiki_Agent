#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import requests


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return rows
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _openrouter_embed(text: str, *, model: str, base_url: str, api_key: str) -> list[float]:
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is required for embeddings")
    resp = requests.post(
        f"{base_url.rstrip('/')}/embeddings",
        json={"model": model, "input": text},
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    rows = data.get("data") or []
    if rows and isinstance(rows[0], dict) and "embedding" in rows[0]:
        return [float(v) for v in rows[0]["embedding"]]
    if "embedding" in data:
        return [float(v) for v in data["embedding"]]
    raise ValueError("OpenRouter embedding response did not include an embedding")


def _chunks(text: str, *, chunk_chars: int = 1800, overlap: int = 200) -> list[str]:
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


def _load_wiki_docs(run_root: Path) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    wiki_root = run_root / "wiki"
    if wiki_root.exists():
        for path in sorted(wiki_root.rglob("*.md")):
            docs.append({"url": "", "title": path.stem, "path": str(path), "text": path.read_text(encoding="utf-8", errors="replace")})
    return docs


def _load_pdf_chunk_docs(run_root: Path) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for row in _read_jsonl(run_root / "s05" / "pdf_chunks.jsonl"):
        text = str(row.get("text") or "")
        source_path = str(row.get("source_path") or "").strip()
        if not text.strip() or not source_path:
            continue
        try:
            page_number = int(row.get("page_number") or 0)
            chunk_index = int(row.get("chunk_index") or 0)
        except (TypeError, ValueError):
            continue

        filename = Path(source_path).name
        if page_number > 0:
            title = f"{filename} page {page_number}"
            path = f"{source_path}#page={page_number}&chunk={chunk_index}"
        else:
            title = filename
            path = f"{source_path}#chunk={chunk_index}"
        docs.append({"url": "", "title": title, "path": path, "text": text})
    return docs


def _load_docs_for_indexing(run_root: Path) -> list[dict[str, str]]:
    return _load_wiki_docs(run_root) + _load_pdf_chunk_docs(run_root)


def _create_schema(zvec: Any, *, dimension: int) -> Any:
    return zvec.CollectionSchema(
        name="smu_wiki",
        fields=[
            zvec.FieldSchema(name="text", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(name="title", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(name="url", data_type=zvec.DataType.STRING),
            zvec.FieldSchema(name="path", data_type=zvec.DataType.STRING),
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Index wiki markdown and PDF chunks into Zvec with OpenRouter embeddings.")
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--model", default="openai/text-embedding-3-small")
    parser.add_argument("--openrouter-base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--openrouter-api-key", default="")
    parser.add_argument("--chunk-chars", type=int, default=1800)
    args = parser.parse_args()

    try:
        import zvec
    except Exception as exc:
        raise SystemExit(f"zvec is not installed. Install with: pip install zvec. Error: {exc}")

    run_root = args.run_root.resolve()
    db_path = (args.db or (run_root / "zvec_index")).resolve()
    docs = _load_docs_for_indexing(run_root)
    if not docs:
        raise SystemExit(f"No wiki markdown or PDF chunks found under {run_root}")

    first_text = docs[0]["text"][: args.chunk_chars]
    api_key = args.openrouter_api_key or __import__("os").getenv("OPENROUTER_API_KEY", "")
    first_embedding = _openrouter_embed(first_text, model=args.model, base_url=args.openrouter_base_url, api_key=api_key)
    schema = _create_schema(zvec, dimension=len(first_embedding))
    collection = zvec.create_and_open(path=str(db_path), schema=schema)

    zdocs = []
    count = 0
    for doc in docs:
        for idx, chunk in enumerate(_chunks(doc["text"], chunk_chars=args.chunk_chars), start=1):
            embedding = first_embedding if count == 0 else _openrouter_embed(chunk, model=args.model, base_url=args.openrouter_base_url, api_key=api_key)
            doc_id = hashlib.sha1(f"{doc['path']}:{idx}".encode("utf-8")).hexdigest()
            zdocs.append(
                zvec.Doc(
                    id=doc_id,
                    vectors={"embedding": embedding},
                    fields={"text": chunk, "title": doc["title"], "url": doc["url"], "path": doc["path"]},
                )
            )
            count += 1
            if len(zdocs) >= 64:
                collection.upsert(zdocs) if hasattr(collection, "upsert") else collection.insert(zdocs)
                zdocs = []
    if zdocs:
        collection.upsert(zdocs) if hasattr(collection, "upsert") else collection.insert(zdocs)
    collection.optimize()
    out = {"db_path": str(db_path), "docs": len(docs), "chunks": count, "embedding_model": args.model, "dimension": len(first_embedding)}
    (run_root / "zvec_index_manifest.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
