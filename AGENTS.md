## Skill routing

- At the start of **nontrivial work**, or when unsure which workflow applies, read and follow **`.cursor/skills/skill-router/SKILL.md`** (`skill-router`).
- That skill maps task types to installed plugin skills, Pi skills, and Ralph modes. Do not guess—route first, then load the chosen skill in full.

## Cursor Engineering Plugins

Installed under `~/.cursor/plugins/local/` from [cursor/plugins](https://github.com/cursor/plugins). Reload Cursor after install changes.

| Plugin | Invoke when |
|--------|-------------|
| **pstack** | Rigorous engineering: `/poteto-mode`, `architect`, `how`, `principle-prove-it-works`, `show-me-your-work` for long autonomous runs |
| **ralph-loop** | Cursor IDE Ralph loop: start with `ralph-loop` skill; state in `.cursor/ralph/scratchpad.md`; cancel with `cancel-ralph` |
| **continual-learning** | Hook-driven; mines transcripts into `AGENTS.md` (`## Learned User Preferences`, `## Learned Workspace Facts`) |
| **cli-for-agent** | Designing or reviewing agent-friendly CLIs (`scripts/ralph-loop*.sh`, wiki build scripts) |
| **thermos** | Deep branch audit: `thermos`, `thermo-nuclear-review`, `thermo-nuclear-code-quality-review` |
| **agent-compatibility** | One-shot repo audit: `check-agent-compatibility` |
| **cursor-team-kit** | Engineering subset only: `verify-this`, `check-compiler-errors`, `deslop`, `control-ui`, `control-cli` |
| **teaching** | Learning paths: `create-learning-path`, `run-learning-retrospective` |

**Ralph split:** Pi headless loops use `scripts/ralph-loop-pi.sh` + `.specify/memory/constitution.md`. Cursor IDE loops use the **ralph-loop** plugin hooks. Both can coexist.

**Not in scope:** cloud agents (`orchestrate`, `cursor-sdk`), GTM/sales, git/PR shipping skills (`fix-ci`, `review-and-ship`, etc.) unless explicitly requested.

## Ralph Wiggum

- For Ralph Wiggum/spec-driven autonomous loops, read `.specify/memory/constitution.md` first; it is the project-level Ralph source of truth.
- The Pi-specific Ralph entrypoint is `scripts/ralph-loop-pi.sh`; Pi prompt templates are available as `/ralph-build` and `/ralph-plan` after `/reload`.
- For in-IDE Ralph loops, use the **ralph-loop** plugin (`ralph-loop` / `cancel-ralph` skills).

## Verification Before Completion

- Before saying a fix is done, always run a compile/syntax check for changed code paths.
- If the change affects a running app/service, also run a runtime sanity check (logs or quick smoke path) and confirm no new exceptions.
- Report completion only after both checks pass, or clearly state what could not be verified.

## Exploration Preference

- When the user asks to explore, audit, scan, investigate, or review a broad repo/data/workflow question, use subagents by default.
- If the codebase needs to be explored, use the `explorer` tool by default (or `/explorer` in the interactive TUI).
- Prefer `codegraph` for code search, symbol lookup, dependency/impact analysis, and affected-test discovery. Use plain text search only when `codegraph` cannot answer the question or is unavailable.
- Keep the main thread as the orchestrator: do not load large repo/data context into the main thread when scoped subagents can inspect it independently.
- Spawn focused subagents with their own context windows for separate slices, then summarize only the high-signal findings, evidence, and recommended next questions back in the main thread.
- Do not jump from exploration into implementation. First collect requirements, surface ideas, and iterate with the user unless they explicitly ask to apply a change.

## CodeGraph Index Hygiene

- Use CodeGraph as the first-choice codebase search/index for symbol lookup, call graphs, dependency/impact analysis, affected-test discovery, and broad code mapping.
- Keep `.codegraph/` fresh: after any agent-made source/config/test/doc change in this repository, run `codegraph sync` before further CodeGraph queries and before reporting completion.
- If `codegraph sync` or `codegraph status` reports problems, stop relying on the index for that area and clearly report the issue.
- When delegating to explorer, ask it to use CodeGraph-first searches and to sync/check the index when the task depends on recent changes.

## Git Operations

- Run `git status --short` before modifying files and again before the final response when changes were made.
- Treat pre-existing user changes as untouchable; do not overwrite, stage, revert, rebase, reset, clean, or amend unless explicitly asked.
- Keep changes small and reviewable. Before any user-requested commit, inspect the diff, run relevant verification, then commit only requested files with a clear message.
- Never push or rewrite history without explicit confirmation.
- Explorer/subagents may use only read-only git inspection commands unless explicitly configured otherwise; mutating git operations stay in the main agent with user approval.
