# Wiki Ralph Orchestrator UI

## Goal

Integrate a tmux-backed Pi/Ralph wiki builder into the operator UI so users can launch long-running AI-native wiki work, watch a live task checklist, and see concise streamed progress from the tmux pane and structured event files.

## UI Target

Implement in the **FastAPI + React webapp** (`specs/006-fastapi-react-realtime-app.md`, worktree `ultra-fast-rag-webapp`). Do not add major new Streamlit UI for this spec. Streamlit (`app.py`) remains a read-only parity reference until feature parity is reached.

## Dependencies

- `specs/006-fastapi-react-realtime-app.md` — webapp baseline (SSE status, wiki-agent panel).

- `specs/004-agent-navigable-wiki-map.md` defines the wiki quality target.
- `.pi/skills/wiki-ralph-orchestrator/SKILL.md` defines the orchestrated agent behavior.
- `scripts/ralph-loop-pi.sh` provides fresh-context Ralph iterations.

## Requirements

1. **Targeted Ralph launch**
   - Add support for targeting a specific spec, site root, status directory, model, thinking level, and max iterations.
   - Default target spec: `specs/004-agent-navigable-wiki-map.md`.
   - Default model: `openai-codex/gpt-5.3-codex`.

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
   - Show model/thinking/spec controls.
   - Show progress bar and live task checklist.
   - Show recent structured events and tmux pane tail.
   - Show generated artifact links after build.
   - Subscribe to SSE (`GET /api/stream/sites/{site_id}`) while the tmux/Ralph job is running.

5. **Verification**
   - Tests cover launcher command construction, duplicate-run handling, absent status files, task checklist rendering, and event parsing.
   - Runtime smoke can launch a one-iteration dry run or status-only run without exceptions.

## Task List

- [ ] Extend `scripts/ralph-loop-pi.sh` with `RALPH_TARGET_SPEC`, `RALPH_SITE_ROOT`, and `RALPH_STATUS_DIR` prompt/status support.
- [ ] Add `scripts/wiki-ralph-orchestrator.sh` tmux launcher.
- [ ] Add status writer/reader utility for run/tasks/events/pane tail.
- [ ] Add initial task-list generation from target spec checkboxes.
- [ ] Add duplicate tmux-session detection.
- [ ] Add React Wiki tab controls for model/thinking/spec/max iterations.
- [ ] Add React live checklist component.
- [ ] Add React recent events and pane tail components.
- [ ] Add artifact links for sitemap/navigation/backlinks/graph edges.
- [ ] Add tests.
- [ ] Run compile/tests/smoke.
- [ ] Update planning history and completion log.

## Acceptance Criteria

- [ ] User can launch the AI-native wiki Ralph job from the Wiki tab.
- [ ] Launch uses tmux and the default model `openai-codex/gpt-5.3-codex` unless overridden.
- [ ] Launch targets `specs/004-agent-navigable-wiki-map.md` by default.
- [ ] UI shows live task checklist with checked/completed items.
- [ ] UI streams recent tmux pane lines or structured agent messages.
- [ ] UI prevents duplicate concurrent runs for the same site.
- [ ] Status files survive app reloads and allow progress recovery.
- [ ] Tests pass for launcher/status/UI behavior.
- [ ] Syntax/compile checks pass for changed files.
- [ ] `docs/planning/work-index.md`, `docs/planning/history.md`, and a completion log are updated.

## Status: TODO

<!-- NR_OF_TRIES: 0 -->
