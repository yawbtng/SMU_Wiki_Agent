from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

TARGET_YEAR = 2026


@dataclass(frozen=True)
class UrlPolicyDecision:
    selected: bool
    reason: str = ""
    category: str = "student_candidate"
    severity: str = "allow"


ALLOWLIST_PATTERNS = (
    r"/admission",
    r"/enrollment-services",
    r"/registrar",
    r"/academic-calendar",
    r"/final-exam",
    r"/course-catalog",
    r"/catalog",
    r"/financial-aid",
    r"/financialaid",
    r"/student-financial-services",
    r"/bursar",
    r"/tuition",
    r"/scholarship",
    r"/housing",
    r"/dining",
    r"/student-life",
    r"/studentlife",
    r"/health",
    r"/counseling",
    r"/accessibility",
    r"/disability",
    r"/parking",
    r"/orientation",
    r"/apply",
    r"/academics",
    r"/degree",
    r"/program",
    r"/major",
    r"/minor",
)

HARD_REJECT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("class_or_alumni_notes", r"class[-_\s]?notes|alumni[-_\s]?notes"),
    ("auth_or_account", r"/login|/signin|/sso|/auth|/password|/account|/dashboard"),
    ("search_or_listing_noise", r"/search(?:[/?]|$)|/tag/|/tags/|/category/|/filter|/sort|/topics?/|/listing(?:/|$)|[?&](?:s|q|query|search|filter|sort|order|page|p|offset|start|utm_[^=&]+|fbclid|gclid|gbraid|wbraid|mc_cid|mc_eid)="),
    ("calendar_listing_noise", r"/calendar/(?:list|feed|archive|index)|/events/(?:list|category|archive)|/event-calendar(?:/|$)"),
    ("technical_or_generated_noise", r"/feed|/rss|/atom|/xmlrpc|/api/|/ajax|/json|/embed|/print|/download|/export|/wp-content/|/assets/(?:css|js|images?)/"),
    ("draft_test_or_template", r"/staging|/test|/demo|/draft|/brand(?:/|\n|$)|design-components|content-block|slide-show|carousel|brand-web-guidelines|/template(?:/|$)|/component(?:s)?(?:/|$)"),
    ("donor_advancement_or_alumni", r"/donor(?:/|$)|/giving(?:/|$)|/(?:gift|gifts|gift-planning|ways-to-give)(?:/|$)|/advancement(?:/|$)|annual[-_]?report|/annual-report|/campaign(?:/|$)|/fundraising|/development(?:/|$|/(?:about|advancement|campaign|donor|fundraising|gift|giving|office|staff|support|ways-to-give)(?:/|$))"),
    ("alumni_stories_or_events", r"/alumni/(?:stories|events|news|magazine|spotlight)|/alumni-spotlight|/reunion(?:/|$)"),
    ("hr_or_employee", r"/human-resources(?:/|$)|/hr(?:/|$)|/employment(?:/|$)|/(?:employee|employees|faculty-staff)/benefits(?:/|$)|/faculty-staff(?:/|$)|/staff-association|/employee-(?:resources|benefits)|/workday(?:/|$)"),
    ("governance_or_admin", r"/aboutsmu/administration|/office-of-the-president(?:/|$)|/presidents?-office(?:/|$)|/president(?:/|$)|/trustee|/trustees|/board(?:/|$)|/provost|/vice-president|/chancellor|/cabinet(?:/|$)|/governance(?:/|$)"),
    ("generic_news_archive", r"/news/(?:articles/)?archive(?:/|$)"),
    ("staff_faculty_bio", r"(?:^|\n)(?:/[^\n]+)?/(?:faculty|staff)/(?:directory|profiles?|bio(?:graphy)?)(?:/|$)|/(?:faculty|staff)/[a-z0-9]+(?:-[a-z0-9]+)+/?(?:\?|$)|/people/[^/\n]+/?$|/profile/[^/\n]+/?$"),
    ("media_or_asset_noise", r"\.(?:jpe?g|png|gif|svg|webp|zip|mp4|mov)(?:\?|$)|/media/(?:files|assets)(?:/|$)"),
)

CONTEXTUAL_REJECT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("general_alumni_section", r"/alumni(?:/|$)"),
)

DATED_NEWS_PATTERNS = (
    r"/(news|stories|story|press-releases?|media|blog|magazine|coxtoday-magazine)/20\d{2}[-/]\d{2}[-/]\d{2}",
    r"/20\d{2}-\d{2}-\d{2}-",
    r"/20\d{2}/\d{2}/\d{2}/",
)

DATED_ARCHIVE_PATTERNS = (
    r"/latest-at-lyle/\d{4}-\d{2}/",
    r"/stories/.+20\d{2}",
    r"/press-releases/20\d{6}",
    r"/professors-institute(?:/professors-institute)?-20\d{2}",
    r"/20\d{2}-virtual-graduation",
    r"/symposia-and-workshops/20\d{2}",
    r"/20\d{2}-ntcc-scholars",
    r"/20\d{2}-20\d{2}-faculty-publications",
    r"/20\d{2}-20\d{2}-passport-directory",
    r"/coursedescriptions/(fall|spring)-20\d{2}",
    r"/course-schedule/(fall|spring)-20\d{2}",
    r"alternategrade.*20\d{2}",
)

MONTH_SLUGS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)

YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
COMPACT_DATE_RE = re.compile(r"(?:^|/)(20\d{2})(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?:[-_/]|$)")


SOCIAL_NETLOCS = (
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "tiktok.com",
)


_HAYSTACK_RE_FLAGS = re.IGNORECASE | re.MULTILINE


def _text(url: str, title: str = "") -> str:
    parsed = urlparse(str(url or ""))
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.netloc}\n{parsed.path}{query}\n{title}".lower()


