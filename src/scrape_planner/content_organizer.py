from __future__ import annotations

from pathlib import Path


def build_content_organizer_task(
    *,
    run_root: Path,
    site_url: str,
    run_id: str,
    skill_path: Path,
) -> str:
    return f"""# Content Organizer Task

Use the Pi skill at:
`{skill_path}`

## Inputs

- run_root: `{run_root}`
- site_url: `{site_url}`
- run_id: `{run_id}`
- scrape_manifest: `{run_root / "scrape_manifest.json"}`
- cleanup_manifest: `{run_root / "cleanup_manifest.json"}`
- source_exclusion_plan: `{run_root.parent / "source_exclusion_plan.json"}`

## Required work

1. Read the skill file exactly.
2. Inspect cleaned markdown first; fall back to raw scrape markdown only when cleaned output is missing.
3. Keep raw scrape artifacts untouched.
4. Quarantine useless, thin, duplicate, navigation-only, stale news/event, or irrelevant pages from final wiki organization.
5. Organize useful content into school, department, office/service, academic program, document, and people/professor groups.
6. Put people/professor profiles under their identifiable school or department when evidence exists.
7. Write final artifacts:
   - `{run_root / "wiki" / "index.md"}`
   - `{run_root / "wiki" / "graph.json"}`
   - `{run_root / "wiki" / "pages"}`
   - `{run_root / "content_organizer" / "quarantine.json"}`
   - `{run_root / "content_organizer" / "report.md"}`

Do not invent facts. Preserve source URLs in every generated page.
"""
