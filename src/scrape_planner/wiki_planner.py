from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .storage import read_json, write_json


DEFAULT_TOPIC_PATTERNS = {
    "Departments Wiki": [
        "department",
        "school of",
        "college of",
        "faculty",
        "academic units",
    ],
    "Finance Wiki": [
        "tuition",
        "fees",
        "cost",
        "financial aid",
        "billing",
        "payment",
        "student accounts",
    ],
    "Scholarships Wiki": [
        "scholarship",
        "grant",
        "fellowship",
        "aid",
        "award",
    ],
    "Admissions Wiki": [
        "admission",
        "apply",
        "application",
        "deadline",
        "requirements",
    ],
    "Programs Wiki": [
        "program",
        "degree",
        "major",
        "minor",
        "graduate",
        "undergraduate",
    ],
    "Student Life Wiki": [
        "housing",
        "dining",
        "campus life",
        "student services",
        "health",
        "orientation",
    ],
    "Registrar Wiki": [
        "registrar",
        "calendar",
        "transcript",
        "enrollment",
        "course catalog",
        "academic records",
    ],
}


def normalize_corpus_sources(run_root: Path) -> list[dict[str, Any]]:
    cleanup_rows = read_json(run_root / "cleanup_manifest.json", [])
    scrape_rows = read_json(run_root / "scrape_manifest.json", [])
    document_rows = read_json(run_root / "document_ingest" / "manifest.json", [])
    sources: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    cleaned_urls: set[str] = set()

    def _append_source(
        *,
        source_type: str,
        path_value: str,
        text: str,
        url: str = "",
        title: str = "",
        source_path: str = "",
        metadata_path: str = "",
        raw_html_path: str = "",
        text_length: int | None = None,
        fetch_mode: str = "",
    ) -> None:
        normalized_path = str(path_value).strip()
        if not normalized_path or normalized_path in seen_paths:
            return
        seen_paths.add(normalized_path)
        sources.append(
            {
                "source_type": source_type,
                "url": str(url or "").strip(),
                "path": normalized_path,
                "title": str(title or Path(normalized_path).stem),
                "text": text,
                "source_path": str(source_path or "").strip(),
                "metadata_path": str(metadata_path or "").strip(),
                "raw_html_path": str(raw_html_path or "").strip(),
                "text_length": int(text_length) if text_length is not None else len(text),
                "fetch_mode": str(fetch_mode or "").strip(),
            }
        )

    for row in cleanup_rows:
        path = row.get("cleaned_markdown_path")
        if row.get("status") == "cleaned" and path and Path(path).exists():
            url = str(row.get("url") or "").strip()
            if url:
                cleaned_urls.add(url)
            _append_source(
                source_type="cleaned_markdown",
                url=url,
                title=str(row.get("title") or ""),
                path_value=str(path),
                text=Path(path).read_text(encoding="utf-8", errors="ignore"),
                source_path=str(row.get("source_markdown_path") or ""),
                text_length=row.get("text_length"),
            )

    for row in document_rows if isinstance(document_rows, list) else []:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").strip().lower()
        if status and status not in {"converted", "ready", "success"}:
            continue
        path = str(row.get("converted_markdown_path") or row.get("markdown_path") or "").strip()
        if not path or not Path(path).exists():
            continue
        _append_source(
            source_type="document_markdown",
            url=str(row.get("url") or "").strip(),
            title=str(row.get("title") or ""),
            path_value=path,
            text=Path(path).read_text(encoding="utf-8", errors="ignore"),
            source_path=str(row.get("source_path") or row.get("input_path") or ""),
            text_length=row.get("text_length"),
        )

    for row in scrape_rows:
        path = row.get("markdown_path")
        url = str(row.get("url") or "").strip()
        if url in cleaned_urls:
            continue
        if row.get("status") == "success" and path and Path(path).exists():
            _append_source(
                source_type="scraped_markdown",
                url=url,
                title=str(row.get("title") or ""),
                path_value=str(path),
                text=Path(path).read_text(encoding="utf-8", errors="ignore"),
                metadata_path=str(row.get("metadata_path") or ""),
                raw_html_path=str(row.get("raw_html_path") or ""),
                text_length=row.get("text_length"),
                fetch_mode=str(row.get("fetch_mode") or ""),
            )
    return sources


def suggest_wiki_topics(run_root: Path, max_sources_per_topic: int = 12) -> dict[str, Any]:
    sources = normalize_corpus_sources(run_root)
    topic_rows = []
    for topic, patterns in DEFAULT_TOPIC_PATTERNS.items():
        matches = []
        for source in sources:
            text = source["text"].lower()
            score = sum(len(re.findall(re.escape(pattern), text)) for pattern in patterns)
            url = (source.get("url") or "").lower()
            score += sum(5 for pattern in patterns if pattern.replace(" ", "-") in url or pattern in url)
            if score > 0:
                matches.append(
                    {
                        "url": source.get("url"),
                        "path": source.get("path"),
                        "score": score,
                    }
                )
        matches.sort(key=lambda item: item["score"], reverse=True)
        topic_rows.append(
            {
                "topic": topic,
                "selected": len(matches) > 0,
                "source_count": len(matches),
                "top_sources": matches[:max_sources_per_topic],
            }
        )
    topic_rows.sort(key=lambda item: item["source_count"], reverse=True)
    result = {"topics": topic_rows, "source_count": len(sources)}
    write_json(run_root / "wiki_topic_plan.json", result)
    return result


def build_topic_wiki_prompt(run_root: Path, selected_topics: list[dict[str, Any]]) -> str:
    prompt = """# Topic Wiki Build Prompt

Build focused, student-useful wiki pages from the source markdown files below.

Required output:
- wiki/index.md
- wiki/pages/departments.md when selected
- wiki/pages/finance.md when selected
- wiki/pages/scholarships.md when selected
- one page per selected topic using stable lowercase slugs

Rules:
- Use only facts present in source markdown.
- Prefer current/recent content when sources conflict.
- Include a Sources section with source URLs or file paths.
- Add related wikilinks between pages.
- Keep pages useful for current and prospective students.

Selected topics and source files:
"""
    for topic in selected_topics:
        if not topic.get("selected"):
            continue
        prompt += f"\n## {topic['topic']}\n"
        for source in topic.get("top_sources", []):
            prompt += f"- {source.get('path')} | {source.get('url')} | score={source.get('score')}\n"
    (run_root / "topic_wiki_prompt.md").write_text(prompt, encoding="utf-8")
    return prompt
