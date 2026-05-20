---
name: content-organizer
description: Organizes scraped and cleaned university content into a graph-style wiki after scraping, quarantining useless pages while preserving raw artifacts.
---

<objective>
Turn scraped university content into a useful, source-grounded wiki organized by school, department, office, service, document, and people/professor profiles. Do not run URL ranking. Work only after scraping/cleanup has produced content.
</objective>

<inputs>
Expect a task file that names:
- `run_root`
- `site_url`
- `run_id`
- `scrape_manifest`
- `cleanup_manifest`
- `source_exclusion_plan`

Read cleaned markdown from `cleanup_manifest` first. If a page was scraped successfully but has no cleaned markdown, inspect its raw markdown path from `scrape_manifest`.
</inputs>

<process>
1. Load manifests and build a source inventory with URL, local markdown path, title if available, status, text length, and source type.
2. Classify each usable source into one of these buckets:
   - `school`
   - `department`
   - `office_service`
   - `academic_program`
   - `policy`
   - `document`
   - `people_profile`
   - `general_page`
   - `quarantine`
3. Quarantine pages that are useless for final wiki output:
   - empty or navigation-only content
   - duplicate pages where a stronger canonical source exists
   - stale news, event, story, or press content
   - login/search/filter/feed/archive leftovers
   - thin people pages with no department/school or useful facts
4. Organize retained pages:
   - people/professors under the most specific school or department supported by source text
   - offices/services under office or student-service groups
   - academic material under school -> department -> program/course/policy when identifiable
   - documents/PDFs under the department, office, or topic they support
5. Write wiki pages that preserve factual content and source URLs. Do not invent relationships when evidence is missing; place uncertain sources in an `Unassigned` group.
</process>

<outputs>
Write these files under `run_root`:
- `wiki/index.md`
- `wiki/graph.json`
- `wiki/pages/<stable-slug>.md`
- `content_organizer/quarantine.json`
- `content_organizer/report.md`

`graph.json` must include:
- `nodes`: each node has `id`, `type`, `label`, `source_urls`, and optional `path`
- `edges`: each edge has `source`, `target`, and `relation`
- `quarantined_count`
- `organized_count`

`quarantine.json` must include one row per excluded final-output source with `url`, `path`, `reason`, and `recommended_action`.
</outputs>

<rules>
- Never delete raw scrape files, raw HTML, metadata, scrape manifests, or source markdown.
- "Delete useless" means remove from final wiki organization and record in quarantine.
- Use only facts present in the source files.
- Prefer canonical department, office, catalog, policy, and service pages over dated stories or event pages.
- Keep source URLs visible in generated markdown.
- If required inputs are missing, write `content_organizer/report.md` with the blocker and stop cleanly.
</rules>

<success_criteria>
The run is complete when `wiki/index.md`, `wiki/graph.json`, `content_organizer/quarantine.json`, and `content_organizer/report.md` exist, and the report summarizes organized pages, quarantined pages, uncertain/unassigned pages, and any blockers.
</success_criteria>
