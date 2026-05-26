from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .source_registry import checksum_text


QUALITY_ACTIONS = {"approved", "cleaned", "quarantined", "needs_review"}
CONTACT_SIGNAL_RE = re.compile(
    r"\b(email|phone|contact|office|address|deadline|tuition|fee|cost|admission|admissions|\d{3}[-.\s]\d{3})\b",
    re.I,
)
REDIRECT_RE = re.compile(r"\b(redirecting|you are being redirected|click here if you are not redirected)\b", re.I)
PDF_OBJECT_RE = re.compile(r"\b(obj|endobj|xref|trailer|startxref)\b")
BOILERPLATE_PREFIXES = (
    "home",
    "about",
    "academics",
    "admission",
    "admissions",
    "apply",
    "search",
    "menu",
    "students",
    "faculty",
    "staff",
    "alumni",
    "contact",
    "privacy",
    "copyright",
)


@dataclass(frozen=True)
class SourceQualityRecord:
    source_id: str
    action: str
    reasons: list[str]
    word_count: int
    has_nul_byte: bool
    has_pdf_signature: bool
    has_pdf_object_stream: bool
    redirect_stub: bool
    boilerplate_ratio: float
    link_line_ratio: float
    checksum: str
    duplicate_checksum: bool
    parser_kind: str
    original_path: str
    original_url: str
    cleaned_text: str
    recommended_parser_route: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("cleaned_text", None)
        return payload


def assess_source_quality(
    text: str,
    *,
    source_id: str,
    parser_kind: str = "",
    original_path: str = "",
    original_url: str = "",
    seen_checksums: set[str] | None = None,
) -> SourceQualityRecord:
    checksum = checksum_text(text)
    lines = text.splitlines()
    word_count = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", text))
    has_nul = "\x00" in text
    stripped = text.lstrip()
    has_pdf_signature = stripped.startswith("%PDF")
    has_pdf_object_stream = bool(PDF_OBJECT_RE.search(text)) and ("stream" in text[:2000].lower() or has_pdf_signature)
    redirect_stub = _is_redirect_stub(text, word_count)
    boilerplate_ratio = _boilerplate_ratio(lines)
    link_line_ratio = _link_line_ratio(lines)
    duplicate_checksum = checksum in (seen_checksums or set())
    cleaned_text = strip_repeated_chrome(text)
    cleaned_word_count = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", cleaned_text))
    reasons: list[str] = []
    action = "approved"
    recommended_parser_route = parser_kind or "markdown"

    if has_nul:
        reasons.append("contains_nul_byte")
    if has_pdf_signature:
        reasons.append("starts_with_pdf_signature")
        recommended_parser_route = "pdf"
    if has_pdf_object_stream:
        reasons.append("contains_pdf_object_stream")
        recommended_parser_route = "pdf"
    if redirect_stub:
        reasons.append("redirect_stub")
    if duplicate_checksum:
        reasons.append("duplicate_checksum")

    if has_nul or has_pdf_signature or has_pdf_object_stream or redirect_stub:
        action = "quarantined"
    elif word_count <= 2 and not CONTACT_SIGNAL_RE.search(text):
        action = "needs_review"
        reasons.append("low_word_count")
    elif cleaned_word_count < word_count * 0.75 or boilerplate_ratio >= 0.3 or link_line_ratio >= 0.45:
        action = "cleaned"
        reasons.append("high_boilerplate_or_link_ratio")

    return SourceQualityRecord(
        source_id=source_id,
        action=action,
        reasons=reasons,
        word_count=word_count,
        has_nul_byte=has_nul,
        has_pdf_signature=has_pdf_signature,
        has_pdf_object_stream=has_pdf_object_stream,
        redirect_stub=redirect_stub,
        boilerplate_ratio=round(boilerplate_ratio, 4),
        link_line_ratio=round(link_line_ratio, 4),
        checksum=checksum,
        duplicate_checksum=duplicate_checksum,
        parser_kind=parser_kind,
        original_path=original_path,
        original_url=original_url,
        cleaned_text=cleaned_text,
        recommended_parser_route=recommended_parser_route,
    )


