import {
  buildEmbeddingModel,
  buildMcpModel,
  buildMetricsModel,
  buildMetricsRollupPoints,
  buildMetricsRunTrendPoints,
  formatChartMetricValue,
  formatMcpBlockReason,
  metricsChartRangeLabel,
  metricsRollupCostAmount,
  metricsRunCostAmount,
  metricsRunTrendLabel,
  buildOverviewModel,
  buildScrapeModel,
  formatCost,
  formatCount,
  formatPiEventLabel,
  metricsTokenMixSegments,
  resolveWikiJobStatus,
  scrapeStartPayload,
  summarizePiBuildEvents,
  toneForStatus,
} from './viewModel';

const complete = buildOverviewModel({
  siteId: 'www.smu.edu',
  siteUrl: 'https://www.smu.edu',
  runId: 'manual-2026',
  rawSources: {
    ready_count: 5537,
    by_kind: { web: 5370, pdf: 167 },
    by_status: { ready: 5537 },
  },
  wiki: {
    job_status: 'complete',
    integrated_sources: 5517,
    source_count: 5537,
    pending_source_count: 0,
    changed_source_count: 0,
    review_queue_count: 0,
    last_progress: '2026-05-28T00:00:00Z',
  },
  embeddings: {
    wiki_index_count: 32020,
    raw_index_count: 56860,
    index_health: 'ready',
  },
});

if (complete.statusBand.title !== 'Overview health') {
  throw new Error('overview should use neutral health language');
}

if (complete.essentialMetrics[0].label !== 'Ready Sources') {
  throw new Error('overview should show direct artifact facts from API counts');
}

if (complete.sourceStatusRows[0].status !== 'Ready') {
  throw new Error('overview source status rows should be derived from API counts');
}

if (complete.wikiRows.find((row) => row.metric === 'Integrated sources')?.value !== '5,517') {
  throw new Error('overview wiki rows should expose raw wiki state');
}

if (formatCount(null) !== '0') {
  throw new Error('empty counts should render as zero');
}

if (toneForStatus('needs review') !== 'warning') {
  throw new Error('review states should use warning tone');
}

const queuedEmbeddings = buildEmbeddingModel({
  index_health: 'stale',
  changed_document_count: 7,
  job_state: {
    status: 'queued',
    trigger: 'auto',
    changed_document_count: 7,
    report_path: '/tmp/report.json',
  },
});

if (queuedEmbeddings.indexLabel !== 'Stale') {
  throw new Error('embedding index health should remain separate from rebuild job state');
}

if (queuedEmbeddings.jobLabel !== 'Queued') {
  throw new Error('embedding rebuild job state should render on its own');
}

if (queuedEmbeddings.stats[2].value !== '7') {
  throw new Error('embedding stats should expose pending change count');
}

const rerankerReadyEmbeddings = buildEmbeddingModel({
  index_health: 'ready',
  wiki_index_count: 15,
  raw_index_count: 6,
  reranker_ready: true,
  job_state: { status: 'complete' },
});

if (rerankerReadyEmbeddings.stats.find((stat) => stat.label === 'Reranker')?.value !== 'On') {
  throw new Error('embedding stats should expose reranker on state when the backend reports it ready');
}

const blockedEmbeddings = buildEmbeddingModel({
  index_health: 'missing',
  auto_rebuild_enabled: false,
  auto_rebuild_reason: 'prerequisites_unhealthy',
  job_state: { status: 'idle' },
});

if (blockedEmbeddings.canRebuild) {
  throw new Error('embedding rebuild should be disabled when prerequisites are missing');
}

if (!blockedEmbeddings.disabledHint.includes('prerequisites')) {
  throw new Error('embedding prerequisites should explain why rebuild is blocked');
}

const disabledEmbeddings = buildEmbeddingModel({
  index_health: 'missing',
  auto_rebuild_enabled: false,
  auto_rebuild_reason: 'embedding_disabled',
  job_state: { status: 'idle' },
});

if (disabledEmbeddings.canRebuild || !disabledEmbeddings.disabledHint.includes('Settings')) {
  throw new Error('embedding disabled state should still point operators back to Settings');
}

const runningMcp = buildMcpModel({
  server_available: true,
  index_health: 'ready',
  running: true,
  session_name: 'llm-wiki-mcp-www-smu-edu',
  server_command: '/venv/bin/python -m mcp_servers.llm_wiki_mcp --site-root /data/sites/www.smu.edu',
});

