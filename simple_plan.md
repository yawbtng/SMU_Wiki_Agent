# Simple UI Cleanup Plan

Goal: make the app feel like one clear scrape pipeline, not a pile of debugging tools.

## Product Shape

Use one linear workflow:

1. Setup
2. Discover
3. Scrape
4. Clean
5. Review
6. Settings

The normal user should never see raw queue JSON, tmux internals, huge debug tables, or duplicate workspace/site controls unless they open an Advanced section.

## Phase 1: Rename And Simplify Navigation

- Rename tabs:
  - `Workspace` -> `Setup`
  - remove `Choose URLs`
  - `Cleanup` -> `Clean`
  - `Metrics` -> `Review`
- Keep `Discover`, `Scrape`, `Settings`.
- Remove duplicate or repeated helper text.
- Keep tab order: `Setup`, `Discover`, `Scrape`, `Clean`, `Review`, `Settings`.

## Phase 2: Simplify Setup Tab

Replace the current dashboard with a compact summary:

- Workspace name
- Site URL
- Active run ID
- One primary next-step hint

Hide these in expanders:

- Change active site URL
- Manage workspaces
- Workspace deletion
- Recent sites

No big metric cards. No giant truncated values.

## Phase 3: Simplify Discover Tab

Normal view:

- One primary button: `Refresh Sitemap URLs`
- Show:
  - discovered URL count
  - sitemap source count
  - last refreshed time

Advanced expander:

- raw discovered URL table
- manual URL input
- sitemap notes

## Phase 4: Replace Choose URLs With Do-Not-Parse Planning

Normal view:

- Button: `Build Do-Not-Parse Plan`
- Scrape queue count
- Excluded count
- Exclusion category summary
- Show counts:
  - discovered
  - scrape candidates
  - do-not-parse URLs
  - sitemap sources

Advanced expander:

- manual URL input
- raw discovered URL table
- raw source exclusion plan

Important behavior:

- Do not rank usefulness before scraping.
- Exclude only obvious spam, login/search/filter/feed/archive/news/event/media pages.
- Scrape departments, offices, programs, PDFs, and people/professor pages.

## Phase 5: Simplify Scrape Tab

Normal view:

- One primary button: `Start Scrape`
- Clear status row:
  - queued
  - running
  - completed
  - failed
- Realtime table should show only currently running pages.
- Failed URL retry belongs here.

Advanced expander:

- full queue table
- raw events
- failure export
- debug logs

## Phase 6: Simplify Clean Tab

Normal view:

- Provider selector:
  - `OpenRouter recommended`
  - `Ollama local`
- Model selector based on provider.
- One primary button: `Start Cleaning`
- Show progress:
  - pending
  - running
  - cleaned
  - skipped
  - failed

Hide queue JSON and events under Advanced.

Cleanup results:

- Show only cleaned files.
- Include title, tags, source URL, preview link.
- Preview opens via link.

## Phase 7: Add Pre-Clean Skip Rules

Before LLM cleanup, skip pages that are clearly not useful:

- missing markdown
- empty/thin markdown
- nav/search/menu-only pages
- stale historical archive pages
- old monthly crime logs
- old term course pages when current canonical pages exist
- yearly profile/recipient pages unless explicitly selected
- duplicate title/content pages

Record skip reason in manifest.

## Phase 8: OpenRouter Cleanup Path

Add OpenRouter as a first-class cleanup provider.

- Use `OPENROUTER_API_KEY` from `.env` / Settings.
- Keep Ollama as local fallback.
- Track provider, model, prompt tokens, completion tokens, latency, and estimated cost.
- Prefer OpenRouter for high-quality cleanup if local models produce bad markdown.

## Phase 9: Review Tab

Merge useful metrics into Review.

Show:

- queued URLs
- scraped pages
- cleaned pages
- skipped pages
- failed pages
- estimated cost
- average scrape duration
- average cleanup duration

Also show:

- searchable cleaned files table
- preview links
- content organizer task/report/quarantine

Avoid charts unless they answer a real question.

## Phase 10: Settings Cleanup

Settings should only contain:

- OpenRouter key
- OpenRouter model
- Ollama base URL
- Ollama model
- provider defaults
- cost settings

Remove model/provider controls from other tabs unless needed for the immediate action.

## Validation Checklist

After implementation:

- App starts at `http://127.0.0.1:8501`.
- Inside SMU workspace does not look like workspace creation screen.
- User can follow: Discover -> Scrape -> Clean -> Review.
- Do-not-parse planning excludes obvious spam/news/archive/search/filter/feed pages.
- Scrape realtime view shows running pages only by default.
- Clean results show cleaned files only.
- Advanced/debug internals are hidden by default.
- No raw queue JSON in normal user view.
- No empty cleaned markdown files.
- Cleaned filenames use content-based unique titles.

## Commit Strategy

Commit after each completed phase with a short message, for example:

- `Simplify navigation tabs`
- `Clean up setup dashboard`
- `Simplify discover flow`
- `Replace URL selection with source exclusion`
- `Simplify scrape cockpit`
- `Simplify cleanup flow`
- `Add cleanup skip rules`
- `Add OpenRouter cleanup provider`
- `Merge metrics into review`
- `Clean up settings`
