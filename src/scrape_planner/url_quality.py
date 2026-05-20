from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


DEFAULT_HIGH_VALUE_TERMS = (
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

DEFAULT_SPAMMY_TERMS = (
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

DEFAULT_DATED_PATTERNS = (
    r"/20\d{2}/\d{2}/\d{2}/",
    r"/news/\d{4}/\d{2}",
    r"/calendar/\d{4}/\d{2}",
    r"/event/\d{4}-\d{2}-\d{2}",
    r"/course(?:s|descriptions)?/(?:fall|spring)-20\d{2}",
    r"/course-schedule/(?:fall|spring)-20\d{2}",
    r"/crime-log/",
)


def _coerce_terms(value: Any, default: tuple[str, ...], *, allow_empty: bool = False) -> tuple[str, ...]:
    if isinstance(value, str):
        terms = _split_terms(value)
    elif isinstance(value, (list, tuple)):
        terms = tuple(str(term).strip().lower() for term in value if str(term).strip())
    else:
        terms = ()
    if terms or allow_empty:
        return terms
    return default


def _coerce_patterns(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, str):
        patterns = tuple(line.strip() for line in value.splitlines() if line.strip())
    elif isinstance(value, (list, tuple)):
        patterns = tuple(str(pattern).strip() for pattern in value if str(pattern).strip())
    else:
        patterns = ()
    return patterns or default


@dataclass(frozen=True)
class UrlScoringProfile:
    high_value_terms: tuple[str, ...] = DEFAULT_HIGH_VALUE_TERMS
    spammy_terms: tuple[str, ...] = DEFAULT_SPAMMY_TERMS
    dated_patterns: tuple[str, ...] = DEFAULT_DATED_PATTERNS
    base_student_value: int = 45
    base_scrape_value: int = 55
    high_value_student_boost: int = 30
    high_value_scrape_boost: int = 15
    spammy_student_penalty: int = 35
    spammy_scrape_penalty: int = 25
    dated_student_penalty: int = 25
    dated_scrape_penalty: int = 20
    pdf_student_boost: int = 12
    pdf_scrape_boost: int = 8
    manual_student_boost: int = 50

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "UrlScoringProfile":
        data = data if isinstance(data, dict) else {}
        return cls(
            high_value_terms=_coerce_terms(data.get("high_value_terms"), DEFAULT_HIGH_VALUE_TERMS, allow_empty="high_value_terms" in data),
            spammy_terms=_coerce_terms(data.get("spammy_terms"), DEFAULT_SPAMMY_TERMS, allow_empty="spammy_terms" in data),
            dated_patterns=_coerce_patterns(data.get("dated_patterns"), DEFAULT_DATED_PATTERNS),
            base_student_value=int(data.get("base_student_value", 45) or 45),
            base_scrape_value=int(data.get("base_scrape_value", 55) or 55),
            high_value_student_boost=int(data.get("high_value_student_boost", 30) or 30),
            high_value_scrape_boost=int(data.get("high_value_scrape_boost", 15) or 15),
            spammy_student_penalty=int(data.get("spammy_student_penalty", 35) or 35),
            spammy_scrape_penalty=int(data.get("spammy_scrape_penalty", 25) or 25),
            dated_student_penalty=int(data.get("dated_student_penalty", 25) or 25),
            dated_scrape_penalty=int(data.get("dated_scrape_penalty", 20) or 20),
            pdf_student_boost=int(data.get("pdf_student_boost", 12) or 12),
            pdf_scrape_boost=int(data.get("pdf_scrape_boost", 8) or 8),
            manual_student_boost=int(data.get("manual_student_boost", 50) or 50),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "high_value_terms": list(self.high_value_terms),
            "spammy_terms": list(self.spammy_terms),
            "dated_patterns": list(self.dated_patterns),
            "base_student_value": self.base_student_value,
            "base_scrape_value": self.base_scrape_value,
            "high_value_student_boost": self.high_value_student_boost,
            "high_value_scrape_boost": self.high_value_scrape_boost,
            "spammy_student_penalty": self.spammy_student_penalty,
            "spammy_scrape_penalty": self.spammy_scrape_penalty,
            "dated_student_penalty": self.dated_student_penalty,
            "dated_scrape_penalty": self.dated_scrape_penalty,
            "pdf_student_boost": self.pdf_student_boost,
            "pdf_scrape_boost": self.pdf_scrape_boost,
            "manual_student_boost": self.manual_student_boost,
        }


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


def _path_segments(url: str) -> list[str]:
    parsed = urlparse(str(url or ""))
    segments: list[str] = []
    for raw in parsed.path.split("/"):
        part = raw.strip().lower()
        if not part:
            continue
        for token in re.split(r"[^a-z0-9-]+", part):
            token = token.strip("-")
            if len(token) >= 3:
                segments.append(token)
    return segments


def _term_seen(rows: list[dict[str, Any]], term: str) -> bool:
    needle = term.lower().strip()
    if not needle:
        return False
    normalized = needle.strip("/")
    for row in rows:
        blob = _path_blob(str(row.get("url") or ""))
        if needle in blob or normalized in blob:
            return True
    return False


def suggest_scoring_profile_from_rows(
    rows: list[dict[str, Any]],
    *,
    base_profile: UrlScoringProfile | None = None,
) -> UrlScoringProfile:
    base_profile = base_profile or UrlScoringProfile()
    valid_rows = [row for row in rows if isinstance(row, dict) and row.get("url")]
    if not valid_rows:
        return base_profile

    high_terms = [term for term in DEFAULT_HIGH_VALUE_TERMS if _term_seen(valid_rows, term)]
    spammy_terms = [term for term in DEFAULT_SPAMMY_TERMS if _term_seen(valid_rows, term)]

    segment_counts: dict[str, int] = {}
    for row in valid_rows:
        for segment in set(_path_segments(str(row.get("url") or ""))):
            segment_counts[segment] = segment_counts.get(segment, 0) + 1

    deny_segments = {term.strip("/").lower() for term in DEFAULT_SPAMMY_TERMS}
    deny_segments.update({"www", "edu", "html", "index", "page", "pages"})
    inferred_noise = [
        segment
        for segment, count in sorted(segment_counts.items(), key=lambda item: (-item[1], item[0]))
        if count >= max(3, len(valid_rows) // 200) and segment in deny_segments and segment not in spammy_terms
    ]
    spammy_terms.extend(inferred_noise)

    # Keep the editor useful: observed terms first, then preserve any custom terms the user already saved.
    high_terms = list(dict.fromkeys(high_terms + list(base_profile.high_value_terms)))
    spammy_terms = list(dict.fromkeys(spammy_terms + [term for term in base_profile.spammy_terms if _term_seen(valid_rows, term)]))

    return UrlScoringProfile.from_dict(
        {
            **base_profile.to_dict(),
            "high_value_terms": high_terms or list(base_profile.high_value_terms),
            "spammy_terms": spammy_terms,
        }
    )


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


def score_url_row(
    row: dict[str, Any],
    *,
    target_year: int | None = None,
    profile: UrlScoringProfile | None = None,
) -> dict[str, Any]:
    target_year = target_year or datetime.now(timezone.utc).year
    profile = profile or UrlScoringProfile()
    url = str(row.get("url") or "")
    blob = _path_blob(url)
    content_guess = str(row.get("content_type_guess") or "").lower()
    is_pdf = urlparse(url).path.lower().endswith(".pdf") or "pdf" in content_guess

    student_value = profile.base_student_value
    scrape_value = profile.base_scrape_value
    source_quality = 80 if ".edu" in host_from_url(url) else 65
    freshness = _freshness_score(row.get("lastmod"), target_year)
    reasons: list[str] = []

    if _contains_any(blob, profile.high_value_terms):
        student_value += profile.high_value_student_boost
        scrape_value += profile.high_value_scrape_boost
        reasons.append("student info")
    if is_pdf:
        student_value += profile.pdf_student_boost
        scrape_value += profile.pdf_scrape_boost
        reasons.append("pdf/source document")
    if _contains_any(blob, profile.spammy_terms):
        student_value -= profile.spammy_student_penalty
        scrape_value -= profile.spammy_scrape_penalty
        reasons.append("spammy/noisy path")
    if any(re.search(pattern, blob, re.IGNORECASE) for pattern in profile.dated_patterns):
        years = [int(year) for year in re.findall(r"20\d{2}", blob)]
        if not years or min(years) < target_year - 1:
            student_value -= profile.dated_student_penalty
            scrape_value -= profile.dated_scrape_penalty
            freshness = min(freshness, 35)
            reasons.append("dated archive")

    depth = len([part for part in urlparse(url).path.split("/") if part])
    if depth >= 6:
        scrape_value -= 10
        reasons.append("deep path")
    if row.get("source_sitemap") in {"manual", "seed"}:
        student_value += profile.manual_student_boost
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


def score_and_filter_rows(
    rows: list[dict[str, Any]],
    criteria: UrlCriteria,
    *,
    profile: UrlScoringProfile | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    profile = profile or UrlScoringProfile()
    include_terms = _split_terms(criteria.include_text)
    exclude_terms = _split_terms(criteria.exclude_text)
    include_hosts = {host.lower() for host in criteria.include_hosts if host}
    scored: list[dict[str, Any]] = []
    counts = {"total": 0, "filtered": 0, "selected": 0, "spammy": 0, "pdfs": 0}

    for row in rows:
        if not isinstance(row, dict):
            continue
        counts["total"] += 1
        quality = score_url_row(row, profile=profile)
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
