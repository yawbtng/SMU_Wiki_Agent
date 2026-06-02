import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactDOM from 'react-dom/client';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query';
import { AnyRecord, MetricModel, StatusBandModel, buildEmbeddingModel, buildMcpModel, buildMetricsModel, buildOverviewModel, formatCount, titleCase, toneForStatus } from './viewModel';
import './styles.css';

const SSE_INTERVAL_SECONDS = 3;
const tabs = ['Overview', 'Sources', 'Runs', 'Documents', 'Wiki', 'Embeddings', 'MCP', 'Metrics', 'Settings'];

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchInterval: false,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
});

async function api<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function apiJson<T>(path: string, method: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

const urlPattern = /https?:\/\/[^\s)\]}>"']+/g;
type ChatMessage = { role: 'user' | 'assistant'; text: string };

function urlsFromText(text: string): string[] {
  return [...new Set((text.match(urlPattern) ?? []).map((url) => url.replace(/[.,;]+$/, '')))];
}

function removalTerms(text: string): string[] {
  const stop = new Set(['remove', 'delete', 'exclude', 'filter', 'noise', 'urls', 'url', 'pages', 'page', 'from', 'approved', 'source', 'sources', 'please', 'this', 'that', 'these', 'those', 'demove']);
  return [...new Set(text.toLowerCase().match(/[a-z0-9][a-z0-9-]{3,}/g) ?? [])].filter((term) => !stop.has(term));
}

function areaLabel(value: unknown): string {
  const raw = String(value ?? '/');
  const parts = raw.split('/').filter(Boolean);
  const known: Record<string, string> = {
    cox: 'Cox School of Business',
    dedman: 'Dedman College',
    dedmanlaw: 'Dedman School of Law',
    law: 'Dedman School of Law',
    meadows: 'Meadows School of the Arts',
    lyle: 'Lyle School of Engineering',
    simmons: 'Simmons School of Education',
    perkins: 'Perkins School of Theology',
    admission: 'Admissions',
    'enrollment-services': 'Enrollment Services',
    studentaffairs: 'Student Affairs',
    libraries: 'Libraries',
    oit: 'Technology Services',
    businessfinance: 'Business and Campus Services',
  };
  if (!parts.length) return 'Homepage';
  if (known[parts[0]]) return known[parts[0]];
  return parts.map((part) => part.replace(/-/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase())).join(' · ');
}

function groupRows(groups: AnyRecord[] = []): AnyRecord[] {
  const byArea = new Map<string, number>();
  for (const group of groups) {
    const area = areaLabel(group.subpath);
    byArea.set(area, (byArea.get(area) ?? 0) + Number(group.count ?? 0));
  }
  return [...byArea.entries()]
    .map(([area, count]) => ({ area, count }))
    .sort((left, right) => Number(right.count) - Number(left.count) || String(left.area).localeCompare(String(right.area)));
}

function removeFromApprovedMarkdown(markdown: string, instruction: string): { markdown: string; removed: number; reasons: string[] } {
  const urls = urlsFromText(instruction);
  const terms = urls.length ? [] : removalTerms(instruction);
  let removed = 0;
  const reasons: string[] = [];
  const next = markdown
    .split('\n')
    .filter((line) => {
      const lowered = line.toLowerCase();
      const matchedUrl = urls.find((url) => line.includes(url));
      const matchedTerm = terms.find((term) => lowered.includes(term));
      if (matchedUrl || matchedTerm) {
        removed += 1;
        reasons.push(matchedUrl ?? matchedTerm ?? 'match');
        return false;
      }
      return true;
    })
    .join('\n');
  return { markdown: next, removed, reasons: [...new Set(reasons)] };
}

function fmt(value: unknown, fallback = '—'): string {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value);
}

function siteDisplay(siteId: string, appState?: AnyRecord): { name: string; url: string; runId: string } {
  const workspaces = appState?.state?.workspaces ?? [];
  const match = workspaces.find((item: AnyRecord) => item.id === siteId);
  return {
    name: match?.name ?? titleCase(siteId.replace(/^www\./, '').replace(/\..+$/, '')) ?? siteId,
    url: match?.url ?? appState?.state?.last_site_url ?? `https://${siteId}`,
    runId: appState?.state?.last_run_by_site?.[siteId] ?? appState?.state?.last_run_id ?? '',
  };
}

function activeWorkspaceStatus(runId: string, liveSnapshot: AnyRecord | null, activeTab: string): { label: string; detail: string } {
  if (runId) {
    return { label: 'Scrape run', detail: runId };
  }
  const wiki = (liveSnapshot?.wiki ?? {}) as AnyRecord;
  const wikiStatus = String(wiki.job_status ?? wiki.status ?? '').toLowerCase();
  const wikiSession = String(wiki.tmux_session ?? '').trim();
  if (wikiStatus === 'running' || wikiStatus === 'starting' || wikiStatus === 'initializing') {
    const sessionHint = wikiSession ? wikiSession.replace(/^wiki-/, '').slice(0, 40) : 'in tmux';
    return { label: 'Wiki build', detail: `running · ${sessionHint}` };
  }
  if (wikiStatus === 'stale') {
    return { label: 'Wiki build', detail: 'stale (reported running, tmux gone)' };
  }
  if (wikiStatus === 'complete' || wikiStatus === 'completed') {
    return { label: 'Wiki build', detail: 'complete' };
  }
  const embeddings = (liveSnapshot?.embeddings ?? {}) as AnyRecord;
  const embedStatus = String(embeddings.job_status ?? embeddings.status ?? '').toLowerCase();
  if (embedStatus === 'running' || embedStatus === 'queued') {
    return { label: 'Embeddings', detail: embedStatus };
  }
  if (activeTab === 'Wiki') {
    return { label: 'Scrape run', detail: 'None yet (wiki jobs use tmux, not scrape runs)' };
  }
  return { label: 'Scrape run', detail: 'None yet' };
}

type PiStreamEvent = AnyRecord;

function piEventLabel(event: PiStreamEvent): string {
  const type = String(event.type ?? '');
  if (type === 'message_update') {
    const nested = event.assistantMessageEvent as AnyRecord | undefined;
    if (nested?.type === 'text_delta') return String(nested.delta ?? '');
  }
  if (type === 'tool_execution_start') return `[tool start] ${String(event.toolName ?? '')}`;
  if (type === 'tool_execution_end') {
    return `[tool end] ${String(event.toolName ?? '')}${event.isError ? ' (error)' : ''}`;
  }
  if (type === 'auto_retry_start') return `[retry] ${String(event.errorMessage ?? '')}`;
  if (type.startsWith('agent_') || type.startsWith('turn_') || type.startsWith('message_')) return `[${type}]`;
  if (type === 'session') return `[session ${String((event as AnyRecord).id ?? '').slice(0, 8)}]`;
  return type ? `[${type}]` : '';
}

function useSiteStream(siteId?: string) {
  const [snapshot, setSnapshot] = useState<AnyRecord | null>(null);
  const [piEvents, setPiEvents] = useState<PiStreamEvent[]>([]);
  const [piSkill, setPiSkill] = useState('');
  const [connected, setConnected] = useState(false);
  const digestRef = useRef('');

  useEffect(() => {
    if (!siteId) return;
    setPiEvents([]);
    setPiSkill('');
    const stream = new EventSource(`/api/stream/sites/${encodeURIComponent(siteId)}?interval=${SSE_INTERVAL_SECONDS}`);
    stream.addEventListener('open', () => setConnected(true));
    stream.addEventListener('error', () => setConnected(false));
    stream.addEventListener('site', (event) => {
      setConnected(true);
      const nextDigest = (event as MessageEvent).data;
      if (nextDigest === digestRef.current) return;
      digestRef.current = nextDigest;
      setSnapshot(JSON.parse(nextDigest));
    });
    stream.addEventListener('pi', (event) => {
      setConnected(true);
      const payload = JSON.parse((event as MessageEvent).data) as AnyRecord;
      if (payload.skill) setPiSkill(String(payload.skill));
      const batch = Array.isArray(payload.events) ? (payload.events as PiStreamEvent[]) : [];
      if (batch.length) setPiEvents((prev) => [...prev, ...batch].slice(-400));
    });
    return () => {
      digestRef.current = '';
      stream.close();
    };
  }, [siteId]);

  return { snapshot, connected, piEvents, piSkill, clearPiEvents: () => setPiEvents([]) };
}