if (runningMcp.serverBand.statusLabel !== 'Running') {
  throw new Error('running MCP sessions should render as running');
}

if (runningMcp.serverMetrics[0].value !== 'llm-wiki-mcp-www-smu-edu') {
  throw new Error('MCP metrics should expose the tmux session name');
}

const metricsModel = buildMetricsModel({
  rollup: {
    window: '30d',
    run_count: 2,
    total_tokens: 325,
    llm_tokens: 125,
    embedding_tokens: 200,
    vector_count: 12,
    total_cost: { amount_usd: 0.03, source: 'partial' },
  },
  runs: [
    {
      run_id: 'agent-run-1',
      status: 'completed',
      total_model_tokens: 325,
      llm_usage: { request_count: 1, total_tokens: 125 },
      embedding_usage: { input_tokens: 200, vector_count: 12 },
      cost: { amount_usd: null, source: 'unknown' },
      metrics_health: { status: 'partial', warnings: ['unknown_cost'] },
    },
  ],
});

if (metricsModel.aggregateMetrics[2].value !== '125') {
  throw new Error('metrics model should keep LLM tokens separate from embedding tokens');
}

if (metricsModel.aggregateMetrics[3].value !== '200') {
  throw new Error('metrics model should expose embedding tokens separately');
}

if (metricsModel.runRows[0].cost !== 'Unknown') {
  throw new Error('unknown metric cost must not render as zero');
}

if (!metricsModel.healthWarnings.includes('unknown_cost')) {
  throw new Error('metrics health warnings should surface in the model');
}

if (!metricsModel.scopeNote.includes('Pi agent')) {
  throw new Error('metrics model should explain Pi-only scope');
}

const vectorOnlyTrend = buildMetricsRunTrendPoints([
  {
    run_id: 'embedding-manual-1',
    embedding_usage: { vector_count: 42, input_tokens: null },
    total_model_tokens: 0,
  },
]);

if (vectorOnlyTrend[0]?.tokens !== 42) {
  throw new Error('metrics trend should fall back to embedding vectors when tokens are missing');
}

const vectorTrendPoint = vectorOnlyTrend[0];
if (!vectorTrendPoint?.label.includes('Embed') || !vectorTrendPoint.detail?.includes('embedding-manual-1')) {
  throw new Error('metrics trend labels should show run kind and keep full run id in detail');
}

const trendLabel = metricsRunTrendLabel(
  {
    run_id: 'embedding-manual-20260604T123177554695Z',
    started_at: '2026-06-04T15:30:00Z',
    status: 'completed',
    breakdowns: { trigger: 'manual' },
    embedding_usage: { vector_count: 21 },
  },
  1,
  3,
);

if (!trendLabel.label.startsWith('#2') || !trendLabel.label.includes('Manual')) {
  throw new Error('metrics run labels should use sequence, trigger, and time instead of run id tails');
}

const estimatedCostTrend = buildMetricsRunTrendPoints([
  {
    run_id: 'embed-run-a',
    embedding_usage: { input_tokens: 1_000_000, vector_count: 62 },
    cost: { amount_usd: null, source: 'unknown' },
  },
]);

if (estimatedCostTrend[0]?.cost !== 0.02) {
  throw new Error('metrics trend should estimate embedding cost from input tokens when run cost is unknown');
}

if (metricsChartRangeLabel([62, 62], 'tokens') !== 'Each: 62') {
  throw new Error('chart range label should explain uniform values');
}

if (formatChartMetricValue(0.02, 'cost') !== '$0.0200') {
  throw new Error('chart cost formatting should show micro-dollar precision');
}

const rollupCost = metricsRollupCostAmount({
  total_cost: { amount_usd: null, source: 'unknown' },
  embedding_tokens: 500_000,
});

if (rollupCost !== 0.01) {
  throw new Error('rollup chart should estimate cost from embedding tokens when total cost is unknown');
}

const vectorRollups = buildMetricsRollupPoints({
  '30d': { window: '30d', run_count: 2, total_tokens: 0, vector_count: 90, llm_tokens: 0, embedding_tokens: null },
});

if (vectorRollups[0]?.tokens !== 90) {
  throw new Error('rollup chart points should use vectors when token totals are zero');
}

const vectorMix = metricsTokenMixSegments({
  window: '30d',
  llm_tokens: 0,
  embedding_tokens: null,
  vector_count: 90,
});

