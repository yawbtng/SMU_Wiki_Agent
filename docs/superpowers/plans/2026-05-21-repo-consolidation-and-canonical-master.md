# Repo Consolidation And Canonical Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the useful changes from the active `ultra-fast-rag` worktrees into one canonical Desktop checkout with the preserved 25k-page SMU run data and a single long-lived branch named `master`.

**Architecture:** Use the Desktop checkout at `/Users/abhsheno/Desktop/Projects/ultra-fast-rag` as the canonical repository because it already contains the real `data/` and `app_state.json` artifacts. Build the final code state by starting from the most advanced branch (`codex/operator-ui-redesign`), then layer in the detached corpus changes from `/Users/abhsheno/.codex/worktrees/67f9/ultra-fast-rag`, verify the app against the preserved SMU run, and only then prune extra worktrees and branches.

**Tech Stack:** Git worktrees and branches, Streamlit app (`app.py`), Python test/compile verification, local filesystem copy or rsync for `data/sites/...`, in-app browser smoke check.

---

## Current Repo Facts

- Canonical data currently lives in `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/data`.
- Real SMU run path is `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/sites/www.smu.edu/20260520T195401Z-60ac51`.
- `main` points to `ece0284dc32a300fc5178926b183e15c9819ee03`.
- `codex/add-metrics-page-graphs` points to the same commit as `main`.
- `codex/operator-ui-redesign` is `26` commits ahead of `main`.
- The current detached worktree at `/Users/abhsheno/.codex/worktrees/67f9/ultra-fast-rag` has uncommitted corpus-related changes in:
  - `app.py`
  - `src/scrape_planner/claude_manifest.py`
  - `src/scrape_planner/ui_navigation.py`
  - `src/scrape_planner/wiki_planner.py`
  - `tests/test_wiki_planner.py`

## Affected Paths

- Canonical repo root: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`
- Detached source worktree: `/Users/abhsheno/.codex/worktrees/67f9/ultra-fast-rag`
- Secondary active worktree: `/Users/abhsheno/.codex/worktrees/b22a/ultra-fast-rag`
- Worktree inventory source: `git worktree list --porcelain`
- Canonical app state: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/app_state.json`
- Canonical SMU data root: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/sites/www.smu.edu`
- Plan/audit output to create during execution:
  - `docs/repo-consolidation-audit-2026-05-21.md`
  - `docs/worktree-prune-report-2026-05-21.md`

### Task 1: Create A Safety Snapshot Before Any Merge

**Files:**
- Create: `docs/repo-consolidation-audit-2026-05-21.md`
- Read: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/app_state.json`
- Read: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/sites/www.smu.edu/20260520T195401Z-60ac51/run_status.json`

- [ ] **Step 1: Record the worktree and branch inventory**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git worktree list --porcelain > /tmp/ultra-fast-rag.worktrees.txt
git branch --all --verbose --no-abbrev > /tmp/ultra-fast-rag.branches.txt
```

Expected: both temp files exist and contain the current worktree/branch map.

- [ ] **Step 2: Create immutable backup refs before editing history**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git branch backup/pre-consolidation-root-2026-05-21 codex/operator-ui-redesign
git branch backup/pre-consolidation-main-2026-05-21 main
git tag backup-smu-data-2026-05-21 codex/operator-ui-redesign
```

Expected: `git show-ref --verify refs/heads/backup/pre-consolidation-root-2026-05-21` and `git show-ref --verify refs/tags/backup-smu-data-2026-05-21` both succeed.

- [ ] **Step 3: Snapshot the real SMU run data outside Git**

Run:

```bash
mkdir -p /Users/abhsheno/Desktop/Projects/ultra-fast-rag-backups
rsync -a \
  /Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/sites/www.smu.edu \
  /Users/abhsheno/Desktop/Projects/ultra-fast-rag-backups/
cp /Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/app_state.json \
  /Users/abhsheno/Desktop/Projects/ultra-fast-rag-backups/app_state-2026-05-21.json
