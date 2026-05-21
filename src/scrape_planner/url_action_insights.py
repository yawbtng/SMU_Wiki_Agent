from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any


FRESHNESS_BUCKETS = ("0-30 days", "31-90 days", "91-365 days", ">365 days", "no lastmod")

FAILURE_ACTIONS = {
    "blocked": "Retry slower or with browser fallback; exclude if login-gated.",
    "empty_content": "Retry with browser/JS extraction, then exclude if it is an app shell.",
    "http_error": "Exclude 404s; retry only 5xx or temporary errors.",
    "parse_error": "Retry with a safer parser; exclude the bucket if repeated parsing fails.",
    "timeout": "Retry with lower concurrency or longer timeout.",
    "too_low_signal": "Bulk exclude unless a sample looks student-critical.",
}


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _freshness_bucket(lastmod: Any, now: datetime) -> str:
    parsed = _parse_datetime(lastmod)
    if parsed is None:
        return "no lastmod"
    days = max(0, (now - parsed).days)
    if days <= 30:
        return "0-30 days"
    if days <= 90:
        return "31-90 days"
    if days <= 365:
        return "91-365 days"
    return ">365 days"


def _text_length(row: dict[str, Any]) -> int:
    try:
        return int(row.get("text_length") or 0)
    except (TypeError, ValueError):
        return 0


def _http_statuses(rows: list[dict[str, Any]]) -> str:
    statuses = Counter(str(row.get("http_status")) for row in rows if row.get("http_status") not in (None, ""))
    if not statuses:
        return "-"
    return ", ".join(status for status, _count in statuses.most_common(3))


def build_url_action_dashboard(
    discovered_rows: list[dict[str, Any]],
    manifest_rows: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    sample_limit: int = 8,
) -> dict[str, Any]:
    """Build compact, action-oriented URL insights for the scrape review UI."""

    now = now or datetime.now(timezone.utc)
    discovered = [row for row in discovered_rows if isinstance(row, dict)]
    manifest = [row for row in manifest_rows if isinstance(row, dict)]

    successful = [row for row in manifest if row.get("status") == "success"]
    failed = [row for row in manifest if row.get("status") and row.get("status") != "success"]
    markdown_ready = [row for row in successful if row.get("markdown_path")]
    thin_success = [row for row in successful if _text_length(row) < 1500]

    failure_groups: dict[str, list[dict[str, Any]]] = {}
    for row in failed:
        reason = str(row.get("failure_reason") or "unknown")
        failure_groups.setdefault(reason, []).append(row)

    failure_queue = []
    for reason, rows in sorted(failure_groups.items(), key=lambda item: (-len(item[1]), item[0])):
        failure_queue.append(
            {
                "failure_reason": reason,
                "count": len(rows),
                "http_statuses": _http_statuses(rows),
                "sample_url": rows[0].get("url") or "",
                "recommended_action": FAILURE_ACTIONS.get(reason, "Retry or exclude this failure bucket."),
            }
        )

    freshness_counts = Counter(_freshness_bucket(row.get("lastmod"), now) for row in discovered)
    freshness = [{"bucket": bucket, "count": freshness_counts[bucket]} for bucket in FRESHNESS_BUCKETS if freshness_counts[bucket]]

    summary = {
        "discovered": len(discovered),
        "scraped": len(manifest),
        "successful": len(successful),
        "failed": len(failed),
        "thin_success": len(thin_success),
        "markdown_ready": len(markdown_ready),
    }
    if summary["markdown_ready"]:
        recommended_action = (
            f"Use {summary['markdown_ready']:,} successful markdown pages, "
            f"then repair or exclude {summary['failed']:,} failed URLs."
        )
    elif summary["discovered"]:
        recommended_action = "No markdown corpus yet. Choose a focused URL set, then scrape."
    else:
        recommended_action = "Discover URLs before choosing what to scrape."

    return {
        "summary": summary,
        "recommended_action": recommended_action,
        "failure_queue": failure_queue,
        "freshness": freshness,
    }
