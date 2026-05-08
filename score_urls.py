#!/usr/bin/env python3
"""Score discovered SMU URLs for student-facing wiki scraping value."""

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

INPUT_PATH = "/Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/sites/www.smu.edu/discovered_urls.json"
OUTPUT_PATH = "/Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/sites/www.smu.edu/selected_urls_llm.json"
TARGET_YEAR = 2026
DEFAULT_THRESHOLD = 70

# High-value student-facing path patterns (case-insensitive)
HIGH_VALUE_PATTERNS = [
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
    r"/cost",
    r"/student-life",
    r"/studentlife",
    r"/housing",
    r"/dining",
    r"/career",
    r"/careers",
    r"/registrar",
    r"/records",
    r"/transcript",
    r"/commencement",
    r"/graduation",
    r"/apply",
    r"/application",
    r"/visit",
    r"/events",
    r"/calendar",
    r"/library",
    r"/libraries",
    r"/research",
    r"/international",
    r"/study-abroad",
    r"/abroad",
    r"/health",
    r"/counseling",
    r"/wellness",
    r"/sustainability",
    r"/diversity",
    r"/inclusion",
    r"/accessibility",
    r"/disability",
    r"/safety",
    r"/police",
    r"/parking",
    r"/transportation",
    r"/ Mustang",  # intentional space to avoid substring noise
    r"/_muster",  # real SMU tradition
    r"/honors",
    r"/fellowship",
    r"/internship",
    r"/co-op",
    r"/coop",
    r"/service",
    r"/volunteer",
    r"/leadership",
    r"/athletic",
    r"/sports",
    r"/recreation",
    r"/fitness",
    r"/campus",
    r"/orientation",
    r"/new-student",
    r"/first-year",
    r"/transfer",
    r"/graduate",
    r"/phd",
    r"/masters",
    r"/mba",
    r"/law",
    r"/med",
    r"/engineering",
    r"/business",
    r"/art",
    r"/music",
    r"/theatre",
    r"/dance",
    r"/science",
    r"/humanities",
    r"/social-science",
    r"/policy",
    r"/education",
    r"/computing",
    r"/data",
    r"/ai",
    r"/entrepreneur",
    r"/innovation",
    r"/maker",
]

# Medium-value patterns
MEDIUM_VALUE_PATTERNS = [
    r"/about",
    r"/facts",
    r"/news",
    r"/press",
    r"/media",
    r"/publication",
    r"/magazine",
    r"/blog",
    r"/story",
    r"/history",
    r"/tradition",
    r"/mission",
    r"/vision",
    r"/values",
    r"/history",
    r"/awards",
    r"/recognition",
    r"/ranking",
    r"/accreditation",
    r"/people",
    r"/faculty",
    r"/staff",
    r"/directory",
    r"/contact",
    r"/faq",
    r"/help",
    r"/resources",
    r"/guide",
    r"/handbook",
    r"/policy",
    r"/procedure",
    r"/code",
    r"/conduct",
    r"/ethics",
    r"/title-ix",
    r"/titleix",
    r"/clery",
    r"/ferpa",
    r"/grievance",
    r"/complaint",
    r"/ombuds",
    r"/ Reports",  # intentional space
]

# Low-signal / noisy patterns to penalize
NOISY_PATTERNS = [
    r"/search",
    r"/tag/",
    r"/tags/",
    r"/category/",
    r"/filter",
    r"/sort",
    r"/login",
    r"/signin",
    r"/sso",
    r"/auth",
    r"/password",
    r"/account",
    r"/profile",
    r"/dashboard",
    r"/admin",
    r"/wp-admin",
    r"/feed",
    r"/rss",
    r"/atom",
    r"/xmlrpc",
    r"/api/",
    r"/ajax",
    r"/json",
    r"/embed",
    r"/print",
    r"/download",
    r"/export",
    r"/import",
    r"/backup",
    r"/archive",
    r"/archive/\d{4}",
    r"/old",
    r"/legacy",
    r"/staging",
    r"/test",
    r"/demo",
    r"/draft",
    r"/trash",
    r"/delete",
    r"/remove",
    r"/edit",
    r"/create",
    r"/new",
    r"/add",
    r"/submit",
    r"/form",
    r"/survey",
    r"/poll",
    r"/quiz",
    r"/exam",
    r"/calendar/\d{4}/\d{2}",  # month-level calendar feeds
    r"/event/\d{4}-\d{2}-\d{2}",  # daily event listings
    r"/news/\d{4}/\d{2}",  # monthly news archives
    r"/page/\d+",  # paginated listings
    r"\?page=\d+",
    r"\?p=\d+",
    r"\?post_type=",
    r"\?s=",
    r"\?search=",
    r"\?filter=",
    r"\?sort=",
    r"\?order=",
    r"\?date=",
    r"\?from=",
    r"\?to=",
    r"/author/",
    r"/user/",
    r"/member/",
    r"/person/\d+",
    r"/\d{4}/\d{2}/\d{2}/",  # date-based blog permalinks (often noisy)
]

