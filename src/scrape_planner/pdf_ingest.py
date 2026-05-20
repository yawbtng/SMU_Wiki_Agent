from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .pdf_contracts import PdfChunkRow, PdfQuarantineRow, PdfSourceRow, utc_now_iso


@dataclass(frozen=True)
class PdfIngestConfig:
    max_size_bytes: int = 25 * 1024 * 1024
    min_meaningful_chars: int = 80
    ocr_like_char_threshold: int = 8
    chunk_size: int = 1200
    chunk_overlap: int = 200


@dataclass
class PdfIngestResult:
    sources: list[PdfSourceRow]
    chunks: list[PdfChunkRow]
    quarantine: list[PdfQuarantineRow]


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
            markdown = _parse_pdf_with_docling(path).strip()
        except PdfParserUnavailableError:
            raise
        except Exception as exc:
            quarantine.append(
                PdfQuarantineRow(source_id, str(path), "parse_failed", str(exc), utc_now_iso())
            )
            sources.append(PdfSourceRow(source_id, str(path), size, None, False, utc_now_iso()))
            continue

        total_chars = _meaningful_chars(markdown)
        reason = _classify_low_text(total_chars, 1, cfg)
        if reason is not None:
            quarantine.append(
                PdfQuarantineRow(
                    source_id,
                    str(path),
                    reason,
                    f"meaningful_chars={total_chars} pages=1",
                    utc_now_iso(),
                )
            )
            sources.append(PdfSourceRow(source_id, str(path), size, 1, False, utc_now_iso()))
            continue

        sources.append(PdfSourceRow(source_id, str(path), size, 1, True, utc_now_iso()))
        for chunk_index, chunk_text in enumerate(_chunk_text(markdown, cfg), start=0):
            chunk_id = _chunk_id(source_id, 1, chunk_index, chunk_text)
            chunks.append(
                PdfChunkRow(
                    chunk_id=chunk_id,
                    pdf_source_id=source_id,
                    page_number=1,
                    chunk_index=chunk_index,
                    text=chunk_text,
                    char_count=len(chunk_text),
                    created_at=utc_now_iso(),
                    parser="docling",
                    source_path=str(path),
                )
            )

    return PdfIngestResult(sources=sources, chunks=chunks, quarantine=quarantine)


def _parse_pdf_with_docling(path: Path) -> str:
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise PdfParserUnavailableError("Docling is not installed. Install requirements-pdf.txt.") from exc

    converter = DocumentConverter()
    result = converter.convert(str(path))
    document = getattr(result, "document", None)
    if document is None:
        raise RuntimeError("Docling returned no document")
    if not hasattr(document, "export_to_markdown"):
        raise RuntimeError("Docling document cannot export markdown")
    return str(document.export_to_markdown() or "")


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