def strip_repeated_chrome(text: str) -> str:
    lines = text.splitlines()
    counts = Counter(_normalize_line(line) for line in lines if _normalize_line(line))
    kept: list[str] = []
    for line in lines:
        normalized = _normalize_line(line)
        if not normalized:
            kept.append(line)
            continue
        if counts[normalized] >= 3 and _looks_like_chrome_line(line):
            continue
        if _looks_like_chrome_line(line) and len(normalized.split()) <= 4:
            continue
        kept.append(line)
    cleaned = "\n".join(kept).strip()
    return cleaned + "\n" if cleaned else text


def summarize_quality_records(records: Iterable[SourceQualityRecord | dict[str, Any]]) -> dict[str, Any]:
    counts = {action: 0 for action in sorted(QUALITY_ACTIONS)}
    examples: dict[str, list[dict[str, Any]]] = {action: [] for action in sorted(QUALITY_ACTIONS)}
    for record in records:
        payload = record.to_dict() if isinstance(record, SourceQualityRecord) else dict(record)
        action = str(payload.get("action") or "needs_review")
        if action not in counts:
            action = "needs_review"
        counts[action] += 1
        if len(examples[action]) < 5:
            examples[action].append(
                {
                    "source_id": payload.get("source_id", ""),
                    "reasons": payload.get("reasons", []),
                    "original_url": payload.get("original_url", ""),
                    "original_path": payload.get("original_path", ""),
                }
            )
    return {"counts": counts, "examples": examples}


def write_quality_report(path: Path, *, generated_at: str, records: Iterable[SourceQualityRecord]) -> dict[str, Any]:
    rows = list(records)
    report = {
        "generated_at": generated_at,
        "summary": summarize_quality_records(rows),
        "sources": [row.to_dict() for row in rows],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_dump(report), encoding="utf-8")
    return report


def _json_dump(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def _is_redirect_stub(text: str, word_count: int) -> bool:
    lower = text.lower()
    if REDIRECT_RE.search(lower) and word_count <= 80:
        return True
    return bool("<meta" in lower and "refresh" in lower and word_count <= 120)


def _boilerplate_ratio(lines: list[str]) -> float:
    meaningful = [_normalize_line(line) for line in lines if _normalize_line(line)]
    if not meaningful:
        return 0.0
    chrome = sum(1 for line in meaningful if _looks_like_chrome_line(line))
    repeated = sum(1 for _, count in Counter(meaningful).items() if count >= 3)
    return min(1.0, (chrome + repeated) / max(1, len(meaningful)))


def _link_line_ratio(lines: list[str]) -> float:
    meaningful = [line.strip() for line in lines if line.strip()]
    if not meaningful:
        return 0.0
    link_like = sum(1 for line in meaningful if line.startswith(("-", "*")) and ("http" in line or "](" in line))
    return link_like / len(meaningful)


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip().lower())


def _looks_like_chrome_line(line: str) -> bool:
    if line.lstrip().startswith("#"):
        return False
    normalized = _normalize_line(line).strip("#*- ")
    if not normalized:
        return False
    if "@" in normalized or re.search(r"\d{3}[-.\s]\d{3}", normalized):
        return False
    if normalized.startswith(("skip to", "search", "menu", "copyright", "privacy")):
        return True
    if normalized in BOILERPLATE_PREFIXES:
        return True
    if " | " in normalized and sum(1 for part in normalized.split("|") if part.strip()) >= 4:
        return True
    return bool(re.fullmatch(r"(home|about|academics|admissions?|apply|search|menu)(\s+/\s+.*)?", normalized))


def _has_useful_short_signal(text: str) -> bool:
    return bool(CONTACT_SIGNAL_RE.search(text))
