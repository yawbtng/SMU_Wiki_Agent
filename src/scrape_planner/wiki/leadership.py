from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LeadershipMatch:
    name: str
    role: str
    answer: str
    source_path: str
    source_id: str
    title: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "answer": self.answer,
            "source_path": self.source_path,
            "source_id": self.source_id,
            "title": self.title,
            "confidence": self.confidence,
        }


_NAME = r"[A-Z][A-Za-z\.\-]+(?:[ \t]+[A-Z][A-Za-z\.\-]*){1,4}"
_CREDENTIAL = r"(?:Eng\.D\.|Ph\.D\.|M\.S\.|Ed\.D\.|M\.D\.)"
_ROLE_TITLE = r"Program Director|Department Chair|Chairperson|Director|Chair|Dean|Head"
_ENDOWED_TITLE_PREFIX = r"(?:(?:[A-Z][A-Za-z0-9\.\-']+|Jr\.?|JR\.?|H\.)\s+){0,8}"

_LEADERSHIP_LINE = re.compile(
    rf"(?P<name>{_NAME}),?\s*"
    rf"(?:{_CREDENTIAL}\s*)?"
    r"(?:[—\-–]\s*)?"
    rf"{_ENDOWED_TITLE_PREFIX}"
    rf"(?<!Associate\s)(?P<title>{_ROLE_TITLE})\s+"
    r"(?:of\s+)?"
    r"(?P<role>[^\n.;]{3,120})",
    re.IGNORECASE,
)

_ROLE_FIRST = re.compile(
    rf"(?<!Associate\s)(?P<title>{_ROLE_TITLE})\s+"
    r"(?:of\s+)?(?P<role>[^\n.;]{3,120})[:\s]+"
    rf"(?P<name>{_NAME})",
    re.IGNORECASE,
)

_SOCIAL_NETWORKING = re.compile(
    r"\b(career\s+networking|social\s+networking|networking\s+event|happy\s+hour|alumni\s+networking)\b",
    re.IGNORECASE,
)
_NEXT_PERSON_MARKER = re.compile(r"\s+[A-Z][A-Za-z\.\-]+(?:[ \t]+[A-Z][A-Za-z\.\-]*){1,4},?\s+(?:Eng\.D\.|Ph\.D\.|M\.S\.|Ed\.D\.|M\.D\.)")


def _evidence_text(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "")
    snippet = str(item.get("snippet") or "")
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    body = str(metadata.get("text") or metadata.get("body") or "")
    return f"{title}\n{snippet}\n{body}".strip()


def _clean_role(role: str) -> str:
    role = _NEXT_PERSON_MARKER.split(role, maxsplit=1)[0]
    return role.strip(" \t,;:-")


def leadership_text_boost(query: str, title: str, text: str) -> tuple[float, list[str]]:
    haystack = f"{title}\n{text}"
    if _SOCIAL_NETWORKING.search(haystack):
        return -0.6, ["social_networking_penalty"]
    boost = 0.0
    reasons: list[str] = []
    if _LEADERSHIP_LINE.search(haystack) or _ROLE_FIRST.search(haystack):
        boost += 1.1
        reasons.append("leadership_pattern_boost")
    lower = query.lower()
    if "network engineering" in lower or "network-engineering" in haystack.lower():
        if re.search(r"\bnetwork\s+engineering\b", haystack, re.IGNORECASE):
            boost += 0.5
            reasons.append("network_engineering_match")
    if any(term in lower for term in ("director", "chair", "dean", "who")):
        if re.search(r"\bdirector\b", haystack, re.IGNORECASE):
            boost += 0.25
            reasons.append("director_term_match")
    return boost, reasons


def extract_leadership_from_evidence(
    question: str,
    evidence: list[Any],
    *,
    max_items: int = 8,
) -> LeadershipMatch | None:
    del question  # reserved for future intent filters
    best: LeadershipMatch | None = None
    for item in evidence[:max_items]:
        if not isinstance(item, dict):
            continue
        haystack = _evidence_text(item)
        if _SOCIAL_NETWORKING.search(haystack):
            continue
        for pattern in (_LEADERSHIP_LINE, _ROLE_FIRST):
            match = pattern.search(haystack)
            if not match:
                continue
            name = str(match.group("name") or "").strip()
            role = _clean_role(str(match.group("role") or ""))
            if len(name.split()) < 2 or len(role) < 8:
                continue
            title = str(match.group("title") or "").strip()
            if pattern is _LEADERSHIP_LINE:
                answer = f"{name} is {title} of {role}."
            else:
                answer = f"{name} — {title} of {role}."
            candidate = LeadershipMatch(
                name=name,
                role=role,
                answer=answer,
                source_path=str(item.get("path") or ""),
                source_id=str(item.get("source_id") or ""),
                title=str(item.get("title") or ""),
                confidence=0.85,
            )
            if best is None or candidate.confidence > best.confidence:
                best = candidate
            break
    return best
