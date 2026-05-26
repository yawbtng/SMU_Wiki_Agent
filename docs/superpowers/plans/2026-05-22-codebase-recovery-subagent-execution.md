# Codebase Recovery Plan: Subagent-Driven Execution

## Summary

This plan is the durable handoff for fixing the `ultra-fast-rag` codebase in a new implementation session.

The goal is to turn the current prototype-grown Streamlit app into a structured, testable operator application without rewriting the proven backend pipeline.

Primary pipeline:

```text
discover -> select -> scrape -> normalize -> build wiki -> build index -> query via MCP
```

Canonical visible app:

```text
Overview -> Sources -> Runs -> Corpus -> Wiki -> Retrieval -> Settings
```

Product decisions:

- Stabilize first; do not rewrite the app from scratch.
- `LLM Wiki` is the primary product path.
- Graph and Zvec remain only as advanced or legacy surfaces until proven safe to remove.
- `raw_sources/registry.jsonl` is the central pipeline boundary.
- Use subagents for implementation slices; the lead agent coordinates, reviews, integrates, and validates.
- Stop and ask for a fresh session before context loss instead of relying on compaction.

## Architecture Decisions

### ADR-001: `app.py` Becomes Composition Root Only

Current shape:

```text
app.py ~2988 lines
|
|-- session state
|-- app state persistence
|-- workspace CRUD
|-- scrape controls
|-- PDF/source ingestion
|-- all Streamlit tab rendering
|-- graph workbench
|-- metrics
|-- MCP readiness
`-- settings writes
```

Target shape:

```text
app.py
|
|-- create_app_context()
|-- render_workspace_gate(ctx)
`-- render_workflow(ctx)

src/scrape_planner/app/
|-- context.py
|-- artifact_contracts.py
|-- repositories.py
|-- workflow.py
`-- pages/
    |-- overview.py
    |-- sources.py
    |-- runs.py
    |-- corpus.py
    |-- wiki.py
    |-- retrieval.py
    `-- settings.py
```

Decision: `app.py` may initialize Streamlit, build context, create tabs, and call page renderers. It must not own artifact parsing, workflow rules, scoring, or large page bodies.

### ADR-002: Typed Artifact Contracts Are Public Interfaces

Add typed contracts for durable JSON/JSONL artifacts:

```python
# src/scrape_planner/app/artifact_contracts.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

SourceStatus = Literal["ready", "failed", "needs-review"]
RunState = Literal["ready", "initializing", "running", "paused", "completed", "cancelled", "failed"]

@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    url: str

@dataclass(frozen=True)
class AppState:
    active_workspace_id: str = ""
    workspaces: tuple[Workspace, ...] = ()
    last_run_by_site: dict[str, str] = field(default_factory=dict)

@dataclass(frozen=True)
class RawSourceRow:
    source_id: str
    source_kind: str
    title: str
    markdown_path: str
    metadata_path: str
    checksum: str
    parser: str
    status: SourceStatus
    wiki_status: str = "pending"
    error_reason: str = ""
```

Decision: backend modules can keep writing JSON, but UI and workflow code must read through repositories or contract loaders that validate defaults and path safety.

### ADR-003: Streamlit Pages Receive `AppContext`

```python
# src/scrape_planner/app/context.py
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

class SessionAdapter(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...
    def rerun(self) -> None: ...

@dataclass
class AppContext:
    project_root: Path
    data_root: Path
    env_path: Path
    session: SessionAdapter
    app_state: AppState
    store: object
    runner: object
    tmux_runner: object
    active_workspace: Workspace | None
    active_site_layout: object | None
    active_run_id: str
```

Example page target:

```python
# src/scrape_planner/app/pages/wiki.py
def render_wiki_page(ctx: AppContext) -> None:
    if not ctx.active_site_layout:
        st.info("Create or open a workspace first.")
        return

    layout = ctx.active_site_layout
    raw_status = raw_source_status(layout)
    can_build = raw_sources_ready(raw_status)
    wiki_status = load_wiki_status(layout, raw_status)

    if st.button("Build LLM Wiki", disabled=not can_build, key="build_llm_wiki"):
        result = launch_wiki_builder(layout.site_root, runner=ctx.tmux_runner, resume=True, runtime="pi")
        if result.get("ok"):
            st.success("Started wiki build.")
        else:
            st.error(result.get("error") or "Failed to start LLM Wiki builder.")
```

