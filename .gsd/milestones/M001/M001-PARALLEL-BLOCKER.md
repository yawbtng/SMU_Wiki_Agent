# BLOCKER — auto-mode recovery failed

Unit `research-slice` for `M001/parallel-research` failed to produce this artifact after idle recovery exhausted all retries.

**Reason**: Deterministic policy rejection for research-slice "M001/parallel-research": bash: HARD BLOCK: unit "research-slice" runs under tools-policy "planning" — bash is restricted to read-only commands (cat/grep/git log/etc); cannot run "pwd && ls -la ../../../../../../.gsd/projects/30c3890f0206/milestones/M001". This is a mechanical gate enforced by manifest.tools (#4934). You MUST NOT proceed, retry the same call, or rationalize past this block. If you need to write user source, the work belongs in execute-task, not in a planning unit.. Retrying cannot resolve this gate — writing blocker placeholder to advance pipeline.

This placeholder was written by auto-mode so the pipeline can advance.
Review and replace this file before relying on downstream artifacts.