# Very high signal specific paths
VERY_HIGH_SIGNAL = [
    r"/admission$",
    r"/admissions$",
    r"/academics$",
    r"/financial-aid$",
    r"/financialaid$",
    r"/student-life$",
    r"/studentlife$",
    r"/career$",
    r"/careers$",
    r"/registrar$",
    r"/housing$",
    r"/dining$",
    r"/library$",
    r"/libraries$",
    r"/apply$",
    r"/visit$",
    r"/orientation$",
    r"/commencement$",
    r"/graduation$",
    r"/catalog$",
    r"/calendar$",
    r"/events$",
]

# Very low signal / non-student pages
VERY_LOW_SIGNAL = [
    r"/donor",
    r"/giving",
    r"/gift",
    r"/development",
    r"/advancement",
    r"/alumni",
    r"/trustee",
    r"/board",
    r"/annual-report",
    r"/annualreport",
    r"/president" r"/office-of-the-president",
    r"/administration",
    r"/vice-president",
    r"/provost",
    r"/chancellor",
    r"/dean-",
    r"/director-",
    r"/vp-",
    r"/investment",
    r"/endowment",
    r"/budget",
    r"/finance",
    r"/audit",
    r"/compliance",
    r"/legal",
    r"/general-counsel",
    r"/hr$",
    r"/human-resources",
    r"/employment",
    r"/job",
    r"/career-opportunit",
    r"/staff-",
    r"/faculty-",
    r"/email-messages",
    r"/inauguration",
    r"/pec",
    r"/pec-",
    r"/org-chart",
    r"/expanded-pec",
    r"/21stcenturycouncil",
    r"/hilltop-and-presidents-associates-donors",
    r"/principal-and-major-donors",
    r"/letter-from-the-smu-president",
    r"/turner-letter",
    r"/dedman-letter",
]


def parse_lastmod(lastmod_str):
    if not lastmod_str:
        return None
    try:
        # Handle various ISO formats
        lastmod_str = lastmod_str.replace("Z", "+00:00")
        return datetime.fromisoformat(lastmod_str)
    except Exception:
        return None


def score_freshness(lastmod_dt, target_year):
    if lastmod_dt is None:
        return 50  # unknown freshness = neutral
    try:
        year = lastmod_dt.year
        now = datetime.now(timezone.utc)
        age_days = (now - lastmod_dt).days

        if year == target_year:
            if age_days <= 30:
                return 95
            elif age_days <= 90:
                return 90
            elif age_days <= 180:
                return 85
            else:
                return 80
        elif year == target_year - 1:
            if age_days <= 180:
                return 75
            else:
                return 70
        elif year >= target_year - 2:
            return 60
        elif year >= target_year - 4:
            return 45
        else:
            return 30
    except Exception:
        return 50


