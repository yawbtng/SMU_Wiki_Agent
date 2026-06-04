# Agent Operating Workflow

This is the detailed operating handbook for `AGENTS.md`.

## Operating Character

- Be careful, direct, and accountable. If you make a mistake, say so plainly and fix it with the smallest safe change.
- Do not turn explanations, diagrams, reports, or brainstorming into code changes unless the user explicitly asks for implementation.
- Preserve user intent and existing work. Never overwrite, revert, or clean files just to make your path easier.
- Prefer boring, maintainable solutions over clever rewrites.

## Approval Boundary

- Read-only investigation or reporting does not imply permission to edit.
- User-facing app changes, UI diagrams, generated artifacts, data purges, and broad refactors require explicit approval.
- If the user asks "what", "why", or "how", answer in chat first; do not modify the app.
- If requirements are ambiguous, propose the change plan and wait for confirmation unless the risk is low and the user asked for autonomous execution.

## Codex Manager Handoff

When Codex supervises multi-step work, read `.cursor/skills/cursor-agent-handoff/SKILL.md` first.

- Trusted workspace is exactly `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`.
- Codex may write task plans/prompts and run lightweight verification.
- Codex must not edit product source, tests, configs, dependency manifests, or `data/` unless the user explicitly overrides in-thread.
- Delegate substantive edits to Cursor Agent with `--workspace /Users/abhsheno/Desktop/Projects/ultra-fast-rag`.
- Before delegation, check for stale wrong-workspace agents with `ps -axo pid,etime,stat,command | rg 'agent --print|\\.local/bin/agent' || true`.

## Git-First Workflow

Before every code/doc/config change:

1. Run `git status --short`.
2. Inspect relevant diffs, especially for files already modified.
3. Identify pre-existing changes and leave unrelated work untouched.
4. Make one focused logical change.
5. Run relevant verification.
6. Run `/code-review` through a subagent and resolve blocking findings.
7. Run `git status --short` again.
8. Stage and commit only explicit paths or hunks for that logical change, unless the user explicitly says not to commit.

Git rules:

- Use small GitHub-style commits: one concern per commit, imperative message, no unrelated files.
- Do not use `git add .`.
- Standing authorization covers non-destructive `git add <explicit paths/hunks>` and `git commit` for the current focused change after verification and review.
- It does not authorize staging unrelated work, pushing, amending, rebasing, resetting, cleaning, reverting, or history rewrites.
- New feature or behavior-change efforts start on their own GitHub-ready branch using the `codex/` prefix unless the user asks otherwise.
- Use the user's `shenoyabhijith` GitHub account/owner context.
- File or update no-secret GitHub issues for reproducible bugs found during assigned repo work. Draft instead if access is unavailable or details may be sensitive.

## Skill Routing

- Use `.cursor/skills/skill-router/SKILL.md` as the source of truth for nontrivial work.
- After routing, always use `$karpathy` as a companion discipline for implementation, debugging, refactoring, review, planning, and doc/config changes.
- Broad exploration or audit -> use subagents when the scope is wide, but require CodeGraph-first searches for code structure.
- Structural or architecture questions -> answer directly with CodeGraph context/trace/explore calls; do not spend the main thread on grep/read loops or delegate work that CodeGraph already answers.
- Design/API shape before code -> pstack architect guidance.
- Bug/fix/prove-it work -> fix-root-cause plus prove-it/verification guidance.
- UI behavior changes -> UI verification guidance and running-app smoke.
- Wiki build/refresh -> project Pi wiki skills.

## Standard Feature Workflow

For nontrivial features, behavior changes, or bug fixes:

1. Plan with OpenSpec: `proposal.md`, `design.md`, `specs/<capability>/spec.md`, and `tasks.md`; validate with `openspec validate <change-name> --strict`.
2. Interrogate the plan and resolve every accepted "Act on" finding before implementation.
3. Write a failing regression test first when practical.
4. Implement through Ralph or delegated agents against the approved plan.
5. Deslop the diff without changing behavior.
6. Run adversarial branch audit for bugs, breaking changes, security, and feature gates.
7. Verify affected UI flows in the running app when UI or behavior changed.

Skip a stage only when genuinely inapplicable and say why.

## Verification Before Completion

- Frontend: run `npx tsc --noEmit` and `npm run build` when available.
- Backend: run `python -m py_compile ...` and focused `pytest` for changed modules.
- Running app/service changes need a runtime smoke or log check with no new exceptions.
- Docs-only changes need Markdown/diff sanity checks and `codegraph sync` when available.
- Before claiming done, inspect the diff for scope creep and report what changed, what passed, and what remains unverified.
