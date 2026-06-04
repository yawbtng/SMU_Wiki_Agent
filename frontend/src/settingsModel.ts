export type SettingsRecord = Record<string, unknown>;

export type SettingsDraft = {
  openrouter_api_key: string;
  tavily_api_key: string;
  url_reasoning_openrouter_model: string;
  graph_enrichment_openrouter_model: string;
  graph_answer_openrouter_model: string;
  scrape_concurrency: number;
  scrape_browser_mode: string;
  lightpanda_cdp_url: string;
  embedding_enabled: boolean;
  embedding_model: string;
  zvec_collection: string;
  use_tavily_for_map: boolean;
  tmux_session_grace_minutes: number;
  wiki_builder_runtime: string;
  wiki_skip_pi: boolean;
  tmux_archive_sessions: boolean;
  tmux_reconcile_expired_sessions: boolean;
  pi_cmd: string;
};

export type OpenRouterModelOption = {
  id: string;
  label: string;
  inputPerMTok: number;
  outputPerMTok: number;
  category: 'llm' | 'embedding';
};

export const OPENROUTER_LLM_MODELS: OpenRouterModelOption[] = [
  { id: 'deepseek/deepseek-v4-flash', label: 'DeepSeek V4 Flash', inputPerMTok: 0.28, outputPerMTok: 0.42, category: 'llm' },
  { id: 'openai/gpt-4.1-mini', label: 'OpenAI GPT-4.1 Mini', inputPerMTok: 0.4, outputPerMTok: 1.6, category: 'llm' },
  { id: 'openai/gpt-4.1', label: 'OpenAI GPT-4.1', inputPerMTok: 2, outputPerMTok: 8, category: 'llm' },
  { id: 'anthropic/claude-sonnet-4.5', label: 'Claude Sonnet 4.5', inputPerMTok: 3, outputPerMTok: 15, category: 'llm' },
  { id: 'google/gemini-2.5-flash', label: 'Gemini 2.5 Flash', inputPerMTok: 0.3, outputPerMTok: 2.5, category: 'llm' },
];

export const OPENROUTER_EMBEDDING_MODELS: OpenRouterModelOption[] = [
  { id: 'openai/text-embedding-3-small', label: 'OpenAI text-embedding-3-small', inputPerMTok: 0.02, outputPerMTok: 0, category: 'embedding' },
  { id: 'openai/text-embedding-3-large', label: 'OpenAI text-embedding-3-large', inputPerMTok: 0.13, outputPerMTok: 0, category: 'embedding' },
];

const DEFAULT_OPENROUTER_MODEL = 'deepseek/deepseek-v4-flash';
const DEFAULT_OPENROUTER_EMBEDDING_MODEL = 'openai/text-embedding-3-small';

export function settingsDraftFromState(state: SettingsRecord): SettingsDraft {
  const graceSeconds = numberValue(state.tmux_session_grace_seconds, 1800);
  return {
    openrouter_api_key: stringValue(state.openrouter_api_key),
    tavily_api_key: stringValue(state.tavily_api_key),
    url_reasoning_openrouter_model: normalizeModel(state.url_reasoning_openrouter_model, OPENROUTER_LLM_MODELS, DEFAULT_OPENROUTER_MODEL),
    graph_enrichment_openrouter_model: normalizeModel(state.graph_enrichment_openrouter_model, OPENROUTER_LLM_MODELS, 'openai/gpt-4.1-mini'),
    graph_answer_openrouter_model: normalizeModel(state.graph_answer_openrouter_model, OPENROUTER_LLM_MODELS, DEFAULT_OPENROUTER_MODEL),
    scrape_concurrency: clampInt(state.scrape_concurrency, 4, 1, 16),
    scrape_browser_mode: normalizeBrowserMode(state.scrape_browser_mode),
    lightpanda_cdp_url: stringValue(state.lightpanda_cdp_url),
    embedding_enabled: boolValue(state.embedding_enabled, true),
    embedding_model: normalizeModel(state.embedding_model, OPENROUTER_EMBEDDING_MODELS, DEFAULT_OPENROUTER_EMBEDDING_MODEL),
    zvec_collection: stringValue(state.zvec_collection, 'university_wiki'),
    use_tavily_for_map: boolValue(state.use_tavily_for_map, false),
    tmux_session_grace_minutes: Math.round(graceSeconds / 60),
    wiki_builder_runtime: normalizeWikiRuntime(state.wiki_builder_runtime),
    wiki_skip_pi: boolValue(state.wiki_skip_pi, false),
    tmux_archive_sessions: boolValue(state.tmux_archive_sessions, true),
    tmux_reconcile_expired_sessions: boolValue(state.tmux_reconcile_expired_sessions, true),
    pi_cmd: stringValue(state.pi_cmd, 'pi'),
  };
}

