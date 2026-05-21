from __future__ import annotations

from pathlib import Path
from typing import Any

from .storage import read_json, write_json
from .wiki_planner import normalize_corpus_sources


def build_claude_manifest(run_root: Path, site_url: str, run_id: str) -> dict[str, Any]:
    pages = normalize_corpus_sources(run_root)
    failures = read_json(run_root / "failures.json", [])
    manifest = {
        "site_url": site_url,
        "run_id": run_id,
        "successful_pages": [
            {
                "url": item.get("url"),
                "markdown_path": item.get("path"),
                "title": item.get("title"),
                "source_type": item.get("source_type"),
                "source_path": item.get("source_path"),
                "metadata_path": item.get("metadata_path"),
                "raw_html_path": item.get("raw_html_path"),
                "text_length": item.get("text_length", 0),
                "fetch_mode": item.get("fetch_mode"),
            }
            for item in pages
        ],
        "failures": failures,
        "counts": {"success": len(pages), "failed": len(failures)},
    }
    write_json(run_root / "claude_wiki_manifest.json", manifest)
    prompt = _build_prompt(manifest)
    (run_root / "claude_wiki_prompt.md").write_text(prompt, encoding="utf-8")
    return manifest


def _build_prompt(manifest: dict[str, Any]) -> str:
    return f"""# Claude Wiki Build Prompt

You are given scrape outputs for site `{manifest["site_url"]}` and run `{manifest["run_id"]}`.

Tasks:
1. Read each markdown file from `successful_pages`.
2. Treat `source_type=document_markdown` items as first-class corpus sources alongside web pages.
3. Remove leftover boilerplate/navigation artifacts.
4. Group pages into a wiki taxonomy.
5. Produce a deterministic wiki index with stable section/page slugs.
6. Emit a failure appendix from `failures`.

Output format:
- `wiki/index.md` with section links and page counts.
- `wiki/pages/<slug>.md` for cleaned pages.
- `wiki/failures.md` summarizing failed URLs and likely next action.

Constraints:
- Do not invent facts not present in source markdown.
- Prefer canonical URLs when duplicates are present.
- Keep headings short and stable.
"""
