from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..pdf_contracts import PdfChunkRow, PdfQuarantineRow, PdfSourceRow, utc_now_iso


@dataclass(frozen=True)
class PdfIngestConfig:
    max_size_bytes: int = 25 * 1024 * 1024
    min_meaningful_chars: int = 80
    ocr_like_char_threshold: int = 8
    chunk_size: int = 1200
    chunk_overlap: int = 200
    page_markdown_dir: Path | None = None


@dataclass
class PdfIngestResult:
    sources: list[PdfSourceRow]
    chunks: list[PdfChunkRow]
    quarantine: list[PdfQuarantineRow]


@dataclass(frozen=True)
class ParsedPdf:
    markdown: str
    page_count: int | None
    parser: str = "markitdown"
    pages: list[tuple[int, str]] = field(default_factory=list)


class PdfParserUnavailableError(RuntimeError):
    """Raised when the only supported PDF parser cannot be imported."""


_WORD_RE = re.compile(r"[A-Za-z0-9]")


def ingest_pdfs(paths: list[str | Path], config: PdfIngestConfig | None = None) -> PdfIngestResult:
    cfg = config or PdfIngestConfig()
    sources: list[PdfSourceRow] = []
    chunks: list[PdfChunkRow] = []
    quarantine: list[PdfQuarantineRow] = []

    for raw in paths:
        path = Path(raw)
        source_id = _source_id(path)

        if not path.exists() or not path.is_file():
            quarantine.append(
                PdfQuarantineRow(
                    pdf_source_id=source_id,
                    path=str(path),
                    reason="malformed",
                    detail="File does not exist",
                    quarantined_at=utc_now_iso(),
                )
            )
            sources.append(
                PdfSourceRow(
                    pdf_source_id=source_id,
                    path=str(path),
                    size_bytes=0,
                    page_count=None,
                    accepted=False,
                    created_at=utc_now_iso(),
                )
            )
            continue

        size = path.stat().st_size
        if size > cfg.max_size_bytes:
            quarantine.append(
                PdfQuarantineRow(
                    pdf_source_id=source_id,
                    path=str(path),
                    reason="too_large",
                    detail=f"size_bytes={size} max_size_bytes={cfg.max_size_bytes}",
                    quarantined_at=utc_now_iso(),
                )
            )
            sources.append(PdfSourceRow(source_id, str(path), size, None, False, utc_now_iso()))
            continue

        try:
            parsed = _parse_pdf_with_markitdown(path)
            markdown = parsed.markdown.strip()
        except PdfParserUnavailableError:
            raise
        except Exception as exc:
            quarantine.append(
                PdfQuarantineRow(source_id, str(path), "parse_failed", str(exc), utc_now_iso())
            )
            sources.append(PdfSourceRow(source_id, str(path), size, None, False, utc_now_iso()))
            continue

        page_count = parsed.page_count
        page_count_for_classification = page_count if page_count is not None else 1
        page_count_detail = str(page_count) if page_count is not None else "unknown"
        total_chars = _meaningful_chars(markdown)
        reason = _classify_low_text(total_chars, page_count_for_classification, cfg)
        if reason is not None:
            quarantine.append(
                PdfQuarantineRow(
                    source_id,
                    str(path),
                    reason,
                    f"meaningful_chars={total_chars} pages={page_count_detail}",
                    utc_now_iso(),
                )
            )
            sources.append(PdfSourceRow(source_id, str(path), size, page_count, False, utc_now_iso()))
            continue

        sources.append(PdfSourceRow(source_id, str(path), size, page_count, True, utc_now_iso()))
        _write_page_markdown_files(source_id, path, parsed, cfg)
        chunk_pages = parsed.pages or [(0, markdown)]
        for page_number, page_markdown in chunk_pages:
            for chunk_index, chunk_text in enumerate(_chunk_text(str(page_markdown or ""), cfg), start=0):
                chunk_id = _chunk_id(source_id, int(page_number or 0), chunk_index, chunk_text)
                chunks.append(
                    PdfChunkRow(
                        chunk_id=chunk_id,
                        pdf_source_id=source_id,
                        page_number=int(page_number or 0),
                        chunk_index=chunk_index,
                        text=chunk_text,
                        char_count=len(chunk_text),
                        created_at=utc_now_iso(),
                        parser=parsed.parser,
                        source_path=str(path),
                    )
                )

    return PdfIngestResult(sources=sources, chunks=chunks, quarantine=quarantine)


def _parse_pdf_with_markitdown(path: Path) -> ParsedPdf:
    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise PdfParserUnavailableError("MarkItDown is not installed. Install requirements-pdf.txt.") from exc

    converter = MarkItDown(enable_plugins=False)
    result = converter.convert(str(path))
    markdown = _markitdown_text(result)
    if not markdown.strip():
        raise RuntimeError("MarkItDown returned no markdown")
    pages = _extract_pdf_pages(path)
    return ParsedPdf(
        markdown=markdown,
        page_count=len(pages) if pages else None,
        parser="markitdown",
        pages=pages or [(0, markdown)],
    )


def _markitdown_text(result: object) -> str:
    for attr in ("text_content", "markdown"):
        value = getattr(result, attr, None)
        if value is not None:
            return str(value)
    return str(result or "")


def _extract_pdf_pages(path: Path) -> list[tuple[int, str]]:
    try:
        import pdfplumber
    except ImportError:
        return []

    pages: list[tuple[int, str]] = []
    with pdfplumber.open(path) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            try:
                text = str(page.extract_text() or "").strip()
            finally:
                close = getattr(page, "close", None)
                if callable(close):
                    close()
            if text:
                pages.append((index, text))
    return pages


def _write_page_markdown_files(source_id: str, path: Path, parsed: ParsedPdf, cfg: PdfIngestConfig) -> None:
    if cfg.page_markdown_dir is None:
        return
    source_dir = cfg.page_markdown_dir / source_id
    source_dir.mkdir(parents=True, exist_ok=True)
    index_rows = []
    pages = parsed.pages or [(0, parsed.markdown)]
    for page_number, markdown in pages:
        if not str(markdown or "").strip():
            continue
        if page_number > 0:
            filename = f"page-{page_number:04d}.md"
        else:
            filename = "document.md"
        page_path = source_dir / filename
        page_path.write_text(str(markdown).strip() + "\n", encoding="utf-8")
        index_rows.append(
            {
                "pdf_source_id": source_id,
                "source_path": str(path),
                "page_number": page_number,
                "parser": parsed.parser,
                "markdown_path": str(page_path),
                "char_count": len(str(markdown)),
            }
        )
    if index_rows:
        (source_dir / "pages.json").write_text(json.dumps(index_rows, indent=2), encoding="utf-8")


def _source_id(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:16]


def _chunk_id(source_id: str, page_number: int, chunk_index: int, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{source_id}-p{page_number:04d}-c{chunk_index:04d}-{digest}"


def _meaningful_chars(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _classify_low_text(total_chars: int, page_count: int, cfg: PdfIngestConfig) -> str | None:
    if page_count == 0:
        return "malformed"
    if total_chars <= cfg.ocr_like_char_threshold:
        return "ocr_required"
    if total_chars < cfg.min_meaningful_chars:
        return "low_text"
    return None


def _chunk_text(text: str, cfg: PdfIngestConfig) -> list[str]:
    if not text:
        return []
    chunk_size = max(1, cfg.chunk_size)
    overlap = min(max(0, cfg.chunk_overlap), chunk_size - 1)
    step = chunk_size - overlap
    out: list[str] = []
    i = 0
    while i < len(text):
        out.append(text[i : i + chunk_size])
        i += step
    return out
