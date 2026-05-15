from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter

from src.scrape_planner.pdf_ingest import PdfIngestConfig, ingest_pdfs


def _make_pdf(path: Path, pages: list[str]) -> None:
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=300, height=300)
        if text:
            page.extract_text = lambda _text=text: _text  # type: ignore[attr-defined]
    with path.open("wb") as fh:
        writer.write(fh)


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


def test_malformed_bytes(tmp_path: Path) -> None:
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"not-a-pdf")
    result = ingest_pdfs([p])
    assert result.quarantine[0].reason == "malformed"


def test_encrypted_pdf_classified(tmp_path: Path) -> None:
    p = tmp_path / "enc.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("pw")
    with p.open("wb") as fh:
        writer.write(fh)

    result = ingest_pdfs([p])
    assert result.quarantine[0].reason == "encrypted"
    assert result.chunks == []


def test_low_text_and_ocr_required(tmp_path: Path, monkeypatch) -> None:
    p1 = tmp_path / "ocr.pdf"
    p2 = tmp_path / "low.pdf"
    p1.write_bytes(b"%PDF-1.7\n")
    p2.write_bytes(b"%PDF-1.7\n")

    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakeReader:
        def __init__(self, _path: str) -> None:
            self.is_encrypted = False
            if _path.endswith("ocr.pdf"):
                self.pages = [FakePage(" ")]
            else:
                self.pages = [FakePage("tiny text")]

    monkeypatch.setattr("src.scrape_planner.pdf_ingest.PdfReader", FakeReader)

    result = ingest_pdfs([p1, p2], PdfIngestConfig(min_meaningful_chars=20, ocr_like_char_threshold=2))
    reasons = {q.path.split("/")[-1]: q.reason for q in result.quarantine}
    assert reasons["ocr.pdf"] == "ocr_required"
    assert reasons["low.pdf"] == "low_text"


def test_happy_path_chunks_include_page_and_source_and_deterministic_ids(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "ok.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")

    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakeReader:
        is_encrypted = False

        def __init__(self, _path: str) -> None:
            self.pages = [FakePage("A" * 200), FakePage("B" * 200)]

    monkeypatch.setattr("src.scrape_planner.pdf_ingest.PdfReader", FakeReader)

    cfg = PdfIngestConfig(chunk_size=80, chunk_overlap=20, min_meaningful_chars=10)
    r1 = ingest_pdfs([pdf_path], cfg)
    r2 = ingest_pdfs([pdf_path], cfg)

    assert len(r1.quarantine) == 0
    assert r1.sources[0].accepted is True
    assert all(c.page_number in (1, 2) for c in r1.chunks)
    assert all(c.pdf_source_id == r1.sources[0].pdf_source_id for c in r1.chunks)
    assert [c.chunk_id for c in r1.chunks] == [c.chunk_id for c in r2.chunks]


def test_mixed_valid_invalid_batch(tmp_path: Path, monkeypatch) -> None:
    good = tmp_path / "good.pdf"
    bad = tmp_path / "bad.pdf"
    good.write_bytes(b"%PDF-1.7\n")
    bad.write_bytes(b"bad")

    class FakePage:
        def extract_text(self) -> str:
            return "This is enough meaningful text to pass threshold."

    class FakeReader:
        is_encrypted = False

        def __init__(self, path: str) -> None:
            if path.endswith("bad.pdf"):
                raise Exception("broken")
            self.pages = [FakePage()]

    monkeypatch.setattr("src.scrape_planner.pdf_ingest.PdfReader", FakeReader)

    result = ingest_pdfs([good, bad])
    assert any(s.accepted for s in result.sources)
    assert any(q.reason == "malformed" for q in result.quarantine)
