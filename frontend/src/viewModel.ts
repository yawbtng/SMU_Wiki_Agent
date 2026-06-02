export type AnyRecord = Record<string, any>;
export type Tone = 'active' | 'ready' | 'warning' | 'danger' | 'neutral';

export type MetricModel = {
  label: string;
  value: string;
  help?: string;
};

export type StatusBandModel = {
  title: string;
  subtitle: string;
  statusLabel: string;
  tone: Tone;
  actionLabel: string;
};

export type OverviewInput = {
  siteId: string;
  siteUrl?: string;
  runId?: string;
  rawSources?: AnyRecord;
  wiki?: AnyRecord;
  agent?: AnyRecord;
  embeddings?: AnyRecord;
  run?: AnyRecord;
};

export type OverviewModel = {
  statusBand: StatusBandModel;
  essentialMetrics: MetricModel[];
  sourceStatusRows: AnyRecord[];
  sourceKindRows: AnyRecord[];
  wikiRows: AnyRecord[];
  nextAction: string;
};

export type EmbeddingModel = {
  indexTone: Tone;
  indexLabel: string;
  jobTone: Tone;
  jobLabel: string;
  headline: string;
  lastRebuildLine: string;
  stats: MetricModel[];
  canRebuild: boolean;
  disabledHint: string;
};

export type McpModel = {
  serverBand: StatusBandModel;
  serverMetrics: MetricModel[];
};

export type MetricCost = {
  amount_usd?: number | null;
  source?: 'reported' | 'estimated' | 'unknown' | 'partial' | 'mixed' | string;
};

export type AgentRunSummary = AnyRecord & {
  run_id: string;
  status?: string;
  total_model_tokens?: number | null;
  llm_usage?: AnyRecord;
  embedding_usage?: AnyRecord;
  cost?: MetricCost;
  metrics_health?: AnyRecord;
};

export type MetricsRollup = AnyRecord & {
  window: string;
  run_count?: number;
  total_tokens?: number | null;
  llm_tokens?: number | null;
  embedding_tokens?: number | null;
  total_cost?: MetricCost;
  embedding_cost?: MetricCost;
  vector_count?: number;
};

export type MetricsModel = {
  aggregateMetrics: MetricModel[];
  latestRunMetrics: MetricModel[];
  runRows: AnyRecord[];
  healthWarnings: string[];
};

export function formatCount(value: unknown): string {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric)) return '0';
  return Math.round(numeric).toLocaleString();
}

export function formatCompact(value: unknown): string {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric)) return '0';
  if (Math.abs(numeric) < 1000) return String(Math.round(numeric));
  return Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(numeric);
}

export function formatOptionalCount(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Unknown';
  return formatCompact(value);
}

export function formatCost(cost: MetricCost | null | undefined): string {
  const source = String(cost?.source ?? 'unknown');
  if (cost?.amount_usd === null || cost?.amount_usd === undefined || source === 'unknown') return 'Unknown';
  const amount = Number(cost.amount_usd);
  if (!Number.isFinite(amount)) return 'Unknown';
  const formatted = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 }).format(amount);
  return source === 'reported' ? `${formatted} reported` : `${formatted} ${source}`;
}

