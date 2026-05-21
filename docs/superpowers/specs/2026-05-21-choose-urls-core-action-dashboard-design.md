# URL Action Dashboard Design

## Goal

Replace the legacy Choose URLs experience with a compact Scrape-stage action dashboard that answers what to do next, instead of leading with pre-scrape scoring controls or a large URL table.

## Current Problem

The old tab showed filters, counts, and raw selected/excluded tables. For a 25k URL run, this did not help decide whether to reuse existing scraped pages, retry failures, exclude noise, or prioritize fresh pages.

## Design

Show only core details by default:

- Corpus readiness: discovered URLs, successful markdown pages, failed pages, and thin successful pages.
- Recommended next action: reuse the successful corpus when it exists, otherwise run discovery/scrape.
- Failure repair queue: one row per failure reason with count, sample URL, and recommended action.
- Freshness summary: last modified buckets so the user can prioritize current pages.
- Review samples: a small representative sample of success/failure URLs with URL, status, failure reason, HTTP status, text length, last modified, and markdown availability.

Remove bloat:

- The separate `Choose URLs` tab is removed.
- Manual URL entry stays in `Discover`.
- Pre-scrape usefulness thresholds, max URL caps, LLM URL reasoning, selected URL tables, and spammy/excluded tables are removed from the default workflow.

## Data Sources

- `data/sites/<site_id>/discovered_urls.json` provides URL metadata including `lastmod`, `path_category`, and `content_type_guess`.
- Latest run `scrape_manifest.json` provides scrape status, failure reason, HTTP status, text length, and markdown paths.
- Existing scoring/filtering output remains the source for selected URLs.

## Testing

Add a pure helper that builds the dashboard data from discovered rows and scrape manifest rows. Test summary counts, failure actions, freshness buckets, and representative samples without requiring Streamlit.
