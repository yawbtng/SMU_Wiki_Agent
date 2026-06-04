import {
  SECRET_UNCHANGED,
  estimateOpenRouterCost,
  mergeSecretForSave,
  secretDraftValue,
  secretInputDisplayValue,
  settingsDraftFromState,
  settingsSavePayloadFromDraft,
} from './settingsModel';

const draft = settingsDraftFromState({
  openrouter_api_key: 'or-existing',
  tavily_api_key: 'tv-existing',
  url_reasoning_openrouter_model: 'deepseek/deepseek-v4-flash',
  scrape_concurrency: 10,
  scrape_browser_mode: 'lightpanda',
  lightpanda_cdp_url: 'ws://127.0.0.1:9222',
  embedding_enabled: false,
  embedding_model: 'openai/text-embedding-3-small',
  zvec_collection: 'university_wiki',
  use_tavily_for_map: true,
  tmux_session_grace_seconds: 900,
  tmux_archive_sessions: false,
  tmux_reconcile_expired_sessions: false,
  pi_cmd: '/opt/pi',
});

if (draft.openrouter_api_key !== SECRET_UNCHANGED || draft.tavily_api_key !== SECRET_UNCHANGED) {
  throw new Error('settings draft should mask persisted secrets instead of exposing raw values');
}

if (secretInputDisplayValue(draft.openrouter_api_key) !== '••••••••••••') {
  throw new Error('masked secret input should render a presence placeholder');
}

if (draft.scrape_concurrency !== 10 || draft.scrape_browser_mode !== 'lightpanda') {
  throw new Error('settings draft should expose scrape controls for editing');
}

if (draft.embedding_enabled !== false || draft.use_tavily_for_map !== true) {
  throw new Error('settings draft should preserve boolean provider toggles');
}

const payload = settingsSavePayloadFromDraft({ ...draft, scrape_concurrency: 99, pi_cmd: '' }, {
  openrouter_api_key: 'or-existing',
  tavily_api_key: 'tv-existing',
});

if (payload.openrouter_api_key !== 'or-existing' || payload.tavily_api_key !== 'tv-existing') {
  throw new Error('settings save payload should preserve saved secrets when the draft left them unchanged');
}

const replaced = settingsSavePayloadFromDraft(
  { ...draft, openrouter_api_key: 'or-replaced', tavily_api_key: SECRET_UNCHANGED },
  { openrouter_api_key: 'or-existing', tavily_api_key: 'tv-existing' },
);
if (replaced.openrouter_api_key !== 'or-replaced' || replaced.tavily_api_key !== 'tv-existing') {
  throw new Error('settings save payload should replace only edited secrets');
}

const unchangedBlank = settingsSavePayloadFromDraft(
  { ...draft, openrouter_api_key: '', tavily_api_key: SECRET_UNCHANGED },
  { openrouter_api_key: 'or-existing', tavily_api_key: 'tv-existing' },
);
if (unchangedBlank.openrouter_api_key !== 'or-existing') {
  throw new Error('blank unchanged secret should not erase saved key');
}

if (payload.scrape_concurrency !== 16) {
  throw new Error('settings save payload should clamp scrape concurrency to the supported range');
}

if (payload.pi_cmd !== 'pi') {
  throw new Error('settings save payload should default an empty Pi command to pi');
}

if (payload.tmux_session_grace_seconds !== 900) {
  throw new Error('settings save payload should convert grace minutes back to seconds');
}

if (payload.llm_provider !== 'openrouter' || payload.url_reasoning_provider !== 'openrouter') {
  throw new Error('settings save payload should force OpenRouter providers');
}

if (payload.wiki_builder_runtime !== 'pi' || payload.wiki_skip_pi !== false) {
  throw new Error('settings save payload should always use LLM Wiki compile');
}

if ('graph_enrichment_openrouter_model' in payload || 'graph_answer_openrouter_model' in payload) {
  throw new Error('settings save payload should not include stale wiki graph model fields');
}

if (estimateOpenRouterCost('openai/gpt-4.1-mini', [{ id: 'openai/gpt-4.1-mini', label: 'mini', inputPerMTok: 0.4, outputPerMTok: 1.6, category: 'llm' }], 1_000_000, 1_000_000) !== 2) {
  throw new Error('OpenRouter cost estimate should use selected model pricing');
}
