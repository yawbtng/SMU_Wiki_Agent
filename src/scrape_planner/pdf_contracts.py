from __future__ import annotations

from dataclasses import dataclass

from .core.time import utc_now_iso


@dataclass(frozen=True)
class PdfSourceRow:
    pdf_source_id: str
    path: str
    size_bytes: int
    page_count: int | None
    accepted: bool
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "pdf_source_id": self.pdf_source_id,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "page_count": self.page_count,
            "accepted": self.accepted,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class PdfChunkRow:
    chunk_id: str
    pdf_source_id: str
    page_number: int
    chunk_index: int
    text: str
    char_count: int
    created_at: str
    parser: str = "docling"
    source_path: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "pdf_source_id": self.pdf_source_id,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "char_count": self.char_count,
            "created_at": self.created_at,
            "parser": self.parser,
            "source_path": self.source_path,
        }


@dataclass(frozen=True)
class PdfQuarantineRow:
    pdf_source_id: str
    path: str
    reason: str
    detail: str
    quarantined_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "pdf_source_id": self.pdf_source_id,
            "path": self.path,
            "reason": self.reason,
            "detail": self.detail,
            "quarantined_at": self.quarantined_at,
        }
