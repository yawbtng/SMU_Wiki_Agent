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
  discovery?: AnyRecord;
  approvedCount?: number;
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

export type ScrapeModel = {
  canStart: boolean;
  buttonLabel: string;
  disabledHint: string;
  approvedCount: number;
};

export type ScrapeInput = {
  approvedCount?: number;
  scrapeConcurrency?: number;
  scrapeBrowserMode?: string;
  busy?: boolean;
};

export type WikiJobStatusInput = {
  liveStatus?: unknown;
  reportStatus?: unknown;
  generationStatus?: unknown;
  staleRunning?: boolean;
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
  window?: string;
  run_count?: number;
  total_tokens?: number | null;
  llm_tokens?: number | null;
  embedding_tokens?: number | null;
  total_cost?: MetricCost;
  embedding_cost?: MetricCost;
  vector_count?: number;
};

export type MetricsChartPoint = {
  label: string;
  detail?: string;
  tokens: number;
  vectors: number;
  cost: number;
  runs: number;
};

export type MetricsModel = {
  scopeNote: string;
  aggregateMetrics: MetricModel[];
  latestRunMetrics: MetricModel[];
  runRows: AnyRecord[];
  healthWarnings: string[];
};

export function metricsScopeNote(): string {
  return 'Pi agent and embedding-index jobs only. Scrape runs and page outcomes stay on Runs and are not duplicated here.';
}

export function metricsRunVectors(run: AgentRunSummary): number {
  const count = Number(run.embedding_usage?.vector_count ?? 0);
  return Number.isFinite(count) ? count : 0;
}

export function metricsRunChartValue(run: AgentRunSummary): number {
  const tokens = Number(run.total_model_tokens ?? NaN);
  if (Number.isFinite(tokens) && tokens > 0) return tokens;
  return metricsRunVectors(run);
}

export function metricsRollupVectors(rollup?: MetricsRollup): number {
  const count = Number(rollup?.vector_count ?? 0);
  return Number.isFinite(count) ? count : 0;
}

export function metricsRollupChartValue(rollup?: MetricsRollup): number {
  const tokens = Number(rollup?.total_tokens ?? NaN);
  if (Number.isFinite(tokens) && tokens > 0) return tokens;
  return metricsRollupVectors(rollup);
}

export function metricCostAmount(cost: MetricCost | null | undefined): number {
  if (!cost || cost.amount_usd === null || cost.amount_usd === undefined) return 0;
  const amount = Number(cost.amount_usd);
  return Number.isFinite(amount) ? amount : 0;
}

export function shortMetricsRunLabel(_value: unknown, index: number): string {
  return String(index + 1);
}

export function buildMetricsRunTrendPoints(runs: AgentRunSummary[]): MetricsChartPoint[] {
  return runs
    .slice(0, 12)
    .reverse()
    .map((run, index) => ({
      label: shortMetricsRunLabel(run.run_id, index),
      detail: String(run.run_id ?? '').trim() || undefined,
      tokens: metricsRunChartValue(run),
      vectors: metricsRunVectors(run),
      cost: metricCostAmount(run.cost),
      runs: 1,
    }));
}

export function buildMetricsRollupPoints(rollups: Record<string, MetricsRollup | undefined>): MetricsChartPoint[] {
  return (['30d', '60d', '90d', '365d', 'all_time'] as const)
    .map((label) => {
      const rollup: MetricsRollup = rollups[label] ?? {};
      return {
        label: label === '365d' ? '1y' : label.replace('_', ' '),
        tokens: metricsRollupChartValue(rollup),
        vectors: metricsRollupVectors(rollup),
        cost: metricCostAmount(rollup.total_cost),
        runs: Number(rollup.run_count ?? 0) || 0,
      };
    })
    .filter((point) => point.tokens > 0 || point.vectors > 0 || point.runs > 0 || point.cost > 0);
}

