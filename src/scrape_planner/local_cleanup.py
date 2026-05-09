from __future__ import annotations

import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urlparse

import requests

from .observability import append_event
from .state import RunStateStore
from .storage import read_json, write_json

GENERIC_TITLE_PATTERNS = [
    "home",
    "search",
    "menu",
    "close",
    "submit",
    "navigation",
    "main content",
    "untitled page",
]

TOPIC_TAG_RULES: list[tuple[str, list[str]]] = [
    ("admissions", ["admission", "apply", "application", "requirements", "deadline"]),
    ("financial-aid", ["financial aid", "aid", "fafsa", "scholarship", "grant", "tuition", "fees", "cost"]),
    ("academics", ["major", "minor", "degree", "curriculum", "course", "program"]),
    ("student-life", ["housing", "dining", "campus life", "student services", "wellness", "health"]),
    ("registrar", ["registrar", "enrollment", "transcript", "academic calendar"]),
    ("international", ["international", "visa", "f1", "abroad", "study abroad"]),
    ("career", ["career", "internship", "employment", "job", "resume"]),
]

NOISE_LINE_PATTERNS = [
    r"^Local Ollama Cleanup$",
    r"^Queue Status$",
    r"^Realtime Queue$",
    r"^Queue Events$",
    r"^Cleanup Results$",
    r"^Retry Failed URLs with Tavily$",
    r"^Tavily Settings$",
    r"^Claude Plan$",
    r"^Ollama reachable:\s*`?(True|False)`?$",
    r"^Cleanup progress:\s*\d+/\d+\s+done$",
    r"^Pending$",
    r"^Running$",
    r"^Cleaned$",
    r"^Failed$",
    r"^Use Open Preview to open a file in a separate tab via direct link\.?$",
]


def ollama_available(base_url: str = "http://localhost:11434") -> bool:
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def cleanup_markdown_with_ollama(
    markdown: str,
    *,
    model: str,
    base_url: str = "http://localhost:11434",
    max_tokens: int = 2048,
    think: bool = False,
) -> tuple[str, dict[str, Any]]:
    prompt = (
        "You clean scraped markdown for wiki and search indexing.\n"
        "Rules:\n"
        "1) Remove navigation/menu/footer/social/share noise.\n"
        "2) Keep ALL factual content and section headings from source.\n"
        "3) DO NOT compress or summarize away details.\n"
        "4) Preserve all numbers, dates, requirements, exceptions, caveats, and links.\n"
        "5) Do not add facts not present in source.\n"
        "6) Output markdown only in this exact structure:\n"
        "# <Title>\n"
        "## Full Facts Snapshot\n"
        "- Bullets can be long; include complete details, not shortened versions.\n"
        "## Key Insights\n"
        "- highlight implications but keep original factual details intact.\n"
        "## Cleaned Content\n"
        "- preserve near-complete factual body in organized sections.\n\n"
        "Input markdown:\n"
        f"{markdown}"
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": bool(think),
        "options": {
            "temperature": 0.0,
            "top_p": 0.9,
            "num_predict": max_tokens,
            "num_ctx": 8192,
        },
    }
    resp = requests.post(f"{base_url}/api/chat", json=payload, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    message = data.get("message") or {}
    content = str(message.get("content") or data.get("response") or "").strip()
    if not content:
        raise ValueError("ollama_empty_response")
    meta = {
        "prompt_eval_count": data.get("prompt_eval_count"),
        "eval_count": data.get("eval_count"),
        "total_duration": data.get("total_duration"),
        "eval_duration": data.get("eval_duration"),
    }
    return content, meta


def cleanup_markdown_with_openrouter(
    markdown: str,
    *,
    model: str,
    api_key: str,
    max_tokens: int = 2048,
) -> tuple[str, dict[str, Any]]:
    prompt = (
        "You clean scraped markdown for wiki and search indexing.\n"
        "Rules:\n"
        "1) Remove navigation/menu/footer/social/share noise.\n"
        "2) Keep ALL factual content and section headings from source.\n"
        "3) DO NOT compress or summarize away details.\n"
        "4) Preserve all numbers, dates, requirements, exceptions, caveats, and links.\n"
        "5) Do not add facts not present in source.\n"
        "6) Output markdown only in this exact structure:\n"
        "# <Title>\n"
        "## Full Facts Snapshot\n"
        "- Bullets can be long; include complete details, not shortened versions.\n"
        "## Key Insights\n"
        "- highlight implications but keep original factual details intact.\n"
        "## Cleaned Content\n"
        "- preserve near-complete factual body in organized sections.\n\n"
        "Input markdown:\n"
        f"{markdown}"
    )
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": int(max_tokens),
        },
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()
    content = str(data["choices"][0]["message"]["content"] or "").strip()
    if not content:
        raise ValueError("openrouter_empty_response")
    usage = data.get("usage") or {}
    return content, {
        "prompt_eval_count": usage.get("prompt_tokens"),
        "eval_count": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }


