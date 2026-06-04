---
name: cursor-agent-handoff
description: >-
  Codex manager/supervisor only: delegate substantive work to Cursor Agent in
  the trusted workspace. Use when Codex orchestrates research, plans, or
  implementation in ultra-fast-rag without editing product code directly.
---

# Cursor Agent Handoff (Codex Manager)

## Role

**Codex is manager/supervisor only.** It coordinates work; it does not implement product changes itself.

| Codex may | Codex must not (unless user explicitly overrides in-thread) |
|---------|--------------------------------------------------------------|
| Write task plans under `docs/superpowers/plans/` | Edit product source (`src/`, `frontend/`, etc.) |
| Draft Cursor Agent prompts | Edit tests (`tests/`) |
| Run lightweight verification (`git status`, stale-agent checks, `codegraph status`, narrow compile checks on delegated output) | Edit configs, dependency manifests, or `data/` |
| Summarize evidence and report pass/fail | Commit, push, or rewrite git history |

Override means an explicit in-thread instruction from the user to edit a named path or class of paths. Ambiguous or implied permission does not count.

## Trust boundary

Trusted workspace is exactly `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`. Do not inspect or trust any other directory, including `/Users/abhsheno` and sibling worktrees.

- Never launch `agent` with `--workspace` set to `/Users/abhsheno` or any path outside the trusted workspace.
- Prefix every Cursor Agent prompt with the trust-boundary sentence above.

## Delegation command

Launch Cursor Agent headlessly from the trusted workspace:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
agent --print --model composer-2.5 --trust --workspace /Users/abhsheno/Desktop/Projects/ultra-fast-rag '<prompt>'
```

Research-only pass (no edits):

```bash
agent --print --mode ask --model composer-2.5 --trust --workspace /Users/abhsheno/Desktop/Projects/ultra-fast-rag '<prompt>'
```

Before starting implementation, confirm no stale wrong-workspace agent is running:

```bash
ps -axo pid,etime,stat,command | rg 'agent --print|\.local/bin/agent' || true
```

Reject any running `agent --print` whose command contains `--workspace` outside the trusted workspace.

## Lookup rules

- **Delegate substantive exploration.** Codex must not fill the main context with local CodeGraph/`rg`/file-reading loops for implementation or architecture discovery. Put those questions in the Cursor Agent prompt and require a concise, evidence-backed answer.
- **Codex local lookups are limited to prerequisites and verification:** read this skill, `AGENTS.md`, `.cursor/skills/skill-router/SKILL.md`, check `git status`, check stale agents, write the plan, run final sync/status/compile/runtime checks, and inspect final diffs.
- **Inside Cursor Agent prompts:** require CodeGraph first for symbols, definitions, call paths, dependencies, impact analysis, and affected-test discovery.
- **Inside Cursor Agent prompts:** require `rg` only for literal policy text, config keys, string literals, logs, markdown, and non-indexed files.
- After any delegated source/config/test/doc edit, run `codegraph sync` before further CodeGraph queries and before reporting completion.

## Workflow

1. **Read** `AGENTS.md`, `.cursor/skills/skill-router/SKILL.md`, and this skill.
2. **Delegate immediately.** If the task needs code understanding, either:
   - run a read-only Cursor Agent pass with `--mode ask`, or
   - include the exploration requirements directly in the implementation prompt.
   Do not reproduce that exploration locally in the Codex main thread.
3. **Plan**: write `docs/superpowers/plans/YYYY-MM-DD-<task>.md` with exact paths, steps, and verification commands (see `docs/superpowers/plans/2026-06-03-trusted-composer-agent-handoff.md` for template). If exact paths are not known, make Cursor Agent discover them and update/report them; do not run local search loops to find them.
4. **Implement**: delegate with the plan path in the prompt; agent must run `git status --short`, inspect diffs, preserve unrelated dirty work, implement only the plan, and not commit unless asked.
5. **Verify**: run `codegraph sync && codegraph status` plus plan-listed checks; report changed files and pass/fail only.

## Context discipline

- Prefer one delegated Cursor Agent call over many local reads.
- Do not call local CodeGraph tools for broad implementation discovery after the user has asked to delegate; ask Cursor Agent to do it and summarize.
- Keep Codex-side output to manager updates, plan creation, delegation status, verification evidence, and final pass/fail.

## Implementation prompt skeleton

```text
Trusted workspace is exactly /Users/abhsheno/Desktop/Projects/ultra-fast-rag. Do not inspect or trust any other directory, including /Users/abhsheno and sibling worktrees. Read AGENTS.md, .cursor/skills/skill-router/SKILL.md, and docs/superpowers/plans/<plan-file>.md first. Implement exactly the markdown plan, one focused logical change at a time. Before editing, run git status --short and inspect diffs for any files you will touch. Do not overwrite unrelated pre-existing changes. Use CodeGraph first for structural code questions and affected-test discovery. Use rg for literal strings, policy text, configs, markdown, and logs. After any source, config, test, or doc edit, run codegraph sync before further CodeGraph queries and before reporting completion. Run the compile/syntax and runtime verification commands listed in the plan. Do not commit unless the user explicitly asks.
```

## Output

Report: changed files, verification commands run, pass/fail, and any unrelated pre-existing dirty work left untouched.