export function settingsSavePayloadFromDraft(draft: SettingsDraft): SettingsRecord {
  return {
    openrouter_api_key: draft.openrouter_api_key.trim(),
    tavily_api_key: draft.tavily_api_key.trim(),
    llm_provider: 'openrouter',
    url_reasoning_provider: 'openrouter',
    graph_enrichment_provider: 'openrouter',
    graph_answer_provider: 'openrouter',
    url_reasoning_openrouter_model: normalizeModel(draft.url_reasoning_openrouter_model, OPENROUTER_LLM_MODELS, DEFAULT_OPENROUTER_MODEL),
    graph_enrichment_openrouter_model: normalizeModel(draft.graph_enrichment_openrouter_model, OPENROUTER_LLM_MODELS, 'openai/gpt-4.1-mini'),
    graph_answer_openrouter_model: normalizeModel(draft.graph_answer_openrouter_model, OPENROUTER_LLM_MODELS, DEFAULT_OPENROUTER_MODEL),
    scrape_concurrency: clampInt(draft.scrape_concurrency, 4, 1, 16),
    scrape_browser_mode: normalizeBrowserMode(draft.scrape_browser_mode),
    lightpanda_cdp_url: draft.lightpanda_cdp_url.trim(),
    embedding_enabled: Boolean(draft.embedding_enabled),
    embedding_model: normalizeModel(draft.embedding_model, OPENROUTER_EMBEDDING_MODELS, DEFAULT_OPENROUTER_EMBEDDING_MODEL),
    zvec_collection: draft.zvec_collection.trim() || 'university_wiki',
    use_tavily_for_map: Boolean(draft.use_tavily_for_map),
    tmux_session_grace_seconds: Math.max(0, Math.round(Number(draft.tmux_session_grace_minutes || 0) * 60)),
    wiki_builder_runtime: normalizeWikiRuntime(draft.wiki_builder_runtime),
    wiki_skip_pi: Boolean(draft.wiki_skip_pi),
    tmux_archive_sessions: Boolean(draft.tmux_archive_sessions),
    tmux_reconcile_expired_sessions: Boolean(draft.tmux_reconcile_expired_sessions),
    pi_cmd: draft.pi_cmd.trim() || 'pi',
  };
}

export function openRouterModelOption(modelId: string, options: OpenRouterModelOption[]): OpenRouterModelOption {
  return options.find((option) => option.id === modelId) ?? options[0];
}

export function estimateOpenRouterCost(modelId: string, options: OpenRouterModelOption[], inputTokens: number, outputTokens = 0): number {
  const model = openRouterModelOption(modelId, options);
  return (Math.max(0, inputTokens) / 1_000_000) * model.inputPerMTok + (Math.max(0, outputTokens) / 1_000_000) * model.outputPerMTok;
}

function normalizeModel(value: unknown, options: OpenRouterModelOption[], fallback: string): string {
  const text = stringValue(value, fallback);
  return options.some((option) => option.id === text) ? text : fallback;
}

function stringValue(value: unknown, fallback = ''): string {
  if (value === null || value === undefined) return fallback;
  const text = String(value).trim();
  return text || fallback;
}

function numberValue(value: unknown, fallback: number): number {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function clampInt(value: unknown, fallback: number, min: number, max: number): number {
  const number = Math.round(numberValue(value, fallback));
  return Math.max(min, Math.min(max, number));
}

function boolValue(value: unknown, fallback: boolean): boolean {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'string') return !['0', 'false', 'off', 'no'].includes(value.trim().toLowerCase());
  return Boolean(value);
}

function normalizeBrowserMode(value: unknown): string {
  const mode = stringValue(value, 'none').toLowerCase();
  return mode === 'lightpanda' ? 'lightpanda' : 'none';
}

function normalizeWikiRuntime(value: unknown): string {
  const mode = stringValue(value, 'pi').toLowerCase().replace(/_/g, '-');
  return mode === 'python' || mode === 'deterministic' ? 'python' : 'pi';
}