Decision: page modules render and call application services. They do not parse arbitrary JSON files directly.

### ADR-004: Workflow Registry Owns Tab Order and Dispatch

Replace the raw tab-name list with explicit tab specs:

```python
@dataclass(frozen=True)
class WorkflowTab:
    key: str
    label: str
    renderer: str
    advanced: bool = False

WORKFLOW_TABS = (
    WorkflowTab("overview", "Overview", "pages.overview:render_overview_page"),
    WorkflowTab("sources", "Sources", "pages.sources:render_sources_page"),
    WorkflowTab("runs", "Runs", "pages.runs:render_runs_page"),
    WorkflowTab("corpus", "Corpus", "pages.corpus:render_corpus_page"),
    WorkflowTab("wiki", "Wiki", "pages.wiki:render_wiki_page"),
    WorkflowTab("retrieval", "Retrieval", "pages.retrieval:render_retrieval_page"),
    WorkflowTab("settings", "Settings", "pages.settings:render_settings_page"),
)
```

Decision: tests assert this registry, not old tab names from stale OpenSpec text.

### ADR-005: Artifact Pipeline Remains UI-Agnostic

Keep these modules mostly intact during the first refactor:

```text
sitemap_discovery.py
scrape_worker.py
run_persistence.py
raw_source_normalizer.py
source_registry.py
llm_wiki_builder.py
llm_wiki_index.py
mcp_servers/llm_wiki_mcp.py
```

Decision: first restructure composition and contracts. Do not rewrite the working pipeline while extracting UI.

## Target Data Flow

```text
Workspace
  -> data/app_state.json
  -> data/sites/<site_id>/workspace.json

Sources
  -> discovered_urls.json
  -> selected_urls.json with score/reason/policy/threshold
  -> sources/pdf_ingest/*.jsonl

Runs
  -> <run_id>/selected_urls.json
  -> <run_id>/pages.jsonl
  -> <run_id>/events.jsonl
  -> <run_id>/scrape_manifest.json
  -> <run_id>/markdown/*.md
  -> <run_id>/metadata/*.json

Corpus
  -> raw_sources/registry.jsonl
  -> raw_sources/web|pdf|excel/*.md
  -> raw_sources/reports/*.json

Wiki
  -> wiki/index.md
  -> wiki/pages/*.md
  -> wiki/log.md
  -> wiki/review_queue.md
  -> wiki/reports/*.json

Retrieval
  -> indexes/llm_wiki_documents.jsonl
  -> indexes/llm_wiki_postings.json
  -> indexes/llm_wiki_manifest.json
  -> mcp_servers/llm_wiki_mcp.py query-only
```

## Implementation Waves

### Wave 0: Coordinator Preflight

Owner: lead agent only.

Commands:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
pwd
git status --short
git log --oneline -8
lsof -nP -iTCP:8501 || true
```

If a Streamlit listener exists:

```bash
lsof -a -p <pid> -d cwd -Fn
```

Deliverable: durable note in `docs/superpowers/plans/` recording checkout path, branch, dirty status, active port, listener cwd, known failing tests, and exact verification matrix.

Guardrail: no subagent starts from memory alone.

### Wave 1: Quarantine Stale UI Tests

Owner: test/navigation subagent.

Files:

```text
src/scrape_planner/ui_navigation.py
tests/test_stepper_ui.py
tests/test_operator_navigation_ui.py
tests/test_wiki_ui.py
tests/test_retrieval_ui.py
```

Tasks:

```text
1. Make current operator tabs canonical.
2. Remove or rewrite stale assertions expecting old stepper labels.
3. Preserve useful readiness/status tests from test_stepper_ui.py.
4. Keep source-inspection tests only for security, tab ownership, hidden details, and prohibited legacy copy.
```

Acceptance:

```bash
PYTHONPATH=. /usr/bin/python3 -m pytest \
  tests/test_operator_navigation_ui.py \
  tests/test_wiki_ui.py \
  tests/test_retrieval_ui.py \
  tests/test_stepper_ui.py \
  -q
