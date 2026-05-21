from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class ChunkQuality:
    quality: str
    flags: tuple[str, ...]
    reason: str
    context_label: str
    char_count: int


@dataclass(frozen=True)
class ChunkQualitySummary:
    readiness: str
    ready_for_retrieval: bool
    total: int
    good_count: int
    needs_review_count: int
    poor_count: int
    top_flags: tuple[str, ...]


FLAG_ORDER = (
    "too_short",
    "missing_section_context",
    "boilerplate",
    "likely_navigation",
    "duplicate_like",
    "table_fragment",
    "split_mid_sentence",
)

NAVIGATION_TERMS = {
    "apply",
    "apply now",
    "back",
    "contact",
    "contents",
    "home",
    "menu",
    "next",
    "previous",
    "search",
    "skip",
    "top",
}


def _normalize_section_path(section_path: Sequence[str] | str | None) -> tuple[str, ...]:
    if section_path is None:
        return ()
    if isinstance(section_path, str):
        parts = re.split(r"\s*(?:>|/|::)\s*", section_path)
    else:
        parts = [str(part) for part in section_path]
    return tuple(part.strip() for part in parts if part and str(part).strip())


def _is_duplicate_like(text: str) -> bool:
    lines = [line.strip().lower() for line in text.splitlines() if line.strip()]
    if len(lines) >= 4 and len(set(lines)) <= max(1, len(lines) // 2):
        return True
    words = re.findall(r"[a-z0-9']+", text.lower())
    if len(words) < 12:
        return False
    return len(set(words)) / len(words) < 0.38


def _is_table_fragment(text: str) -> bool:
    if "|" in text or "\t" in text:
        return True
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    numeric_lines = sum(1 for line in lines if len(re.findall(r"\d+", line)) >= 2)
    aligned_lines = sum(1 for line in lines if re.search(r"\S\s{2,}\S", line))
    return numeric_lines >= 2 or aligned_lines >= 2


def _is_boilerplate(text: str) -> bool:
    lowered = text.lower()
    if re.fullmatch(r"\s*page\s+\d+\s*", lowered):
        return True
    catalog_header = (
        "catalog" in lowered
        and re.search(r"\bpage\s+\d+\b", lowered) is not None
        and len(text) < 140
    )
    university_header = (
        "southern methodist university" in lowered
        and re.search(r"\b20\d{2}\b", lowered) is not None
        and len(text) < 180
    )
    return bool(catalog_header or university_header)


def _is_likely_navigation(text: str) -> bool:
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    words = [word for word in cleaned.split() if word]
    if not words:
        return False
    joined = " ".join(words)
    if joined in NAVIGATION_TERMS:
        return True
    nav_hits = sum(1 for term in NAVIGATION_TERMS if term in joined)
    return len(words) <= 12 and nav_hits >= 2


def _split_mid_sentence(text: str, previous_text: str, next_text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    starts_mid_sentence = bool(previous_text.strip()) and stripped[0].islower()
    ends_mid_sentence = bool(next_text.strip()) and stripped[-1:] in {",", ";", ":", "-", "("}
    return starts_mid_sentence or ends_mid_sentence


def classify_chunk_sample(
    text: str,
    source_title: str,
    section_path: Sequence[str] | str | None,
    previous_text: str = "",
    next_text: str = "",
) -> ChunkQuality:
    normalized_text = str(text or "").strip()
    sections = _normalize_section_path(section_path)
    char_count = len(normalized_text)
    word_count = len(re.findall(r"[A-Za-z0-9']+", normalized_text))

    flags: list[str] = []
    if char_count < 40 or word_count < 6:
        flags.append("too_short")
    if not sections:
        flags.append("missing_section_context")
    if _is_boilerplate(normalized_text):
        flags.append("boilerplate")
    if _is_likely_navigation(normalized_text):
        flags.append("likely_navigation")
    if _is_duplicate_like(normalized_text):
        flags.append("duplicate_like")
    if _is_table_fragment(normalized_text):
        flags.append("table_fragment")
    if _split_mid_sentence(normalized_text, previous_text, next_text):
        flags.append("split_mid_sentence")

    ordered_flags = tuple(flag for flag in FLAG_ORDER if flag in set(flags))
    if "too_short" in ordered_flags or len(ordered_flags) >= 3:
        quality = "poor"
    elif ordered_flags:
        quality = "needs_review"
    else:
        quality = "good"

    context_label = " > ".join(sections) if sections else str(source_title or "No section context")
    if quality == "good":
        reason = "Chunk has enough body text and source/section context for retrieval preview."
    elif quality == "poor":
        reason = "Chunk is too thin or fragmented to trust without review."
    else:
        reason = "Chunk has usable text but quality flags should be reviewed before retrieval."

    return ChunkQuality(
        quality=quality,
        flags=ordered_flags,
        reason=reason,
        context_label=context_label,
        char_count=char_count,
    )


def build_chunk_quality_summary(rows: Iterable[Mapping[str, Any]]) -> ChunkQualitySummary:
    samples = [
        classify_chunk_sample(
            text=str(row.get("text") or row.get("content") or ""),
            source_title=str(row.get("source_title") or row.get("title") or row.get("source_path") or "Untitled source"),
            section_path=row.get("section_path") or row.get("sections") or row.get("section") or [],
            previous_text=str(row.get("previous_text") or ""),
            next_text=str(row.get("next_text") or ""),
        )
        for row in rows
        if isinstance(row, Mapping)
    ]
    total = len(samples)
    good_count = sum(1 for sample in samples if sample.quality == "good")
    needs_review_count = sum(1 for sample in samples if sample.quality == "needs_review")
    poor_count = sum(1 for sample in samples if sample.quality == "poor")

    flag_counts: Counter[str] = Counter(flag for sample in samples for flag in sample.flags)
    top_flags = tuple(
        flag
        for flag, _count in sorted(
            flag_counts.items(),
            key=lambda item: (-item[1], FLAG_ORDER.index(item[0]) if item[0] in FLAG_ORDER else len(FLAG_ORDER)),
        )[:5]
    )

    if total == 0:
        readiness = "unknown"
        ready_for_retrieval = False
    elif poor_count or needs_review_count > max(1, total // 4):
        readiness = "needs_review"
        ready_for_retrieval = False
    else:
        readiness = "ready"
        ready_for_retrieval = True

    return ChunkQualitySummary(
        readiness=readiness,
        ready_for_retrieval=ready_for_retrieval,
        total=total,
        good_count=good_count,
        needs_review_count=needs_review_count,
        poor_count=poor_count,
        top_flags=top_flags,
    )