```

Expected: backup directory contains `www.smu.edu/` and `app_state-2026-05-21.json`.

- [ ] **Step 4: Write the audit note**

Write `docs/repo-consolidation-audit-2026-05-21.md` with this exact content:

```md
# Repo Consolidation Audit - 2026-05-21

- Canonical repo target: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`
- Canonical data root: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/data`
- Active SMU run: `data/sites/www.smu.edu/20260520T195401Z-60ac51`
- `main` commit: `ece0284dc32a300fc5178926b183e15c9819ee03`
- `codex/operator-ui-redesign` commit: `1646f0d6b78fa6286f6655b3140f36d271c874d9`
- Detached corpus source worktree: `/Users/abhsheno/.codex/worktrees/67f9/ultra-fast-rag`
- Metrics branch equality: `codex/add-metrics-page-graphs` equals `main`
- Safety backups created: `backup/pre-consolidation-root-2026-05-21`, `backup/pre-consolidation-main-2026-05-21`, `backup-smu-data-2026-05-21`
```

- [ ] **Step 5: Commit the audit note**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git add docs/repo-consolidation-audit-2026-05-21.md
git commit -m "docs: record repo consolidation audit"
```

Expected: one new commit is created on the current branch.

### Task 2: Promote The Detached Corpus Changes To A Named Branch

**Files:**
- Modify: `/Users/abhsheno/.codex/worktrees/67f9/ultra-fast-rag/app.py`
- Modify: `/Users/abhsheno/.codex/worktrees/67f9/ultra-fast-rag/src/scrape_planner/claude_manifest.py`
- Modify: `/Users/abhsheno/.codex/worktrees/67f9/ultra-fast-rag/src/scrape_planner/ui_navigation.py`
- Modify: `/Users/abhsheno/.codex/worktrees/67f9/ultra-fast-rag/src/scrape_planner/wiki_planner.py`
- Create: `/Users/abhsheno/.codex/worktrees/67f9/ultra-fast-rag/tests/test_wiki_planner.py`

- [ ] **Step 1: Create a branch at the detached HEAD**

Run:

```bash
cd /Users/abhsheno/.codex/worktrees/67f9/ultra-fast-rag
git switch -c codex/corpus-normalization-recovery
```

Expected: `git status --branch` shows `## codex/corpus-normalization-recovery`.

- [ ] **Step 2: Run the existing focused verification before committing**

Run:

```bash
cd /Users/abhsheno/.codex/worktrees/67f9/ultra-fast-rag
/usr/bin/python3 -m py_compile \
  app.py \
  src/scrape_planner/wiki_planner.py \
  src/scrape_planner/claude_manifest.py \
  src/scrape_planner/ui_navigation.py \
  src/scrape_planner/ui_claude_plan.py
PYTHONPATH=src /usr/bin/python3 -m pytest \
  tests/test_raw_retrieval.py \
  tests/test_raw_retrieval_integration.py \
  tests/test_wiki_planner.py -q
```

Expected: compile command exits `0` and pytest reports all tests passing.

- [ ] **Step 3: Commit the detached changes as a portable branch**

Run:

```bash
cd /Users/abhsheno/.codex/worktrees/67f9/ultra-fast-rag
git add app.py \
  src/scrape_planner/claude_manifest.py \
  src/scrape_planner/ui_navigation.py \
  src/scrape_planner/wiki_planner.py \
  tests/test_wiki_planner.py
git commit -m "feat: normalize corpus sources for wiki planning"
```

Expected: `git log -1 --oneline` shows the new corpus-normalization commit.

- [ ] **Step 4: Confirm the branch now contains the portable change**

Run:

```bash
cd /Users/abhsheno/.codex/worktrees/67f9/ultra-fast-rag
git rev-parse HEAD
git rev-parse codex/corpus-normalization-recovery
```

Expected: both hashes match.

### Task 3: Build The Consolidation Branch In The Desktop Checkout

