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


def test_load_docs_for_indexing_keeps_markdown_and_pdf_docs(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    md_dir = run_root / "wiki"
    md_dir.mkdir(parents=True)
    (md_dir / "admissions.md").write_text("Admissions markdown page", encoding="utf-8")

    s05 = run_root / "s05"
    s05.mkdir(parents=True)
    (s05 / "pdf_chunks.jsonl").write_text(
        json.dumps(
            {
                "chunk_id": "pdf1-p0002-c0001-def",
                "pdf_source_id": "pdf1",
                "page_number": 2,
                "chunk_index": 1,
                "text": "Tuition PDF chunk",
                "char_count": 17,
                "created_at": "2026-05-20T00:00:00+00:00",
                "parser": "docling",
                "source_path": "/tmp/tuition.pdf",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    docs = _load_docs_for_indexing(run_root)

    assert [doc["title"] for doc in docs] == ["admissions", "tuition.pdf page 2"]
    assert [doc["text"] for doc in docs] == ["Admissions markdown page", "Tuition PDF chunk"]
