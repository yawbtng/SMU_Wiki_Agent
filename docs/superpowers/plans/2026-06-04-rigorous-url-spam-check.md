# Rigorous URL Spam Check

## Goal

Make URL approval stricter before URLs enter `approved_urls.md`, especially for school-selection commands such as "Choose Dedman". The operator should see stronger spam/noise filtering evidence in the URL selection UI and the backend should reject obvious low-value URLs before proposal/approval counts are shown.

## Constraints

- Trusted workspace is exactly `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`.
- Preserve unrelated dirty work. Do not revert, reformat, or clean files outside this task.
- Use CodeGraph first for structural lookup and affected-test discovery.
- Use `rg` only for literal strings/policy text.
- Keep FastAPI thin. Prefer a focused policy/helper module change over expanding route logic.
- Do not write to `data/` fixtures unless a test explicitly creates temporary data.
- Do not commit.

## Implementation Scope

Likely paths:

- `src/scrape_planner/scrape/url_policy.py`
- `src/scrape_planner/webapp/approved_urls.py`
- `tests/test_webapp_api.py` or a focused approved-URLs/policy test file
- `frontend/src/main.tsx` only if the backend already returns better fields that need to be displayed

## Behavior Requirements

1. Add a more rigorous spam/noise classification layer for discovered URLs before they are counted as eligible or matched by chat commands.
2. Reject or strongly demote URL/title patterns that are not student-useful, including:
   - old dated news/articles and archive paths
   - donor/giving/advancement/campaign pages
   - alumni stories/events unless explicitly student-service oriented
   - HR/employee/benefits/staff-association pages
   - governance/admin/trustee/president/provost-only pages
   - staff/faculty bio pages unless they are part of an academic program context
   - search, listing, tag, feed, calendar listing, template, component, and thin navigation pages
   - obvious media/asset/download/mailto/social/query-noise URLs
3. Preserve legitimate student-useful content:
   - admissions, registrar, enrollment, academic calendar, catalog, final exams
   - tuition, billing, financial aid, scholarships
   - housing, dining, health, counseling, accessibility, parking, student affairs
   - school/college academic programs, departments, courses, advising, clinics, research opportunities
   - official policies/legal disclosures relevant to students
4. For chat analysis such as "Choose Dedman", report:
   - matched eligible count after stricter spam filtering
   - top selectable subpaths
   - top rejection reasons with counts
   - a small sample of rejected noisy matches if the existing payload shape can support it without a large UI rewrite
5. Avoid brittle broad substring filters that would reject valid student pages just because the path contains a risky token in a benign context.

## Tests

Add focused tests that prove:

- known spam/noise patterns are rejected with stable reasons
- known student-useful URLs remain eligible
- a command like "Choose Dedman" does not select unrelated lexical matches outside the intended school path when the URL group is not actually Dedman
- rejection reason counts are exposed in the analysis/chat response

## Verification Commands

Run all that apply after edits:

```bash
python -m py_compile src/scrape_planner/scrape/url_policy.py src/scrape_planner/webapp/approved_urls.py
pytest tests/test_webapp_api.py -q
pytest tests/test_cleanup_policy.py -q
npx tsc --noEmit
npm run build
codegraph sync
codegraph status
```

If frontend is unchanged, `npx tsc --noEmit` and `npm run build` are still preferred because the URL approval UI consumes this payload.

## Browser Smoke

With the app running at `http://127.0.0.1:5173/`:

1. Open SMU workspace.
2. Go to Sources.
3. Send or draft a URL approval command such as `Choose Dedman`.
4. Confirm the UI reports stricter rejection counts and does not imply noisy unrelated matches will be approved.
5. Confirm browser console has no new errors.
