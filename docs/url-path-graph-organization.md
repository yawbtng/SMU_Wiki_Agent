# URL Path Graph Organization Study

## Current implementation update

The app now builds a **dynamic per-university URL graph profile** instead of relying on SMU-specific school names. During graph build it infers root units, areas, departments/programs, and hierarchy edges from the actual URL paths in the run, writes the profile to `knowledge_graph/graph_profile.json`, and tags pages to the deepest matching path unit. Optional OpenRouter label cleanup can be enabled with `UFR_GRAPH_PROFILE_LLM=1` and `OPENROUTER_API_KEY`.

Scraping now defaults to lightweight HTTP fetches only. Browser rendering uses **Lightpanda via CDP** when `LIGHTPANDA_CDP_URL` or `LIGHTPANDA_WS_ENDPOINT` is configured; Chrome/Chromium/Playwright browser launch fallback is disabled.

Source run: `data/sites/www.smu.edu/20260520T071858Z-caa0cd`

Compact page rows studied: **2,160** scraped URLs.

## Path distribution

| Top path | Count | Notes |
|---|---:|---|
| `/businessfinance` | 1,096 | Largest cluster; mostly internal operations, HR, finance, police, risk, facilities, parking. |
| `/alumni` | 243 | Events, awards, stories, volunteer/resources. |
| `/cape` | 178 | Continuing/professional education certificates, short courses, help center. |
| `/admission` | 146 | Undergraduate/transfer/international admissions, financial aid, visits. |
| `/cox` | 129 | Cox school content, mostly faculty and department pages. |
| `/aboutsmu` | 124 | Administration, president/trustees, facts, maps, annual reports. |
| `/brand-web-guidelines` | 70 | Web/content/design/SEO guidelines. |
| `/ciq` | 50 | Cultural intelligence content/events/news. |
| `/brand` | 25 | Brand guidelines and editorial style. |
| `/academic-ceremonies` | 23 | Ceremony events/history. |
| `/abroad` | 17 | Study abroad safety/resources/programs. |

## Recommended graph hierarchy

Use URL path as the deterministic skeleton, then enrich with page title/headings and markdown links.

```text
SMU
├── Audience / Lifecycle
│   ├── Prospective Students
│   │   ├── Admission
│   │   ├── Financial Aid
│   │   ├── Campus Visit
│   │   └── Accepted Students
│   ├── Current Students
│   │   ├── Parking / ID / Transportation
│   │   ├── Police / Safety
│   │   ├── Academic Ceremonies
│   │   ├── Abroad
│   │   └── CAPE Programs
│   ├── Faculty / Staff
│   │   ├── HR
│   │   ├── Payroll / Finance
│   │   ├── Facilities
│   │   └── Risk Management
│   └── Alumni
│       ├── Events
│       ├── Awards
│       ├── Groups / Networks
│       └── News / Stories
├── Academic / Units
│   ├── Cox School of Business
│   ├── CAPE
│   └── CIQ
├── Operations / Services
│   ├── Business & Finance
│   ├── Campus Services
│   ├── Facilities
│   ├── Police
│   └── Risk Management
├── Institutional
│   ├── About SMU
│   ├── Administration
│   ├── President / Trustees
│   ├── Maps / Facts
│   └── Annual Reports
└── Web / Communications
    ├── Brand
    └── Brand Web Guidelines
```

## Node types

| Node type | Generated from | Example |
|---|---|---|
| `site` | Domain root | `smu.edu` |
| `section` | First URL segment | `businessfinance`, `admission`, `alumni` |
| `unit` | First 2 path segments or known school/unit | `businessfinance/hr`, `cox/academics` |
| `topic` | First 3 path segments or normalized subject | `admission/apply/transfer` |
| `page` | Individual scraped URL | Actual page URL + markdown artifact |
| `audience` | Rule/enrichment tag | prospective-student, current-student, staff, alumni |
| `service` | Rule/enrichment tag | parking, payroll, safety, financial-aid |

## Edge types

| Edge | Meaning |
|---|---|
| `contains` | Path hierarchy: section -> unit -> topic -> page |
| `belongs_to` | Page belongs to unit/office/school |
| `for_audience` | Page targets an audience such as prospective students or staff |
| `about_topic` | Page discusses a normalized service/topic |
| `links_to` | Markdown/html hyperlink between scraped pages |
| `related_to` | Shared title tokens, shared headings, or same normalized topic |
| `supersedes` | Optional for dated/versioned pages such as annual reports or fee years |

## URL-pattern mapping rules

| URL pattern | Graph placement | Audience tags |
|---|---|---|
| `/admission/apply/*` | Prospective Students > Admission > Apply | prospective-student |
| `/admission/financial-aid-resources/*` | Prospective Students > Financial Aid | prospective-student |
| `/admission/accepted-students/*` | Prospective Students > Accepted Students | admitted-student |
| `/businessfinance/hr/*` | Faculty/Staff > HR | faculty-staff |
| `/businessfinance/officeoffinanceandplanning/payroll/*` | Faculty/Staff > Payroll | faculty-staff |
| `/businessfinance/campusservices/parkingandidcardservices/*` | Current Students > Parking/ID/Transportation | current-student, faculty-staff |
| `/businessfinance/police/*` | Current Students > Safety/Police | current-student, faculty-staff, visitor |
| `/businessfinance/risk-management/*` | Operations > Risk Management | faculty-staff |
| `/businessfinance/facilities/*` | Operations > Facilities | faculty-staff, visitor |
| `/alumni/events/*` | Alumni > Events | alumni |
| `/alumni/groups-and-networks/*` | Alumni > Groups/Networks | alumni |
| `/cape/programs/*` | Academic/Units > CAPE > Programs | professional-learner, current-student |
| `/cox/academics/faculty/*` | Academic/Units > Cox > Faculty | prospective-student, academic |
| `/aboutsmu/administration/*` | Institutional > Administration | general |
| `/brand-web-guidelines/*` | Web/Communications > Web Guidelines | staff, web-editor |
| `/brand/*` | Web/Communications > Brand | staff, communicator |
| `/abroad/*` | Current Students > Study Abroad | current-student |

## Observations

1. The scrape is operational-heavy: about half the studied URLs are under `/businessfinance`.
2. URL paths are consistent enough to use as the primary graph skeleton.
3. Student-facing content is present but mixed with staff/internal pages; audience tagging is important.
4. Faculty-directory-like pages (`/cox/academics/faculty/*`) should be grouped separately from policy/service pages.
5. Dated pages and archives should remain in the graph but be lower priority unless explicitly searched.

## Recommended build order

1. Build deterministic path tree from URL segments.
2. Attach page artifact metadata: title, markdown path, raw html path, status, text length.
3. Add rule-based audience/topic tags from URL patterns.
4. Parse markdown links and add `links_to` edges between scraped pages.
5. Add normalized topic nodes for common services: admissions, financial aid, parking, payroll, HR, police, facilities, risk, alumni events, CAPE certificates.
6. Rank pages for student value using path rules + title/headings + text length.
7. Hide or de-prioritize internal/admin/archive nodes in student-facing search, but keep them reachable in the full graph.