**Files:**
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/app.py`
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/src/scrape_planner/*.py`
- Modify: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/tests/*.py`

- [ ] **Step 1: Start from the most advanced code branch**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git switch codex/operator-ui-redesign
git switch -c codex/consolidated-canonical
```

Expected: `git status --branch` shows `## codex/consolidated-canonical`.

- [ ] **Step 2: Compare the corpus branch against the Desktop checkout before merging**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git diff --stat codex/operator-ui-redesign..codex/corpus-normalization-recovery
```

Expected: diff summary includes the corpus files from the detached recovery branch.

- [ ] **Step 3: Merge the recovered corpus branch**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git merge --no-ff codex/corpus-normalization-recovery
```

Expected: merge succeeds, or if there are conflicts they are limited to the corpus files and `app.py`.

- [ ] **Step 4: Resolve conflicts by preserving both operator UI and corpus normalization**

Use this resolution rule:

```text
- Keep operator navigation and runtime/status work from `codex/operator-ui-redesign`.
- Keep the `Corpus` stage wiring from the recovered branch.
- Keep `normalize_corpus_sources(...)` and the `tests/test_wiki_planner.py` coverage.
- Do not overwrite Desktop `data/` paths or `app_state.json`.
```

- [ ] **Step 5: Verify the merged code state**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
/usr/bin/python3 -m py_compile \
  app.py \
  src/scrape_planner/wiki_planner.py \
  src/scrape_planner/claude_manifest.py \
  src/scrape_planner/ui_navigation.py \
  src/scrape_planner/ui_claude_plan.py
PYTHONPATH=src /usr/bin/python3 -m pytest \
  tests/test_raw_retrieval.py \
  tests/test_raw_retrieval_integration.py \
  tests/test_wiki_planner.py -q
```

Expected: both commands exit `0`.

- [ ] **Step 6: Commit any manual conflict resolution**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git add app.py src/scrape_planner tests
git commit -m "merge: consolidate operator UI with corpus normalization"
```

Expected: the consolidation branch contains a merge commit or a follow-up conflict-resolution commit.

### Task 4: Reattach The Preserved SMU Data To The Canonical Checkout

**Files:**
- Read: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/app_state.json`
- Read: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/sites/www.smu.edu/20260520T195401Z-60ac51/selected_urls.json`
- Read: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/sites/www.smu.edu/20260520T195401Z-60ac51/scrape_manifest.json`

- [ ] **Step 1: Confirm the data still matches the expected counts**

Run:

```bash
jq 'length' /Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/sites/www.smu.edu/20260520T195401Z-60ac51/selected_urls.json
jq 'length' /Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/sites/www.smu.edu/20260520T195401Z-60ac51/scrape_manifest.json
jq '[.[] | .status] | group_by(.) | map({status: .[0], count: length})' \
  /Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/sites/www.smu.edu/20260520T195401Z-60ac51/scrape_manifest.json
```

Expected:

```text
25376
25376
[
  {"status":"failed","count":1570},
  {"status":"success","count":23806}
]
```

- [ ] **Step 2: Verify the workspace is still registered**

Run:

```bash
jq '.workspaces' /Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/app_state.json
```

Expected: it contains the `www.smu.edu` workspace.

- [ ] **Step 3: If the canonical branch modifies ignored runtime files, restore them from backup**

Run only if needed:

```bash
rsync -a \
  /Users/abhsheno/Desktop/Projects/ultra-fast-rag-backups/www.smu.edu/ \
  /Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/sites/www.smu.edu/
cp /Users/abhsheno/Desktop/Projects/ultra-fast-rag-backups/app_state-2026-05-21.json \
  /Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/app_state.json
```

Expected: the Desktop checkout retains the original SMU run files and workspace state.

### Task 5: Verify The Canonical Checkout In Runtime

**Files:**
- Run: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/app.py`
- Read: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag/data/sites/www.smu.edu/20260520T195401Z-60ac51/*`

- [ ] **Step 1: Stop the stale non-canonical Streamlit listeners**

Run:

```bash
lsof -nP -iTCP:8501 -sTCP:LISTEN
lsof -nP -iTCP:8502 -sTCP:LISTEN
```

Expected: identify the old listeners before starting the canonical app.

- [ ] **Step 2: Launch the canonical Desktop checkout**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
/usr/bin/python3 -m streamlit run app.py --server.port 8501 --server.headless true
```

Expected: Streamlit serves the Desktop checkout on `http://localhost:8501`.

- [ ] **Step 3: Verify the browser shows the preserved SMU workspace and previous run**

Use the in-app browser to confirm:

```text
- Workspace list contains Southern Methodist University
- Opening the workspace does not show "No workspaces yet"
- The run picker surfaces the preserved run `20260520T195401Z-60ac51`
- The Corpus/Graph/operator surfaces load without exceptions
```

- [ ] **Step 4: Re-run targeted verification from the canonical checkout**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
/usr/bin/python3 -m py_compile app.py
PYTHONPATH=src /usr/bin/python3 -m pytest tests/test_wiki_planner.py -q
```

Expected: both commands pass while the app remains up.

### Task 6: Move The Canonical State Onto `master` And Prune The Sprawl

**Files:**
- Create: `docs/worktree-prune-report-2026-05-21.md`

- [ ] **Step 1: Fast-forward `master` to the validated consolidation branch**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git switch master
git merge --ff-only codex/consolidated-canonical
```

Expected: `master` now points at the validated canonical commit.

- [ ] **Step 2: Make the Desktop checkout the only long-lived worktree**

Run:

```bash
git worktree remove /Users/abhsheno/.codex/worktrees/67f9/ultra-fast-rag
git worktree remove /Users/abhsheno/.codex/worktrees/b22a/ultra-fast-rag
git worktree remove /Users/abhsheno/.codex/worktrees/f98b/ultra-fast-rag
git worktree prune
```

Expected: `git worktree list` shows only `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`.

- [ ] **Step 3: Delete only the now-obsolete active feature branches**

Run:

```bash
git branch -d codex/add-metrics-page-graphs
git branch -d codex/operator-ui-redesign
git branch -d codex/corpus-normalization-recovery
git branch -d codex/consolidated-canonical
```

Expected: those branches are removed because `master` contains their commits.

- [ ] **Step 4: Leave salvage branches untouched until a second cleanup pass**

Write `docs/worktree-prune-report-2026-05-21.md` with this exact content:

```md
# Worktree Prune Report - 2026-05-21

- Canonical branch: `master`
- Canonical checkout: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`
- Removed worktrees:
  - `/Users/abhsheno/.codex/worktrees/67f9/ultra-fast-rag`
  - `/Users/abhsheno/.codex/worktrees/b22a/ultra-fast-rag`
  - `/Users/abhsheno/.codex/worktrees/f98b/ultra-fast-rag`
- Removed branches:
  - `codex/add-metrics-page-graphs`
  - `codex/operator-ui-redesign`
  - `codex/corpus-normalization-recovery`
  - `codex/consolidated-canonical`
- Preserved safety refs:
  - `backup/pre-consolidation-root-2026-05-21`
  - `backup/pre-consolidation-main-2026-05-21`
  - `backup-smu-data-2026-05-21`
- Deferred cleanup:
  - all `salvage/*` branches
  - all old experiment branches at `90a06cd890b51124b1b5afc1d4c71f415b6b024e`
```

- [ ] **Step 5: Commit the prune report**

Run:

```bash
cd /Users/abhsheno/Desktop/Projects/ultra-fast-rag
git add docs/worktree-prune-report-2026-05-21.md
git commit -m "docs: record worktree consolidation cleanup"
```

Expected: final `master` contains both the code consolidation and the cleanup record.

## Self-Review

- Spec coverage:
  - One canonical checkout: covered in Tasks 3, 5, and 6.
  - Preserve latest features: covered by using `codex/operator-ui-redesign` plus the detached corpus branch in Task 3.
  - Preserve the 25k-page scrape data: covered in Tasks 1 and 4.
  - End with one long-lived branch `master`: covered in Task 6.
- Placeholder scan:
  - No `TBD`, `TODO`, or vague “handle later” steps remain.
- Type and name consistency:
  - Canonical branch names, worktree paths, and SMU run path are consistent across all tasks.
