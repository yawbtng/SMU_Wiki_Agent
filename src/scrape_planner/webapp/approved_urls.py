from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException

from ..core.storage import read_json, write_json
from ..core.url_utils import APPROVED_URL_RE, parse_approved_urls_markdown
from ..scrape.url_policy import classify_url_for_student_wiki
from .deps import site_root, to_jsonable, utc_now
from .schemas import ApprovedUrlsChatRequest, ApprovedUrlsCommitRequest

APPROVED_URLS_HEADER = "# Approved URLs\n\n<!-- scrape-planner:approved-urls:v1 -->\n"


def approved_urls_path(site_id: str) -> Path:
    return site_root(site_id) / "approved_urls.md"


SCHOOL_PATH_ROOTS = {"cox", "dedman", "dedmanlaw", "law", "lyle", "meadows", "simmons", "perkins"}

SCHOOL_TERM_TO_ROOT = {
    "cox": "cox",
    "dedman": "dedman",
    "deadman": "dedman",
    "dedmanlaw": "dedmanlaw",
    "law": "dedmanlaw",
    "lyle": "lyle",
    "meadows": "meadows",
    "simmons": "simmons",
    "perkins": "perkins",
}

LAW_SCHOOL_TERMS = {"dedmanlaw", "law"}


def _school_roots_from_terms(terms: list[str]) -> set[str]:
    roots: set[str] = set()
    normalized_terms: set[str] = set()
    for term in terms:
        normalized = str(term or "").strip().lower().replace("-", "").replace(" ", "")
        normalized_terms.add(normalized)
        if not normalized:
            continue
        if normalized in LAW_SCHOOL_TERMS:
            roots.update({"dedmanlaw", "law"})
        elif root := SCHOOL_TERM_TO_ROOT.get(normalized):
            roots.add(root)
    if normalized_terms & LAW_SCHOOL_TERMS and "schools" not in normalized_terms:
        roots.discard("dedman")
    return roots


def _url_school_root(url: str) -> str:
    parts = [part.lower() for part in urlparse(url).path.split("/") if part]
    if parts and parts[0] in SCHOOL_PATH_ROOTS:
        return parts[0]
    return ""