function App() {
  const [activeTab, setActiveTab] = useState('Overview');
  const [siteId, setSiteId] = useState('');
  const queryClientHook = useQueryClient();
  const sitesQuery = useQuery({ queryKey: ['sites'], queryFn: () => api<AnyRecord>('/api/sites') });
  const appState = useQuery({ queryKey: ['app-state'], queryFn: () => api<AnyRecord>('/api/app-state') });
  const sites = sitesQuery.data?.sites ?? [];

  useEffect(() => {
    if (!siteId && sites.length) {
      const saved = String(appState.data?.state?.active_workspace_id ?? '').trim();
      const savedSite = saved ? sites.find((site: AnyRecord) => site.id === saved) : undefined;
      const populated = sites.find((site: AnyRecord) => site.has_sources);
      setSiteId(savedSite?.has_sources ? saved : (populated?.id ?? saved ?? sites[0].id));
    }
  }, [appState.data, siteId, sites]);

  const stream = useSiteStream(siteId);
  const overviewHeader = useQuery({
    queryKey: ['overview-header', siteId],
    queryFn: () => api<AnyRecord>(`/api/sites/${encodeURIComponent(siteId)}/overview`),
    enabled: !!siteId,
    staleTime: 10_000,
  });
  const handleSiteDiscovered = useCallback((nextSiteId: string) => {
    setSiteId(nextSiteId);
    queryClientHook.invalidateQueries({ queryKey: ['sites'] });
    queryClientHook.invalidateQueries({ queryKey: ['app-state'] });
    queryClientHook.invalidateQueries({ queryKey: ['approved-urls', nextSiteId] });
  }, [queryClientHook]);
  const display = siteDisplay(siteId, appState.data);
  const selectedSite = sites.find((site: AnyRecord) => site.id === siteId);
  const activeStatus = activeWorkspaceStatus(display.runId, stream.snapshot ?? overviewHeader.data ?? null, activeTab);

  let bootstrapMessage: string | null = null;
  if (sitesQuery.isPending) {
    bootstrapMessage = 'Loading sites…';
  } else if (sitesQuery.isError) {
    const detail = sitesQuery.error instanceof Error ? sitesQuery.error.message : 'request failed';
    bootstrapMessage = `API unavailable (${detail}). Run ./start.sh from the repo root and confirm http://127.0.0.1:8000/api/health responds.`;
  } else if (!sites.length) {
    bootstrapMessage = 'No site data found. Set SCRAPE_PLANNER_DATA_ROOT to your data directory.';
  } else if (!siteId) {
    bootstrapMessage = 'Loading workspace…';
  }

  return (
    <div className="app-shell">
      <main className="page">
        <Hero
          activeTab={activeTab}
          activeStatus={activeStatus}
          connected={stream.connected}
          dataRoot={sitesQuery.data?.data_root}
          site={selectedSite}
          siteName={display.name}
          siteUrl={display.url}
        />
        <WorkspaceToolbar
          siteName={display.name}
          siteUrl={display.url}
          activeStatus={activeStatus}
          sites={sites}
          siteId={siteId}
          onSiteId={setSiteId}
          onSiteDiscovered={handleSiteDiscovered}
        />
        <WorkflowNav activeTab={activeTab} onTab={setActiveTab} />
        {bootstrapMessage ? (
          <EmptyState message={bootstrapMessage} />
        ) : (
          <TabView
            tab={activeTab}
            siteId={siteId}
            site={selectedSite}
            siteName={display.name}
            siteUrl={display.url}
            runId={display.runId}
            liveSnapshot={stream.snapshot}
            streamConnected={stream.connected}
            piEvents={stream.piEvents}
            piSkill={stream.piSkill}
            onClearPiEvents={stream.clearPiEvents}
            appState={appState.data}
          />
        )}
      </main>
    </div>
  );
}

const Hero = memo(function Hero({
  activeTab,
  activeStatus,
  connected,
  dataRoot,
  site,
  siteName,
  siteUrl,
}: {
  activeTab: string;
  activeStatus: { label: string; detail: string };
  connected: boolean;
  dataRoot?: string;
  site?: AnyRecord;
  siteName: string;
  siteUrl: string;
}) {
  return (
    <section className="design-shell">
      <div className="design-shell-copy">
        <div>
          <div className="design-kicker">Knowledge Operations Platform</div>
          <h1>University Knowledge Ops</h1>
          <p>Coordinate source intake, scrape operations, document review, wiki production, embeddings, and metrics from one operator workspace.</p>
        </div>
        <div className="design-stat-row">
          <div className="design-stat">
            <div className="design-stat-label">Workflow</div>
            <div className="design-stat-value">{tabs.length} stages</div>
          </div>
          <div className="design-stat">
            <div className="design-stat-label">Workspaces</div>
            <div className="design-stat-value">{site ? '1' : '0'}</div>
          </div>
          <div className="design-stat wide">
            <div className="design-stat-label">{activeStatus.label}</div>
            <div className="design-stat-value mono">{activeStatus.detail}</div>
          </div>
        </div>
      </div>
      <div className="hero-foot">
        <span>{siteName}</span>
        <span>{siteUrl}</span>
        <span className={connected ? 'live-pill' : 'live-pill muted'}>{connected ? 'Live' : 'Connecting'}</span>
        <span className="data-root">{dataRoot}</span>
      </div>
    </section>
  );
});

const WorkspaceToolbar = memo(function WorkspaceToolbar({
  siteName,
  siteUrl,
  activeStatus,
  sites,
  siteId,
  onSiteId,
  onSiteDiscovered,
}: {
  siteName: string;
  siteUrl: string;
  activeStatus: { label: string; detail: string };
  sites: AnyRecord[];
  siteId: string;
  onSiteId: (siteId: string) => void;
  onSiteDiscovered: (siteId: string) => void;
}) {
  const [discoverUrl, setDiscoverUrl] = useState(siteUrl || 'https://www.smu.edu');
  const [discoverMessage, setDiscoverMessage] = useState('');
  const runDiscovery = useCallback(async () => {
    const target = discoverUrl.trim();
    if (!target) return;
    setDiscoverMessage('Reading robots.txt and sitemap.xml…');
    try {
      const payload = await apiJson<AnyRecord>('/api/discover', 'POST', { site_url: target, timeout: 30 });
      setDiscoverMessage(`Discovered ${formatCount(payload.discovered_total)} URLs from ${formatCount(payload.sitemap_sources?.length)} sitemap source(s).`);
      onSiteDiscovered(String(payload.site_id));
    } catch (error) {
      setDiscoverMessage(error instanceof Error ? error.message : 'Discovery failed');
    }
  }, [discoverUrl, onSiteDiscovered]);
  return (
    <section className="workspace-row">
      <div className="workspace-toolbar">
        <div className="workspace-toolbar-title">{siteName}</div>
        <div className="workspace-toolbar-copy">{siteUrl}</div>
        <div className="workspace-toolbar-meta">
          <span>{activeStatus.label}</span>
          <strong>{activeStatus.detail}</strong>
        </div>
      </div>
      <div className="workspace-actions">
        <select value={siteId} onChange={(event) => onSiteId(event.target.value)} aria-label="Workspace">
          {sites.map((site: AnyRecord) => (
            <option key={site.id} value={site.id}>
              {site.id}
            </option>
          ))}
        </select>
        <input value={discoverUrl} onChange={(event) => setDiscoverUrl(event.target.value)} placeholder="https://university.edu" aria-label="University URL" />
        <button type="button" onClick={runDiscovery}>Discover university</button>
        {discoverMessage && <span className="inline-status">{discoverMessage}</span>}
      </div>
    </section>
  );
});

const WorkflowNav = memo(function WorkflowNav({ activeTab, onTab }: { activeTab: string; onTab: (tab: string) => void }) {
  return (
    <nav className="workflow-nav" aria-label="Workflow section">
      {tabs.map((tab) => (
        <button key={tab} type="button" className={tab === activeTab ? 'active' : ''} onClick={() => onTab(tab)}>
          <span className="nav-dot" />
          {tab}
        </button>
      ))}
    </nav>
  );
});

const TabView = memo(function TabView({
  tab,
  siteId,
  site,
  siteName,
  siteUrl,
  runId,
  liveSnapshot,
  streamConnected,
  piEvents,
  piSkill,
  onClearPiEvents,
  appState,
}: {
  tab: string;
  siteId: string;
  site?: AnyRecord;
  siteName: string;
  siteUrl: string;
  runId: string;
  liveSnapshot: AnyRecord | null;
  streamConnected: boolean;
  piEvents: PiStreamEvent[];
  piSkill: string;
  onClearPiEvents: () => void;
  appState?: AnyRecord;
}) {
  if (tab === 'Overview') return <Overview siteId={siteId} siteName={siteName} siteUrl={siteUrl} runId={runId} liveSnapshot={liveSnapshot} streamConnected={streamConnected} />;
  if (tab === 'Sources') return <Sources siteId={siteId} hasSources={Boolean(site?.has_sources)} siteLabel={siteName} />;
  if (tab === 'Runs') return <Runs siteId={siteId} runId={runId} />;
  if (tab === 'Documents') return <Documents siteId={siteId} />;
  if (tab === 'Wiki') return <Wiki siteId={siteId} liveSnapshot={liveSnapshot} piEvents={piEvents} piSkill={piSkill} onClearPiEvents={onClearPiEvents} />;
  if (tab === 'Embeddings') return <Embeddings siteId={siteId} liveSnapshot={liveSnapshot} />;
  if (tab === 'MCP') return <McpServer siteId={siteId} liveSnapshot={liveSnapshot} />;
  if (tab === 'Metrics') return <Metrics siteId={siteId} />;
  if (tab === 'Settings') return <Settings appState={appState} />;
  return <EmptyState message={`${tab} is unavailable.`} />;
});