def _slugify_tag(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return cleaned[:40]


def _slugify_filename(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return cleaned[:120] or "untitled-page"


def _output_path_for_title(out_dir: Path, title: str) -> Path:
    base = _slugify_filename(title)
    candidate = out_dir / f"{base}.md"
    idx = 2
    while candidate.exists():
        candidate = out_dir / f"{base}-{idx}.md"
        idx += 1
    return candidate


def _title_output_path(out_dir: Path, title: str, current_path: Path | None = None) -> Path:
    base = _slugify_filename(title)
    candidate = out_dir / f"{base}.md"
    if current_path and candidate.exists() and candidate.resolve() == current_path.resolve():
        return candidate
    idx = 2
    while candidate.exists():
        if current_path and candidate.resolve() == current_path.resolve():
            return candidate
        candidate = out_dir / f"{base}-{idx}.md"
        idx += 1
    return candidate


def _rename_cleaned_file_to_title(out_dir: Path, row: dict[str, Any], title: str) -> str | None:
    old_value = str(row.get("cleaned_markdown_path") or "").strip()
    if not old_value:
        return None
    old_path = Path(old_value)
    if not old_path.exists():
        return None
    new_path = _title_output_path(out_dir, title, current_path=old_path)
    if old_path.resolve() != new_path.resolve():
        old_path.rename(new_path)
    return str(new_path)


def _derive_tags(url: str, markdown: str, title: str) -> list[str]:
    text = f"{title}\n{markdown}".lower()
    tags: list[str] = ["source:web"]
    parsed = urlparse(str(url or ""))
    host = parsed.netloc.lower().replace("www.", "")
    if host:
        tags.append(f"domain:{_slugify_tag(host)}")
    path_parts = [p for p in parsed.path.split("/") if p.strip()]
    for seg in path_parts[:3]:
        s = _slugify_tag(seg)
        if len(s) >= 3:
            tags.append(f"path:{s}")
    for topic, keys in TOPIC_TAG_RULES:
        if any(k in text for k in keys):
            tags.append(f"topic:{topic}")
    if re.search(r"\b(deadline|due|by\s+\w+|\d{4})\b", text):
        tags.append("signal:deadline")
    if re.search(r"\b(cost|tuition|fee|scholarship|grant|\$)\b", text):
        tags.append("signal:money")
    if re.search(r"\b(requirement|required|eligibility)\b", text):
        tags.append("signal:requirements")
    if re.search(r"\b(contact|email|phone|office)\b", text):
        tags.append("signal:contact")
    uniq: list[str] = []
    seen: set[str] = set()
    for t in tags:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq[:12]


def _inject_frontmatter(markdown: str, *, title: str, url: str, tags: list[str]) -> str:
    body = markdown.strip()
    tag_line = "[" + ", ".join(f'"{t}"' for t in tags) + "]"
    fm = (
        "---\n"
        f'title: "{title.replace(chr(34), "")}"\n'
        f'source_url: "{url}"\n'
        f"tags: {tag_line}\n"
        "doc_type: cleaned_page\n"
        "---\n\n"
    )
    return fm + body + "\n"


def _extract_first_heading(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            candidate = stripped.lstrip("#").strip()
            if candidate:
                return candidate
    return ""


def _is_generic_title(text: str) -> bool:
    lowered = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not lowered:
        return True
    if len(lowered) < 4:
        return True
    return any(pat == lowered or pat in lowered for pat in GENERIC_TITLE_PATTERNS)


def _strip_generated_title_suffix(title: str) -> str:
    return re.sub(r"\s+\(\d+\)$", "", str(title or "").strip())


def _extract_meaningful_title_from_content(markdown: str) -> str:
    for line in markdown.splitlines():
        candidate = line.strip().lstrip("#").strip()
        if not candidate:
            continue
        if candidate.startswith("[") and "](" in candidate:
            continue
        if _is_generic_title(candidate):
            continue
        # Prefer short factual headings
        if len(candidate) <= 120:
            return candidate
    # fallback: first sentence-like line
    for line in markdown.splitlines():
        candidate = re.sub(r"\s+", " ", line.strip())
        if not candidate or candidate.startswith("#") or candidate.startswith("["):
            continue
        if _is_generic_title(candidate):
            continue
        if 6 <= len(candidate) <= 120:
            return candidate
    return ""


def _title_from_url(url: str) -> str:
    path = urlparse(str(url or "")).path.strip("/")
    if not path:
        return "Untitled Page"
    chunk = path.split("/")[-1].replace("-", " ").replace("_", " ")
    chunk = re.sub(r"\s+", " ", chunk).strip()
    if not chunk:
        return "Untitled Page"
    return chunk.title()


def _base_title_for_page(markdown: str, url: str) -> str:
    heading = _extract_first_heading(markdown)
    if heading and not _is_generic_title(heading):
        return _strip_generated_title_suffix(heading)
    inferred = _extract_meaningful_title_from_content(markdown)
    if inferred:
        return _strip_generated_title_suffix(inferred)
    return _strip_generated_title_suffix(_title_from_url(url))


def _unique_title(base_title: str, used_titles: set[str]) -> str:
    title = (base_title or "Untitled Page").strip()
    key = title.lower()
    if key not in used_titles:
        used_titles.add(key)
        return title
    idx = 2
    while True:
        candidate = f"{title} ({idx})"
        ckey = candidate.lower()
        if ckey not in used_titles:
            used_titles.add(ckey)
            return candidate
        idx += 1


def _apply_title(markdown: str, title: str) -> str:
    lines = markdown.splitlines()
    first_heading_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("#"):
            first_heading_idx = i
            break
    heading_line = f"# {title}"
    if first_heading_idx is None:
        body = markdown.strip()
        return f"{heading_line}\n\n{body}\n" if body else f"{heading_line}\n"
    lines[first_heading_idx] = heading_line
    updated = "\n".join(lines).strip()
    return f"{updated}\n"


def _normalize_fragmented_money_lines(text: str) -> str:
    # Convert OCR-like fragments such as:
    # "6\n,\n390\nt\nu\ni\nt\ni\no\nn\n+\nf\ne\ne\no\nf\n6,390tuition+feeof1,700 = $8,090"
    # into:
    # "6,390 tuition + fee of 1,700 = $8,090"
    def _money_fix(match: re.Match[str]) -> str:
        lhs = re.sub(r"\s+", "", match.group(1))
        rhs = match.group(2)
        return f"{lhs} tuition + fee of {rhs}"

    text = re.sub(
        r"(?<!\d)(\d{1,3}\s*,\s*\d{3})(?:\s*[a-zA-Z]){6,}\s*(\d{1,3}\s*,\s*\d{3}\s*=\s*\$\s*\d[\d,]*)",
        _money_fix,
        text,
        flags=re.IGNORECASE,
    )
    return text


def _remove_ui_leak_lines(markdown: str) -> str:
    noise_regexes = [re.compile(pat, re.IGNORECASE) for pat in NOISE_LINE_PATTERNS]
    kept: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped and any(rx.match(stripped) for rx in noise_regexes):
            continue
        kept.append(line)
    return "\n".join(kept)


def _postprocess_cleaned_markdown(markdown: str) -> str:
    cleaned = markdown.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _normalize_fragmented_money_lines(cleaned)
    cleaned = _remove_ui_leak_lines(cleaned)
    # Avoid very tall spacing after removing noisy lines.
    cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned).strip()
    return f"{cleaned}\n" if cleaned else ""


def _preclean_skip_reason(markdown: str, url: str = "") -> str:
    text = re.sub(r"\s+", " ", str(markdown or "")).strip()
    lowered = text.lower()
    path = urlparse(str(url or "")).path.lower()
    if not text:
        return "empty_markdown"
    if len(text) < 250:
        return "thin_markdown"
    nav_words = sum(1 for key in ["menu", "search", "login", "breadcrumb", "footer", "navigation"] if key in lowered)
    factual_words = sum(1 for key in ["admission", "tuition", "degree", "program", "deadline", "requirement", "course", "scholarship"] if key in lowered)
    if nav_words >= 3 and factual_words == 0:
        return "nav_search_menu_only"
    current_year = datetime.now(timezone.utc).year
    year_matches = [int(y) for y in re.findall(r"\b(20\d{2})\b", path)]
    if year_matches and max(year_matches) <= current_year - 2:
        if re.search(r"(archive|news|stories|events|recipient|profile|scholar|crime|log|spring|summer|fall|winter|term|20\d{2})", path):
            return "stale_historical_archive"
    if re.search(r"/(january|february|march|april|may|june|july|august|september|october|november|december)[-/]?\d{4}", path):
        return "old_monthly_archive"
    if re.search(r"(spring|summer|fall|winter)-20\d{2}|20\d{2}-(spring|summer|fall|winter)", path):
        return "old_term_course_page"
    return ""


def run_sequential_cleanup(
    run_root: Path,
    *,
    model: str,
    base_url: str = "http://localhost:11434",
    max_tokens: int = 2048,
    think: bool = False,
    provider: str = "ollama",
    openrouter_api_key: str = "",
) -> dict[str, Any]:
    pages = read_json(run_root / "scrape_manifest.json", [])
    selected = [p for p in pages if p.get("status") == "success" and p.get("markdown_path")]
    out_dir = run_root / "cleaned_markdown"
    out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    used_titles: set[str] = set()
    for page in selected:
        src_path = Path(page["markdown_path"])
        if not src_path.exists():
            records.append({"url": page.get("url"), "status": "skipped", "reason": "missing_markdown"})
            continue
        try:
            source_markdown = src_path.read_text(encoding="utf-8")
            skip_reason = _preclean_skip_reason(source_markdown, str(page.get("url") or ""))
            if skip_reason:
                records.append({"url": page.get("url"), "status": "skipped", "reason": skip_reason, "source_markdown_path": str(src_path)})
                continue
            if provider == "openrouter":
                cleaned, _meta = cleanup_markdown_with_openrouter(
                    source_markdown,
                    model=model,
                    api_key=openrouter_api_key,
                    max_tokens=max_tokens,
                )
            else:
                cleaned, _meta = cleanup_markdown_with_ollama(
                    source_markdown,
                    model=model,
                    base_url=base_url,
                    max_tokens=max_tokens,
                    think=think,
                )
            cleaned = _postprocess_cleaned_markdown(cleaned)
            base_title = _base_title_for_page(cleaned, str(page.get("url") or ""))
            unique_title = _unique_title(base_title, used_titles)
            cleaned = _apply_title(cleaned, unique_title)
            tags = _derive_tags(str(page.get("url") or ""), cleaned, unique_title)
            cleaned = _inject_frontmatter(
                cleaned,
                title=unique_title,
                url=str(page.get("url") or ""),
                tags=tags,
            )
            out_path = _output_path_for_title(out_dir, unique_title)
            out_path.write_text(cleaned, encoding="utf-8")
            records.append(
                {
                    "url": page.get("url"),
                    "status": "cleaned",
                    "title": unique_title,
                    "tags": tags,
                    "source_markdown_path": str(src_path),
                    "cleaned_markdown_path": str(out_path),
                }
            )
        except Exception as exc:
            records.append({"url": page.get("url"), "status": "failed", "reason": str(exc)})

    write_json(run_root / "cleanup_manifest.json", records)
    return {
        "total": len(selected),
        "cleaned": sum(1 for r in records if r["status"] == "cleaned"),
        "failed": sum(1 for r in records if r["status"] == "failed"),
        "skipped": sum(1 for r in records if r["status"] == "skipped"),
        "manifest_path": str(run_root / "cleanup_manifest.json"),
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CleanupRunner:
    def __init__(self, state: RunStateStore) -> None:
        self.state = state
        self._threads: dict[str, threading.Thread] = {}

    def _key(self, site_id: str, run_id: str) -> str:
        return f"{site_id}:{run_id}"

    def is_active(self, site_id: str, run_id: str) -> bool:
        key = self._key(site_id, run_id)
        thread = self._threads.get(key)
        return bool(thread and thread.is_alive())

    def start(
        self,
        *,
        site_id: str,
        run_id: str,
        run_root: Path,
        model: str,
        base_url: str,
        max_tokens: int,
        concurrency: int,
        think: bool = False,
        provider: str = "ollama",
        openrouter_api_key: str = "",
    ) -> None:
        key = self._key(site_id, run_id)
        if key in self._threads and self._threads[key].is_alive():
            return
        self.state.set_cleanup_cancel(site_id, run_id, False)
        thread = threading.Thread(
            target=self._execute,
            kwargs={
                "site_id": site_id,
                "run_id": run_id,
                "run_root": run_root,
                "model": model,
                "base_url": base_url,
                "max_tokens": max_tokens,
                "concurrency": max(1, concurrency),
                "think": bool(think),
                "provider": provider,
                "openrouter_api_key": openrouter_api_key,
            },
            daemon=True,
        )
        self._threads[key] = thread
        thread.start()

    def cancel(self, site_id: str, run_id: str) -> None:
        self.state.set_cleanup_cancel(site_id, run_id, True)
        status = self.state.get_cleanup_status(site_id, run_id)
        if status:
            status["state"] = "cancelling"
            self.state.set_cleanup_status(site_id, run_id, status)

    def _execute(
        self,
        *,
        site_id: str,
        run_id: str,
        run_root: Path,
        model: str,
        base_url: str,
        max_tokens: int,
        concurrency: int,
        think: bool = False,
        provider: str = "ollama",
        openrouter_api_key: str = "",
    ) -> None:
        pages = read_json(run_root / "scrape_manifest.json", [])
        selected = [p for p in pages if p.get("status") == "success" and p.get("markdown_path")]
        out_dir = run_root / "cleaned_markdown"
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = run_root / "cleanup_manifest.json"
        status_path = run_root / "cleanup_status.json"
        events_path = run_root / "cleanup_events.jsonl"
        existing_items = read_json(manifest_path, [])
        existing_by_url: dict[str, dict[str, Any]] = {}
        if isinstance(existing_items, list):
            for row in existing_items:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or "").strip()
                if url:
                    existing_by_url[url] = row

        items: list[dict[str, Any]] = []
        used_titles: set[str] = set()
        title_lock = threading.Lock()
        for page in selected:
            url = str(page.get("url") or "").strip()
            prev = dict(existing_by_url.get(url, {}))
            status = str(prev.get("status") or "pending").lower()
            cleaned_path = str(prev.get("cleaned_markdown_path") or "")
            cleaned_exists = bool(cleaned_path and Path(cleaned_path).exists() and Path(cleaned_path).stat().st_size > 0)
            # Resume behavior:
            # - keep already cleaned items if artifact exists
            # - recycle in-flight rows to pending on restart
            # - keep failed/skipped as-is (explicit retry can handle them)
            if status == "cleaned" and not cleaned_exists:
                status = "pending"
            if status == "running":
                status = "pending"
            title = str(prev.get("title") or "").strip()
            if status == "cleaned" and cleaned_exists:
                try:
                    text = Path(cleaned_path).read_text(encoding="utf-8", errors="ignore")
                    title = _base_title_for_page(text, url) if text.strip() else title
                    if title:
                        prev["cleaned_markdown_path"] = _rename_cleaned_file_to_title(out_dir, prev, title) or prev.get("cleaned_markdown_path")
                        cleaned_path = str(prev.get("cleaned_markdown_path") or "")
                except Exception:
                    pass
            item = {
                "url": url,
                "status": status if status in {"pending", "running", "cleaned", "failed", "skipped"} else "pending",
                "source_markdown_path": page.get("markdown_path"),
                "cleaned_markdown_path": prev.get("cleaned_markdown_path") if cleaned_exists else None,
                "reason": prev.get("reason"),
                "title": title or prev.get("title"),
            }
            if title:
                used_titles.add(title.lower())
            items.append(item)

        pending0 = sum(1 for i in items if i["status"] == "pending")
        running0 = sum(1 for i in items if i["status"] == "running")
        cleaned0 = sum(1 for i in items if i["status"] == "cleaned")
        failed0 = sum(1 for i in items if i["status"] == "failed")
        skipped0 = sum(1 for i in items if i["status"] == "skipped")

        self.state.set_cleanup_items(site_id, run_id, items)
        previous_status = read_json(status_path, {})
        status_obj = {
            "state": "running",
            "total": len(items),
            "pending": pending0,
            "running": running0,
            "cleaned": cleaned0,
            "failed": failed0,
            "skipped": skipped0,
            "concurrency": concurrency,
            "started_at": previous_status.get("started_at") or _utc_now_iso(),
            "finished_at": None,
            "model": model,
            "base_url": base_url,
            "think": bool(think),
            "provider": provider,
        }
        self.state.set_cleanup_status(
            site_id,
            run_id,
            status_obj,
        )
        write_json(status_path, status_obj)
        write_json(manifest_path, items)
        if not events_path.exists():
            write_json(events_path, [])

        def update_item(idx: int, **patch: Any) -> None:
            items[idx].update(patch)
            self.state.set_cleanup_items(site_id, run_id, items)
            write_json(manifest_path, items)

        def push_cleanup_event(payload: dict[str, Any]) -> None:
            self.state.push_cleanup_event(site_id, run_id, payload)
            existing_events = read_json(events_path, [])
            existing_events.append(payload)
            write_json(events_path, existing_events)

        def update_status() -> None:
            pending = sum(1 for i in items if i["status"] == "pending")
            running = sum(1 for i in items if i["status"] == "running")
            cleaned = sum(1 for i in items if i["status"] == "cleaned")
            failed = sum(1 for i in items if i["status"] == "failed")
            skipped = sum(1 for i in items if i["status"] == "skipped")
            status = self.state.get_cleanup_status(site_id, run_id)
            status.update(
                {
                    "pending": pending,
                    "running": running,
                    "cleaned": cleaned,
                    "failed": failed,
                    "skipped": skipped,
                }
            )
            self.state.set_cleanup_status(site_id, run_id, status)
            write_json(status_path, status)

        def worker(idx: int) -> None:
            row = items[idx]
            src_path = Path(row["source_markdown_path"] or "")
            if not src_path.exists():
                update_item(idx, status="skipped", reason="missing_markdown")
                push_cleanup_event({"ts": _utc_now_iso(), "url": row["url"], "event": "skipped"})
                update_status()
                return
            try:
                source_markdown = src_path.read_text(encoding="utf-8")
                skip_reason = _preclean_skip_reason(source_markdown, str(row.get("url") or ""))
                if skip_reason:
                    update_item(idx, status="skipped", reason=skip_reason)
                    push_cleanup_event({"ts": _utc_now_iso(), "url": row["url"], "event": "skipped", "reason": skip_reason})
                    update_status()
                    return
                update_item(idx, status="running")
                update_status()
                t0 = time.perf_counter()
                if provider == "openrouter":
                    cleaned, meta = cleanup_markdown_with_openrouter(
                        source_markdown,
                        model=model,
                        api_key=openrouter_api_key,
                        max_tokens=max_tokens,
                    )
                else:
                    cleaned, meta = cleanup_markdown_with_ollama(
                        source_markdown,
                        model=model,
                        base_url=base_url,
                        max_tokens=max_tokens,
                        think=think,
                    )
                cleaned = _postprocess_cleaned_markdown(cleaned)
                base_title = _base_title_for_page(cleaned, str(row.get("url") or ""))
                with title_lock:
                    unique_title = _unique_title(base_title, used_titles)
                cleaned = _apply_title(cleaned, unique_title)
                tags = _derive_tags(str(row.get("url") or ""), cleaned, unique_title)
                cleaned = _inject_frontmatter(
                    cleaned,
                    title=unique_title,
                    url=str(row.get("url") or ""),
                    tags=tags,
                )
                latency_ms = int((time.perf_counter() - t0) * 1000)
                out_path = _output_path_for_title(out_dir, unique_title)
                out_path.write_text(cleaned, encoding="utf-8")
                if out_path.stat().st_size == 0:
                    raise ValueError("cleaned_markdown_empty_after_write")
                update_item(idx, status="cleaned", cleaned_markdown_path=str(out_path), title=unique_title, tags=tags)
                push_cleanup_event({"ts": _utc_now_iso(), "url": row["url"], "event": "cleaned"})
                append_event(
                    run_root,
                    {
                        "provider": provider,
                        "operation": "cleanup_page",
                        "status": "success",
                        "url": row["url"],
                        "model": model,
                        "latency_ms": latency_ms,
                        "prompt_tokens": meta.get("prompt_eval_count"),
                        "completion_tokens": meta.get("eval_count"),
                    },
                )
            except Exception as exc:
                update_item(idx, status="failed", reason=str(exc))
                push_cleanup_event({"ts": _utc_now_iso(), "url": row["url"], "event": "failed"})
                append_event(
                    run_root,
                    {
                        "provider": provider,
                        "operation": "cleanup_page",
                        "status": "failed",
                        "url": row["url"],
                        "model": model,
                        "error": str(exc),
                    },
                )
            update_status()

        # Only process pending rows; this preserves previous work on resume.
        pending_indices = [idx for idx, row in enumerate(items) if str(row.get("status") or "").lower() == "pending"]
        futures = {}
        next_idx = 0
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            while next_idx < len(pending_indices) or futures:
                if self.state.get_cleanup_cancel(site_id, run_id):
                    break
                while next_idx < len(pending_indices) and len(futures) < concurrency:
                    idx = pending_indices[next_idx]
                    futures[pool.submit(worker, idx)] = idx
                    next_idx += 1
                if futures:
                    done, _ = wait(futures.keys(), timeout=0.5, return_when=FIRST_COMPLETED)
                    for d in done:
                        futures.pop(d, None)

        write_json(manifest_path, items)
        pending_left = sum(1 for i in items if i["status"] == "pending")
        running_left = sum(1 for i in items if i["status"] == "running")
        cancel_requested = self.state.get_cleanup_cancel(site_id, run_id)
        if cancel_requested:
            final_state = "cancelled"
        elif pending_left == 0 and running_left == 0:
            final_state = "completed"
        else:
            final_state = "interrupted"
        status = self.state.get_cleanup_status(site_id, run_id)
        status["state"] = final_state
        status["pending"] = pending_left
        status["running"] = running_left
        status["finished_at"] = _utc_now_iso()
        self.state.set_cleanup_status(site_id, run_id, status)
        write_json(status_path, status)
