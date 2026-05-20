from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlparse

import requests

from .storage import write_json


SOURCE_EXCLUSION_FILENAME = "source_exclusion_plan.json"
SCRAPE_DECISION = "scrape"
DO_NOT_PARSE_DECISION = "do_not_parse"
SOURCE_CATEGORIES = (
    "spam",
    "login",
    "search",
    "filter",
    "feed",
    "archive",
    "news",
    "event",
    "duplicate",
    "media",
    "scrape_candidate",
)

MEDIA_EXTENSIONS = {
    ".css",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".m4a",
    ".mov",
    ".mp3",
    ".mp4",
    ".png",
    ".svg",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".zip",
}
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".csv", ".txt"}
LOGIN_SEGMENTS = {"login", "signin", "sign-in", "sso", "auth", "password", "logout", "wp-login"}
SEARCH_SEGMENTS = {"search", "site-search", "find"}
FILTER_QUERY_KEYS = {"filter", "sort", "order", "facet", "tag", "category", "page", "paged", "post_type"}
FEED_SEGMENTS = {"feed", "rss", "atom", "xmlrpc"}
ARCHIVE_SEGMENTS = {"archive", "archives", "old", "legacy"}
NEWS_SEGMENTS = {"news", "story", "stories", "press", "press-releases", "article", "articles", "blog"}
EVENT_SEGMENTS = {"event", "events"}
SPAM_SEGMENTS = {"wp-admin", "admin", "cart", "checkout", "embed", "print", "share", "calendar-feed"}


def source_exclusion_plan_path(site_root: Path) -> Path:
    return site_root / SOURCE_EXCLUSION_FILENAME


