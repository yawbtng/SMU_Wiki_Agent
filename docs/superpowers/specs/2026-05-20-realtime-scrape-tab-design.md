# Realtime Scrape Tab Design

## Goal

Make the Scrape tab minimal, realtime, and fast. The tab should feel like a live monitor rather than a dense data-management page. It must also make pause and resume behavior obvious so continuing a run does not look like starting over.

## Current Context

The Streamlit app currently renders the Scrape tab in `app.py`. It shows command buttons, concurrency, auto-refresh, seven run metrics, retry actions, filters, and a paginated page table in one visible flow. Runtime data comes from `_load_scrape_runtime`, `RunStateStore`, `pages.jsonl`, `run_status.json`, and run artifacts under `data/sites/<site_id>/<run_id>/`.

`ScrapeRunner.resume()` already attempts to reuse existing successful page states and skip successful URLs. The confusing behavior comes from two places:

- `Start Scrape` always creates a new run, so using it after a pause starts from the beginning by design.
- `_execute()` rebuilds the visible run state for the selected URL set and re-emits queued states for unfinished rows, which can make a resumed run look like a fresh run even when successful pages are preserved.

## Design Direction

Use a realtime activity stream with scraped-page preview links.

The Scrape tab stays focused on the current run: command bar, compact health, active workers/current URLs, recently scraped pages, and current failures. The full detailed page table remains available behind an expander, not in the default view.

Successful scraped pages get an `Open preview` link that opens a dedicated rendered markdown preview in a new browser page.

## Scrape Tab Layout

### Command Bar

The top command bar should be compact and explicit:

- `Start New Scrape`: creates a new run ID and starts from selected URLs.
- `Pause`: requests pause for the active run.
- `Resume Current Run`: continues the same run from saved page state.
- `Cancel`: cancels the active run.
- `Refresh` and `Auto-refresh` controls.
- Selected URL count and active run ID.

The copy should avoid ambiguity. `Start New Scrape` must not be presented as the way to continue after pausing.

### Live Health

Show a small status header with:

- State
- Progress count and percentage
- Running count
- Success count
- Failed count
- Remaining count
- Pages per minute

If status is still initializing, derive totals from selected URLs and show a loading state instead of blank content.

### Realtime Activity

Default activity should emphasize what changed recently:

- Currently running URLs, grouped by worker when available.
- Latest successful pages, newest first.
- Latest failures, newest first.
- Short event stream for run lifecycle and page completion events.

The default view should only show a small number of rows per section. Full detail stays in expanders.

### Full Detail

The existing detailed page table remains useful, but it should be collapsed by default under a label like `All pages and filters`. Existing filtering and pagination can remain there to avoid losing functionality.

## Scraped Page Preview

Add a top-level Streamlit preview route using query parameters. When the query contains `view=scraped_page`, the app renders a dedicated preview page instead of the normal workflow tabs.

The route should identify the page by stable URL slug, with the source URL shown after lookup:

- `site_id`
- `run_id`
- `page_slug`, derived with the existing scrape-worker SHA1 URL slug convention

The preview loads the saved markdown artifact from the run's `markdown/` directory and renders it with `st.markdown`. It also shows:

- Source URL
- Run ID
- HTTP status if available
- Fetch mode if available
- Text length if available

If no markdown artifact exists yet, the preview shows a loading/not-ready state rather than an error-heavy page.

Preview links from the scrape tab should open in a new browser page. Use an HTML anchor rendered through Streamlit markdown with `target="_blank"` and a query string containing `view=scraped_page`, `site_id`, `run_id`, and `page_slug`.

## Pause And Resume Behavior

Pause and resume must be explicit and testable:

- `Start New Scrape` always starts from the selected URL list with a new run ID.
- `Pause` keeps the current run ID and waits for in-flight pages to finish.
- `Resume Current Run` keeps the same run ID and only processes unfinished pages.
- Existing successful pages must stay successful and must not be fetched again.
- Queued, paused, cancelled, failed, or interrupted pages are eligible to continue.
- The UI should label resumed work as continuing the current run, not starting over.

The implementation plan should include tests that prove resume does not call the fetcher for already-successful pages, using persisted `pages.jsonl` or state store data.

## Loading States

The Scrape tab should always show a clear state:

- Starting: `Starting run...` with selected URL count.
- Initializing: `Preparing queue...` with a spinner or status placeholder.
- Running before first completion: show queued/running counts and loading indicators.
- Pausing: `Pausing after in-flight pages finish...`.
- Paused: show completed and remaining counts, plus `Resume Current Run` as the primary action.
- Resuming: `Continuing from last saved page state...`.
- Preview loading: `Scraped markdown is not ready yet.` if the artifact is missing.

These states should avoid blank screens and avoid implying that pause/resume lost progress.

## Data Flow

The UI should continue to read from existing sources:

- `run_status.json` for run state and counts.
- `pages.jsonl` and in-memory/Redis page state for per-page status.
- Markdown artifacts under `markdown/` for preview rendering.
- Metadata artifacts under `metadata/` for preview context.

No scrape worker API contract change is required for the initial UI redesign. Worker changes should be limited to fixing resume-state correctness if tests expose a real skip/persistence bug.

## Testing

Add or update tests for:

- Resume skips already-successful pages and only fetches unfinished pages.
- Resume can use persisted page state, not only in-memory state.
- Preview route resolves a markdown artifact from a page row or URL slug.
- Missing preview markdown produces a friendly not-ready state.

For Streamlit-only rendering that is difficult to unit test directly, extract small pure helpers for preview URL generation, markdown path resolution, and run summary derivation.

## Acceptance Criteria

- The Scrape tab default view is minimal and realtime-first.
- Full page details are collapsed by default.
- Successful pages expose an `Open preview` link that opens rendered markdown in a new page.
- Pause and resume controls make it clear whether the user is starting new or continuing current work.
- Resuming a run does not re-fetch successful pages.
- Starting, pausing, paused, resuming, and preview-loading states are visible and non-blank.
