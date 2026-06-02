import { buildEmbeddingModel, buildMcpModel, buildMetricsModel, buildOverviewModel, formatCost, formatCount, toneForStatus } from './viewModel';

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

if (formatCost({ amount_usd: 0.02, source: 'estimated' }) !== '$0.02 estimated') {
  throw new Error('estimated cost provenance should survive formatting');
}