def _matches_any(text: str, patterns: tuple[str, ...], *, flags: int = _HAYSTACK_RE_FLAGS) -> bool:
    return any(re.search(pattern, text, flags) for pattern in patterns)


def _years(text: str) -> list[int]:
    years = [int(value) for value in YEAR_RE.findall(text)]
    years.extend(int(value) for value in COMPACT_DATE_RE.findall(text))
    return years


def _is_current_or_future_year(year: int, target_year: int = TARGET_YEAR) -> bool:
    return year >= target_year - 1


def parse_lastmod(lastmod_str: str | None) -> datetime | None:
    if not lastmod_str:
        return None
    try:
        normalized = str(lastmod_str).replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except Exception:
        return None


def score_freshness_from_lastmod(lastmod_dt: datetime | None, target_year: int = TARGET_YEAR) -> int:
    if lastmod_dt is None:
        return 50
    try:
        year = lastmod_dt.year
        now = datetime.now(timezone.utc)
        age_days = (now - lastmod_dt).days
        if year == target_year:
            if age_days <= 30:
                return 95
            if age_days <= 90:
                return 90
            if age_days <= 180:
                return 85
            return 80
        if year == target_year - 1:
            if age_days <= 180:
                return 75
            return 70
        if year >= target_year - 2:
            return 60
        if year >= target_year - 4:
            return 45
        return 30
    except Exception:
        return 50


def detect_dated_archive(url: str, *, target_year: int = TARGET_YEAR) -> str:
    """Return a reason when URL content is stale even if sitemap lastmod is fresh."""
    path = urlparse(str(url or "")).path.lower()
    years = _years(path)
    oldest_year = min(years) if years else None

    crime_log_month = rf"/crime-log/.*/20\d{{2}}/({'|'.join(MONTH_SLUGS)})$"
    if re.search(crime_log_month, path, re.IGNORECASE):
        if oldest_year is None or not _is_current_or_future_year(oldest_year, target_year):
            return "historical monthly crime log"

    for pattern in DATED_ARCHIVE_PATTERNS:
        if re.search(pattern, path, re.IGNORECASE):
            if oldest_year is None or not _is_current_or_future_year(oldest_year, target_year):
                return "dated archive page"

    if re.search(r"/20\d{2}-\d{2}-\d{2}-", path):
        if oldest_year is not None and not _is_current_or_future_year(oldest_year, target_year):
            return "old dated article"

    if oldest_year is not None and oldest_year < target_year - 1:
        if re.search(r"/(tuition|factsheets|directory|schedule|spring|fall)[-_]?", path):
            return "old year-specific page"

    return ""


def _is_social_or_mailto(url: str) -> str:
    parsed = urlparse(str(url or ""))
    scheme = (parsed.scheme or "").lower()
    if scheme == "mailto":
        return "mailto_link"
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if any(host == domain or host.endswith(f".{domain}") for domain in SOCIAL_NETLOCS):
        return "social_or_external_profile"
    return ""


def _is_academic_program_faculty_profile(url: str) -> bool:
    path = urlparse(str(url or "")).path.lower()
    return bool(re.search(r"/academics/(?:departments/[^/]+|programs/.+)/faculty/profiles?/", path))


def classify_url_for_student_wiki(url: str, *, title: str = "", lastmod: str | None = None, target_year: int = TARGET_YEAR) -> UrlPolicyDecision:
    """Return a pre-scrape decision for student-facing university wiki URLs.

    This is intentionally stricter than scoring: hard-reject URLs never reach the
    scraper, even if sitemap lastmod is recent. CMS lastmod can change because
    nav/templates changed while body content remains old.
    """
    _ = lastmod  # retained for API compatibility; path/year signals are authoritative
    haystack = _text(url, title)
    if not str(url or "").strip():
        return UrlPolicyDecision(False, "empty_url", "invalid", "hard_reject")

    external_reason = _is_social_or_mailto(url)
    if external_reason:
        return UrlPolicyDecision(False, external_reason, "non_student_or_noise", "hard_reject")

    is_allowlisted = _matches_any(haystack, ALLOWLIST_PATTERNS)

    for reason, pattern in HARD_REJECT_PATTERNS:
        if re.search(pattern, haystack, _HAYSTACK_RE_FLAGS):
            if reason == "staff_faculty_bio" and _is_academic_program_faculty_profile(url):
                continue
            return UrlPolicyDecision(False, reason, "non_student_or_noise", "hard_reject")

    if not is_allowlisted:
        for reason, pattern in CONTEXTUAL_REJECT_PATTERNS:
            if re.search(pattern, haystack, _HAYSTACK_RE_FLAGS):
                return UrlPolicyDecision(False, reason, "non_student_or_noise", "hard_reject")

    years = _years(haystack)
    oldest_year = min(years) if years else None
    is_dated_news = _matches_any(haystack, DATED_NEWS_PATTERNS)
    if is_dated_news and (oldest_year is None or not _is_current_or_future_year(oldest_year, target_year)):
        return UrlPolicyDecision(False, "old_dated_news_or_article", "stale", "hard_reject")

    archive_reason = detect_dated_archive(url, target_year=target_year)
    if archive_reason:
        return UrlPolicyDecision(False, "dated_archive_page", "stale", "hard_reject")

    if oldest_year is not None and oldest_year < target_year - 1:
        return UrlPolicyDecision(False, "old_year_specific_noncanonical_page", "stale", "hard_reject")

    if is_allowlisted:
        return UrlPolicyDecision(True, "student_canonical_allowlist", "student_canonical", "allow")

    return UrlPolicyDecision(True, "student_candidate", "student_candidate", "allow")