export function metricsTokenMixSegments(rollup?: MetricsRollup): { label: string; value: number; tone: 'llm' | 'embeddings' }[] {
  const llm = Number(rollup?.llm_tokens ?? 0);
  const embeddingRaw = rollup?.embedding_tokens;
  const embedding =
    embeddingRaw === null || embeddingRaw === undefined ? metricsRollupVectors(rollup) : Number(embeddingRaw);
  const segments = [
    { label: 'LLM', value: Number.isFinite(llm) ? llm : 0, tone: 'llm' as const },
    { label: 'Embeddings', value: Number.isFinite(embedding) ? embedding : 0, tone: 'embeddings' as const },
  ];
  return segments.filter((segment) => segment.value > 0);
}

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

export function formatMetricsRollupTotalTokens(rollup?: MetricsRollup): string {
  const vectors = metricsRollupVectors(rollup);
  const raw = rollup?.total_tokens;
  if ((raw === null || raw === undefined || Number(raw) === 0) && vectors > 0) {
    return formatCount(vectors);
  }
  return formatOptionalCount(raw);
}

export function formatMetricsRollupEmbeddingTokens(rollup?: MetricsRollup): string {
  const vectors = metricsRollupVectors(rollup);
  const raw = rollup?.embedding_tokens;
  if ((raw === null || raw === undefined) && vectors > 0) {
    return formatCount(vectors);
  }
  return formatOptionalCount(raw);
}

export function formatMetricsRunTotalTokens(run: AgentRunSummary): string {
  const vectors = metricsRunVectors(run);
  const raw = run.total_model_tokens;
  if ((raw === null || raw === undefined || Number(raw) === 0) && vectors > 0) {
    return formatCount(vectors);
  }
  return formatOptionalCount(raw);
}

