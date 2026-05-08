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


def _read_source_files(run_root: Path) -> list[dict[str, Any]]:
    cleanup_rows = read_json(run_root / "cleanup_manifest.json", [])
    scrape_rows = read_json(run_root / "scrape_manifest.json", [])
    sources: list[dict[str, Any]] = []

    for row in cleanup_rows:
        path = row.get("cleaned_markdown_path")
        if row.get("status") == "cleaned" and path and Path(path).exists():
            sources.append({"url": row.get("url"), "path": path, "text": Path(path).read_text(encoding="utf-8", errors="ignore")})

    if sources:
        return sources

    for row in scrape_rows:
        path = row.get("markdown_path")
        if row.get("status") == "success" and path and Path(path).exists():
            sources.append({"url": row.get("url"), "path": path, "text": Path(path).read_text(encoding="utf-8", errors="ignore")})
    return sources


def suggest_wiki_topics(run_root: Path, max_sources_per_topic: int = 12) -> dict[str, Any]:
    sources = _read_source_files(run_root)
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

