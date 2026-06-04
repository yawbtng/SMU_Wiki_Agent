from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _deterministic_llm_wiki_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use deterministic dense-shaped embeddings so tests do not call OpenRouter."""

    def _embed_text(text: str, *_args: object, **_kwargs: object) -> list[float]:
        vector = [0.0] * 1536
        for token in re.findall(r"[a-z0-9]+", str(text).lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % len(vector)
            sign = 1.0 if digest[4] % 2 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if not norm:
            return vector
        return [round(value / norm, 6) for value in vector]

    monkeypatch.setattr(
        "src.scrape_planner.wiki.llm_wiki_index.embed_text",
        _embed_text,
    )
    monkeypatch.setattr(
        "src.scrape_planner.wiki.llm_wiki_index.embed_texts",
        lambda texts, *_args, **_kwargs: [_embed_text(text) for text in texts],
    )
    monkeypatch.setattr(
        "src.scrape_planner.index.zvec_store._load_zvec_module",
        lambda: _FakeZvec,
    )
    try:
        from src.scrape_planner.wiki import llm_wiki_index as index_module

        index_module._reset_embedding_backend_state()
    except Exception:
        pass


class _FakeZvec:
    class DataType:
        STRING = "string"
        VECTOR_FP32 = "vector_fp32"

    class MetricType:
        COSINE = "cosine"

    class HnswIndexParam:
        def __init__(self, *, metric_type: str) -> None:
            self.metric_type = metric_type

    class FieldSchema:
        def __init__(self, *, name: str, data_type: str) -> None:
            self.name = name
            self.data_type = data_type

    class VectorSchema:
        def __init__(self, *, name: str, data_type: str, dimension: int, index_param: object) -> None:
            self.name = name
            self.data_type = data_type
            self.dimension = dimension
            self.index_param = index_param

    class CollectionSchema:
        def __init__(self, *, name: str, fields: list[object], vectors: list[object]) -> None:
            self.name = name
            self.fields = fields
            self.vectors = vectors

    class VectorQuery:
        def __init__(self, *, field_name: str, vector: list[float]) -> None:
            self.field_name = field_name
            self.vector = vector

    class Doc:
        def __init__(self, *, id: str, fields: dict[str, object], vectors: dict[str, list[float]]) -> None:
            self.id = id
            self.fields = fields
            self.vectors = vectors

    @staticmethod
    def create_and_open(*, path: str, schema: object | None) -> "_FakeCollection":
        return _FakeCollection(Path(path), reset=schema is not None)

    @staticmethod
    def open(*, path: str) -> "_FakeCollection":
        return _FakeCollection(Path(path), reset=False)


class _FakeCollection:
    def __init__(self, path: Path, *, reset: bool) -> None:
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)
        if reset:
            self._write([])

    def upsert(self, docs: list[_FakeZvec.Doc]) -> None:
        existing = {str(row.get("id") or ""): row for row in self._read()}
        for doc in docs:
            existing[str(doc.id)] = {"id": doc.id, "fields": doc.fields, "vectors": doc.vectors}
        self._write(list(existing.values()))

    insert = upsert
    add_documents = upsert

    def optimize(self) -> None:
        return None

    def close(self) -> None:
        return None

    def query(self, *, vectors: _FakeZvec.VectorQuery, topk: int) -> list[SimpleNamespace]:
        scored: list[tuple[float, dict[str, object]]] = []
        for row in self._read():
            row_vectors = row.get("vectors") if isinstance(row.get("vectors"), dict) else {}
            vector = row_vectors.get(vectors.field_name) if isinstance(row_vectors, dict) else None
            score = _cosine(vectors.vector, vector)
            if score <= 0:
                continue
            scored.append((score, row))
        return [
            SimpleNamespace(
                score=score,
                doc=SimpleNamespace(id=row.get("id"), fields=row.get("fields") if isinstance(row.get("fields"), dict) else {}),
            )
            for score, row in sorted(scored, key=lambda item: (-item[0], str(item[1].get("id") or "")))[:topk]
        ]

    def _path(self) -> Path:
        return self.path / "fake_zvec_docs.json"

    def _read(self) -> list[dict[str, object]]:
        path = self._path()
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []

    def _write(self, rows: list[dict[str, object]]) -> None:
        self._path().write_text(json.dumps(rows), encoding="utf-8")


def _cosine(left: list[float], right: object) -> float:
    if not isinstance(right, list) or len(left) != len(right):
        return 0.0
    total = 0.0
    for left_value, right_value in zip(left, right):
        try:
            total += float(left_value) * float(right_value)
        except (TypeError, ValueError):
            continue
    return max(0.0, total)