const Overview = memo(function Overview({
  siteId,
  siteName,
  siteUrl,
  runId,
  liveSnapshot,
  streamConnected,
}: {
  siteId: string;
  siteName: string;
  siteUrl: string;
  runId: string;
  liveSnapshot: AnyRecord | null;
  streamConnected: boolean;
}) {
  const overview = useQuery({
    queryKey: ['overview', siteId],
    queryFn: () => api<AnyRecord>(`/api/sites/${siteId}/overview`),
    enabled: !!siteId && !streamConnected,
  });
  const runs = useQuery({
    queryKey: ['runs', siteId],
    queryFn: () => api<AnyRecord>(`/api/sites/${siteId}/runs`),
    enabled: !!siteId,
  });
  const data = liveSnapshot ?? overview.data;
  const activeRun = (runs.data?.runs ?? []).find((run: AnyRecord) => run.run_id === runId) ?? (runs.data?.runs ?? []).find((run: AnyRecord) => run.status?.state);
  const model = buildOverviewModel({
    siteId: siteName || siteId,
    siteUrl,
    runId,
    rawSources: data?.raw_sources,
    wiki: data?.wiki,
    agent: data?.agent,
    embeddings: data?.embeddings,
    run: activeRun,
  });
  return (
    <section>
      <h2>Overview</h2>
      <StatusBand band={model.statusBand} />
      <MetricStrip metrics={model.essentialMetrics} />
      <div className="two-col overview-grid">
        <Panel title="Source status">
          <DataTable columns={[["status", "Status"], ["count", "Count"]]} rows={model.sourceStatusRows} />
        </Panel>
        <Panel title="Source kinds">
          <DataTable columns={[["kind", "Kind"], ["count", "Count"]]} rows={model.sourceKindRows} />
        </Panel>
      </div>
      <Panel title="Wiki state">
        <DataTable columns={[["metric", "Metric"], ["value", "Value"]]} rows={model.wikiRows} />
      </Panel>
      <details className="operator-details">
        <summary>Operator Details</summary>
        <JsonBlock value={{ overview: data ?? overview.error?.message ?? 'Loading', next_action: model.nextAction }} />
      </details>
    </section>
  );
});

const Sources = memo(function Sources({ siteId, hasSources = true, siteLabel }: { siteId: string; hasSources?: boolean; siteLabel?: string }) {
  const [query, setQuery] = useState('');
  const [approvalPrompt, setApprovalPrompt] = useState('Select a broad but high-signal set of URLs for a student-facing university knowledge base. Include current and prospective student pages for admissions, apply, accepted students, transfer, international, enrollment services, registrar, academic calendar, final exams, transcripts, records, catalog, course catalog, majors, minors, degree programs, advising, curriculum, tuition, fees, bursar, billing, payment, financial aid, scholarships, cost of attendance, housing, dining, student life, student affairs, health, counseling, accessibility, disability, parking, police, campus services, bookstore, libraries, technology services, OIT services, academic policies, legal disclosures, Title IX, sexual harassment, orientation, commencement, schools and colleges, Cox, Dedman, Dedman Law, Law, Meadows, Lyle, Simmons, Perkins, Guildhall, Moody, CAPE, programs, academics, departments, centers, institutes, clinics, and research pages that describe student academic opportunities. Exclude HR employee pages, staff directories, donor/giving/alumni/event/news noise, old dated stories, annual reports, admin governance, search/listing/tag/feed pages, and thin navigation.');
  const [approvedMarkdown, setApprovedMarkdown] = useState('');
  const [approvalMessage, setApprovalMessage] = useState('');
  const [pendingProposal, setPendingProposal] = useState<AnyRecord | null>(null);
  const [chatInput, setChatInput] = useState('');
  const [chatPending, setChatPending] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [showApprovedFile, setShowApprovedFile] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    { role: 'assistant', text: 'Tell me what student-useful sources to approve, or paste URLs/noise patterns to remove from approved_urls.md.' },
  ]);
  const queryClientHook = useQueryClient();
  const sources = useQuery({
    queryKey: ['sources', siteId],
    queryFn: () => api<AnyRecord>(`/api/sites/${siteId}/sources?limit=500`),
    enabled: !!siteId,
  });
  const approved = useQuery({
    queryKey: ['approved-urls', siteId],
    queryFn: () => api<AnyRecord>(`/api/sites/${siteId}/approved-urls`),
    enabled: !!siteId,
  });
  useEffect(() => {
    if (approved.data?.markdown !== undefined) setApprovedMarkdown(String(approved.data.markdown));
  }, [approved.data?.markdown]);
  const rows = filterRows(sources.data?.rows ?? [], query, ['source_id', 'title', 'original_url', 'markdown_path', 'source_kind', 'status', 'wiki_status']);
  const previewActive = Boolean(pendingProposal);
  const selectedPayload = pendingProposal ?? approved.data ?? {};
  const approvedGroups = groupRows(selectedPayload.groups ?? []);
  const availableGroups = groupRows(selectedPayload.available_groups ?? []);
  const pendingAddedGroups = groupRows(pendingProposal?.added_groups ?? []);
  const pendingRemovedGroups = groupRows(pendingProposal?.removed_groups ?? []);
  const pendingRejectedGroups = groupRows(pendingProposal?.rejected_groups ?? []);
  const draftApproved = useCallback(async () => {
    setApprovalMessage('Asking LLM to draft approved URLs…');
    const payload = await apiJson<AnyRecord>(`/api/sites/${siteId}/approved-urls/chat`, 'POST', {
      message: 'Approve the broad student-useful URL set using the base approval prompt.',
      base_prompt: approvalPrompt,
      markdown: approvedMarkdown,
      limit: 30000,
      autosave: false,
    });
    setPendingProposal(payload);
    queryClientHook.setQueryData(['approved-urls-preview', siteId], payload);
    const reply = String(payload.assistant_message ?? `Approved ${formatCount(payload.count)} URLs.`);
    setChatMessages((items) => [...items, { role: 'assistant', text: reply }]);
    setApprovalMessage(reply);
  }, [approvalPrompt, approvedMarkdown, queryClientHook, siteId]);
  const saveApproved = useCallback(async (markdownOverride?: string, removeTerms: string[] = []) => {
    const nextMarkdown = markdownOverride ?? approvedMarkdown;
    setApprovalMessage('Saving approved_urls.md…');
    const payload = removeTerms.length
      ? await apiJson<AnyRecord>(`/api/sites/${siteId}/approved-urls/commit`, 'POST', { markdown: nextMarkdown, remove_terms: removeTerms })
      : await apiJson<AnyRecord>(`/api/sites/${siteId}/approved-urls`, 'PUT', { markdown: nextMarkdown });
    setApprovedMarkdown(String(payload.markdown ?? nextMarkdown));
    setPendingProposal(null);
    queryClientHook.setQueryData(['approved-urls', siteId], payload);
    setApprovalMessage(`Saved ${formatCount(payload.count)} approved URLs. Future scrapes will use only this file.`);
  }, [approvedMarkdown, queryClientHook, siteId]);
  const sendApprovalChat = useCallback(async () => {
    const message = chatInput.trim();
    if (!message || chatPending) return;
    setChatMessages((items) => [...items, { role: 'user', text: message }]);
    setChatInput('');
    setChatPending(true);
    setApprovalMessage('LLM agent is thinking…');
    try {
      const payload = await apiJson<AnyRecord>(`/api/sites/${siteId}/approved-urls/chat`, 'POST', {
        message,
        base_prompt: approvalPrompt,
        markdown: approvedMarkdown,
        limit: 30000,
        autosave: false,
      });
      if (payload.intent === 'approve' || payload.intent === 'remove') {
        setPendingProposal(payload);
        queryClientHook.setQueryData(['approved-urls-preview', siteId], payload);
      }
      const reply = String(payload.assistant_message ?? `Approved URL count is now ${formatCount(payload.count)}.`);
      setChatMessages((items) => [...items, { role: 'assistant', text: reply }]);
      setApprovalMessage(reply);
    } catch (error) {
      const reply = error instanceof Error ? error.message : 'LLM agent failed.';
      setChatMessages((items) => [...items, { role: 'assistant', text: reply }]);
      setApprovalMessage(reply);
    } finally {
      setChatPending(false);
    }
  }, [approvalPrompt, approvedMarkdown, chatInput, chatPending, queryClientHook, siteId]);
  const loadError = sources.isError || approved.isError;
  const loadErrorDetail = [
    sources.isError ? `sources (${sources.error instanceof Error ? sources.error.message : 'failed'})` : '',
    approved.isError ? `approved URLs (${approved.error instanceof Error ? approved.error.message : 'failed'})` : '',
  ].filter(Boolean).join('; ');

  return (
    <section>
      {loadError && (
        <p className="embeddings-rebuild-line alert soft">
          Could not load site data ({loadErrorDetail}). If the API is stuck, run <code>./stop.sh &amp;&amp; ./start.sh</code> and hard-refresh the page.
        </p>
      )}
      {!loadError && !hasSources && (
        <p className="embeddings-rebuild-line alert soft">
          <strong>{siteLabel ?? siteId}</strong> has no scraped sources yet. Use the workspace dropdown to switch to a site with data (for example <code>www.smu.edu</code>).
        </p>
      )}
      <Panel title="Approval chat">
        <div className="approval-chat-shell">
          <div className="chat-topbar">
            <div>
              <div className="chat-title">URL selection agent</div>
              <div className="chat-subtitle">Ask questions, approve groups, or remove noisy patterns.</div>
            </div>
            <button className="icon-button" type="button" onClick={() => setSettingsOpen(true)} aria-label="Open approval settings">⚙</button>
          </div>
          <div className="chat-log imessage" aria-label="Approval chat transcript">
            {chatMessages.map((message, index) => (
              <div className={`chat-bubble ${message.role}`} key={`${message.role}-${index}`}>{message.text}</div>
            ))}
            {chatPending && (
              <div className="chat-bubble assistant typing" aria-label="LLM agent is typing">
                <span />
                <span />
                <span />
              </div>
            )}
          </div>
          <div className="chat-compose imessage-compose">
            <input
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') sendApprovalChat();
              }}
              placeholder="Message URL agent"
            />
            <button type="button" onClick={sendApprovalChat} disabled={chatPending}>{chatPending ? 'Thinking' : 'Send'}</button>
          </div>
          <div className="approval-actions compact">
            <button type="button" onClick={draftApproved}>Draft proposal</button>
            <button type="button" onClick={() => saveApproved()}>Save file edits</button>
            <button type="button" onClick={() => setShowApprovedFile((value) => !value)}>{showApprovedFile ? 'Hide file' : 'Show file'}</button>
            <span>{approvalMessage || `${formatCount(selectedPayload.count)} URLs ${previewActive ? 'in preview' : 'currently approved'}`}</span>
          </div>
        </div>
        {settingsOpen && (
          <div className="settings-modal-backdrop" role="presentation" onClick={() => setSettingsOpen(false)}>
            <div className="settings-modal" role="dialog" aria-modal="true" aria-label="Approval settings" onClick={(event) => event.stopPropagation()}>
              <div className="settings-modal-header">
                <h3>Approval settings</h3>
                <button className="icon-button" type="button" onClick={() => setSettingsOpen(false)} aria-label="Close approval settings">×</button>
              </div>
              <p className="muted">Edit the standing prompt the LLM uses when interpreting URL selection requests.</p>
              <label className="field-label">Base approval prompt</label>
              <textarea className="approval-prompt" value={approvalPrompt} onChange={(event) => setApprovalPrompt(event.target.value)} />
            </div>
          </div>
        )}
        {pendingProposal && (
          <div className="proposal-panel">
            <div className="proposal-header">
              <div>
                <h3>Review proposed URL update</h3>
                <p className="muted">Nothing has been written yet. Review the aggregate paths, then click OK to update <code>approved_urls.md</code>.</p>
              </div>
              <div className="proposal-actions">
                <button type="button" onClick={() => saveApproved(String(pendingProposal.markdown ?? ''), pendingProposal.intent === 'remove' ? (pendingProposal.terms ?? []) : [])}>OK, update file</button>
                <button type="button" onClick={() => setPendingProposal(null)}>Cancel</button>
              </div>
            </div>
            <div className="approval-grid">
              <div className="approved-summary">
                <h3>Will select</h3>
                <DataTable columns={[["area", "Area"], ["count", "URLs"]]} rows={pendingAddedGroups} />
              </div>
              <div className="approved-summary">
                <h3>Will reject or skip</h3>
                <DataTable columns={[["area", "Area"], ["count", "URLs"]]} rows={pendingRejectedGroups} />
              </div>
              {pendingRemovedGroups.length > 0 && (
                <div className="approved-summary">
                  <h3>Will remove</h3>
                  <DataTable columns={[["area", "Area"], ["count", "URLs"]]} rows={pendingRemovedGroups} />
                </div>
              )}
            </div>
          </div>
        )}
        <div className="discovery-counts">
          <span><strong>{formatCount((selectedPayload as AnyRecord)?.discovery?.discovered_total)}</strong> discovered URLs</span>
          <span><strong>{formatCount((selectedPayload as AnyRecord)?.discovery?.eligible_total)}</strong> policy-eligible</span>
          <span><strong>{formatCount((selectedPayload as AnyRecord)?.discovery?.rejected_total)}</strong> filtered as noise</span>
          <span><strong>{formatCount((selectedPayload as AnyRecord)?.count)}</strong> {previewActive ? 'selected in preview' : 'selected for approved_urls.md'}</span>
        </div>
        <div className="approval-grid">
          <div className="approved-summary">
            <h3>{previewActive ? 'Selected areas preview' : 'Selected areas'}</h3>
            <DataTable
              columns={[
                ['area', 'Area'],
                ['count', 'URLs'],
              ]}
              rows={approvedGroups}
            />
          </div>
          <div className="approved-summary">
            <h3>Available areas</h3>
            <p className="muted">Chat “approve Cox”, “approve Dedman”, or “approve schools” to add these groups.</p>
            <DataTable
              columns={[
                ['area', 'Area'],
                ['count', 'URLs'],
              ]}
              rows={availableGroups}
            />
          </div>
        </div>
        {showApprovedFile && (
          <>
            <label className="field-label">approved_urls.md</label>
            <textarea className="approved-markdown" value={approvedMarkdown} onChange={(event) => setApprovedMarkdown(event.target.value)} spellCheck={false} />
          </>
        )}
      </Panel>
      <Panel title={`Raw source registry (${formatCount(sources.data?.total)})`}>
        <ToolbarInput value={query} onChange={setQuery} placeholder="Search sources, URLs, paths, status" />
        <DataTable
          columns={[
            ['source_id', 'ID'],
            ['source_kind', 'Kind'],
            ['status', 'Status'],
            ['wiki_status', 'Wiki'],
            ['title', 'Title'],
            ['markdown_path', 'Path/URL'],
          ]}
          rows={rows}
        />
      </Panel>
    </section>
  );
});