if (vectorMix.length !== 1 || vectorMix[0].value !== 90) {
  throw new Error('token mix should use vectors when embedding tokens are unavailable');
}

const vectorRollupModel = buildMetricsModel({
  rollup: {
    window: '30d',
    run_count: 2,
    total_tokens: 0,
    llm_tokens: 0,
    embedding_tokens: null,
    vector_count: 90,
  },
});

if (vectorRollupModel.aggregateMetrics[1].value !== '90') {
  throw new Error('aggregate metric strip should fall back to embedding vectors for total tokens');
}

if (vectorRollupModel.aggregateMetrics[3].value !== '90') {
  throw new Error('aggregate metric strip should fall back to embedding vectors for embedding tokens');
}

if (!formatMcpBlockReason('missing_index').includes('Embeddings')) {
  throw new Error('MCP block reason should map missing_index to operator guidance');
}

if (formatMcpBlockReason('Index version is llm-wiki-hybrid-v1; expected llm-wiki-hybrid-v2.').includes('Embeddings')) {
  throw new Error('MCP block reason should preserve full backend messages');
}

if (formatCost({ amount_usd: 0.02, source: 'estimated' }) !== '$0.02 estimated') {
  throw new Error('estimated cost provenance should survive formatting');
}

const scrapeReady = buildScrapeModel({ approvedCount: 5, scrapeConcurrency: 8, scrapeBrowserMode: 'lightpanda' });
if (!scrapeReady.canStart || scrapeReady.approvedCount !== 5) {
  throw new Error('scrape model should enable start when approved URLs exist');
}

const scrapePayload = scrapeStartPayload({ approvedCount: 5, scrapeConcurrency: 8, scrapeBrowserMode: 'lightpanda' });
if (scrapePayload.prefer_approved !== true || scrapePayload.concurrency !== 8 || scrapePayload.browser_mode !== 'lightpanda') {
  throw new Error('scrape payload should call the scrape API with settings-derived concurrency and browser mode');
}

const scrapeBlocked = buildScrapeModel({ approvedCount: 0 });
if (scrapeBlocked.canStart || !scrapeBlocked.disabledHint.includes('Approve')) {
  throw new Error('scrape model should block start when no approved URLs exist');
}

const archivedWiki = resolveWikiJobStatus({ liveStatus: 'running', reportStatus: 'archived', staleRunning: false });
if (archivedWiki.label !== 'Archived') {
  throw new Error('wiki hero status should prefer archived report status over stale live running');
}

const staleWiki = resolveWikiJobStatus({ liveStatus: 'running', reportStatus: 'running', staleRunning: true });
if (staleWiki.label !== 'Stale') {
  throw new Error('wiki hero status should reconcile stale running jobs when tmux is gone');
}

const failedWiki = resolveWikiJobStatus({ liveStatus: 'running', reportStatus: 'failed', generationStatus: 'running', staleRunning: false });
if (failedWiki.label !== 'Failed') {
  throw new Error('wiki status should prefer reconciled failed reports over stale running generation state');
}

const stalledWiki = resolveWikiJobStatus({ liveStatus: 'running', reportStatus: 'stalled', generationStatus: 'running', staleRunning: false });
if (stalledWiki.label !== 'Stalled' || stalledWiki.tone !== 'warning') {
  throw new Error('wiki status should surface silent live Pi jobs as stalled warnings');
}

const buildSummary = summarizePiBuildEvents([
  { type: 'message_update', text: 'token noise should be skipped' },
  { type: 'tool_start', status: 'running', message: 'Compiling wiki pages' },
  { type: 'tool_end', status: 'failed', message: 'No models match pattern "github-copilot/gpt-4o"' },
]);
if (!buildSummary.some((line) => line.includes('No models match pattern'))) {
  throw new Error('build event summary should surface runtime failure lines without token noise');
}

const readToolLabel = formatPiEventLabel({
  type: 'tool_execution_start',
  toolName: 'read',
  args: { path: 'docs/wiki/page.md', offset: 120 },
});
if (!readToolLabel.includes('read') || !readToolLabel.includes('path=docs/wiki/page.md') || readToolLabel.includes('[object Object]')) {
  throw new Error('tool execution labels should render toolName and compact args');
}

const turnEndLabel = formatPiEventLabel({
  type: 'turn_end',
  status: { usage: { input_tokens: 10 } },
});
if (turnEndLabel.includes('[object Object]')) {
  throw new Error('turn lifecycle labels should never render object payloads as [object Object]');
}