def _url_group_key(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return "/"
    if parts[0].lower() in SCHOOL_PATH_ROOTS:
        return f"/{parts[0]}"
    if len(parts) == 1:
        return f"/{parts[0]}"
    return f"/{parts[0]}/{parts[1]}"


def _url_groups(urls: list[str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = {}
    for url in urls:
        grouped.setdefault(_url_group_key(url), []).append(url)
    return [
        {"subpath": subpath, "count": len(items), "examples": items[:3]}
        for subpath, items in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def _term_matches_url_or_group(url: str, terms: list[str]) -> bool:
    school_roots = _school_roots_from_terms(terms)
    if school_roots:
        return _url_school_root(url) in school_roots
    haystack = f"{url}\n{_url_group_key(url)}".lower().replace("-", " ")
    compact = haystack.replace(" ", "-")
    for term in terms:
        if str(term or "").strip().lower() in SCHOOL_TERM_TO_ROOT:
            continue
        needle = str(term or "").strip().lower().replace("/", " ").replace("-", " ")
        if not needle:
            continue
        if needle in haystack or needle.replace(" ", "-") in compact:
            return True
    return False


def _discovery_url_pool(site_id: str, *, extra_exclude_terms: list[str] | None = None) -> dict[str, Any]:
    rows = read_json(site_root(site_id) / "discovered_urls.json", [])
    exclude_terms = extra_exclude_terms or []
    eligible_urls: list[str] = []
    rejected = 0
    total = 0
    reject_reasons: Counter[str] = Counter()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        total += 1
        url = str(row.get("url") or "")
        title = str(row.get("title") or "")
        if row.get("excluded_reason") == "operator_rejected_area" or _term_matches_url_or_group(url, exclude_terms):
            rejected += 1
            reject_reasons["operator_rejected_area" if row.get("excluded_reason") == "operator_rejected_area" else "operator_exclude_term"] += 1
            continue
        decision = classify_url_for_student_wiki(url, title=title, lastmod=row.get("lastmod"))
        if decision.selected:
            eligible_urls.append(url)
        else:
            rejected += 1
            reject_reasons[decision.reason] += 1
    return {
        "discovered_total": total,
        "eligible_total": len(eligible_urls),
        "rejected_total": rejected,
        "reject_reasons": [{"reason": reason, "count": count} for reason, count in reject_reasons.most_common()],
        "groups": _url_groups(eligible_urls),
    }


def approved_urls_payload(site_id: str) -> dict[str, Any]:
    path = approved_urls_path(site_id)
    markdown = path.read_text(encoding="utf-8") if path.exists() else APPROVED_URLS_HEADER + "\n"
    urls = parse_approved_urls_markdown(markdown)
    pool = _discovery_url_pool(site_id)
    return {"site_id": site_id, "path": str(path), "markdown": markdown, "urls": urls, "groups": _url_groups(urls), "available_groups": pool["groups"], "discovery": {"discovered_total": pool["discovered_total"], "eligible_total": pool["eligible_total"], "rejected_total": pool["rejected_total"]}, "count": len(urls), "generated_at": utc_now()}


def _policy_filtered_approved_markdown(markdown: str) -> tuple[str, list[dict[str, str]]]:
    content = markdown if markdown.strip() else APPROVED_URLS_HEADER + "\n"
    if "scrape-planner:approved-urls:v1" not in content:
        content = APPROVED_URLS_HEADER + "\n" + content.strip() + "\n"

    accepted_lines: dict[str, str] = {}
    rejected: list[dict[str, str]] = []
    for url in _approved_url_lines(content):
        decision = classify_url_for_student_wiki(url)
        if decision.selected:
            accepted_lines[url] = url
        else:
            rejected.append({"url": url, "reason": decision.reason})
    if not accepted_lines:
        return APPROVED_URLS_HEADER + "\n", rejected
    return _render_approved_urls_markdown(accepted_lines), rejected


def write_approved_urls_payload(site_id: str, markdown: str) -> dict[str, Any]:
    path = approved_urls_path(site_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    content, rejected = _policy_filtered_approved_markdown(markdown)
    path.write_text(content, encoding="utf-8")
    payload = approved_urls_payload(site_id)
    return {**payload, "filtered_rejected_urls": rejected}


def apply_operator_discovery_exclusions(site_id: str, terms: list[str]) -> int:
    clean_terms = [str(term or "").strip() for term in terms if str(term or "").strip()]
    if not clean_terms:
        return 0
    path = site_root(site_id) / "discovered_urls.json"
    rows = read_json(path, [])
    if not isinstance(rows, list):
        return 0
    changed = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "")
        if not url or not _term_matches_url_or_group(url, clean_terms):
            continue
        if row.get("excluded_reason") != "operator_rejected_area" or row.get("selected") is not False:
            row["selected"] = False
            row["excluded_reason"] = "operator_rejected_area"
            changed += 1
    if changed:
        write_json(path, rows)
    return changed


def commit_approved_urls_payload(site_id: str, request: ApprovedUrlsCommitRequest) -> dict[str, Any]:
    excluded_count = apply_operator_discovery_exclusions(site_id, request.remove_terms)
    payload = write_approved_urls_payload(site_id, request.markdown)
    return {**payload, "operator_excluded_count": excluded_count}


def approval_chat_log_path(site_id: str) -> Path:
    return site_root(site_id) / "approved_urls_chat.jsonl"


def _append_approval_chat_event(site_id: str, event: dict[str, Any]) -> None:
    path = approval_chat_log_path(site_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {**event, "site_id": site_id, "created_at": utc_now()}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(to_jsonable(row), sort_keys=True) + "\n")


def _approved_url_lines(markdown: str) -> dict[str, str]:
    lines: dict[str, str] = {}
    for line in (markdown or "").splitlines():
        match = APPROVED_URL_RE.search(line)
        if not match:
            continue
        url = match.group(0).rstrip(".,;")
        lines.setdefault(url, line.strip() or f"- [x] {url}")
    return lines


def _render_approved_urls_markdown(lines_by_url: dict[str, str], *, note: str = "") -> str:
    lines = [APPROVED_URLS_HEADER.rstrip(), ""]
    if note:
        lines.extend([f"> {note}", ""])
    lines.extend(["## Approved for next scrape", ""])
    for url in sorted(lines_by_url):
        lines.append(f"- [x] {url}")
    return "\n".join(lines).rstrip() + "\n"


def _message_urls(message: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in APPROVED_URL_RE.finditer(message or ""):
        url = match.group(0).rstrip(".,;")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _message_subpaths(message: str) -> list[str]:
    subpaths: list[str] = []
    for match in re.finditer(r"\bpath:([^\s,;]+)", message or "", flags=re.IGNORECASE):
        raw = match.group(1).strip()
        if raw == "/":
            subpath = "/"
        else:
            subpath = "/" + raw.strip("/")
        if subpath not in subpaths:
            subpaths.append(subpath)
    return subpaths


def _removal_terms(message: str) -> list[str]:
    stop = {"remove", "delete", "exclude", "filter", "demove", "noise", "noisy", "bad", "reject", "rejected", "approved", "approve", "source", "sources", "url", "urls", "page", "pages", "anything", "with", "from", "file", "scrape", "please"}
    terms: list[str] = []
    for token in re.findall(r"[a-z0-9][a-z0-9-]{2,}", message.lower()):
        if token not in stop and token not in terms:
            terms.append(token)
    return terms


def _candidate_rows_for_instruction(site_id: str, instruction: str, *, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    root = site_root(site_id)
    raw_rows = read_json(root / "discovered_urls.json", [])
    row_list = [row for row in raw_rows if isinstance(row, dict)] if isinstance(raw_rows, list) else []
    terms = _message_terms(instruction)
    school_roots = _school_roots_from_terms(terms)
    explicit_urls = _message_urls(instruction)
    matched_groups: set[str] = {_url_group_key(url) for url in explicit_urls}
    matched_groups.update(_message_subpaths(instruction))
    if school_roots:
        matched_groups.update(f"/{root}" for root in school_roots)
    rejected: list[dict[str, Any]] = []

    for row in row_list:
        url = str(row.get("url") or "")
        title = str(row.get("title") or "")
        haystack = f"{url}\n{title}".lower()
        if url and not school_roots and (not terms or any(term in haystack for term in terms)):
            matched_groups.add(_url_group_key(url))

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    discovered_urls = {str(row.get("url") or "") for row in row_list}

    for url in explicit_urls:
        if url in discovered_urls:
            continue
        decision = classify_url_for_student_wiki(url)
        if decision.selected:
            candidates.append({"url": url, "title": "", "reason": "explicit_url"})
            seen.add(url)
        else:
            rejected.append({"url": url, "reason": decision.reason})

    for row in row_list:
        if len(candidates) >= limit:
            break
        url = str(row.get("url") or "")
        if not url or url in seen:
            continue
        if row.get("excluded_reason") == "operator_rejected_area":
            continue
        if matched_groups and _url_group_key(url) not in matched_groups:
            continue
        title = str(row.get("title") or "")
        decision = classify_url_for_student_wiki(url, title=title, lastmod=row.get("lastmod"))
        if decision.selected:
            candidates.append({"url": url, "title": title, "reason": f"subpath:{_url_group_key(url)}"})
            seen.add(url)
        else:
            rejected.append({"url": url, "reason": decision.reason})
    return candidates, rejected, terms


def _positive_instruction_text(message: str) -> str:
    return re.split(r"\b(?:exclude|reject|do not include|avoid|remove)\b", message, maxsplit=1, flags=re.IGNORECASE)[0]


def _approval_select_limit(message: str) -> int | None:
    for pattern in (
        r"\b(?:top|first|best|up\s+to)\s+(\d{1,6})\b",
        r"\bchoose\s+(\d{1,6})\b",
        r"\b(\d{1,6})\s+(?:urls?|pages?|links?)\b",
    ):
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            value = int(match.group(1))
            if value > 0:
                return value
    return None


def _message_terms(message: str) -> list[str]:
    message = _positive_instruction_text(message)
    aliases = {
        "registrar": ["registrar", "enrollment-services", "transcript", "records"],
        "calendar": ["academic-calendar", "final-exam", "calendar"],
        "catalog": ["course-catalog", "catalog", "course", "degree", "program"],
        "tuition": ["tuition", "bursar", "billing", "payment", "cost"],
        "aid": ["financial-aid", "financialaid", "scholarship"],
        "housing": ["housing", "dining", "student-life", "health", "counseling", "parking", "orientation", "accessibility"],
        "admission": ["admission", "apply", "application", "transfer", "visit"],
        "cox": ["cox"],
        "dedmanlaw": ["dedmanlaw", "dedman law", "dedman-law"],
        "law": ["law"],
        "dedman": ["dedman", "deadman"],
        "deadman": ["dedman", "deadman"],
        "meadows": ["meadows"],
        "lyle": ["lyle"],
        "simmons": ["simmons"],
        "perkins": ["perkins"],
        "schools": ["cox", "dedman", "dedmanlaw", "meadows", "lyle", "simmons", "perkins"],
    }
    lowered = message.lower()
    terms: list[str] = []
    for key, values in aliases.items():
        if key == "schools":
            if re.search(r"\b(?:schools|colleges)\b", lowered):
                terms.extend(values)
            continue
        if re.search(rf"\b{re.escape(key)}\b", lowered) or any(re.search(rf"\b{re.escape(value)}\b", lowered) for value in values):
            terms.extend(values)
    for token in re.findall(r"[a-z0-9][a-z0-9-]{3,}", lowered):
        if token not in {
            "approve",
            "approved",
            "choose",
            "source",
            "sources",
            "scrape",
            "pages",
            "urls",
            "url",
            "student",
            "students",
            "top",
            "first",
            "best",
            "limit",
            "hundred",
        }:
            terms.append(token)
    deduped: list[str] = []
    for term in terms:
        if term not in deduped:
            deduped.append(term)
    return deduped


def _analysis_terms(message: str) -> list[str]:
    stop = {"how", "many", "count", "counts", "summary", "summarize", "show", "list", "top", "breakdown", "why", "explain", "could", "eligible", "available", "selected", "urls", "url", "select", "selected", "have", "we", "the", "for", "from", "and", "group", "groups"}
    terms: list[str] = []
    for token in re.findall(r"[a-z0-9][a-z0-9-]{2,}", message.lower()):
        if token not in stop and token not in terms:
            terms.append(token)
    return terms


def _url_matches_analysis_terms(url: str, title: str, terms: list[str], *, school_roots: set[str]) -> bool:
    if not terms:
        return True
    if school_roots:
        return _url_school_root(url) in school_roots
    haystack = f"{url}\n{title}".lower()
    return any(term in haystack for term in terms if term not in SCHOOL_TERM_TO_ROOT)


def _approval_analysis(site_id: str, markdown: str, message: str) -> dict[str, Any]:
    rows = read_json(site_root(site_id) / "discovered_urls.json", [])
    selected_urls = set(parse_approved_urls_markdown(markdown))
    terms = _analysis_terms(message)
    school_roots = _school_roots_from_terms(terms)
    eligible_urls: list[str] = []
    matched_eligible_urls: list[str] = []
    reject_reasons: Counter[str] = Counter()
    rejected_samples: list[dict[str, str]] = []
    scoped_rejected_samples: list[dict[str, str]] = []
    root_counts: Counter[str] = Counter()
    path_school_roots = {"cox", "dedman", "dedmanlaw", "law", "lyle", "meadows", "simmons", "perkins"}
    student_roots = {"admission", "enrollment-services", "studentaffairs", "student-life", "libraries", "bursar", "financialaid", "student-financial-services", "housing", "dining"}
    school_or_student = 0

    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "")
        title = str(row.get("title") or "")
        haystack = f"{url}\n{title}".lower()
        if row.get("excluded_reason") == "operator_rejected_area":
            reject_reasons["operator_rejected_area"] += 1
            continue
        decision = classify_url_for_student_wiki(url, title=title, lastmod=row.get("lastmod"))
        if decision.selected:
            eligible_urls.append(url)
            if _url_matches_analysis_terms(url, title, terms, school_roots=school_roots):
                matched_eligible_urls.append(url)
            parts = [part.lower() for part in urlparse(url).path.split("/") if part]
            root = parts[0] if parts else "/"
            root_counts[root] += 1
            if root in path_school_roots or root in student_roots or any(marker in haystack for marker in ("/registrar", "/academic-calendar", "/tuition", "/financial-aid", "/scholarship", "/housing", "/dining", "/health", "/accessibility", "/orientation")):
                school_or_student += 1
        else:
            reject_reasons[decision.reason] += 1
            sample = {"url": url, "reason": decision.reason}
            if len(rejected_samples) < 5:
                rejected_samples.append(sample)
            if _url_matches_analysis_terms(url, title, terms, school_roots=school_roots) and len(scoped_rejected_samples) < 5:
                scoped_rejected_samples.append(sample)

    selected_groups = _url_groups(sorted(selected_urls))
    available_groups = _url_groups(eligible_urls)
    matched_groups = _url_groups(matched_eligible_urls) if terms else available_groups
    return {
        "discovered_total": len(rows) if isinstance(rows, list) else 0,
        "eligible_total": len(eligible_urls),
        "rejected_total": sum(reject_reasons.values()),
        "selected_total": len(selected_urls),
        "school_or_student_total": school_or_student,
        "top_roots": [{"root": root, "count": count} for root, count in root_counts.most_common(15)],
        "top_available_groups": available_groups[:15],
        "matched_terms": terms,
        "matched_school_roots": sorted(school_roots),
        "matched_eligible_total": len(matched_eligible_urls),
        "matched_groups": matched_groups[:15],
        "selected_groups": selected_groups[:15],
        "reject_reasons": [{"reason": reason, "count": count} for reason, count in reject_reasons.most_common()],
        "rejected_samples": scoped_rejected_samples if terms and scoped_rejected_samples else rejected_samples,
    }


def _analysis_message(analysis: dict[str, Any]) -> str:
    lines = [
        f"Discovered {analysis['discovered_total']} URLs.",
        f"Could select {analysis['eligible_total']} policy-eligible URLs.",
        f"Filtered {analysis['rejected_total']} noisy or stale URLs.",
        f"Currently approved {analysis['selected_total']} URLs.",
        f"School or student-service candidate count is {analysis['school_or_student_total']} URLs.",
    ]
    if analysis.get("matched_terms"):
        scope = ", ".join(analysis.get("matched_school_roots") or analysis["matched_terms"])
        lines.append(f"For {scope}, matched {analysis['matched_eligible_total']} eligible URLs after spam filtering.")
    top = analysis.get("matched_groups") or analysis.get("top_available_groups") or []
    if top:
        lines.append("Top selectable subpaths:")
        lines.extend(f"{item['subpath']}: {item['count']}" for item in top[:8])
    reasons = analysis.get("reject_reasons") or []
    if reasons:
        lines.append("Top rejection reasons:")
        lines.extend(f"{item['reason']}: {item['count']}" for item in reasons[:5])
    samples = analysis.get("rejected_samples") or []
    if samples:
        lines.append("Sample rejected noisy URLs:")
        lines.extend(f"{item['url']} ({item['reason']})" for item in samples[:3])
    return "\n".join(lines)


def _operator_intent_from_message(message: str, analysis: dict[str, Any] | None) -> dict[str, Any]:
    lowered = message.lower()
    if any(
        phrase in lowered
        for phrase in (
            "how many",
            "how ",
            "what ",
            "why ",
            "explain",
            "show top",
            "summarize",
            "summary",
            "breakdown",
            "could we select",
        )
    ):
        intent = "analyze"
        terms = _analysis_terms(message)
    elif any(token in lowered for token in ("remove", "delete", "exclude", "filter", "drop", "demote")):
        intent = "remove"
        terms = _removal_terms(message)
    elif any(token in lowered for token in ("approve", "add", "include", "select", "choose", "scrape")):
        intent = "approve"
        terms = _message_terms(message)
    else:
        intent = "analyze"
        terms = _analysis_terms(message)
    response = _analysis_message(analysis) if intent == "analyze" and analysis is not None else ""
    return {
        "provider": "operator",
        "status": "success",
        "intent": intent,
        "terms": terms[:20],
        "response": response,
    }


def approval_chat_payload(site_id: str, request: ApprovedUrlsChatRequest) -> dict[str, Any]:
    message = request.message.strip()
    current = request.markdown if request.markdown is not None else approved_urls_payload(site_id)["markdown"]
    lines_by_url = _approved_url_lines(current)
    removed: list[dict[str, str]] = []
    added: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    terms: list[str] = []
    analysis: dict[str, Any] | None = _approval_analysis(site_id, current, message)
    llm = _operator_intent_from_message(message, analysis)
    intent = str(llm.get("intent") or "").lower()
    if intent not in {"analyze", "approve", "remove"}:
        raise HTTPException(status_code=502, detail=f"URL agent returned invalid intent: {intent or 'missing'}")
    llm_terms = [str(term) for term in llm.get("terms", []) if str(term).strip()]
    exact_path_terms = [f"path:{subpath}" for subpath in _message_subpaths(message)]
    effective_message = " ".join([*llm_terms, *exact_path_terms]) if llm_terms or exact_path_terms else message

    if intent == "remove":
        urls = _message_urls(message)
        terms = llm_terms or ([] if urls else _removal_terms(message))
        for url, line in list(lines_by_url.items()):
            lowered = line.lower()
            matched_url = next((item for item in urls if item == url or item in line), "")
            matched_term = next((term for term in terms if term in lowered), "")
            if matched_url or matched_term:
                removed.append({"url": url, "reason": matched_url or matched_term})
                lines_by_url.pop(url, None)
        if removed:
            assistant_message = f"{'Removed' if request.autosave else 'Proposed removing'} {len(removed)} approved URL(s)."
        else:
            assistant_message = "I did not find matching approved URLs. Paste an exact URL or a distinctive path term."
    elif intent == "approve":
        select_cap = _approval_select_limit(message)
        select_limit = min(request.limit, select_cap) if select_cap else request.limit
        candidates, rejected_rows, terms = _candidate_rows_for_instruction(site_id, effective_message, limit=select_limit)
        rejected = [{"url": str(item.get("url") or ""), "reason": str(item.get("reason") or "") } for item in rejected_rows]
        for item in candidates:
            url = item["url"]
            if url in lines_by_url:
                continue
            label = f" — {item['title']}" if item.get("title") else ""
            lines_by_url[url] = f"- [x] {url}{label}"
            added.append({"url": url, "reason": str(item.get("reason") or "selected")})
        verb = "Added" if request.autosave else "Proposed adding"
        assistant_message = f"{verb} {len(added)} approved URL(s). Rejected {len(rejected)} noisy URL(s)."
    else:
        assistant_message = str(llm.get("response") or "").strip() or _analysis_message(analysis)

    markdown = _render_approved_urls_markdown(lines_by_url, note="Managed by Approval chat. Edit by chatting or changing this file directly.")
    should_save = request.autosave and intent in {"remove", "approve"}
    saved = False
    saved_payload: dict[str, Any] | None = None
    if should_save:
        saved_payload = write_approved_urls_payload(site_id, markdown)
        saved = True
    event = {
        "message": message,
        "base_prompt": request.base_prompt,
        "autosave": request.autosave,
        "added": added,
        "removed": removed,
        "rejected": rejected[:100],
        "approved_count": len(lines_by_url),
        "analysis": analysis,
        "llm": llm,
        "intent": intent,
    }
    _append_approval_chat_event(site_id, event)
    pool = _discovery_url_pool(site_id, extra_exclude_terms=terms if intent == "remove" else [])
    added_urls = [item["url"] for item in added]
    removed_urls = [item["url"] for item in removed]
    rejected_urls = [item["url"] for item in rejected]
    response_markdown = str(saved_payload["markdown"]) if saved_payload else markdown
    response_urls = list(saved_payload["urls"]) if saved_payload else list(lines_by_url)
    response_groups = list(saved_payload["groups"]) if saved_payload else _url_groups(list(lines_by_url))
    response_count = int(saved_payload["count"]) if saved_payload else len(lines_by_url)
    filtered_rejected_urls = list(saved_payload.get("filtered_rejected_urls", [])) if saved_payload else []
    return {
        "site_id": site_id,
        "assistant_message": assistant_message + (" Saved approved_urls.md." if saved else (" Review the proposed URL groups, then click Update approved_urls.md." if intent in {"remove", "approve"} else "")),
        "markdown": response_markdown,
        "urls": response_urls,
        "groups": response_groups,
        "added_groups": _url_groups(added_urls),
        "removed_groups": _url_groups(removed_urls),
        "rejected_groups": _url_groups(rejected_urls),
        "available_groups": pool["groups"],
        "discovery": {"discovered_total": pool["discovered_total"], "eligible_total": pool["eligible_total"], "rejected_total": pool["rejected_total"]},
        "count": response_count,
        "filtered_rejected_urls": filtered_rejected_urls,
        "added": added,
        "removed": removed,
        "rejected": rejected,
        "terms": terms,
        "saved": saved,
        "analysis": analysis,
        "llm": llm,
        "intent": intent,
        "path": str(approved_urls_path(site_id)),
        "generated_at": utc_now(),
    }