const Runs = memo(function Runs({ siteId, runId }: { siteId: string; runId: string }) {
  const [openRun, setOpenRun] = useState(runId);
  const runs = useQuery({
    queryKey: ['runs', siteId],
    queryFn: () => api<AnyRecord>(`/api/sites/${siteId}/runs`),
    enabled: !!siteId,
    refetchInterval: 5000,
  });
  const detail = useQuery({
    queryKey: ['run', siteId, openRun],
    queryFn: () => api<AnyRecord>(`/api/sites/${siteId}/runs/${openRun}`),
    enabled: Boolean(siteId && openRun && !['wiki', 'indexes', 'raw_sources', 'sources'].includes(openRun)),
  });
  const active = (runs.data?.runs ?? []).find((run: AnyRecord) => run.run_id === openRun) ?? (runs.data?.runs ?? [])[0];
  return (
    <section>
      <h2>Runs</h2>
      <StatusBand
        band={{
          title: 'Scrape run',
          subtitle: active?.run_id ?? 'No active run selected',
          statusLabel: titleCase(active?.status?.state ?? 'Ready'),
          tone: toneForStatus(active?.status?.state ?? 'ready'),
          actionLabel: active?.status?.state === 'completed' ? 'Review results' : 'Monitor run',
        }}
      />
      <MetricStrip
        metrics={[
          { label: 'Runs', value: formatCount(runs.data?.runs?.length) },
          { label: 'Pages', value: formatCount(active?.page_count) },
          { label: 'Events', value: formatCount(active?.event_count) },
          { label: 'Concurrency', value: formatCount(active?.status?.concurrency) },
        ]}
      />
      <div className="two-col">
        <Panel title="Run history">
          <div className="index-list">
            {(runs.data?.runs ?? []).map((run: AnyRecord) => (
              <button key={run.run_id} className={run.run_id === openRun ? 'index-card active' : 'index-card'} onClick={() => setOpenRun(run.run_id)} type="button">
                <span>{run.run_id}</span>
                <small>{titleCase(run.status?.state ?? 'artifact')}</small>
              </button>
            ))}
          </div>
        </Panel>
        <Panel title="Run detail">
          <JsonBlock value={detail.data ?? active ?? 'Choose a persisted run.'} />
        </Panel>
      </div>
    </section>
  );
});

const Documents = memo(function Documents({ siteId }: { siteId: string }) {
  const [group, setGroup] = useState('PDF pages');
  const [query, setQuery] = useState('');
  const [selectedPath, setSelectedPath] = useState('');
  const sources = useQuery({
    queryKey: ['document-sources', siteId],
    queryFn: () => api<AnyRecord>(`/api/sites/${siteId}/sources?limit=1000`),
    enabled: !!siteId,
  });
  const groups = useMemo(() => documentGroups(sources.data?.rows ?? []), [sources.data]);
  useEffect(() => {
    if (!groups.includes(group) && groups.length) setGroup(groups[0]);
  }, [group, groups]);
  const groupRows = useMemo(() => filterRows(rowsForGroup(sources.data?.rows ?? [], group), query, ['source_id', 'title', 'markdown_path', 'original_url', 'source_kind']), [group, query, sources.data]);
  useEffect(() => {
    if (!selectedPath && groupRows[0]?.markdown_path) setSelectedPath(groupRows[0].markdown_path);
  }, [groupRows, selectedPath]);
  const preview = useQuery({
    queryKey: ['document-preview', siteId, selectedPath],
    queryFn: () => api<AnyRecord>(`/api/sites/${siteId}/document-preview?path=${encodeURIComponent(selectedPath)}`),
    enabled: Boolean(siteId && selectedPath),
  });
  return (
    <section>
      <h2>Documents</h2>
      <div className="review-shell">
        <div className="document-toolbar">
          <Segmented options={groups} value={group} onChange={(next) => { setGroup(next); setSelectedPath(''); }} />
          <ToolbarInput value={query} onChange={setQuery} placeholder="Search title, path, source ID" />
        </div>
        <div className="two-col documents-grid">
          <Panel title="Sources">
            <div className="document-count">{formatCount(groupRows.length)} {group === 'PDF pages' ? 'pages' : 'sources'} · index view</div>
            <div className="index-list">
              {groupRows.slice(0, 160).map((row: AnyRecord) => (
                <button key={row.source_id} className={row.markdown_path === selectedPath ? 'index-card active' : 'index-card'} type="button" onClick={() => setSelectedPath(row.markdown_path)}>
                  <span>{row.title || row.source_id}</span>
                  <small>{row.markdown_path || row.original_url}</small>
                </button>
              ))}
            </div>
          </Panel>
          <Panel title="Preview">
            <MarkdownPreview content={preview.data?.content} label={selectedPath} loading={preview.isLoading} error={preview.error?.message} />
          </Panel>
        </div>
      </div>
    </section>
  );
});