```

Gate: any remaining failures must be classified as pre-existing or assigned to the next wave.

### Wave 2: Add Contracts, Context, and Repositories

Owner: architecture subagent.

New files:

```text
src/scrape_planner/app/__init__.py
src/scrape_planner/app/artifact_contracts.py
src/scrape_planner/app/context.py
src/scrape_planner/app/repositories.py
```

Tasks:

```text
1. Add typed contracts for app state, workspace, discovered URL, selected URL, run status, raw source row, wiki status, index status, MCP status.
2. Add repository loaders/writers for app_state.json and site-level artifacts.
3. Add AppContext and SessionAdapter.
4. Keep app.py behavior unchanged except replacing direct helpers where safe.
```

Acceptance:

```bash
/usr/bin/python3 -m py_compile app.py src/scrape_planner/app/*.py
PYTHONPATH=. /usr/bin/python3 -m pytest tests/test_data_root.py tests/test_state.py tests/test_raw_source_registry.py -q
```

Gate: contracts load existing artifacts without changing their file format.

### Wave 3: Extract Page Modules

Owner: UI extraction subagent. One page per subtask, no parallel edits to `app.py`.

New files:

```text
src/scrape_planner/app/pages/overview.py
src/scrape_planner/app/pages/sources.py
src/scrape_planner/app/pages/runs.py
src/scrape_planner/app/pages/corpus.py
src/scrape_planner/app/pages/wiki.py
src/scrape_planner/app/pages/retrieval.py
src/scrape_planner/app/pages/settings.py
```

Order:

```text
1. Overview
2. Wiki
3. Settings
4. Retrieval shell only
5. Sources
6. Runs
7. Corpus
```

Do not deeply rewrite each page during extraction. First move behavior behind `render_*_page(ctx)`.

Acceptance after each page:

```bash
/usr/bin/python3 -m py_compile app.py src/scrape_planner/app/pages/*.py
PYTHONPATH=. /usr/bin/python3 -m pytest <owned UI tests> -q
```

Runtime gate after any visible change:

```bash
TMP_DATA=$(mktemp -d /tmp/ufr-data.XXXXXX)
PYTHONPATH=. ULTRA_FAST_RAG_DATA_ROOT="$TMP_DATA" /usr/bin/python3 -m streamlit run app.py \
  --server.headless true --server.address 127.0.0.1 --server.port 8765
curl -fsS http://127.0.0.1:8765/_stcore/health
```

Also inspect logs for `Traceback`, `ModuleNotFoundError`, and Streamlit import errors.

### Wave 4: Add Missing Operator Actions

Owner: pipeline/UI bridge subagent.

Files:

```text
src/scrape_planner/app/pages/corpus.py
src/scrape_planner/app/pages/retrieval.py
src/scrape_planner/raw_source_normalizer.py
src/scrape_planner/llm_wiki_index.py
src/scrape_planner/stepper_status.py
mcp_servers/llm_wiki_mcp.py
```

Actions to expose:

```text
1. Normalize Corpus
2. Build Retrieval Index
3. Run MCP Smoke Check
```

Rules:

```text
Normalize Corpus may write raw_sources/* and reports only.
Build Retrieval Index may write indexes/* only.
MCP Smoke Check must be read-only.
```

Acceptance:

```bash
PYTHONPATH=. /usr/bin/python3 -m pytest \
  tests/test_raw_source_normalization.py \
  tests/test_llm_wiki_index.py \
  tests/test_llm_wiki_mcp.py \
  tests/test_retrieval_ui.py \
  -q
```

Runtime smoke must click or exercise equivalent app paths if a browser/app tool is available; otherwise run CLI actions and verify status reports.

### Wave 5: URL Selection Becomes a Library

Owner: data-quality subagent.

New file:

```text
src/scrape_planner/url_selection.py
```

Replace hard-coded `score_urls.py` behavior with:

```python
@dataclass(frozen=True)
class SelectionPolicy:
    threshold: int
    max_per_category: int
    exclude_patterns: tuple[str, ...]
    coverage_targets: dict[str, int]

@dataclass(frozen=True)
class ScoredURL:
    url: str
    score: int
    reason: str
    category: str
    selected: bool
    policy: str
```

Pipeline:

```text
1. hard URL filtering
2. cheap content profiling when content exists
3. coverage-aware scoring
4. optional AI label after content evidence
```

Acceptance:

```bash
PYTHONPATH=. /usr/bin/python3 -m pytest tests/test_url_scoring.py tests/test_sitemap_discovery.py -q
```

Add tests for:

```text
auth/login/search/archive filtered
old year archive demoted
businessfinance cannot dominate corpus
admission/enrollment/student-life retained
selected_urls.json includes score/reason/policy/threshold
```

### Wave 6: Gate Legacy Graph and Zvec

Owner: retrieval cleanup subagent.

Files:

```text
src/scrape_planner/markdown_graph.py
src/scrape_planner/zvec_index.py
mcp_servers/markdown_graph_mcp.py
mcp_servers/smu_zvec_mcp.py
src/scrape_planner/app/pages/retrieval.py
```

Decision:

```text
LLM Wiki retrieval is primary.
Graph is advanced evidence explorer.
Zvec is experimental/legacy.
```

Acceptance:

```bash
PYTHONPATH=. /usr/bin/python3 -m pytest \
  tests/test_markdown_graph.py \
  tests/test_markdown_graph_mcp.py \
  tests/test_zvec_index.py \
  tests/test_zvec_index_run.py \
  tests/test_zvec_mcp.py \
  tests/test_retrieval_ui.py \
  -q
```

Gate: default UI must not look graph-first.

### Wave 7: Final Verification and Documentation

Owner: coordinator.

Commands:

```bash
/usr/bin/python3 -m py_compile app.py scripts/*.py src/scrape_planner/*.py src/scrape_planner/app/*.py src/scrape_planner/app/pages/*.py mcp_servers/*.py
PYTHONPATH=. /usr/bin/python3 -m pytest tests -q
PYTHONPATH=. /usr/bin/python3 scripts/validate_llm_wiki_stepper.py \
  --output-root data/validation/llm-wiki-stepper \
  --report-path docs/validation/llm-wiki-stepper-validation.json \
  --smu-limit 3
openspec validate build-llm-wiki-stepper --strict
```

If `openspec` is unavailable, record that as not verified.

Runtime smoke:

```bash
TMP_DATA=$(mktemp -d /tmp/ufr-data.XXXXXX)
PYTHONPATH=. ULTRA_FAST_RAG_DATA_ROOT="$TMP_DATA" /usr/bin/python3 -m streamlit run app.py \
  --server.headless true --server.address 127.0.0.1 --server.port 8765
curl -fsS http://127.0.0.1:8765/_stcore/health
```

Visible app smoke on `8501` only after listener cwd is verified.

## Subagent Operating Rules

Use one fresh subagent per bounded task:

```text
Task 1: navigation/tests
Task 2: contracts/context/repos
Task 3: page extraction
Task 4: operator actions
Task 5: URL selection
Task 6: graph/Zvec gating
Task 7: validation/docs
```

Do not dispatch parallel workers that edit the same file. Especially do not allow parallel edits to `app.py`.

Every implementation subagent must report:

```text
status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
files changed
tests run
commands run
failures
manual/runtime checks
residual risks
```

Every task gets two reviews:

```text
1. Spec compliance review
2. Code quality review
```

Do not proceed while either review has open issues.

## Context Window and Session Guardrails

Stop and ask for a new session when any of these are true:

```text
remaining context is below about 25 percent
a task crosses its assigned ownership boundary
runtime port/checkouts become ambiguous
app.py plus more than two backend modules were touched
validation failures require broad debugging
the agent cannot summarize exact changed files and tests from memory
```

Before stopping, create a durable handoff note when file edits are allowed:

```text
docs/superpowers/plans/YYYY-MM-DD-refactor-handoff.md
```

The handoff must include:

```text
active checkout path
branch
dirty status
active Streamlit port and listener cwd
files changed
tests passed/failed
commands run
last error text
next exact command
artifact paths touched
```

If still in Plan Mode or no edits are allowed, provide the same handoff in chat and stop. Do not rely on compaction to continue correctly.

## Baseline Verification From Planning Pass

Read-only exploration reported:

```text
compile passed for app.py, ui_navigation.py, stepper_status.py, run_analytics.py, validate_llm_wiki_stepper.py
operator/UI refactor slice: 15 passed
LLM Wiki E2E slice: 3 passed
test_stepper_ui.py: 8 failed, 8 passed, stale against current operator tabs
Streamlit boot smoke passed at http://127.0.0.1:8765/_stcore/health with temp data root
```

Treat the stale `test_stepper_ui.py` failures as Wave 1 cleanup, not as evidence that the runtime app cannot boot.

## Assumptions

- Stabilize first, no rewrite.
- Current operator tabs are canonical.
- LLM Wiki is the main product path.
- Graph and Zvec are not deleted in the first pass.
- Existing durable artifacts remain compatible.
- `/usr/bin/python3` is the test/runtime interpreter for this repo unless a verified venv replaces it.
- No task is complete without compile checks, focused tests, and runtime smoke when the app surface changes.