def score_url(url_item):
    url = url_item.get("url", "")
    path = urlparse(url).path.lower()
    lastmod_str = url_item.get("lastmod", "")
    lastmod_dt = parse_lastmod(lastmod_str)

    # Base scores
    student_value = 50
    freshness = score_freshness(lastmod_dt, TARGET_YEAR)
    source_quality = 85 if url.endswith(".edu") or ".edu/" in url else 70
    scrape_value = 70

    # Check noisy patterns first
    noisy = False
    for pattern in NOISY_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            noisy = True
            break

    if noisy:
        scrape_value -= 30
        student_value -= 20

    # Check very low signal
    very_low = False
    for pattern in VERY_LOW_SIGNAL:
        if re.search(pattern, url, re.IGNORECASE):
            very_low = True
            break

    if very_low:
        student_value -= 25
        scrape_value -= 15

    # Check high value
    high_match = False
    for pattern in HIGH_VALUE_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            high_match = True
            break

    if high_match:
        student_value += 25
        scrape_value += 15

    # Check very high signal
    for pattern in VERY_HIGH_SIGNAL:
        if re.search(pattern, url, re.IGNORECASE):
            student_value += 15
            scrape_value += 10
            break

    # Check medium value
    medium_match = False
    for pattern in MEDIUM_VALUE_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            medium_match = True
            break

    if medium_match:
        student_value += 10
        scrape_value += 5

    # Root domain bonus
    if path == "/" or path == "":
        student_value = max(student_value, 60)
        source_quality = 90

    # Path depth penalty (deep paths are often lower value)
    depth = len([p for p in path.split("/") if p])
    if depth >= 5:
        scrape_value -= 10
        student_value -= 5
    if depth >= 7:
        scrape_value -= 10
        student_value -= 10

    # Donor/giving specific heavy penalty
    if re.search(r"/donor|/giving|/gift|/principal-and-major-donors|/hilltop-and-presidents-associates-donors|/development|/advancement", url, re.IGNORECASE):
        student_value -= 30
        scrape_value -= 20

    # Annual report old years heavy penalty
    if re.search(r"/annual-report/\d{4}", url, re.IGNORECASE) or re.search(r"/annualreport", url, re.IGNORECASE):
        year_match = re.search(r"/(\d{4})", url)
        if year_match:
            report_year = int(year_match.group(1))
            if report_year < TARGET_YEAR - 2:
                student_value -= 25
                freshness -= 20

    # Individual person bios heavy penalty
    if re.search(r"/dean-[a-z]+|/director-[a-z]+|/vp-[a-z]+|/assistant-vice-president|/cio$|/president$|/president-emeritus|/ccio-", url, re.IGNORECASE):
        student_value -= 30
        scrape_value -= 15

    # Clamp scores
    student_value = max(0, min(100, student_value))
    freshness = max(0, min(100, freshness))
    source_quality = max(0, min(100, source_quality))
    scrape_value = max(0, min(100, scrape_value))

    # Final composite score (weighted)
    score = round(
        student_value * 0.40 +
        freshness * 0.25 +
        source_quality * 0.15 +
        scrape_value * 0.20
    )
    score = max(0, min(100, score))

    # Generate reason
    reasons = []
    if high_match:
        reasons.append("high student-value content")
    elif medium_match:
        reasons.append("moderate student relevance")
    else:
        reasons.append("limited direct student value")

    if lastmod_dt and lastmod_dt.year == TARGET_YEAR:
        reasons.append("current-year content")
    elif lastmod_dt and lastmod_dt.year == TARGET_YEAR - 1:
        reasons.append("previous-year content")
    elif lastmod_dt and lastmod_dt.year < TARGET_YEAR - 2:
        reasons.append("stale content")

    if noisy:
        reasons.append("noisy/technical page")
    if very_low:
        reasons.append("administrative/non-student focus")
    if depth >= 5:
        reasons.append("deep page hierarchy")

    reason = "; ".join(reasons)

    return {
        "url": url,
        "score": score,
        "reason": reason,
        "student_value": student_value,
        "freshness": freshness,
        "source_quality": source_quality,
        "scrape_value": scrape_value,
    }


def main():
    print(f"Reading {INPUT_PATH} ...")
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Loaded {len(data)} URLs. Scoring ...")

    scored = []
    for item in data:
        scored_item = score_url(item)
        scored.append(scored_item)

    # Sort by score descending
    scored.sort(key=lambda x: x["score"], reverse=True)

    selected = [
        {
            "url": s["url"],
            "priority": s["score"],
            "reason": s["reason"],
        }
        for s in scored
        if s["score"] >= DEFAULT_THRESHOLD
    ]

    output = {
        "selection_method": "pi_skill_url_scorer",
        "default_threshold": DEFAULT_THRESHOLD,
        "target_year": TARGET_YEAR,
        "total_scored": len(scored),
        "total_selected": len(selected),
        "scored_urls": scored,
        "selected_urls": selected,
    }

    print(f"Writing {OUTPUT_PATH} ...")
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Done. Selected {len(selected)} URLs out of {len(scored)} (threshold={DEFAULT_THRESHOLD}).")
    print(f"Top 5 scores: {[s['score'] for s in scored[:5]]}")
    print(f"Bottom 5 scores: {[s['score'] for s in scored[-5:]]}")


if __name__ == "__main__":
    main()