def canonical_url_key(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    scheme = parsed.scheme.lower() or "https"
    host = parsed.netloc.lower()
    path = re.sub(r"/+$", "", parsed.path or "/") or "/"
    query_pairs = [
        (key.lower(), value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=False)
        if not key.lower().startswith(("utm_", "fbclid", "gclid"))
    ]
    query = "&".join(f"{key}={value}" for key, value in sorted(query_pairs))
    return f"{scheme}://{host}{path}?{query}" if query else f"{scheme}://{host}{path}"


def _path_segments(url: str) -> list[str]:
    parsed = urlparse(str(url or ""))
    segments: list[str] = []
    for raw in parsed.path.split("/"):
        part = raw.strip().lower()
        if part:
            segments.append(part)
    return segments


def _extension(url: str) -> str:
    path = urlparse(str(url or "")).path.lower()
    match = re.search(r"(\.[a-z0-9]{2,5})$", path)
    return match.group(1) if match else ""


def _has_dated_event_path(url: str) -> bool:
    path = urlparse(str(url or "")).path.lower()
    return bool(
        re.search(r"/20\d{2}/\d{1,2}(/|$)", path)
        or re.search(r"/20\d{2}-\d{2}-\d{2}", path)
        or re.search(r"/(january|february|march|april|may|june|july|august|september|october|november|december)(/|$)", path)
    )


def local_source_decision(row: dict[str, Any], *, duplicate: bool = False) -> dict[str, Any]:
    url = str(row.get("url") or "").strip()
    parsed = urlparse(url)
    segments = set(_path_segments(url))
    query_keys = {key.lower() for key, _value in parse_qsl(parsed.query, keep_blank_values=True)}
    ext = _extension(url)

    if duplicate:
        return _decision(url, DO_NOT_PARSE_DECISION, "duplicate", "Duplicate URL after canonical normalization.", 0.98)
    if row.get("excluded_reason"):
        return _decision(url, DO_NOT_PARSE_DECISION, "spam", f"Discovery excluded this URL: {row.get('excluded_reason')}.", 0.95)
    if ext in MEDIA_EXTENSIONS:
        return _decision(url, DO_NOT_PARSE_DECISION, "media", f"Static media or asset file `{ext}`.", 0.96)
    if ext in DOCUMENT_EXTENSIONS:
        return _decision(url, SCRAPE_DECISION, "scrape_candidate", "Document/source file should remain available for scraping or ingest.", 0.86)
    if segments & LOGIN_SEGMENTS:
        return _decision(url, DO_NOT_PARSE_DECISION, "login", "Login/authentication path.", 0.96)
    if segments & SEARCH_SEGMENTS or query_keys & {"q", "query", "search", "s"}:
        return _decision(url, DO_NOT_PARSE_DECISION, "search", "Search result path or query.", 0.94)
    if query_keys & FILTER_QUERY_KEYS or segments & {"filter", "filters", "sort"}:
        return _decision(url, DO_NOT_PARSE_DECISION, "filter", "Filtered/sorted listing URL.", 0.9)
    if segments & FEED_SEGMENTS:
        return _decision(url, DO_NOT_PARSE_DECISION, "feed", "Feed/API syndication path.", 0.95)
    if segments & ARCHIVE_SEGMENTS or re.search(r"/20\d{2}/\d{2}/\d{2}/", parsed.path.lower()):
        return _decision(url, DO_NOT_PARSE_DECISION, "archive", "Archive or dated permalink path.", 0.86)
    if segments & NEWS_SEGMENTS:
        return _decision(url, DO_NOT_PARSE_DECISION, "news", "News/story/blog page is excluded before scrape by default.", 0.82)
    if segments & EVENT_SEGMENTS and _has_dated_event_path(url):
        return _decision(url, DO_NOT_PARSE_DECISION, "event", "Dated event page.", 0.84)
    if segments & SPAM_SEGMENTS:
        return _decision(url, DO_NOT_PARSE_DECISION, "spam", "Technical, commerce, print, or admin path.", 0.9)
    return _decision(url, SCRAPE_DECISION, "scrape_candidate", "No obvious pre-scrape exclusion signal.", 0.75)


def build_local_source_exclusion_plan(
    *,
    site_url: str,
    discovered_rows: list[dict[str, Any]],
    method: str = "local_source_exclusion_fallback",
) -> dict[str, Any]:
    seen: set[str] = set()
    decisions: list[dict[str, Any]] = []
    for row in discovered_rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        key = canonical_url_key(url)
        decisions.append(local_source_decision(row, duplicate=key in seen))
        seen.add(key)
    return _plan_payload(site_url=site_url, method=method, decisions=decisions, model=None, errors=[])


def build_source_exclusion_plan(
    *,
    site_url: str,
    discovered_rows: list[dict[str, Any]],
    out_path: Path | None = None,
    model: str = "deepseek/deepseek-v4-flash",
    api_key: str | None = None,
    batch_size: int = 400,
    sleep_between_batches_sec: float = 0.0,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    key = (api_key or "").strip()
    if not key:
        payload = build_local_source_exclusion_plan(site_url=site_url, discovered_rows=discovered_rows)
        if out_path is not None:
            write_json(out_path, payload)
        return payload

    batches = [discovered_rows[idx : idx + batch_size] for idx in range(0, len(discovered_rows), batch_size)]
    decisions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for idx, batch in enumerate(batches, start=1):
        if progress_callback is not None:
            progress_callback(idx - 1, len(batches), f"Classifying source batch {idx}/{len(batches)}")
        try:
            parsed = _call_openrouter_source_json(
                api_key=key,
                model=model,
                prompt=_build_source_exclusion_prompt(site_url=site_url, discovered_rows=batch, batch_note=f"Batch {idx} of {len(batches)}"),
            )
            normalized = normalize_source_decisions(batch, parsed.get("decisions", []))
        except Exception as exc:
            errors.append({"batch": idx, "error": str(exc)})
            normalized = build_local_source_exclusion_plan(
                site_url=site_url,
                discovered_rows=batch,
                method="local_source_exclusion_batch_fallback",
            )["decisions"]
        decisions.extend(normalized)
        if progress_callback is not None:
            progress_callback(idx, len(batches), f"Finished source batch {idx}/{len(batches)}")
        if sleep_between_batches_sec > 0:
            time.sleep(sleep_between_batches_sec)

    payload = _plan_payload(
        site_url=site_url,
        method="openrouter_source_exclusion",
        decisions=decisions,
        model=model,
        errors=errors,
    )
    if out_path is not None:
        write_json(out_path, payload)
    return payload


def normalize_source_decisions(discovered_rows: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url = {str(row.get("url") or ""): row for row in decisions if isinstance(row, dict) and row.get("url")}
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in discovered_rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        key = canonical_url_key(url)
        raw = dict(by_url.get(url) or {})
        if not raw:
            raw = local_source_decision(row, duplicate=key in seen)
        raw["url"] = url
        raw["decision"] = _coerce_decision(raw.get("decision"))
        raw["category"] = _coerce_category(raw.get("category"), raw["decision"])
        raw["reason"] = str(raw.get("reason") or "No reason supplied.").strip()[:400]
        raw["confidence"] = _coerce_confidence(raw.get("confidence"))
        if key in seen:
            raw = local_source_decision(row, duplicate=True)
        normalized.append(raw)
        seen.add(key)
    return normalized


def apply_source_exclusion_plan(discovered_rows: list[dict[str, Any]], plan: dict[str, Any]) -> list[dict[str, Any]]:
    decisions = plan.get("decisions", []) if isinstance(plan, dict) else []
    by_url = {str(row.get("url") or ""): row for row in decisions if isinstance(row, dict) and row.get("url")}
    rows: list[dict[str, Any]] = []
    for row in discovered_rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        decision = by_url.get(url) or local_source_decision(row)
        selected = str(decision.get("decision") or "") == SCRAPE_DECISION
        rows.append(
            {
                **row,
                "selected": selected,
                "excluded_reason": None if selected else str(decision.get("category") or "do_not_parse"),
                "source_decision": decision.get("decision"),
                "source_category": decision.get("category"),
                "source_reason": decision.get("reason"),
                "source_confidence": decision.get("confidence"),
            }
        )
    return rows


def summarize_source_exclusion_plan(plan: dict[str, Any]) -> dict[str, int]:
    decisions = plan.get("decisions", []) if isinstance(plan, dict) else []
    summary = {"total": 0, "scrape": 0, "do_not_parse": 0}
    for item in decisions:
        if not isinstance(item, dict):
            continue
        summary["total"] += 1
        decision = str(item.get("decision") or "")
        if decision == SCRAPE_DECISION:
            summary["scrape"] += 1
        elif decision == DO_NOT_PARSE_DECISION:
            summary["do_not_parse"] += 1
        category = str(item.get("category") or "unknown")
        summary[category] = summary.get(category, 0) + 1
    return summary


def _decision(url: str, decision: str, category: str, reason: str, confidence: float) -> dict[str, Any]:
    return {
        "url": url,
        "decision": decision,
        "category": category,
        "reason": reason,
        "confidence": round(float(confidence), 2),
    }


def _plan_payload(
    *,
    site_url: str,
    method: str,
    decisions: list[dict[str, Any]],
    model: str | None,
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = summarize_source_exclusion_plan({"decisions": decisions})
    return {
        "site_url": site_url,
        "selection_method": method,
        "model": model,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "categories": list(SOURCE_CATEGORIES),
        "counts": summary,
        "errors": errors,
        "decisions": decisions,
    }


def _build_source_exclusion_prompt(site_url: str, discovered_rows: list[dict[str, Any]], batch_note: str = "") -> str:
    compact = [
        {
            "url": row.get("url"),
            "lastmod": row.get("lastmod"),
            "path_category": row.get("path_category"),
            "source_sitemap": row.get("source_sitemap"),
            "excluded_reason": row.get("excluded_reason"),
        }
        for row in discovered_rows
        if isinstance(row, dict)
    ]
    return (
        "Classify URLs before scraping. Do not rank usefulness. Only block obvious do-not-parse sources.\n"
        f"Site: {site_url}\n"
        f"{batch_note}\n"
        "Return every input URL exactly once.\n"
        "Decision rules:\n"
        "- decision=scrape for normal university pages, departments, offices, services, programs, people/professors, policies, and documents/PDFs.\n"
        "- decision=do_not_parse only for spam, login/auth, search, filter/sort, feed/API, archive, news/story/blog, dated events, duplicates, and static media assets.\n"
        "- Do not exclude professor/person pages just because they are profiles; they will be organized after scrape.\n"
        "- Do not exclude offices, schools, departments, catalogs, schedules, PDFs, tuition, aid, admissions, registrar, housing, or services.\n"
        "Allowed categories: spam, login, search, filter, feed, archive, news, event, duplicate, media, scrape_candidate.\n"
        "Return strict JSON only with schema:\n"
        '{"decisions":[{"url":"...","decision":"scrape|do_not_parse","category":"...","reason":"...","confidence":0.0}]}\n'
        f"Candidates JSON:\n{json.dumps(compact, ensure_ascii=True)}"
    )


def _call_openrouter_source_json(*, api_key: str, model: str, prompt: str) -> dict[str, Any]:
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": "You classify pre-scrape URL exclusions. Return JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
        },
        timeout=120,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:1000]}")
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    return _loads_json_from_text(content)


def _loads_json_from_text(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("No JSON object found in model response.")
        payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Model response must be a JSON object.")
    return payload


def _coerce_decision(value: Any) -> str:
    decision = str(value or "").strip().lower().replace("-", "_")
    return DO_NOT_PARSE_DECISION if decision in {DO_NOT_PARSE_DECISION, "exclude", "skip"} else SCRAPE_DECISION


def _coerce_category(value: Any, decision: str) -> str:
    category = str(value or "").strip().lower().replace(" ", "_")
    if category not in SOURCE_CATEGORIES:
        return "scrape_candidate" if decision == SCRAPE_DECISION else "spam"
    if decision == SCRAPE_DECISION:
        return "scrape_candidate"
    return category


def _coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except Exception:
        confidence = 0.5
    if confidence > 1:
        confidence = confidence / 100.0
    return round(max(0.0, min(1.0, confidence)), 2)
