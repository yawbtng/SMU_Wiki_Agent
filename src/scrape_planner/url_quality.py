from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


HIGH_VALUE_PATTERNS = (
    "admission",
    "academics",
    "catalog",
    "course",
    "degree",
    "major",
    "program",
    "financial-aid",
    "scholarship",
    "tuition",
    "cost",
    "student-life",
    "housing",
    "dining",
    "career",
    "registrar",
    "records",
    "transcript",
    "commencement",
    "graduation",
    "apply",
    "visit",
    "calendar",
    "library",
    "international",
    "study-abroad",
    "health",
    "counseling",
    "parking",
    "orientation",
    "graduate",
    "undergraduate",
)

SPAMMY_PATTERNS = (
    "search",
    "tag/",
    "category/",
    "filter",
    "login",
    "signin",
    "sso",
    "auth",
    "feed",
    "rss",
    "xmlrpc",
    "ajax",
    "print",
    "archive",
    "legacy",
    "staging",
    "page/",
    "author/",
    "donor",
    "giving",
    "gift",
    "alumni",
    "trustee",
    "annual-report",
    "annualreport",
)

DATED_PATTERNS = (
    r"/20\d{2}/\d{2}/\d{2}/",
    r"/news/\d{4}/\d{2}",
    r"/calendar/\d{4}/\d{2}",
    r"/event/\d{4}-\d{2}-\d{2}",
    r"/course(?:s|descriptions)?/(?:fall|spring)-20\d{2}",
    r"/course-schedule/(?:fall|spring)-20\d{2}",
    r"/crime-log/",
)


@dataclass(frozen=True)
class UrlCriteria:
    include_text: str = ""
    exclude_text: str = ""
    include_hosts: tuple[str, ...] = ()
    max_urls: int = 500
    threshold: int = 70
    include_pdfs: bool = True


def host_from_url(url: str) -> str:
    return urlparse(str(url or "")).netloc.lower()


def _path_blob(url: str) -> str:
    parsed = urlparse(str(url or ""))
    return f"{parsed.netloc}{parsed.path}?{parsed.query}".lower()


def _contains_any(blob: str, terms: tuple[str, ...]) -> bool:
    return any(term and term.lower() in blob for term in terms)


def _split_terms(value: str) -> tuple[str, ...]:
    return tuple(term.strip().lower() for term in re.split(r"[,\n]", value or "") if term.strip())


def _freshness_score(lastmod: Any, target_year: int) -> int:
    if not lastmod:
        return 50
    try:
        parsed = datetime.fromisoformat(str(lastmod).replace("Z", "+00:00"))
    except Exception:
        return 50
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - parsed).days
    if parsed.year >= target_year:
        return 95 if age_days <= 180 else 85
    if parsed.year == target_year - 1:
        return 75
    if parsed.year == target_year - 2:
        return 60
    return 35


def score_url_row(row: dict[str, Any], *, target_year: int | None = None) -> dict[str, Any]:
    target_year = target_year or datetime.now(timezone.utc).year
    url = str(row.get("url") or "")
    blob = _path_blob(url)
    content_guess = str(row.get("content_type_guess") or "").lower()
    is_pdf = urlparse(url).path.lower().endswith(".pdf") or "pdf" in content_guess

    student_value = 45
    scrape_value = 55
    source_quality = 80 if ".edu" in host_from_url(url) else 65
    freshness = _freshness_score(row.get("lastmod"), target_year)
    reasons: list[str] = []

    if _contains_any(blob, HIGH_VALUE_PATTERNS):
        student_value += 30
        scrape_value += 15
        reasons.append("student info")
    if is_pdf:
        student_value += 12
        scrape_value += 8
        reasons.append("pdf/source document")
    if _contains_any(blob, SPAMMY_PATTERNS):
        student_value -= 35
        scrape_value -= 25
        reasons.append("spammy/noisy path")
    if any(re.search(pattern, blob, re.IGNORECASE) for pattern in DATED_PATTERNS):
        years = [int(year) for year in re.findall(r"20\d{2}", blob)]
        if not years or min(years) < target_year - 1:
            student_value -= 25
            scrape_value -= 20
            freshness = min(freshness, 35)
            reasons.append("dated archive")

    depth = len([part for part in urlparse(url).path.split("/") if part])
    if depth >= 6:
        scrape_value -= 10
        reasons.append("deep path")
    if row.get("source_sitemap") == "manual":
        student_value += 8
        source_quality += 5
        reasons.append("manual add")

    student_value = max(0, min(100, student_value))
    scrape_value = max(0, min(100, scrape_value))
    source_quality = max(0, min(100, source_quality))
    freshness = max(0, min(100, freshness))
    score = round(student_value * 0.45 + scrape_value * 0.25 + freshness * 0.20 + source_quality * 0.10)

    if not reasons:
        reasons.append("generic page")
    return {
        "url": url,
        "host": host_from_url(url),
        "score": int(max(0, min(100, score))),
        "reason": "; ".join(reasons),
        "student_value": student_value,
        "freshness": freshness,
        "source_quality": source_quality,
        "scrape_value": scrape_value,
        "is_pdf": is_pdf,
        "spammy": any(part in reasons for part in ("spammy/noisy path", "dated archive")),
    }


def score_and_filter_rows(rows: list[dict[str, Any]], criteria: UrlCriteria) -> tuple[list[dict[str, Any]], dict[str, int]]:
    include_terms = _split_terms(criteria.include_text)
    exclude_terms = _split_terms(criteria.exclude_text)
    include_hosts = {host.lower() for host in criteria.include_hosts if host}
    scored: list[dict[str, Any]] = []
    counts = {"total": 0, "filtered": 0, "selected": 0, "spammy": 0, "pdfs": 0}

    for row in rows:
        if not isinstance(row, dict):
            continue
        counts["total"] += 1
        quality = score_url_row(row)
        blob = _path_blob(quality["url"])
        if include_hosts and quality["host"] not in include_hosts:
            counts["filtered"] += 1
            continue
        if include_terms and not _contains_any(blob, include_terms):
            counts["filtered"] += 1
            continue
        if exclude_terms and _contains_any(blob, exclude_terms):
            counts["filtered"] += 1
            continue
        if quality["is_pdf"]:
            counts["pdfs"] += 1
            if not criteria.include_pdfs:
                counts["filtered"] += 1
                continue

        merged = {**row, **quality}
        merged["selected"] = int(quality["score"]) >= int(criteria.threshold)
        if merged["selected"]:
            counts["selected"] += 1
        if quality["spammy"]:
            counts["spammy"] += 1
        scored.append(merged)

    scored.sort(key=lambda item: (bool(item.get("selected")), int(item.get("score") or 0)), reverse=True)
    if criteria.max_urls > 0:
        selected_count = 0
        for row in scored:
            if row.get("selected"):
                selected_count += 1
                if selected_count > criteria.max_urls:
                    row["selected"] = False
                    row["reason"] = f"{row.get('reason', '')}; over max URL cap".strip("; ")
        counts["selected"] = min(counts["selected"], criteria.max_urls)
    return scored, counts
