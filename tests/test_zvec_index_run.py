from __future__ import annotations

import json
from pathlib import Path

from scripts.zvec_index_run import _load_docs_for_indexing


def test_load_docs_for_indexing_includes_pdf_chunks(tmp_path: Path) -> None:
    chunks_path = tmp_path / "s05" / "pdf_chunks.jsonl"
    chunks_path.parent.mkdir(parents=True)
    pdf_path = tmp_path / "catalog.pdf"
    chunks = [
        {
            "source_path": str(pdf_path),
            "page_number": 3,
            "chunk_index": 5,
            "text": "Admissions requirements for first-year students.",
        },
        {
            "source_path": str(pdf_path),
            "page_number": 0,
            "chunk_index": 6,
            "text": "Document-level catalog introduction.",
        },
    ]
    chunks_path.write_text("\n".join(json.dumps(chunk) for chunk in chunks), encoding="utf-8")

    docs = _load_docs_for_indexing(tmp_path)

    assert docs == [
        {
            "url": "",
            "title": "catalog.pdf page 3",
            "path": f"{pdf_path}#page=3&chunk=5",
            "text": "Admissions requirements for first-year students.",
        },
        {
            "url": "",
            "title": "catalog.pdf",
            "path": f"{pdf_path}#chunk=6",
            "text": "Document-level catalog introduction.",
        },
    ]


def test_load_docs_for_indexing_skips_bad_pdf_chunk_rows(tmp_path: Path) -> None:
    chunks_path = tmp_path / "s05" / "pdf_chunks.jsonl"
    chunks_path.parent.mkdir(parents=True)
    pdf_path = tmp_path / "catalog.pdf"
    rows = [
        json.dumps({"source_path": str(pdf_path), "page_number": 1, "chunk_index": 0, "text": "Valid text."}),
        "",
        "not json",
        json.dumps(["not", "a", "dict"]),
        json.dumps({"source_path": str(pdf_path), "page_number": 2, "chunk_index": 1, "text": ""}),
        json.dumps({"source_path": "", "page_number": 2, "chunk_index": 2, "text": "Missing source."}),
    ]
    chunks_path.write_text("\n".join(rows), encoding="utf-8")

    docs = _load_docs_for_indexing(tmp_path)

    assert docs == [
        {
            "url": "",
            "title": "catalog.pdf page 1",
            "path": f"{pdf_path}#page=1&chunk=0",
            "text": "Valid text.",
        }
    ]
