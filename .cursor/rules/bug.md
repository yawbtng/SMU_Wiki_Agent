# Known bugs and regressions

## Docker fresh clone shows "No site data found" (2026-06-06)

**Symptom:** Operator UI at `http://127.0.0.1:8000` (or a smoke port like `18080`) shows `No site data found. Set SCRAPE_PLANNER_DATA_ROOT…` even though the API health check passes.

**Root cause:** `data/` is gitignored, so clones start empty. Docker mounted `./data` (or a removed test dataset path) with no `sites/` children.

**Fix:** `scripts/bootstrap-data.sh` copies `fixtures/demo-workspace` into the runtime data root when empty. Docker entrypoint and `./start.sh` call it automatically on first boot.

## OpenRouter embedding rebuild fails with generic unavailable message (2026-06-05)

**Symptom:** Embeddings tab shows `OpenRouter embeddings unavailable. Set OPENROUTER_API_KEY…` even when Settings shows OpenRouter key as `set`. Rebuild reaches the embedding plan then fails at 0%.

**Root cause:** Saved `openrouter_api_key` in `data/app_state.json` is bridged into the worker, but OpenRouter returns **401 Unauthorized** (invalid, revoked, or expired key). The old error text did not distinguish missing keys from rejected keys.

**Fix for operators:** Create a new API key at [openrouter.ai/keys](https://openrouter.ai/keys), paste it in Settings → OpenRouter, save, then click **Rebuild embeddings**.

**Code follow-up:** `_embedding_unavailable_message()` surfaces 401/402 explicitly; `create_app()` applies the app-state env bridge at startup so reranker readiness reflects saved keys.

## Workspace delete fails for symlinked site directories (2026-06-05)

**Symptom:** Confirm delete on a workspace card (e.g. `demo.edu` pointing at another checkout) does nothing or shows a generic 500; the card stays in the dashboard.

**Root cause:** `delete_site_payload()` used `shutil.rmtree()` on `data/sites/<id>`. When that path is a symlink (common when sibling worktrees share site data), Python 3.14 raises `OSError: Cannot call rmtree on a symbolic link`.

**Fix:** `remove_site_directory()` unlinks symlink entries without deleting their targets; regular directories still use `shutil.rmtree()`.
