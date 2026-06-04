from __future__ import annotations

from pathlib import Path

import pytest

from src.scrape_planner.index.zvec_store import (
    ZvecStoreUnavailable,
    _zvec_doc_id,
    _zvec_string,
    query_zvec_documents,
    replace_zvec_documents,
    zvec_ready,
)


def test_replace_and_query_zvec_documents_persists_metadata(tmp_path: Path) -> None:
    site_root = tmp_path / "site"
    rows = [
        {
            "id": "wiki:admissions:1",
            "corpus": "wiki",
            "source_kind": "wiki",
            "source_id": "wiki/pages/admissions.md",
            "source_ids": ["web_admissions"],
            "path": "wiki/pages/admissions.md",
            "title": "Admissions",
            "checksum": "abc",
            "text": "The deadline is February 1.",
            "embedding_vector": [1.0, 0.0, 0.0],
        },
        {
            "id": "raw:web_admissions:1",
            "corpus": "raw",
            "source_kind": "web",
            "source_id": "web_admissions",
            "source_ids": ["web_admissions"],
            "path": "raw_sources/web/web_admissions.md",
            "title": "Admissions Raw",
            "checksum": "def",
            "text": "Raw admissions source.",
            "embedding_vector": [0.0, 1.0, 0.0],
        },
    ]

    report = replace_zvec_documents(site_root, rows, dimensions=3)
    hits = query_zvec_documents(site_root, [1.0, 0.0, 0.0], top_k=1)
    ready = zvec_ready(site_root)

    assert report["ready"] is True
    assert report["documents"] == 2
    assert ready["ready"] is True
    assert hits == [
        {
            "id": "wiki:admissions:1",
            "score": 1.0,
            "corpus": "wiki",
            "source_kind": "wiki",
            "source_id": "wiki/pages/admissions.md",
            "source_ids": ["web_admissions"],
            "path": "wiki/pages/admissions.md",
            "title": "Admissions",
            "checksum": "abc",
            "text": "The deadline is February 1.",
        }
    ]


def test_query_missing_zvec_collection_raises(tmp_path: Path) -> None:
    with pytest.raises(ZvecStoreUnavailable, match="zvec collection missing"):
        query_zvec_documents(tmp_path / "site", [1.0, 0.0], top_k=1)


def test_zvec_internal_ids_and_strings_are_storage_safe() -> None:
    assert _zvec_doc_id("raw:pdf_001cffd8128ae15d:1").startswith("d")
    assert ":" not in _zvec_doc_id("raw:pdf_001cffd8128ae15d:1")
    assert _zvec_string("ok\x00bad\x08") == "ok bad "