export function formatMetricsRunEmbeddingTokens(run: AgentRunSummary): string {
  const embedding = run.embedding_usage ?? {};
  const vectors = metricsRunVectors(run);
  const raw = embedding.input_tokens;
  if ((raw === null || raw === undefined) && vectors > 0) {
    return formatCount(vectors);
  }
  return formatOptionalCount(raw);
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
  const discovery = input.discovery ?? {};
  const readySources = Number(raw.ready_count ?? wiki.source_count ?? 0);
  const discoveredTotal = Number(discovery.discovered_total ?? 0);
  const eligibleTotal = Number(discovery.eligible_total ?? 0);
  const rejectedTotal = Number(discovery.rejected_total ?? 0);
  const approvedCount = Number(input.approvedCount ?? 0);
  const hasDiscovery = discoveredTotal > 0;
  const needsReview = Number(raw.by_status?.['needs-review'] ?? raw.by_status?.needs_review ?? 0) + Number(wiki.review_queue_count ?? 0);
  const pendingOrChanged = Number(wiki.pending_source_count ?? 0) + Number(wiki.changed_source_count ?? 0);
  const wikiStatus = String(wiki.job_status ?? 'not started');
  const indexDocs = Number(embeddings.wiki_index_count ?? 0);
  const lastUpdated = wiki.last_progress || embeddings.last_build_time || input.run?.status?.finished_at || input.run?.status?.updated_at || 'Unknown';
  const health = needsReview > 0 ? 'Needs review' : pendingOrChanged > 0 ? 'Update needed' : readySources <= 0 && hasDiscovery ? 'Discovery ready' : indexDocs <= 0 ? 'Index missing' : titleCase(wikiStatus);
  const nextAction = needsReview > 0 ? 'Review flagged sources' : pendingOrChanged > 0 ? 'Update wiki' : readySources <= 0 && hasDiscovery ? 'Approve and scrape sources' : indexDocs <= 0 ? 'Build index' : 'Monitor';
  const sourceStatusRows = rowsFromCounts(raw.by_status, 'status');
  const sourceKindRows = rowsFromCounts(raw.by_kind, 'kind');
  const discoveryRows = hasDiscovery
    ? [
        { status: 'Discovered URLs', count: formatCount(discoveredTotal) },
        { status: 'Eligible URLs', count: formatCount(eligibleTotal) },
        { status: 'Rejected URLs', count: formatCount(rejectedTotal) },
        { status: 'Approved URLs', count: formatCount(approvedCount) },
      ]
    : [];

  return {
    statusBand: {
      title: 'Overview health',
      subtitle: input.siteUrl || input.siteId || 'Workspace',
      statusLabel: health,
      tone: toneForStatus(health),
      actionLabel: nextAction,
    },
    essentialMetrics: hasDiscovery && readySources <= 0
      ? [
          { label: 'Discovered URLs', value: formatCount(discoveredTotal) },
          { label: 'Eligible URLs', value: formatCount(eligibleTotal) },
          { label: 'Approved URLs', value: formatCount(approvedCount) },
          { label: 'Ready Sources', value: formatCount(readySources), help: 'Scrape after approval' },
        ]
      : [
          { label: 'Ready Sources', value: formatCount(readySources) },
          { label: 'Needs Review', value: formatCount(needsReview) },
          { label: 'Pending Changes', value: formatCount(pendingOrChanged) },
          { label: 'Wiki Index Docs', value: formatCount(indexDocs), help: String(lastUpdated).slice(0, 19) },
        ],
    sourceStatusRows: sourceStatusRows.length ? sourceStatusRows : discoveryRows,
    sourceKindRows: sourceKindRows.length ? sourceKindRows : (hasDiscovery ? [{ kind: 'Discovered URL pool', count: formatCount(discoveredTotal) }] : []),
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
  const rebuildReason = String(embeddings.auto_rebuild_reason ?? '');
  const disabled = rebuildReason === 'embedding_disabled';
  const blocked = !disabled && embeddings.auto_rebuild_enabled === false;

  let headline = 'Vectors are indexed and ready for search.';
  if (disabled) headline = 'Embeddings are disabled in Settings.';
  else if (blocked) headline = 'Embedding rebuild is waiting for ready sources and wiki pages.';
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
    {
      label: 'Reranker',
      value: embeddings.reranker_ready ? 'On' : 'Off',
      help: embeddings.reranker?.model || embeddings.reranker_model || undefined,
    },
  ];

  return {
    indexTone: toneForStatus(indexHealth),
    indexLabel: titleCase(indexHealth || 'unknown'),
    jobTone: toneForStatus(jobStatus),
    jobLabel: titleCase(jobStatus || 'idle'),
    headline,
    lastRebuildLine,
    stats,
    canRebuild: !disabled && !blocked,
    disabledHint: disabled
      ? 'Turn on embeddings in Settings to rebuild.'
      : blocked
        ? 'Missing wiki/index prerequisites — finish wiki build before rebuilding embeddings.'
        : '',
  };
}

export function buildScrapeModel(input: ScrapeInput = {}): ScrapeModel {
  const approvedCount = Number(input.approvedCount ?? 0);
  const busy = Boolean(input.busy);
  const canStart = approvedCount > 0 && !busy;
  let disabledHint = '';
  if (approvedCount <= 0) disabledHint = 'Approve URLs in Sources before starting a scrape.';
  else if (busy) disabledHint = 'Scrape run is starting or already in progress.';
  return {
    canStart,
    buttonLabel: busy ? 'Starting scrape…' : 'Start scrape',
    disabledHint,
    approvedCount,
  };
}

export function scrapeStartPayload(input: ScrapeInput = {}): Record<string, unknown> {
  const concurrency = Number(input.scrapeConcurrency ?? 4);
  return {
    concurrency: Number.isFinite(concurrency) ? Math.max(1, Math.min(16, Math.round(concurrency))) : 4,
    prefer_approved: true,
    browser_mode: String(input.scrapeBrowserMode ?? 'none').toLowerCase() === 'lightpanda' ? 'lightpanda' : 'none',
  };
}

export function resolveWikiJobStatus(input: WikiJobStatusInput = {}): { label: string; tone: Tone } {
  const candidates = [input.reportStatus, input.generationStatus, input.liveStatus]
    .map((value) => String(value ?? '').trim().toLowerCase())
    .filter(Boolean);
  let status = candidates[0] || 'ready';
  if (status === 'archived') status = 'archived';
  else if (input.staleRunning && ['running', 'starting', 'initializing'].includes(status)) status = 'stale';
  return { label: titleCase(status), tone: toneForStatus(status) };
}

