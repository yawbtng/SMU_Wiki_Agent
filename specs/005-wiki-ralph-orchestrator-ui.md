# Wiki Compile Orchestrator UI

## Status: SUPERSEDED

The Ralph loop strategy has been removed for wiki generation. Use the single noninteractive LLM Wiki v2 compile path from spec 002 instead.

## Goal

Integrate a tmux-backed LLM Wiki v2 builder into the operator UI so users can launch AI-native wiki compile work and see concise streamed progress from the tmux pane and structured event files.

## UI Target

Implement in the **FastAPI + React webapp** (`specs/006-fastapi-react-realtime-app.md`, worktree `ultra-fast-rag-webapp`). Do not add major new Streamlit UI for this spec. Streamlit (`app.py`) remains a read-only parity reference until feature parity is reached.

## Dependencies

- `specs/006-fastapi-react-realtime-app.md` — webapp baseline (SSE status, wiki-agent panel).

- `specs/004-agent-navigable-wiki-map.md` defines the wiki quality target.
- `.pi/skills/llm-wiki-v2/SKILL.md` defines the semantic wiki compile behavior.
- `.pi/skills/llm-wiki-noninteractive/scripts/build_wiki.sh` runs compile, lint, index, and optional smoke checks.

## Requirements

1. **Targeted LLM Wiki v2 launch**
   - Add support for targeting a site root, rebuild/resume mode, and status directory.
   - Default skill: `.pi/skills/llm-wiki-v2`.

2. **Tmux orchestration**
   - Provide a single command/script that starts the run in tmux.
   - Prevent duplicate concurrent runs per site unless explicitly forced.
   - Pipe or capture tmux pane output into a site-local log.

3. **Status artifacts**
   - Write/read:
     - `wiki-agent-run-latest.json`
     - `wiki-agent-tasks-latest.json`
     - `wiki-agent-events-latest.jsonl`
     - `wiki-agent-pane-latest.log`
     - `wiki-agent-summary-latest.md`

4. **Webapp Wiki UI** (React; not Streamlit)
   - Add a Wiki tab section for **Build AI-Native Wiki**.
   - Show build mode, runtime, status, and recent compile events.
   - Show recent structured events and tmux pane tail.
   - Show generated artifact links after build.
   - Subscribe to SSE (`GET /api/stream/sites/{site_id}`) while the tmux wiki job is running.

5. **Verification**
   - Tests cover launcher command construction, duplicate-run handling, absent status files, task checklist rendering, and event parsing.
   - Runtime smoke can launch a one-iteration dry run or status-only run without exceptions.

## Task List

- [ ] Launch `.pi/skills/llm-wiki-noninteractive/scripts/build_wiki.sh` from the webapp.
- [ ] Add status writer/reader utility for run/tasks/events/pane tail.
- [ ] Add initial task-list generation from target spec checkboxes.
- [ ] Add duplicate tmux-session detection.
- [ ] Add React Wiki tab controls for rebuild/resume and runtime status.
- [ ] Add React recent events and pane tail components.
- [ ] Add artifact links for sitemap/navigation/backlinks/graph edges.
- [ ] Add tests.
- [ ] Run compile/tests/smoke.
- [ ] Update planning history and completion log.

## Acceptance Criteria

- [ ] User can launch the AI-native LLM Wiki v2 compile from the Wiki tab.
- [ ] Launch uses tmux and the `.pi/skills/llm-wiki-v2` compile path.
- [ ] UI shows build status and recent events.
- [ ] UI streams recent tmux pane lines or structured agent messages.
- [ ] UI prevents duplicate concurrent runs for the same site.
- [ ] Status files survive app reloads and allow progress recovery.
- [ ] Tests pass for launcher/status/UI behavior.
- [ ] Syntax/compile checks pass for changed files.
- [ ] `docs/planning/work-index.md`, `docs/planning/history.md`, and a completion log are updated.

<!-- NR_OF_TRIES: 0 -->
