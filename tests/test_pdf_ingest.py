from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.scrape_planner.pdf.pdf_ingest import (
    ParsedPdf,
    PdfIngestConfig,
    PdfParserUnavailableError,
    _parse_pdf_with_markitdown,
    ingest_pdfs,
)


def test_empty_input_returns_no_rows(tmp_path: Path) -> None:
    result = ingest_pdfs([])
    assert result.sources == []
    assert result.chunks == []
    assert result.quarantine == []


def test_nonexistent_file_is_malformed(tmp_path: Path) -> None:
    result = ingest_pdfs([tmp_path / "missing.pdf"])
    assert len(result.quarantine) == 1
    assert result.quarantine[0].reason == "malformed"


def test_too_large_boundary(tmp_path: Path) -> None:
    p = tmp_path / "big.pdf"
    p.write_bytes(b"0" * 11)
    result = ingest_pdfs([p], PdfIngestConfig(max_size_bytes=10))
    assert result.quarantine[0].reason == "too_large"


def test_markitdown_parse_failure_is_recorded_without_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_path = tmp_path / "bad.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")

    def fail_markitdown(_path: Path) -> str:
        raise RuntimeError("markitdown could not parse")

    monkeypatch.setattr("src.scrape_planner.pdf.pdf_ingest._parse_pdf_with_markitdown", fail_markitdown)

    result = ingest_pdfs([pdf_path])

    assert result.chunks == []
    assert result.sources[0].accepted is False
    assert result.sources[0].page_count is None
    assert result.quarantine[0].reason == "parse_failed"
    assert "markitdown could not parse" in result.quarantine[0].detail


def test_markitdown_empty_output_is_low_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_path = tmp_path / "empty.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")

    monkeypatch.setattr("src.scrape_planner.pdf.pdf_ingest._parse_pdf_with_markitdown", lambda _path: ParsedPdf("", 1))

    result = ingest_pdfs([pdf_path], PdfIngestConfig(min_meaningful_chars=20, ocr_like_char_threshold=-1))

    assert result.chunks == []
    assert result.sources[0].accepted is False
    assert result.sources[0].page_count == 1
    assert result.quarantine[0].reason == "low_text"
    assert "pages=1" in result.quarantine[0].detail


def test_markitdown_happy_path_chunks_deterministically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_path = tmp_path / "ok.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")
    markdown = "# Catalog\n\n" + "Admissions requirements and tuition information for students. " * 6

    monkeypatch.setattr("src.scrape_planner.pdf.pdf_ingest._parse_pdf_with_markitdown", lambda _path: ParsedPdf(markdown, 1))

    cfg = PdfIngestConfig(chunk_size=80, chunk_overlap=20, min_meaningful_chars=10)
    r1 = ingest_pdfs([pdf_path], cfg)
    r2 = ingest_pdfs([pdf_path], cfg)

    assert r1.quarantine == []
    assert r1.sources[0].accepted is True
    assert r1.sources[0].page_count == 1
    assert all(c.page_number == 0 for c in r1.chunks)
    assert all(c.pdf_source_id == r1.sources[0].pdf_source_id for c in r1.chunks)
    assert [c.text for c in r1.chunks] == [c.text for c in r2.chunks]
    assert [c.chunk_id for c in r1.chunks] == [c.chunk_id for c in r2.chunks]


def test_markitdown_page_count_is_preserved_for_page_level_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "multi.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")

    monkeypatch.setattr(
        "src.scrape_planner.pdf.pdf_ingest._parse_pdf_with_markitdown",
        lambda _path: ParsedPdf(
            "# Catalog\n\n" + "Admissions requirements and tuition information for students. " * 4,
            2,
            "markitdown",
            [
                (1, "# Catalog Page 1\n\n" + "Admissions requirements and tuition information for students. " * 3),
                (2, "# Catalog Page 2\n\n" + "Admissions requirements and tuition information for students. " * 3),
            ],
        ),
    )

    result = ingest_pdfs([pdf_path], PdfIngestConfig(min_meaningful_chars=20))

    assert result.quarantine == []
    assert result.sources[0].page_count == 2
    assert {chunk.page_number for chunk in result.chunks} == {1, 2}


def test_missing_markitdown_raises_setup_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_path = tmp_path / "ok.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")
    real_import = __import__

    def block_markitdown(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("markitdown"):
            raise ImportError("no markitdown")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", block_markitdown)

    with pytest.raises(PdfParserUnavailableError, match="MarkItDown is not installed"):
        ingest_pdfs([pdf_path])


def test_pdf_chunks_include_markitdown_parser_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_path = tmp_path / "catalog.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")

    monkeypatch.setattr(
        "src.scrape_planner.pdf.pdf_ingest._parse_pdf_with_markitdown",
        lambda _path: ParsedPdf("# Catalog\n\nAdmissions requirements and tuition information for students.", None),
    )

    result = ingest_pdfs([pdf_path], PdfIngestConfig(min_meaningful_chars=20))

    assert result.quarantine == []
    assert result.chunks[0].parser == "markitdown"
    assert result.chunks[0].source_path == str(pdf_path)


def test_markitdown_parser_splits_pages_for_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_path = tmp_path / "catalog.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")

    class FakeMarkItDown:
        def __init__(self, *, enable_plugins: bool) -> None:
            assert enable_plugins is False

        def convert(self, path: str) -> object:
            assert path == str(pdf_path)
            return SimpleNamespace(markdown="Page one admissions.\n\nPage two tuition.")

    class FakePage:
        def __init__(self, text: str) -> None:
            self.text = text
            self.closed = False

        def extract_text(self) -> str:
            return self.text

        def close(self) -> None:
            self.closed = True

    class FakePdf:
        def __init__(self) -> None:
            self.pages = [FakePage("Page one admissions."), FakePage("Page two tuition.")]

        def __enter__(self) -> "FakePdf":
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("markitdown.MarkItDown", FakeMarkItDown)
    monkeypatch.setattr("pdfplumber.open", lambda _path: FakePdf())

    parsed = _parse_pdf_with_markitdown(pdf_path)

    assert parsed.page_count == 2
    assert parsed.pages == [(1, "Page one admissions."), (2, "Page two tuition.")]
    assert parsed.markdown == "Page one admissions.\n\nPage two tuition."
