#!/usr/bin/env python3
"""Regenerate fixtures/demo-workspace for first-run Docker and local bootstrap."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

os.environ.setdefault("LLM_WIKI_ALLOW_HASH_FALLBACK", "1")

from src.scrape_planner.core.storage import write_json
from src.scrape_planner.sources.source_registry import write_registry_rows
from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index
from tests.fixtures.llm_wiki import NOW, _fixture_site, _write_source, _write_wiki_page

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "demo-workspace"
SITE_ID = "codex.test.edu"
SITE_URL = "http://codex.test.edu"


def _build_site() -> Path:
    build_root = ROOT / ".tmp-demo-workspace-build"
    if build_root.exists():
        shutil.rmtree(build_root)
    site_root = _fixture_site(build_root)

    tuition_row = _write_source(
        site_root,
        source_id="web_tuition",
        title="Tuition Raw",
        body="# Tuition Raw\n\nUndergraduate tuition is $58,000 per year before aid.\n",
    )
    tuition_row["wiki_page_paths"] = ["wiki/pages/tuition-and-aid.md"]
    registry_path = site_root / "raw_sources" / "registry.jsonl"
    rows = [json.loads(line) for line in registry_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows.append(tuition_row)
    write_registry_rows(registry_path, rows)

    _write_wiki_page(
        site_root,
        name="tuition-and-aid",
        title="Tuition and Aid",
        tags=["tuition", "financial-aid"],
        source_ids=["web_tuition"],
        body="# Tuition and Aid\n\nUndergraduate tuition is $58,000 per year before aid.\n",
    )
    _write_wiki_page(
        site_root,
        name="index",
        title="Codex Fixture University",
        tags=["overview"],
        source_ids=["web_admissions", "web_tuition"],
        body="# Codex Fixture University\n\nDemo workspace shipped with Ultra Fast RAG for first-run setup.\n",
    )
    (site_root / "wiki" / "index.md").write_text(
        "# Codex Fixture University\n\nOpen a workspace below to explore admissions and tuition pages.\n",
        encoding="utf-8",
    )
    write_json(
        site_root / "discovery_summary.json",
        {
            "site_id": SITE_ID,
            "site_url": SITE_URL,
            "name": "Codex Fixture University",
            "discovered_total": 5,
            "eligible_total": 5,
            "rejected_total": 0,
            "excluded_by_policy": 0,
            "sitemap_sources": ["fixture"],
            "notes": ["Bundled demo workspace for first-run bootstrap."],
            "generated_at": NOW,
        },
    )
    build_llm_wiki_index(site_root, now=NOW)
    return site_root


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    site_root = _build_site()
    dest_site = OUT / "sites" / SITE_ID
    dest_site.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(site_root, dest_site)

    write_json(
        OUT / "app_state.json",
        {
            "active_workspace_id": SITE_ID,
            "workspaces": [
                {
                    "id": SITE_ID,
                    "name": "Codex Fixture University",
                    "url": SITE_URL,
                }
            ],
            "last_site_url": SITE_URL,
            "last_site_id": SITE_ID,
            "site_history": [SITE_URL],
            "openrouter_api_key": "",
            "tavily_api_key": "",
            "gemini_api_key": "",
        },
    )

    build_root = ROOT / ".tmp-demo-workspace-build"
    if build_root.exists():
        shutil.rmtree(build_root)

    print(f"Wrote demo workspace to {OUT}")


if __name__ == "__main__":
    main()
