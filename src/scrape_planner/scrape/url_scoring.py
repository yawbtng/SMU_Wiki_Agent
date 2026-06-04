from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from .url_policy import TARGET_YEAR, detect_dated_archive, parse_lastmod, score_freshness_from_lastmod

DEFAULT_THRESHOLD = 70

HIGH_VALUE_PATTERNS = (
    r"/admission",
    r"/academics",
    r"/catalog",
    r"/course",
    r"/degree",
    r"/major",
    r"/minor",
    r"/program",
    r"/financial-aid",
    r"/financialaid",
    r"/scholarship",
    r"/tuition",
    r"/registrar",
    r"/housing",
    r"/dining",
    r"dining",
    r"/student-life",
    r"/studentlife",
    r"/health",
    r"/counseling",
    r"/accessibility",
    r"/disability",
    r"/parking",
    r"/orientation",
    r"/apply",
    r"/calendar",
)

MEDIUM_VALUE_PATTERNS = (
    r"/about",
    r"/news",
    r"/press",
    r"/magazine",
    r"/blog",
    r"/story",
    r"/policy",
    r"/faq",
    r"/handbook",
)

NOISY_PATTERNS = (
    r"/search",
    r"/tag/",
    r"/login",
    r"/signin",
    r"/feed",
    r"/rss",
    r"/archive",
    r"/staging",
    r"/test",
    r"/demo",
)

VERY_HIGH_SIGNAL = (
    r"/admission$",
    r"/registrar$",
    r"/catalog$",
    r"/financial-aid$",
    r"/housing$",
)

VERY_LOW_SIGNAL = (
    r"/donor",
    r"/giving",
    r"/development",
    r"/advancement",
    r"/alumni",
    r"/president",
    r"/administration",
)


def score_url(url_item: dict[str, Any], *, target_year: int = TARGET_YEAR) -> dict[str, Any]:
    url = str(url_item.get("url") or "")
    path = urlparse(url).path.lower()
    lastmod_dt = parse_lastmod(url_item.get("lastmod"))

    student_value = 50
    freshness = score_freshness_from_lastmod(lastmod_dt, target_year)
    source_quality = 85 if url.endswith(".edu") or ".edu/" in url else 70
    scrape_value = 70
    dated_archive_reason = detect_dated_archive(url, target_year=target_year)

    noisy = any(re.search(pattern, url, re.IGNORECASE) for pattern in NOISY_PATTERNS)
    if noisy:
        scrape_value -= 30
        student_value -= 20

    very_low = any(re.search(pattern, url, re.IGNORECASE) for pattern in VERY_LOW_SIGNAL)
    if very_low:
        student_value -= 25
        scrape_value -= 15

    high_match = any(re.search(pattern, url, re.IGNORECASE) for pattern in HIGH_VALUE_PATTERNS)
    if high_match:
        student_value += 25
        scrape_value += 15

    if any(re.search(pattern, url, re.IGNORECASE) for pattern in VERY_HIGH_SIGNAL):
        student_value += 15
        scrape_value += 10

    medium_match = any(re.search(pattern, url, re.IGNORECASE) for pattern in MEDIUM_VALUE_PATTERNS)
    if medium_match:
        student_value += 10
        scrape_value += 5

    if dated_archive_reason:
        student_value -= 35
        scrape_value -= 25
        freshness = min(freshness, 35)

    depth = len([part for part in path.split("/") if part])
    if depth >= 5:
        scrape_value -= 10
        student_value -= 5
    if depth >= 7:
        scrape_value -= 10
        student_value -= 10

    student_value = max(0, min(100, student_value))
    freshness = max(0, min(100, freshness))
    source_quality = max(0, min(100, source_quality))
    scrape_value = max(0, min(100, scrape_value))

    score = round(student_value * 0.40 + freshness * 0.25 + source_quality * 0.15 + scrape_value * 0.20)
    score = max(0, min(100, score))

    reasons: list[str] = []
    if high_match:
        reasons.append("high student-value content")
    elif medium_match:
        reasons.append("moderate student relevance")
    else:
        reasons.append("limited direct student value")
    if lastmod_dt and lastmod_dt.year == target_year:
        reasons.append("current-year content")
    elif lastmod_dt and lastmod_dt.year == target_year - 1:
        reasons.append("previous-year content")
    elif lastmod_dt and lastmod_dt.year < target_year - 2:
        reasons.append("stale content")
    if noisy:
        reasons.append("noisy/technical page")
    if very_low:
        reasons.append("administrative/non-student focus")
    if dated_archive_reason:
        reasons.append(dated_archive_reason)

    return {
        "url": url,
        "score": score,
        "reason": "; ".join(reasons),
        "student_value": student_value,
        "freshness": freshness,
        "source_quality": source_quality,
        "scrape_value": scrape_value,
    }


def select_scored_urls(scored: list[dict[str, Any]], *, threshold: int = DEFAULT_THRESHOLD) -> list[dict[str, Any]]:
    return [
        {"url": item["url"], "priority": item["score"], "reason": item["reason"]}
        for item in scored
        if int(item.get("score") or 0) >= threshold
    ]
