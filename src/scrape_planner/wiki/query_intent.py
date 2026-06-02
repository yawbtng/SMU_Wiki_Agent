from __future__ import annotations

import re
from dataclasses import dataclass


LEADERSHIP_HINTS = (
    "director",
    "chair",
    "dean",
    "head of",
    "program director",
    "coordinator",
    "who is",
    "who's",
    "whos",
)

NETWORKING_ALIASES = (
    "network engineering",
    "ms-network-engineering",
    "ece",
    "eets",
    "lyle school of engineering",
    "electrical and computer engineering",
)


@dataclass(frozen=True)
class RetrievalQueryPlan:
    original: str
    effective: str
    expansions: tuple[str, ...]
    person_lookup: bool
    leadership_query: bool


def is_person_lookup_query(query: str) -> bool:
    lower = re.sub(r"\s+", " ", str(query or "").strip().lower())
    if not lower:
        return False
    if re.search(r"\bwho\b", lower):
        return True
    return any(term in lower for term in LEADERSHIP_HINTS)


def is_leadership_query(query: str) -> bool:
    lower = re.sub(r"\s+", " ", str(query or "").strip().lower())
    return any(term in lower for term in LEADERSHIP_HINTS)


def prepare_retrieval_query(query: str) -> RetrievalQueryPlan:
    original = re.sub(r"\s+", " ", str(query or "").strip())
    lower = original.lower()
    expansions: list[str] = []
    effective = original
    person_lookup = is_person_lookup_query(original)
    leadership_query = is_leadership_query(original)

    if re.search(r"\bnetworking\b", lower) and "network engineering" not in lower:
        if leadership_query or person_lookup or re.search(r"\b(program|major|degree|ms|m\.s)\b", lower):
            effective = re.sub(r"\bnetworking\b", "network engineering", effective, flags=re.IGNORECASE)
            expansions.extend(NETWORKING_ALIASES)

    if leadership_query and re.search(r"\bsmu\b", lower) and "lyle" not in lower:
        expansions.append("lyle school of engineering")

    if expansions:
        extra = " ".join(term for term in expansions if term.lower() not in lower)
        if extra:
            effective = f"{effective} {extra}".strip()

    return RetrievalQueryPlan(
        original=original,
        effective=effective,
        expansions=tuple(expansions),
        person_lookup=person_lookup,
        leadership_query=leadership_query,
    )
