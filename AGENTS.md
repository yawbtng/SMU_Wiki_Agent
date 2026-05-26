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
