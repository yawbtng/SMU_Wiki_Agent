# CodeGraph Guide

This project has a CodeGraph MCP/server index when `.codegraph/` exists. Prefer it for structural code questions because it is tree-sitter parsed and faster than grep loops.

## Use CodeGraph For

| Question | Tool |
| --- | --- |
| Where is symbol X defined? | `codegraph_search` |
| What calls Y? | `codegraph_callers` |
| What does Y call? | `codegraph_callees` |
| How does X reach Y? | `codegraph_trace` |
| What would break if Z changes? | `codegraph_impact` |
| Show signature/source/docstring | `codegraph_node` |
| Focused context for an area | `codegraph_context` |
| Several related symbols at once | `codegraph_explore` |
| Files under a path | `codegraph_files` |
| Index health | `codegraph_status` |

## Rules

- Do not grep first for symbols. Use CodeGraph first, then native search only for literal strings, comments, logs, markdown, configs, or non-indexed data.
- For architecture questions, use `codegraph_context` then one `codegraph_explore`.
- For flow questions, start with `codegraph_trace`; do not rebuild the path with many search/caller calls.
- Answer structural and architecture questions directly with CodeGraph before considering subagents. Delegate only broad scans, independent audits, or work that CodeGraph cannot answer by itself.
- Trust CodeGraph results unless `codegraph status` reports problems.
- After any source/config/test/doc change, run `codegraph sync` before more CodeGraph queries and before reporting completion.
- If `codegraph` is not on PATH, try `/Users/abhsheno/.local/bin/codegraph`.
- If `.codegraph/` does not exist, ask: "I notice this project doesn't have CodeGraph initialized. Want me to run `codegraph init -i` to build the index?"
