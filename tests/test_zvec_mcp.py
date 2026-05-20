from __future__ import annotations

from types import SimpleNamespace

from mcp_servers.smu_zvec_mcp import query_zvec_index, zvec_index_info


class FakeZvec:
    class VectorQuery:
        def __init__(self, field_name, vector):
            self.field_name = field_name
            self.vector = vector


class FakeCollection:
    def __init__(self) -> None:
        self.seen_topk = None
        self.seen_vector = None

    def query(self, *, vectors, topk):
        self.seen_topk = topk
        self.seen_vector = vectors.vector
        return [
            SimpleNamespace(
                score=0.91,
                doc=SimpleNamespace(
                    fields={
                        "title": "Catalog",
                        "url": "https://example.edu/catalog.pdf",
                        "path": "/tmp/catalog.pdf",
                        "source_kind": "pdf",
                        "source_id": "chunk-1",
                        "text": "PDF catalog content",
                    }
                ),
            )
        ]


def test_query_zvec_index_formats_pdf_source_metadata() -> None:
    collection = FakeCollection()

    rows = query_zvec_index(
        "catalog",
        top_k=3,
        collection=collection,
        zvec_module=FakeZvec,
        embed_fn=lambda query: [1.0, 2.0],
    )

    assert collection.seen_topk == 3
    assert collection.seen_vector == [1.0, 2.0]
    assert rows == [
        {
            "score": 0.91,
            "title": "Catalog",
            "url": "https://example.edu/catalog.pdf",
            "path": "/tmp/catalog.pdf",
            "source_kind": "pdf",
            "source_id": "chunk-1",
            "text": "PDF catalog content",
        }
    ]


def test_zvec_index_info_is_importable_without_mcp_dependency() -> None:
    info = zvec_index_info()
    assert "db_path" in info
    assert info["embedding_model"]