const Wiki = memo(function Wiki({
  siteId,
  liveSnapshot,
  piEvents,
  piSkill,
  onClearPiEvents,
}: {
  siteId: string;
  liveSnapshot: AnyRecord | null;
  piEvents: PiStreamEvent[];
  piSkill: string;
  onClearPiEvents: () => void;
}) {
  const queryClientHook = useQueryClient();
  const [query, setQuery] = useState('');
  const [selectedPath, setSelectedPath] = useState('');
  const [jobBusy, setJobBusy] = useState(false);
  const [jobError, setJobError] = useState('');
  const [pageView, setPageView] = useState<'guides' | 'sources' | 'all'>('guides');
  const pages = useQuery({
    queryKey: ['wiki-pages', siteId, query, pageView],
    queryFn: () => api<AnyRecord>(
      `/api/sites/${encodeURIComponent(siteId)}/wiki/pages?limit=400&view=${pageView}&q=${encodeURIComponent(query)}`,
    ),
    enabled: !!siteId,
  });
  const wikiGeneration = useQuery({
    queryKey: ['wiki-generation', siteId],
    queryFn: () => api<AnyRecord>(`/api/sites/${encodeURIComponent(siteId)}/wiki/generation`),
    enabled: !!siteId,
    refetchInterval: 5000,
  });
  const wikiJob = useQuery({
    queryKey: ['wiki-job', siteId],
    queryFn: () => api<AnyRecord>(`/api/sites/${encodeURIComponent(siteId)}/jobs/llm-wiki-noninteractive`),
    enabled: !!siteId,
    refetchInterval: 2000,
  });
  const tmuxSessions = useQuery({
    queryKey: ['tmux-sessions', siteId],
    queryFn: () => api<AnyRecord>(`/api/sites/${encodeURIComponent(siteId)}/tmux-sessions`),
    enabled: !!siteId,
    refetchInterval: 4000,
  });
  const agentDetail = useQuery({
    queryKey: ['wiki-agent', siteId],
    queryFn: () => api<AnyRecord>(`/api/sites/${siteId}/wiki/agent`),
    enabled: !!siteId,
    refetchInterval: 2000,
  });
  const agent = agentDetail.data ?? liveSnapshot?.agent ?? {};
  const wikiReport = (wikiJob.data?.report ?? {}) as AnyRecord;
  const wikiJobRunning = ['running', 'starting', 'initializing'].includes(
    String(wikiReport.job_status ?? wikiReport.status ?? '').toLowerCase(),
  );
  const overview = liveSnapshot ?? {};
  useEffect(() => {
    if (!selectedPath && pages.data?.pages?.[0]?.path) setSelectedPath(`wiki/${pages.data.pages[0].path}`);
  }, [pages.data, selectedPath]);
  const preview = useQuery({
    queryKey: ['wiki-preview', siteId, selectedPath],
    queryFn: () => api<AnyRecord>(`/api/sites/${siteId}/document-preview?path=${encodeURIComponent(selectedPath)}`),
    enabled: Boolean(siteId && selectedPath),
  });
  const taskItems = agent.tasks?.items ?? [];
  const completed = Number(agent.tasks?.completed ?? 0);
  const total = Number(agent.tasks?.total ?? taskItems.length);

  const launchWikiJob = useCallback(async (rebuild: boolean) => {
    if (!siteId || jobBusy) return;
    setJobBusy(true);
    setJobError('');
    onClearPiEvents();
    try {
      await apiJson<AnyRecord>(`/api/sites/${encodeURIComponent(siteId)}/jobs`, 'POST', {
        skill: 'llm-wiki-noninteractive',
        prompt: rebuild ? 'rebuild wiki' : 'resume wiki',
        rebuild_wiki: rebuild,
      });
      await queryClientHook.invalidateQueries({ queryKey: ['wiki-agent', siteId] });
      await queryClientHook.invalidateQueries({ queryKey: ['tmux-sessions', siteId] });
      await queryClientHook.invalidateQueries({ queryKey: ['wiki-job', siteId] });
    } catch (err) {
      setJobError(err instanceof Error ? err.message : 'Job launch failed');
    } finally {
      setJobBusy(false);
    }
  }, [siteId, jobBusy, onClearPiEvents, queryClientHook]);

  const displayPiEvents = useMemo(() => {
    const polled = [
      ...(Array.isArray(wikiJob.data?.pi_events) ? (wikiJob.data.pi_events as PiStreamEvent[]) : []),
      ...(Array.isArray(agentDetail.data?.events) ? (agentDetail.data.events as PiStreamEvent[]) : []),
    ];
    if (!piEvents.length) return polled.slice(-400);
    if (!polled.length) return piEvents;
    const seen = new Set<string>();
    const merged: PiStreamEvent[] = [];
    for (const event of [...polled, ...piEvents]) {
      const key = JSON.stringify(event);
      if (seen.has(key)) continue;
      seen.add(key);
      merged.push(event);
    }
    return merged.slice(-400);
  }, [agentDetail.data?.events, piEvents, wikiJob.data?.pi_events]);

  const piText = useMemo(() => {
    const chunks: string[] = [];
    for (const event of displayPiEvents) {
      const label = piEventLabel(event);
      if (label) chunks.push(label);
    }
    return chunks.join('');
  }, [displayPiEvents]);

  const piStructured = useMemo(
    () => displayPiEvents.filter((event) => {
      const type = String(event.type ?? '');
      return type && type !== 'message_update' && !type.startsWith('message_');
    }).slice(-40),
    [displayPiEvents],
  );

  const archiveTmuxSession = useCallback(async (session: string) => {
    if (!siteId || !session) return;
    await apiJson<AnyRecord>(
      `/api/sites/${encodeURIComponent(siteId)}/tmux-sessions/${encodeURIComponent(session)}/archive`,
      'POST',
      {},
    );
    await queryClientHook.invalidateQueries({ queryKey: ['tmux-sessions', siteId] });
    await queryClientHook.invalidateQueries({ queryKey: ['wiki-job', siteId] });
    await queryClientHook.invalidateQueries({ queryKey: ['wiki-agent', siteId] });
  }, [queryClientHook, siteId]);

  return (
    <section>
      <h2>Wiki</h2>
      <StatusBand
        band={{
          title: 'Wiki build',
          subtitle: 'Keep generated wiki pages synchronized with prepared web, PDF, and document sources.',
          statusLabel: titleCase(overview.wiki?.job_status ?? 'Ready'),
          tone: toneForStatus(overview.wiki?.job_status ?? 'ready'),
          actionLabel: String(overview.wiki?.job_status ?? '').toLowerCase().includes('complete') ? 'Wiki current' : 'Monitor wiki',
        }}
      />
      <MetricStrip
        metrics={[
          { label: 'Sources Ready', value: formatCount(overview.wiki?.source_count) },
          { label: 'Sources Waiting', value: formatCount(overview.wiki?.pending_source_count) },
          { label: 'PDF Waiting', value: formatCount(overview.wiki?.pending_pdf_sources) },
          { label: 'Changed', value: formatCount(overview.wiki?.changed_source_count) },
        ]}
      />
      <Panel title="Wiki build">
        <div className="wiki-builder">
          <p className="wiki-builder-lede muted">
            Pi compiles student guides with wiki links, backlinks, and sitemap checks.
          </p>
          <div className="wiki-builder-bar">
            <button type="button" className="primary" disabled={jobBusy} onClick={() => void launchWikiJob(true)}>
              {jobBusy ? 'Starting…' : 'Build wiki'}
            </button>
            <button type="button" disabled={jobBusy} onClick={() => void launchWikiJob(false)}>
              Update wiki
            </button>
            {jobError && <span className="inline-status alert-inline">{jobError}</span>}
          </div>
          <details className="operator-details wiki-builder-settings">
            <summary>Run settings</summary>
            <dl className="wiki-builder-meta">
              <div>
                <dt>Model</dt>
                <dd>{agent.run?.model ?? 'openai-codex/gpt-5.3-codex'}</dd>
              </div>
              <div>
                <dt>Thinking</dt>
                <dd>{agent.run?.thinking ?? 'high'}</dd>
              </div>
              <div>
                <dt>Spec</dt>
                <dd>{agent.run?.target_spec ?? 'specs/004-agent-navigable-wiki-map.md'}</dd>
              </div>
              <div>
                <dt>Loops</dt>
                <dd>{agent.run?.max_iterations ?? 50}</dd>
              </div>
            </dl>
          </details>
        </div>
      </Panel>
      <Panel title="Tmux sessions">
        <p className="setting-help">Wiki builds run in tmux. Archive a session to capture pane output and close it.</p>
        <div className="tmux-session-list">
          {tmuxSessions.isPending ? (
            <p className="setting-help">Loading tmux sessions…</p>
          ) : tmuxSessions.isError ? (
            <p className="alert soft">Could not load tmux sessions: {tmuxSessions.error instanceof Error ? tmuxSessions.error.message : 'request failed'}</p>
          ) : (tmuxSessions.data?.sessions ?? []).length ? (
            (tmuxSessions.data?.sessions ?? []).map((row: AnyRecord) => (
              <div key={String(row.session)} className="tmux-session-row">
                <div>
                  <strong>{row.session}</strong>
                  <small>
                    {row.alive ? 'live' : 'not running'}
                    {row.job_status ? ` · ${row.job_status}` : ''}
                    {row.stale_name ? ' · report name normalized for tmux' : ''}
                  </small>
                </div>
                <button type="button" className="ghost" disabled={!row.alive} onClick={() => void archiveTmuxSession(String(row.session))}>
                  Archive & close
                </button>
              </div>
            ))
          ) : (
            <p className="setting-help">No wiki tmux sessions for this site. Launch Build/Update to create one.</p>
          )}
        </div>
      </Panel>
      <Panel title="Pi agent event stream">
        <MetricStrip
          metrics={[
            { label: 'Skill', value: piSkill || fmt(overview.wiki?.runtime) || 'llm-wiki-noninteractive' },
            { label: 'Events', value: formatCount(displayPiEvents.length) },
            { label: 'Job', value: wikiJobRunning ? 'running' : fmt(wikiReport.job_status ?? 'idle') },
            { label: 'Mode', value: 'pi --mode json' },
          ]}
        />
        {piText ? (
          <pre className="pi-event-text">{piText}</pre>
        ) : (
          <p className="setting-help">
            {wikiJobRunning
              ? 'Waiting for Pi JSON events (SSE + polled tail). If this stays empty, check wiki/reports/wiki-build-pi-events.jsonl.'
              : 'Start a Pi wiki job to see message_update text deltas and tool events here.'}
          </p>
        )}
        {piStructured.length > 0 && (
          <details className="operator-details" open>
            <summary>Structured events (latest {piStructured.length})</summary>
            <pre className="json">{JSON.stringify(piStructured, null, 2)}</pre>
          </details>
        )}
      </Panel>
      <Panel title="Wiki generation status">
        <MetricStrip
          metrics={[
            { label: 'Build', value: fmt(wikiGeneration.data?.job_status ?? overview.wiki?.job_status) },
            { label: 'Semantic pages', value: formatCount(wikiGeneration.data?.semantic_page_count) },
            { label: 'Evidence pages', value: formatCount(wikiGeneration.data?.source_page_count) },
            { label: 'Index updated', value: wikiGeneration.data?.index_updated_at ? fmt(wikiGeneration.data.index_updated_at).slice(0, 19) : '—' },
          ]}
        />
        <p className="setting-help">
          Student wiki should be mostly <strong>semantic</strong> guides (school/admissions/courses). The ~{formatCount(wikiGeneration.data?.source_page_count)} evidence pages are per-PDF shards — hidden by default in the page list.
        </p>
      </Panel>
      <Panel title="Build activity">
        {agent.stale_running && (
          <div className="alert soft">
            Ralph agent status is stale: recorded session {fmt(agent.run?.tmux_session)} is not present in tmux. The deterministic wiki build remains the source of truth for this panel.
          </div>
        )}
        <MetricStrip
          metrics={[
            { label: 'Runtime', value: fmt(overview.wiki?.runtime ?? agent.run?.runtime ?? 'python') },
            { label: 'State', value: fmt(overview.wiki?.job_status ?? agent.run?.status ?? 'ready') },
            { label: 'Sources', value: formatCount(overview.wiki?.integrated_sources) },
            { label: 'Pages', value: formatCount(overview.wiki?.pages_created) },
          ]}
        />
        <div className="progress-line">
          <span>AI-native wiki tasks: {completed}/{total} complete</span>
          <progress value={total ? completed / total : 0} max={1} />
        </div>
        {taskItems.length > 0 && (
          <details className="operator-details" open>
            <summary>AI-native task checklist</summary>
            <ul className="task-list">
              {taskItems.map((task: AnyRecord, index: number) => (
                <li key={`${task.title ?? index}-${index}`}>{task.status === 'complete' ? '[x]' : task.status === 'running' ? '->' : '[ ]'} {task.title ?? task.name ?? JSON.stringify(task)} <span>{task.status}</span></li>
              ))}
            </ul>
          </details>
        )}
        <details className="operator-details">
          <summary>Legacy builder log / artifacts</summary>
          <pre className="json">{agent.pane_log_tail || JSON.stringify(agent.events ?? [], null, 2)}</pre>
        </details>
      </Panel>
      <div className="two-col documents-grid">
        <Panel title="Wiki pages">
          <div className="action-row">
            <label>
              View
              <select value={pageView} onChange={(event) => { setPageView(event.target.value as 'guides' | 'sources' | 'all'); setSelectedPath(''); }}>
                <option value="guides">Student guides (semantic)</option>
                <option value="sources">Evidence / PDF shards</option>
                <option value="all">All pages</option>
              </select>
            </label>
          </div>
          <ToolbarInput value={query} onChange={(next) => { setQuery(next); setSelectedPath(''); }} placeholder="Title, section, or path" />
          <div className="document-count">
            {formatCount(pages.data?.pages?.length)} {pageView} pages
            {pageView === 'guides' ? ' · Cox, Dedman, admissions guides, etc.' : ''}
          </div>
          <div className="index-list">
            {(pages.data?.pages ?? []).map((page: AnyRecord) => (
              <button
                key={page.path}
                className={`wiki/${page.path}` === selectedPath ? 'index-card active' : 'index-card'}
                type="button"
                onClick={() => setSelectedPath(`wiki/${page.path}`)}
              >
                <span>{page.title ?? page.path}</span>
                <small>
                  {page.page_type ? `${page.page_type} · ` : ''}
                  {page.category ? `${page.category} · ` : ''}
                  {page.path}
                  {' · '}
                  {Math.round(Number(page.size ?? 0) / 1024)} KB
                </small>
              </button>
            ))}
          </div>
        </Panel>
        <Panel title="Preview">
          <MarkdownPreview content={preview.data?.content} label={selectedPath} loading={preview.isLoading} error={preview.error?.message} />
        </Panel>
      </div>
    </section>
  );
});

