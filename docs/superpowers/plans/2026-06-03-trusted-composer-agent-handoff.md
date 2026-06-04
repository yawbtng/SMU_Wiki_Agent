# Trusted Composer Agent Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run Cursor Agent through Composer only inside `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`, with a research pass, a markdown implementation plan, and evidence-based verification before completion.

**Architecture:** Codex writes the task-specific markdown plan in this repo, then launches Cursor Agent headlessly with `--workspace /Users/abhsheno/Desktop/Projects/ultra-fast-rag`. The research pass is read-only and must use `rg` for literal policy/text lookups and CodeGraph for structural code questions. The implementation pass reads the plan file and executes only the plan, preserving unrelated dirty work.

**Tech Stack:** Cursor Agent CLI (`agent`), Composer 2.5, `rg`, CodeGraph, `AGENTS.md`, `.cursor/skills/skill-router/SKILL.md`, repo-local verification commands.

---

## Trust Boundary

- Trusted workspace: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`
- Do not launch Cursor Agent with `--workspace /Users/abhsheno`.
- Do not inspect or trust sibling worktrees unless the user explicitly changes the trust boundary.
- Start every Cursor Agent prompt with the trust boundary sentence below:

```text
Trusted workspace is exactly /Users/abhsheno/Desktop/Projects/ultra-fast-rag. Do not inspect or trust any other directory, including /Users/abhsheno and sibling worktrees.
```

## Task 1: Research With Composer

**Files:**
- Read: `AGENTS.md`
- Read: `.cursor/skills/skill-router/SKILL.md`
- Read as needed: task-relevant source, tests, specs, and docs inside the trusted workspace only

- [ ] **Step 1: Confirm no stale wrong-workspace agent is running**

Run:

```bash
ps -axo pid,etime,stat,command | rg 'agent --print|\\.local/bin/agent' || true
```

Expected: no running `agent --print` process whose command contains `--workspace /Users/abhsheno`.

- [ ] **Step 2: Run the read-only research agent**

Run from `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`:

```bash
agent --print --mode ask --model composer-2.5 --trust --workspace /Users/abhsheno/Desktop/Projects/ultra-fast-rag 'Trusted workspace is exactly /Users/abhsheno/Desktop/Projects/ultra-fast-rag. Do not inspect or trust any other directory, including /Users/abhsheno and sibling worktrees. Read AGENTS.md and .cursor/skills/skill-router/SKILL.md first. Research only; do not edit files. Use CodeGraph first for symbols, definitions, call paths, dependencies, impact analysis, and affected-test discovery. Use rg for literal policy text, config keys, string literals, logs, markdown, and non-indexed files. Return evidence-backed findings, exact files/symbols involved, and the verification commands needed for the implementation plan.'
```

Expected: the response cites repo-local evidence and does not report edits.

## Task 2: Write The Task-Specific Markdown Plan

**Files:**
- Create: `docs/superpowers/plans/YYYY-MM-DD-task-name.md`
- Read: research output from Task 1
- Read: task-relevant repo files only inside `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`

- [ ] **Step 1: Create a task-specific plan**

Write the task-specific plan under `docs/superpowers/plans/` with:

```markdown
# Task Name Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One sentence describing the concrete requested change.

**Architecture:** Two or three sentences explaining how the change fits this repo.

**Tech Stack:** Exact languages, framework pieces, tools, and verification commands used by this repo.

---

## Trust Boundary

- Trusted workspace: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`
- Do not inspect or trust any other directory.

## Tasks

### Task 1: First Concrete Change

**Files:**
- Modify: `exact/repo/path.py`
- Test: `tests/exact_test.py`

- [ ] **Step 1: Write the failing test**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest tests/exact_test.py::test_specific_behavior -q
```

Expected: fails for the missing behavior.

- [ ] **Step 2: Implement the minimal change**

Describe the exact function, class, route, component, or config change and include enough code-level detail for an agent to make only that edit.

- [ ] **Step 3: Verify the task**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m py_compile exact/repo/path.py tests/exact_test.py
PYTHONPATH=. .venv/bin/pytest tests/exact_test.py::test_specific_behavior -q
```

Expected: both commands pass.
```

Expected: the task-specific plan has exact repo paths, concrete verification commands, and no unrelated scope.

## Task 3: Implement With Composer From The Plan File

**Files:**
- Read: `AGENTS.md`
- Read: `.cursor/skills/skill-router/SKILL.md`
- Read: `docs/superpowers/plans/YYYY-MM-DD-task-name.md`
- Modify only: files listed in the task-specific plan

- [ ] **Step 1: Start the implementation agent**

Run from `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`:

```bash
agent --print --model composer-2.5 --trust --workspace /Users/abhsheno/Desktop/Projects/ultra-fast-rag 'Trusted workspace is exactly /Users/abhsheno/Desktop/Projects/ultra-fast-rag. Do not inspect or trust any other directory, including /Users/abhsheno and sibling worktrees. Read AGENTS.md, .cursor/skills/skill-router/SKILL.md, and docs/superpowers/plans/YYYY-MM-DD-task-name.md first. Implement exactly the markdown plan, one focused logical change at a time. Before editing, run git status --short and inspect diffs for any files you will touch. Do not overwrite unrelated pre-existing changes. Use CodeGraph first for structural code questions and affected-test discovery. Use rg for literal strings, policy text, configs, markdown, and logs. After any source, config, test, or doc edit, run codegraph sync before further CodeGraph queries and before reporting completion. Run the compile/syntax and runtime verification commands listed in the plan. Do not commit unless the user explicitly asks.'
```

Expected: the agent modifies only planned files, reports verification output, and leaves unrelated dirty work alone.

## Task 4: Completion Verification

**Files:**
- Check: files changed by the implementation agent
- Check: `.codegraph/` state through `codegraph status` or the configured CodeGraph MCP

- [ ] **Step 1: Sync/check CodeGraph after edits**

Run:

```bash
codegraph sync
codegraph status
```

Expected: sync and status succeed. If the shell command is unavailable, use the configured CodeGraph MCP status/sync path and report the exact fallback.

- [ ] **Step 2: Run compile/syntax checks for changed code paths**

For Python changes, run:

```bash
PYTHONPATH=. .venv/bin/python -m py_compile path/to/changed.py tests/path/to/changed_test.py
```

For frontend changes, run the repo-local frontend verification command named in the task-specific plan.

Expected: all syntax/compile checks pass.

- [ ] **Step 3: Run behavior/runtime sanity checks**

Run the narrow tests named in the task-specific plan. If the change affects a running app or operator UI, also run a runtime sanity check against the affected path and confirm no new exceptions in logs or console output.

Expected: behavior checks pass and no new runtime exceptions are found.

- [ ] **Step 4: Report final state**

Run:

```bash
git status --short
```

Expected: report changed files, verification commands, pass/fail state, and any unrelated pre-existing dirty work.
