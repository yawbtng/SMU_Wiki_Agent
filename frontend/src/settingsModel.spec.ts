import { settingsDraftFromState, settingsSavePayloadFromDraft } from './settingsModel';

const draft = settingsDraftFromState({
  openrouter_api_key: 'or-existing',
  tavily_api_key: 'tv-existing',
  url_reasoning_openrouter_model: 'deepseek/deepseek-v4-flash',
  graph_enrichment_openrouter_model: 'openai/gpt-4.1-mini',
  graph_answer_openrouter_model: 'deepseek/deepseek-v4-flash',
  scrape_concurrency: 10,
  scrape_browser_mode: 'lightpanda',
  lightpanda_cdp_url: 'ws://127.0.0.1:9222',
  embedding_enabled: false,
  embedding_model: 'nomic-embed-text:latest',
  zvec_collection: 'university_wiki',
  use_tavily_for_map: true,
  tmux_session_grace_seconds: 900,
  wiki_builder_runtime: 'python',
  wiki_skip_pi: true,
  tmux_archive_sessions: false,
  tmux_reconcile_expired_sessions: false,
  pi_cmd: '/opt/pi',
});

if (draft.openrouter_api_key !== 'or-existing') {
  throw new Error('settings draft should expose the OpenRouter key for editing');
}

if (draft.tavily_api_key !== 'tv-existing') {
  throw new Error('settings draft should expose the Tavily key for editing');
}

if (draft.scrape_concurrency !== 10 || draft.scrape_browser_mode !== 'lightpanda') {
  throw new Error('settings draft should expose scrape controls for editing');
}

if (draft.embedding_enabled !== false || draft.use_tavily_for_map !== true) {
  throw new Error('settings draft should preserve boolean provider toggles');
}

const payload = settingsSavePayloadFromDraft({ ...draft, scrape_concurrency: 99, pi_cmd: '' });

if (payload.openrouter_api_key !== 'or-existing' || payload.tavily_api_key !== 'tv-existing') {
  throw new Error('settings save payload should include API keys');
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
