from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.scrape_planner.storage import write_json
from src.scrape_planner.zvec_index import chunks, load_index_docs


def test_load_index_docs_prefers_raw_scrape_and_pdf_sources(tmp_path: Path) -> None:
    run_root = tmp_path / "data" / "sites" / "www.example.edu" / "run-1"
    markdown_dir = run_root / "markdown"
    markdown_dir.mkdir(parents=True)
    raw_md = markdown_dir / "page.md"
    raw_md.write_text("Raw scraped page text", encoding="utf-8")
    write_json(
        run_root / "scrape_manifest.json",
        [{"status": "success", "url": "https://www.example.edu/about", "markdown_path": str(raw_md)}],
    )

    s05 = run_root / "s05"
    s05.mkdir()
    (s05 / "pdf_sources.jsonl").write_text(
        json.dumps({"pdf_source_id": "pdf-1", "path": str(tmp_path / "catalog.pdf"), "accepted": True}) + "\n",
        encoding="utf-8",
    )
    (s05 / "pdf_chunks.jsonl").write_text(
        json.dumps({"chunk_id": "chunk-1", "pdf_source_id": "pdf-1", "text": "PDF catalog text"}) + "\n",
        encoding="utf-8",
    )

    docs = load_index_docs(run_root, ingest_uploaded_pdfs=False)

    assert {doc.source_kind for doc in docs} == {"raw_scrape", "pdf"}
    assert any(doc.url == "https://www.example.edu/about" and doc.text == "Raw scraped page text" for doc in docs)
    assert any(doc.source_kind == "pdf" and doc.title == "catalog.pdf" and doc.text == "PDF catalog text" for doc in docs)


def test_chunks_overlap() -> None:
    assert chunks("abcdef", chunk_chars=4, overlap=2) == ["abcd", "cdef"]


def test_uploaded_pdf_materialization_preserves_existing_downloaded_pdf_chunks(tmp_path: Path, monkeypatch) -> None:
    run_root = tmp_path / "data" / "sites" / "www.example.edu" / "run-1"
    s05 = run_root / "s05"
    s05.mkdir(parents=True)
    (s05 / "pdf_sources.jsonl").write_text(
        json.dumps({"pdf_source_id": "downloaded", "path": "downloaded.pdf", "accepted": True}) + "\n",
        encoding="utf-8",
    )
    (s05 / "pdf_chunks.jsonl").write_text(
        json.dumps({"chunk_id": "downloaded-c1", "pdf_source_id": "downloaded", "text": "Downloaded PDF text"}) + "\n",
        encoding="utf-8",
    )

    upload_path = tmp_path / "uploaded.pdf"
    upload_path.write_bytes(b"%PDF-1.7")
    write_json(run_root.parent / "sources" / "pdf_manifest.json", [{"path": str(upload_path)}])

    class Source:
        def to_dict(self):
            return {"pdf_source_id": "uploaded", "path": str(upload_path), "accepted": True}

    class Chunk:
        def to_dict(self):
            return {"chunk_id": "uploaded-c1", "pdf_source_id": "uploaded", "text": "Uploaded PDF text"}

    monkeypatch.setattr(
        "src.scrape_planner.zvec_index.ingest_pdfs",
        lambda paths, config: SimpleNamespace(sources=[Source()], chunks=[Chunk()], quarantine=[]),
    )

    docs = load_index_docs(run_root, ingest_uploaded_pdfs=True)

    assert {doc.source_id for doc in docs if doc.source_kind == "pdf"} == {"downloaded-c1", "uploaded-c1"}
    assert {doc.text for doc in docs if doc.source_kind == "pdf"} == {"Downloaded PDF text", "Uploaded PDF text"}