export function titleCase(value: unknown): string {
  const text = String(value ?? '').trim();
  if (!text) return 'Ready';
  return text
    .replace(/[_-]+/g, ' ')
    .split(/\s+/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(' ');
}

function rowsFromCounts(counts: AnyRecord | undefined, labelKey: string): AnyRecord[] {
  return Object.entries(counts ?? {})
    .map(([label, count]) => ({ [labelKey]: titleCase(label), count: formatCount(count) }))
    .sort((a, b) => Number(String(b.count).replace(/,/g, '')) - Number(String(a.count).replace(/,/g, '')));
}

export function toneForStatus(value: unknown): Tone {
  const status = String(value ?? '').toLowerCase();
  if (['running', 'initializing', 'active', 'queued', 'starting'].some((item) => status.includes(item))) return 'active';
  if (['complete', 'completed', 'ready', 'current', 'ok', 'healthy'].some((item) => status.includes(item))) return 'ready';
  if (['failed', 'error', 'stale', 'missing', 'danger'].some((item) => status.includes(item))) return 'danger';
  if (['review', 'pending', 'waiting', 'warning', 'paused'].some((item) => status.includes(item))) return 'warning';
  return 'neutral';
}

export function buildOverviewModel(input: OverviewInput): OverviewModel {
  const raw = input.rawSources ?? {};
  const wiki = input.wiki ?? {};
  const embeddings = input.embeddings ?? {};
  const readySources = Number(raw.ready_count ?? wiki.source_count ?? 0);
  const needsReview = Number(raw.by_status?.['needs-review'] ?? raw.by_status?.needs_review ?? 0) + Number(wiki.review_queue_count ?? 0);
  const pendingOrChanged = Number(wiki.pending_source_count ?? 0) + Number(wiki.changed_source_count ?? 0);
  const wikiStatus = String(wiki.job_status ?? 'not started');
  const indexDocs = Number(embeddings.wiki_index_count ?? 0);
  const lastUpdated = wiki.last_progress || embeddings.last_build_time || input.run?.status?.finished_at || input.run?.status?.updated_at || 'Unknown';
  const health = needsReview > 0 ? 'Needs review' : pendingOrChanged > 0 ? 'Update needed' : indexDocs <= 0 ? 'Index missing' : titleCase(wikiStatus);
  const nextAction = needsReview > 0 ? 'Review flagged sources' : pendingOrChanged > 0 ? 'Update wiki' : indexDocs <= 0 ? 'Build index' : 'Monitor';

  return {
    statusBand: {
      title: 'Overview health',
      subtitle: input.siteUrl || input.siteId || 'Workspace',
      statusLabel: health,
      tone: toneForStatus(health),
      actionLabel: nextAction,
    },
    essentialMetrics: [
      { label: 'Ready Sources', value: formatCount(readySources) },
      { label: 'Needs Review', value: formatCount(needsReview) },
      { label: 'Pending Changes', value: formatCount(pendingOrChanged) },
      { label: 'Wiki Index Docs', value: formatCount(indexDocs), help: String(lastUpdated).slice(0, 19) },
    ],
    sourceStatusRows: rowsFromCounts(raw.by_status, 'status'),
    sourceKindRows: rowsFromCounts(raw.by_kind, 'kind'),
    wikiRows: [
      { metric: 'Wiki status', value: titleCase(wikiStatus) },
      { metric: 'Integrated sources', value: formatCount(wiki.integrated_sources) },
      { metric: 'Pending sources', value: formatCount(wiki.pending_source_count) },
      { metric: 'Changed sources', value: formatCount(wiki.changed_source_count) },
      { metric: 'Review queue', value: formatCount(wiki.review_queue_count) },
    ],
    nextAction,
  };
}

export function formatShortTime(value: unknown): string {
  const text = String(value ?? '').trim();
  if (!text) return '';
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return text.slice(0, 16);
  const diffMs = Date.now() - date.getTime();
  if (diffMs < 60_000) return 'just now';
  if (diffMs < 3_600_000) return `${Math.max(1, Math.floor(diffMs / 60_000))}m ago`;
  if (diffMs < 86_400_000) return `${Math.max(1, Math.floor(diffMs / 3_600_000))}h ago`;
  return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

export function buildEmbeddingModel(embeddings: AnyRecord = {}): EmbeddingModel {
  const job = embeddings.job_state ?? {};
  const indexHealth = String(embeddings.index_health ?? 'missing').toLowerCase();
  const jobStatus = String(job.status ?? 'idle').toLowerCase();
  const changedCount = Number(job.changed_document_count ?? embeddings.changed_document_count ?? 0);
  const wikiCount = Number(embeddings.wiki_index_count ?? 0);
  const rawCount = Number(embeddings.raw_index_count ?? 0);
  const disabled = embeddings.auto_rebuild_enabled === false || embeddings.auto_rebuild_reason === 'embedding_disabled';

  let headline = 'Vectors are indexed and ready for search.';
  if (disabled) headline = 'Embeddings are disabled in Settings.';
  else if (indexHealth === 'stale') headline = 'Index may be stale — rebuild if answers look outdated.';
  else if (indexHealth === 'missing') headline = 'No index yet — run a rebuild after wiki sources are ready.';

  let lastRebuildLine = 'No rebuild has run for this site yet.';
  if (jobStatus === 'running' || jobStatus === 'queued') {
    const trigger = job.trigger ? String(job.trigger) : 'manual';
    lastRebuildLine = `Rebuild in progress (${trigger})…`;
  } else if (jobStatus === 'complete' || jobStatus === 'completed' || jobStatus === 'success') {
    const when = formatShortTime(job.completed_at || job.updated_at);
    const changedLabel = changedCount > 0 ? `${formatCount(changedCount)} docs updated` : 'no new documents';
    const trigger = job.trigger ? String(job.trigger) : 'manual';
    lastRebuildLine = when ? `Last rebuild · ${trigger} · ${when} · ${changedLabel}` : `Last rebuild · ${trigger} · ${changedLabel}`;
  } else if (String(job.last_error ?? '').trim()) {
    lastRebuildLine = String(job.last_error);
  }

  const stats: MetricModel[] = [
    { label: 'Wiki vectors', value: formatCount(wikiCount) },
    { label: 'Source vectors', value: formatCount(rawCount) },
    { label: 'Pending changes', value: formatCount(changedCount) },
  ];
  if (!embeddings.reranker_ready) {
    stats.push({ label: 'Reranker', value: 'Off' });
  }

  return {
    indexTone: toneForStatus(indexHealth),
    indexLabel: titleCase(indexHealth || 'unknown'),
    jobTone: toneForStatus(jobStatus),
    jobLabel: titleCase(jobStatus || 'idle'),
    headline,
    lastRebuildLine,
    stats,
    canRebuild: !disabled,
    disabledHint: disabled ? 'Turn on embeddings in Settings to rebuild.' : '',
  };
}

export function buildMcpModel(mcp: AnyRecord = {}): McpModel {
  const running = Boolean(mcp.running);
  const available = Boolean(mcp.server_available);
  const status = running ? 'running' : available ? 'ready' : 'unavailable';
  return {
    serverBand: {
      title: 'MCP server',
      subtitle: mcp.last_error || 'Start the query-only LLM Wiki MCP server for the active site.',
      statusLabel: titleCase(status),
      tone: toneForStatus(status),
      actionLabel: running ? 'Server running' : available ? 'Start MCP server' : 'Command unavailable',
    },
    serverMetrics: [
      { label: 'Session', value: mcp.session_name || 'none' },
      { label: 'Index Health', value: titleCase(mcp.index_health ?? 'missing') },
      { label: 'Command', value: available ? 'available' : 'missing', help: mcp.server_command },
      { label: 'Updated', value: mcp.updated_at || '—' },
    ],
  };
}

export function buildMetricsModel({
  runs = [],
  rollup,
}: {
  runs?: AgentRunSummary[];
  rollup?: MetricsRollup;
}): MetricsModel {
  const latest = runs[0] ?? {};
  const latestLlm = latest.llm_usage ?? {};
  const latestEmbedding = latest.embedding_usage ?? {};
  const warnings = (latest.metrics_health?.warnings ?? []).map((item: unknown) => String(item));
  return {
    aggregateMetrics: [
      { label: 'Runs', value: formatCount(rollup?.run_count) },
      { label: 'Total Tokens', value: formatOptionalCount(rollup?.total_tokens) },
      { label: 'LLM Tokens', value: formatOptionalCount(rollup?.llm_tokens) },
      { label: 'Embedding Tokens', value: formatOptionalCount(rollup?.embedding_tokens) },
      { label: 'Embedding Vectors', value: formatCount(rollup?.vector_count) },
      { label: 'Cost', value: formatCost(rollup?.total_cost) },
    ],
    latestRunMetrics: [
      { label: 'Run Tokens', value: formatOptionalCount(latest.total_model_tokens) },
      { label: 'LLM Requests', value: formatCount(latestLlm.request_count) },
      { label: 'LLM Tokens', value: formatOptionalCount(latestLlm.total_tokens) },
      { label: 'Embedding Vectors', value: formatCount(latestEmbedding.vector_count) },
      { label: 'Embedding Tokens', value: formatOptionalCount(latestEmbedding.input_tokens) },
      { label: 'Cost', value: formatCost(latest.cost) },
    ],
    runRows: runs.map((run) => {
      const llm = run.llm_usage ?? {};
      const embedding = run.embedding_usage ?? {};
      return {
        run_id: run.run_id,
        status: titleCase(run.status ?? 'unknown'),
        total_tokens: formatOptionalCount(run.total_model_tokens),
        llm_tokens: formatOptionalCount(llm.total_tokens),
        embedding_tokens: formatOptionalCount(embedding.input_tokens),
        vectors: formatCount(embedding.vector_count),
        cost: formatCost(run.cost),
        health: titleCase(run.metrics_health?.status ?? 'unknown'),
      };
    }),
    healthWarnings: warnings,
  };
}