function embeddingPhaseLabel(phase: string): string {
  switch (String(phase || '').toLowerCase()) {
    case 'queued':
      return 'Queued — starting worker';
    case 'building_index':
      return 'Building hybrid index';
    case 'complete':
    case 'completed':
    case 'success':
      return 'Rebuild complete';
    case 'failed':
    case 'error':
      return 'Rebuild failed';
    case 'skipped':
      return 'Skipped (no changes)';
    default:
      return '';
  }
}

const Embeddings = memo(function Embeddings({ siteId, liveSnapshot }: { siteId: string; liveSnapshot: AnyRecord | null }) {
  const queryClientHook = useQueryClient();
  const embeddings = liveSnapshot?.embeddings ?? {};
  const jobState = (embeddings.job_state ?? {}) as AnyRecord;
  const initialActive = ['running', 'queued', 'starting', 'initializing'].includes(String(jobState.status ?? '').toLowerCase());
  const [watchJob, setWatchJob] = useState(initialActive);
  const [message, setMessage] = useState('');

  const jobPoll = useQuery({
    queryKey: ['embedding-job', siteId],
    queryFn: () => api<AnyRecord>(`/api/sites/${encodeURIComponent(siteId)}/embeddings/job`),
    enabled: !!siteId && watchJob,
    refetchInterval: (query) => {
      const status = String(query.state.data?.job_state?.status ?? '').toLowerCase();
      return ['running', 'queued', 'starting', 'initializing'].includes(status) ? 1500 : false;
    },
  });

  const liveEmbeddings = useMemo(() => {
    const polled = jobPoll.data?.job_state as AnyRecord | undefined;
    if (!polled) return embeddings;
    const merged = { ...embeddings, job_state: polled };
    const summary = jobPoll.data?.report_summary as AnyRecord | undefined;
    if (summary?.wiki_index_count != null) merged.wiki_index_count = summary.wiki_index_count;
    if (summary?.raw_index_count != null) merged.raw_index_count = summary.raw_index_count;
    return merged;
  }, [embeddings, jobPoll.data]);

  const model = buildEmbeddingModel(liveEmbeddings);
  const logTail = (jobPoll.data?.log_tail ?? []) as string[];
  const phase = String(jobPoll.data?.phase ?? '');
  const phaseLabel = embeddingPhaseLabel(phase);
  const busy = ['Running', 'Queued'].includes(model.jobLabel);

  useEffect(() => {
    if (initialActive) setWatchJob(true);
  }, [initialActive]);

  useEffect(() => {
    const status = String(jobPoll.data?.job_state?.status ?? '').toLowerCase();
    if (['complete', 'completed', 'success', 'failed', 'error', 'skipped'].includes(status)) {
      queryClientHook.invalidateQueries({ queryKey: ['overview-header', siteId] });
      if (status === 'complete' || status === 'completed' || status === 'success') {
        setMessage('Rebuild finished');
      } else if (status === 'failed' || status === 'error') {
        setMessage(String(jobPoll.data?.job_state?.last_error ?? 'Rebuild failed'));
      }
    }
  }, [jobPoll.data, queryClientHook, siteId]);

  const triggerRebuild = useCallback(async () => {
    setMessage('Starting…');
    setWatchJob(true);
    try {
      const response = await fetch(`/api/sites/${encodeURIComponent(siteId)}/embeddings/rebuild`, { method: 'POST' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(String(payload.detail ?? payload.reason ?? response.statusText));
      const status = String(payload.status ?? 'queued');
      if (status === 'already_running') setMessage('Already running — showing live log below');
      else if (status === 'blocked') setMessage('Blocked — check wiki and sources first');
      else if (status === 'disabled') setMessage('Embeddings disabled');
      else if (status === 'skipped') setMessage('Skipped — no documents changed');
      else setMessage('Rebuild started — live log below');
      void jobPoll.refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Rebuild failed');
    }
  }, [jobPoll, siteId]);

  const showActivity = watchJob || busy || logTail.length > 0;

  return (
    <section>
      <h2>Embeddings</h2>
      <div className="embeddings-summary">
        <div className="embeddings-summary-top">
          <div className="embeddings-pills">
            <span className={`status-pill ${model.indexTone}`}>Index · {model.indexLabel}</span>
            <span className={`status-pill ${model.jobTone}`}>Job · {model.jobLabel}</span>
          </div>
          <p className="embeddings-headline">{model.headline}</p>
          <p className="embeddings-rebuild-line">{model.lastRebuildLine}</p>
        </div>
        <dl className="embeddings-stats">
          {model.stats.map((stat) => (
            <div key={stat.label}>
              <dt>{stat.label}</dt>
              <dd>{stat.value}</dd>
            </div>
          ))}
        </dl>
        {showActivity && (
          <div className="embeddings-activity" aria-live="polite">
            <div className="embeddings-activity-head">
              <strong>{phaseLabel || (jobPoll.isFetching ? 'Checking status…' : 'Rebuild activity')}</strong>
              {jobPoll.isFetching && <span className="inline-status">Updating…</span>}
            </div>
            <pre className="embeddings-activity-log">
              {logTail.length ? logTail.join('\n') : 'Waiting for worker log output…'}
            </pre>
          </div>
        )}
        <div className="action-row embeddings-actions">
          <button type="button" onClick={triggerRebuild} disabled={!model.canRebuild || busy}>
            {busy ? 'Rebuilding…' : 'Rebuild embeddings'}
          </button>
          {message && <span className="inline-status">{message}</span>}
          {!message && model.disabledHint && <span className="inline-status">{model.disabledHint}</span>}
        </div>
      </div>
      <details className="operator-details">
        <summary>Raw embedding state (debug)</summary>
        <JsonBlock value={liveEmbeddings} />
      </details>
    </section>
  );
});

const McpServer = memo(function McpServer({ siteId, liveSnapshot }: { siteId: string; liveSnapshot: AnyRecord | null }) {
  const queryClientHook = useQueryClient();
  const overviewPoll = useQuery({
    queryKey: ['overview-header', siteId],
    queryFn: () => api<AnyRecord>(`/api/sites/${encodeURIComponent(siteId)}/overview`),
    enabled: !!siteId,
    staleTime: 5_000,
  });
  const mcp = (overviewPoll.data?.mcp ?? liveSnapshot?.mcp ?? {}) as AnyRecord;
  const model = buildMcpModel(mcp);
  const [message, setMessage] = useState('');
  const running = Boolean(mcp.running);
  const canStart = Boolean(mcp.server_available) && !running;
  const canStop = running;

  const refreshMcp = useCallback(() => {
    void overviewPoll.refetch();
    queryClientHook.invalidateQueries({ queryKey: ['overview-header', siteId] });
  }, [overviewPoll, queryClientHook, siteId]);

  const startServer = useCallback(async () => {
    setMessage('Starting…');
    try {
      const response = await fetch(`/api/sites/${encodeURIComponent(siteId)}/mcp/start`, { method: 'POST' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(String(payload.detail ?? response.statusText));
      const status = String(payload.status ?? 'started');
      if (status === 'already_running') setMessage('Already running');
      else if (status === 'blocked') setMessage('Cannot start — command unavailable');
      else setMessage(status === 'started' ? 'MCP server started' : titleCase(status));
      refreshMcp();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Start failed');
    }
  }, [refreshMcp, siteId]);

  const stopServer = useCallback(async () => {
    setMessage('Stopping…');
    try {
      const response = await fetch(`/api/sites/${encodeURIComponent(siteId)}/mcp/stop`, { method: 'POST' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(String(payload.detail ?? response.statusText));
      const status = String(payload.status ?? 'stopped');
      if (status === 'not_running') setMessage('Server was not running');
      else setMessage(status === 'stopped' ? 'MCP server stopped' : titleCase(status));
      refreshMcp();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Stop failed');
    }
  }, [refreshMcp, siteId]);

  return (
    <section>
      <h2>MCP</h2>
      <div className="embeddings-summary mcp-summary">
        <div className="embeddings-summary-top">
          <div className="embeddings-pills">
            <span className={`status-pill ${model.serverBand.tone}`}>
              Server · {model.serverBand.statusLabel}
            </span>
            {mcp.session_name && (
              <span className="status-pill neutral">{String(mcp.session_name)}</span>
            )}
          </div>
          <p className="embeddings-headline">
            {running
              ? 'LLM Wiki MCP is running in tmux for this site.'
              : mcp.server_available
                ? 'Start the query-only MCP server so agents can search this site index.'
                : 'MCP server command is not configured for this workspace.'}
          </p>
          {mcp.last_error && <p className="embeddings-rebuild-line alert soft">{String(mcp.last_error)}</p>}
        </div>
        <dl className="embeddings-stats">
          <div>
            <dt>Index</dt>
            <dd>{titleCase(mcp.index_health ?? 'missing')}</dd>
          </div>
          <div>
            <dt>Command</dt>
            <dd>{mcp.server_available ? 'Ready' : 'Missing'}</dd>
          </div>
        </dl>
        <div className="action-row embeddings-actions">
          <button type="button" className="ghost" onClick={startServer} disabled={!canStart}>
            Start MCP
          </button>
          <button type="button" onClick={stopServer} disabled={!canStop}>
            Stop MCP
          </button>
          {message && <span className="inline-status">{message}</span>}
        </div>
      </div>
      <details className="operator-details">
        <summary>Raw MCP state (debug)</summary>
        <JsonBlock value={mcp} />
      </details>
    </section>
  );
});

const Metrics = memo(function Metrics({ siteId }: { siteId: string }) {
  const [windowLabel, setWindowLabel] = useState('30d');
  const [selectedRunId, setSelectedRunId] = useState('');
  const runs = useQuery({ queryKey: ['agent-metrics-runs', siteId], queryFn: () => api<AnyRecord>(`/api/sites/${siteId}/metrics/runs`), enabled: !!siteId });
  const rollups = useQuery({
    queryKey: ['agent-metrics-rollups', siteId],
    queryFn: () => api<AnyRecord>(`/api/sites/${siteId}/metrics/rollups?windows=30d,60d,90d,365d&include_all_time=true`),
    enabled: !!siteId,
  });
  const rows = runs.data?.runs ?? [];
  const selectedRun = selectedRunId ? rows.find((run: AnyRecord) => run.run_id === selectedRunId) : rows[0];
  const rollup = rollups.data?.rollups?.[windowLabel] ?? rollups.data?.rollups?.['30d'];
  const model = buildMetricsModel({ runs: rows, rollup });
  const selectedModel = buildMetricsModel({ runs: selectedRun ? [selectedRun] : [] });
  return (
    <section>
      <h2>Metrics</h2>
      <Panel title="Pi Agent Aggregates">
        <div className="segmented">
          {['30d', '60d', '90d', '365d', 'all_time'].map((label) => (
            <button key={label} type="button" className={windowLabel === label ? 'active' : ''} onClick={() => setWindowLabel(label)}>
              {label === '365d' ? '1 year' : label.replace('_', ' ')}
            </button>
          ))}
        </div>
        <MetricStrip metrics={model.aggregateMetrics} />
      </Panel>
      <Panel title="Agent Metrics Per Run">
        <DataTable
          columns={[
            ['run_id', 'Run'],
            ['state', 'State'],
            ['total_tokens', 'Total Tokens'],
            ['llm_tokens', 'LLM Tokens'],
            ['embedding_tokens', 'Embedding Tokens'],
            ['vectors', 'Vectors'],
            ['cost', 'Cost'],
            ['health', 'Health'],
          ]}
          rows={model.runRows}
          onRowClick={(row) => setSelectedRunId(String(row.run_id ?? ''))}
        />
      </Panel>
      <Panel title="Selected Run Detail">
        {selectedRun ? (
          <>
            <MetricStrip metrics={selectedModel.latestRunMetrics} />
            {selectedModel.healthWarnings.length > 0 && <div className="inline-status warning">Health: {selectedModel.healthWarnings.join(', ')}</div>}
            <div className="detail-grid">
              <Panel title="LLM Usage">
                <JsonBlock value={selectedRun.llm_usage ?? {}} />
              </Panel>
              <Panel title="Embedding Usage">
                <JsonBlock value={selectedRun.embedding_usage ?? {}} />
              </Panel>
            </div>
          </>
        ) : (
          <EmptyState message="No Pi agent metrics have been recorded yet." />
        )}
      </Panel>
    </section>
  );
});

const Settings = memo(function Settings({ appState }: { appState?: AnyRecord }) {
  const state = appState?.state ?? {};
  const queryClientHook = useQueryClient();
  const [saveMessage, setSaveMessage] = useState('');
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState(() => wikiTmuxDraftFromState(state));

  useEffect(() => {
    setDraft(wikiTmuxDraftFromState(state));
  }, [appState]);

  const graceMinutes = draft.tmux_session_grace_minutes;
  const saveSettings = useCallback(async () => {
    setSaving(true);
    setSaveMessage('');
    try {
      const payload = {
        tmux_session_grace_seconds: Math.max(0, Math.round(Number(graceMinutes) * 60)),
        wiki_builder_runtime: draft.wiki_builder_runtime,
        wiki_skip_pi: draft.wiki_skip_pi,
        tmux_archive_sessions: draft.tmux_archive_sessions,
        tmux_reconcile_expired_sessions: draft.tmux_reconcile_expired_sessions,
        pi_cmd: draft.pi_cmd.trim() || 'pi',
      };
      await apiJson<AnyRecord>('/api/app-state', 'PUT', { payload });
      await queryClientHook.invalidateQueries({ queryKey: ['app-state'] });
      setSaveMessage('Settings saved.');
    } catch (error) {
      setSaveMessage(error instanceof Error ? error.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  }, [draft, graceMinutes, queryClientHook]);

  return (
    <section>
      <h2>Settings</h2>
      <p>Configure local providers, models, scraping, retrieval, research, and wiki/tmux lifecycle.</p>
      <MetricStrip
        metrics={[
          { label: 'OpenRouter', value: state.openrouter_api_key ? 'set' : 'missing' },
          { label: 'Scraper', value: fmt(state.scrape_browser_mode, 'none') },
          { label: 'Wiki runtime', value: fmt(state.wiki_builder_runtime, 'pi') },
          { label: 'Tmux grace', value: `${formatCount(Math.round((state.tmux_session_grace_seconds ?? 1800) / 60))} min` },
        ]}
      />
      <div className="settings-grid">
        {[
          ['Keys', ['OpenRouter key', 'Tavily key']],
          ['LLM', ['URL reasoning', 'Wiki enrichment', 'Wiki Q&A']],
          ['Scraping', ['Scrape concurrency', 'Browser fallback', 'Lightpanda CDP URL']],
          ['Indexing', ['Embeddings enabled', 'Embedding model', 'Zvec collection']],
          ['Research', ['Use Tavily for university map']],
        ].map(([title, items]) => (
          <Panel key={String(title)} title={String(title)}>
            {(items as string[]).map((item) => (
              <label key={item} className="setting-row">
                <span>{item}</span>
                <input readOnly value={settingValue(item, state)} />
              </label>
            ))}
          </Panel>
        ))}
        <Panel title="Wiki / Tmux">
          <label className="setting-row">
            <span>Session grace period (minutes)</span>
            <input
              type="number"
              min={0}
              step={1}
              value={draft.tmux_session_grace_minutes}
              onChange={(event) => setDraft((current) => ({ ...current, tmux_session_grace_minutes: Number(event.target.value) }))}
            />
          </label>
          <p className="setting-help">Finished wiki tmux sessions stay open this long for log review, then auto-close.</p>
          <label className="setting-row">
            <span>Wiki builder runtime</span>
            <select
              value={draft.wiki_builder_runtime}
              onChange={(event) => setDraft((current) => ({ ...current, wiki_builder_runtime: event.target.value }))}
            >
              <option value="pi">Pi agent (llm-wiki-v2)</option>
              <option value="python">Python pipeline only</option>
            </select>
          </label>
          <label className="setting-row setting-row-inline">
            <span>Skip Pi compile (dev)</span>
            <input
              type="checkbox"
              checked={draft.wiki_skip_pi}
              onChange={(event) => setDraft((current) => ({ ...current, wiki_skip_pi: event.target.checked }))}
            />
          </label>
          <label className="setting-row setting-row-inline">
            <span>Archive tmux session logs</span>
            <input
              type="checkbox"
              checked={draft.tmux_archive_sessions}
              onChange={(event) => setDraft((current) => ({ ...current, tmux_archive_sessions: event.target.checked }))}
            />
          </label>
          <label className="setting-row setting-row-inline">
            <span>Auto-reconcile expired sessions</span>
            <input
              type="checkbox"
              checked={draft.tmux_reconcile_expired_sessions}
              onChange={(event) => setDraft((current) => ({ ...current, tmux_reconcile_expired_sessions: event.target.checked }))}
            />
          </label>
          <label className="setting-row">
            <span>Pi command</span>
            <input value={draft.pi_cmd} onChange={(event) => setDraft((current) => ({ ...current, pi_cmd: event.target.value }))} />
          </label>
          <label className="setting-row">
            <span>Archive directory (relative to site wiki)</span>
            <input readOnly value={fmt(state.tmux_archive_subdir, 'wiki/reports/tmux-archives')} />
          </label>
        </Panel>
      </div>
      <div className="settings-actions">
        <button type="button" onClick={saveSettings} disabled={saving}>
          {saving ? 'Saving…' : 'Save All Settings'}
        </button>
        {saveMessage && <span className="inline-status">{saveMessage}</span>}
      </div>
    </section>
  );
});

type WikiTmuxDraft = {
  tmux_session_grace_minutes: number;
  wiki_builder_runtime: string;
  wiki_skip_pi: boolean;
  tmux_archive_sessions: boolean;
  tmux_reconcile_expired_sessions: boolean;
  pi_cmd: string;
};

function wikiTmuxDraftFromState(state: AnyRecord): WikiTmuxDraft {
  const graceSeconds = Number(state.tmux_session_grace_seconds ?? 1800);
  return {
    tmux_session_grace_minutes: Math.round(graceSeconds / 60),
    wiki_builder_runtime: String(state.wiki_builder_runtime || 'pi'),
    wiki_skip_pi: Boolean(state.wiki_skip_pi),
    tmux_archive_sessions: state.tmux_archive_sessions !== false,
    tmux_reconcile_expired_sessions: state.tmux_reconcile_expired_sessions !== false,
    pi_cmd: String(state.pi_cmd || 'pi'),
  };
}

function settingValue(item: string, state: AnyRecord): string {
  const map: AnyRecord = {
    'OpenRouter key': state.openrouter_api_key ? 'set' : 'missing',
    'Tavily key': state.tavily_api_key ? 'set' : 'missing',
    'URL reasoning': state.url_reasoning_openrouter_model,
    'Wiki enrichment': state.graph_enrichment_openrouter_model,
    'Wiki Q&A': state.graph_answer_openrouter_model,
    'Scrape concurrency': state.scrape_concurrency,
    'Browser fallback': state.scrape_browser_mode,
    'Lightpanda CDP URL': state.lightpanda_cdp_url,
    'Embeddings enabled': state.embedding_enabled === false ? 'off' : 'on',
    'Embedding model': state.embedding_model,
    'Zvec collection': state.zvec_collection,
    'Use Tavily for university map': state.use_tavily_for_map ? 'on' : 'off',
  };
  return fmt(map[item], '');
}

const StatusBand = memo(function StatusBand({ band }: { band: StatusBandModel }) {
  return (
    <section className={`status-band ${band.tone}`}>
      <div>
        <div className="command-kicker">Command Center // {band.statusLabel}</div>
        <div className="status-title">{band.title}</div>
        <div className="status-subtitle">{band.subtitle}</div>
      </div>
      <div className="status-side">
        <span className="status-badge">{band.statusLabel}</span>
        <span className="status-action">↳ {band.actionLabel}</span>
      </div>
    </section>
  );
});

const MetricStrip = memo(function MetricStrip({ metrics }: { metrics: MetricModel[] }) {
  return (
    <div className="operator-metric-strip" style={{ '--metric-columns': Math.min(Math.max(metrics.length, 1), 4) } as React.CSSProperties}>
      {metrics.map((metric) => (
        <article className="operator-metric-card" key={metric.label}>
          <div className="operator-metric-label"><span className="operator-metric-sigil">◆</span><span>{metric.label}</span></div>
          <div className="operator-metric-value">{metric.value}</div>
          {metric.help && <div className="operator-metric-foot">{metric.help}</div>}
        </article>
      ))}
    </div>
  );
});

const Panel = memo(function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="panel">
      <h3>{title}</h3>
      {children}
    </section>
  );
});

const JsonBlock = memo(function JsonBlock({ value }: { value: unknown }) {
  const text = useMemo(() => JSON.stringify(value, null, 2), [value]);
  return <pre className="json">{text}</pre>;
});

function DataTable({ columns, rows, onRowClick }: { columns: [string, string][]; rows: AnyRecord[]; onRowClick?: (row: AnyRecord) => void }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{columns.map(([, label]) => <th key={label}>{label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, 250).map((row, idx) => (
            <tr key={row.source_id ?? row.run_id ?? row.path ?? idx} onClick={onRowClick ? () => onRowClick(row) : undefined}>
              {columns.map(([key]) => <td key={key}>{fmt(row[key])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MarkdownPreview({ content, label, loading, error }: { content?: string; label?: string; loading?: boolean; error?: string }) {
  if (loading) return <div className="empty">Loading selected source…</div>;
  if (error) return <div className="alert">{error}</div>;
  if (!content) return <div className="empty">Choose a source to preview rendered Markdown.</div>;
  return (
    <article className="markdown-preview">
      {label && <div className="preview-label">{label}</div>}
      <div className="markdown-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </div>
    </article>
  );
}

function ToolbarInput({ value, onChange, placeholder }: { value: string; onChange: (value: string) => void; placeholder: string }) {
  return <input className="toolbar-input" value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />;
}

function Segmented({ options, value, onChange }: { options: string[]; value: string; onChange: (value: string) => void }) {
  return (
    <div className="segmented">
      {options.map((option) => (
        <button key={option} type="button" className={option === value ? 'active' : ''} onClick={() => onChange(option)}>
          {option}
        </button>
      ))}
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return <div className="empty">{message}</div>;
}

function filterRows(rows: AnyRecord[], query: string, keys: string[]): AnyRecord[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return rows;
  return rows.filter((row) => keys.some((key) => String(row[key] ?? '').toLowerCase().includes(needle)));
}

function documentGroups(rows: AnyRecord[]): string[] {
  const groups = [];
  if (rows.some((row) => row.source_kind === 'web')) groups.push('Scraped URLs');
  if (rows.some((row) => row.source_kind === 'pdf')) groups.push('PDF pages');
  if (rows.some((row) => !['web', 'pdf'].includes(row.source_kind))) groups.push('Other documents');
  return groups.length ? groups : ['Other documents'];
}

function rowsForGroup(rows: AnyRecord[], group: string): AnyRecord[] {
  if (group === 'Scraped URLs') return rows.filter((row) => row.source_kind === 'web');
  if (group === 'PDF pages') return rows.filter((row) => row.source_kind === 'pdf');
  return rows.filter((row) => !['web', 'pdf'].includes(row.source_kind));
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={queryClient}>
    <App />
  </QueryClientProvider>,
);
