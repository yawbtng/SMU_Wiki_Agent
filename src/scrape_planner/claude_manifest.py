from __future__ import annotations

from pathlib import Path
from typing import Any

from .storage import read_json, write_json


def build_claude_manifest(run_root: Path, site_url: str, run_id: str) -> dict[str, Any]:
    pages = read_json(run_root / "scrape_manifest.json", [])
    failures = read_json(run_root / "failures.json", [])
    success_pages = [item for item in pages if item.get("status") == "success"]
    manifest = {
        "site_url": site_url,
        "run_id": run_id,
        "successful_pages": [
            {
                "url": item["url"],
                "markdown_path": item.get("markdown_path"),
                "metadata_path": item.get("metadata_path"),
                "raw_html_path": item.get("raw_html_path"),
                "text_length": item.get("text_length", 0),
                "fetch_mode": item.get("fetch_mode"),
            }
            for item in success_pages
        ],
        "failures": failures,
        "counts": {"success": len(success_pages), "failed": len(failures)},
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
2. Remove leftover boilerplate/navigation artifacts.
3. Group pages into a wiki taxonomy.
4. Produce a deterministic wiki index with stable section/page slugs.
5. Emit a failure appendix from `failures`.

Output format:
- `wiki/index.md` with section links and page counts.
- `wiki/pages/<slug>.md` for cleaned pages.
- `wiki/failures.md` summarizing failed URLs and likely next action.

Constraints:
- Do not invent facts not present in source markdown.
- Prefer canonical URLs when duplicates are present.
- Keep headings short and stable.
"""