export function summarizePiBuildEvents(events: AnyRecord[]): string[] {
  const lines: string[] = [];
  const seen = new Set<string>();
  for (const event of events.slice(-80)) {
    const type = String(event.type ?? event.event ?? '').trim();
    const status = String(event.status ?? '').trim();
    const message = String(event.message ?? event.text ?? event.detail ?? '').trim();
    const label = [type, status, message].filter(Boolean).join(' · ');
    if (!label || seen.has(label)) continue;
    seen.add(label);
    if (type.startsWith('message_') || type === 'message_update') continue;
    lines.push(label.slice(0, 240));
  }
  return lines.slice(-12);
}

export function buildMcpModel(mcp: AnyRecord = {}): McpModel {
  const running = Boolean(mcp.running);
  const available = Boolean(mcp.server_available);
  const status = running ? 'running' : available ? 'ready' : 'unavailable';
  return {
    serverBand: {
      title: 'MCP gateway',
      subtitle: mcp.last_error || 'Start one global LLM Wiki MCP gateway for all ready university workspaces.',
      statusLabel: titleCase(status),
      tone: toneForStatus(status),
      actionLabel: running ? 'Gateway running' : available ? 'Start MCP gateway' : 'Command unavailable',
    },
    serverMetrics: [
      { label: 'Session', value: mcp.session_name || 'none' },
      { label: 'Universities', value: `${mcp.ready_university_count ?? 0}/${mcp.university_count ?? 0}` },
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
  const rollupVectors = metricsRollupVectors(rollup);
  const tokensUnavailable = (rollup?.total_tokens === null || rollup?.total_tokens === undefined || rollup?.total_tokens === 0) && rollupVectors > 0;
  const embeddingTokensUnavailable =
    (rollup?.embedding_tokens === null || rollup?.embedding_tokens === undefined) && rollupVectors > 0;
  return {
    scopeNote: metricsScopeNote(),
    aggregateMetrics: [
      { label: 'Runs', value: formatCount(rollup?.run_count) },
      {
        label: 'Total Tokens',
        value: formatMetricsRollupTotalTokens(rollup),
        help: tokensUnavailable ? 'Charts use embedding vectors when token totals are unavailable' : undefined,
      },
      { label: 'LLM Tokens', value: formatOptionalCount(rollup?.llm_tokens) },
      {
        label: 'Embedding Tokens',
        value: formatMetricsRollupEmbeddingTokens(rollup),
        help: embeddingTokensUnavailable ? 'Vector counts shown in charts until token usage is recorded' : undefined,
      },
      { label: 'Embedding Vectors', value: formatCount(rollup?.vector_count) },
      { label: 'Cost', value: formatCost(rollup?.total_cost) },
    ],
    latestRunMetrics: [
      { label: 'Run Tokens', value: formatMetricsRunTotalTokens(latest) },
      { label: 'LLM Requests', value: formatCount(latestLlm.request_count) },
      { label: 'LLM Tokens', value: formatOptionalCount(latestLlm.total_tokens) },
      { label: 'Embedding Vectors', value: formatCount(latestEmbedding.vector_count) },
      { label: 'Embedding Tokens', value: formatMetricsRunEmbeddingTokens(latest) },
      { label: 'Cost', value: formatCost(latest.cost) },
    ],
    runRows: runs.map((run) => {
      const llm = run.llm_usage ?? {};
      const embedding = run.embedding_usage ?? {};
      return {
        run_id: run.run_id,
        status: titleCase(run.status ?? 'unknown'),
        total_tokens: formatMetricsRunTotalTokens(run),
        llm_tokens: formatOptionalCount(llm.total_tokens),
        embedding_tokens: formatMetricsRunEmbeddingTokens(run),
        vectors: formatCount(embedding.vector_count),
        cost: formatCost(run.cost),
        health: titleCase(run.metrics_health?.status ?? 'unknown'),
      };
    }),
    healthWarnings: warnings,
  };
}
