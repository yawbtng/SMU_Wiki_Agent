# OpenRouter App-State Env Bridge

## Objective

Fix the bug where Settings saves `openrouter_api_key` into `data/app_state.json`, but wiki build, embedding, reranker, and MCP jobs fail because launched processes only read `OPENROUTER_API_KEY` from the environment.

## Constraints

- Trusted workspace is exactly `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`.
- Preserve unrelated dirty work, especially current PDF/doc changes.
- Do not print or commit real secrets.
- Use fake keys in tests.
- Do not commit.

## Current Evidence

- `data/app_state.json` contains `openrouter_api_key` with a non-empty value.
- `logs/webapp.env` does not contain `OPENROUTER_API_KEY`.
- `src/scrape_planner/index/embedding_client.py` and `src/scrape_planner/wiki/llm_wiki_index.py` read `OPENROUTER_API_KEY` from `os.getenv`.
- Tmux/Pi/MCP launchers do not bridge saved app-state secrets into child process env.

## Implementation Steps

1. Add a failing regression test first.
   - Preferred location: existing tests near tmux/settings/webapp launch behavior.
   - The test should save/load fake app-state values and assert spawned tmux shell commands export:
     - `OPENROUTER_API_KEY` from `openrouter_api_key`
     - `TAVILY_API_KEY` from `tavily_api_key`
   - Assert only fake values; never inspect real local data.

2. Implement a small env bridge.
   - Preferred home: `src/scrape_planner/app/tmux_settings.py` or a nearby small helper if cleaner.
   - Map non-empty app-state fields:
     - `openrouter_api_key` -> `OPENROUTER_API_KEY`
     - `tavily_api_key` -> `TAVILY_API_KEY`
     - if an existing app-state embedding/rerank model field exists, map it to the corresponding existing env var only if already supported by code.
   - Use `shlex.quote` for shell exports.
   - Never log secret values.

3. Wire the env bridge into tmux-managed commands.
   - Ensure wiki build and MCP tmux sessions inherit the env bridge.
   - Do not require changing the Settings UI.

4. Consider in-process embedding builds.
   - If there is a background embedding/index job that runs inside the Uvicorn process, add the smallest bridge or fallback so it can use saved app-state keys too.
   - Keep this scoped; do not refactor provider configuration broadly.

5. Update or add focused tests.
   - Prove the fake key is exported to tmux shells.
   - If in-process fallback is added, prove it uses app-state only when env is empty.

## Verification

Run at minimum:

```bash
python -m py_compile src/scrape_planner/app/tmux_settings.py src/scrape_planner/infra/tmux_session_shell.py
pytest <new-or-updated-test> -q
pytest tests/test_llm_wiki_index.py::test_query_uses_openrouter_rerank_when_configured -q
```

If a broader webapp verification is reasonably quick, run:

```bash
bash scripts/verify-webapp.sh
```

After source/test/doc changes, run:

```bash
codegraph sync
codegraph status
```

## Reporting

Report changed files, verification commands and pass/fail. Mention unrelated pre-existing dirty files were left untouched.
