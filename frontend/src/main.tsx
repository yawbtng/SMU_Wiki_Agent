import React, { memo, useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import ReactDOM from 'react-dom/client';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  OPENROUTER_EMBEDDING_MODELS,
  OPENROUTER_LLM_MODELS,
  SECRET_UNCHANGED,
  estimateOpenRouterCost,
  openRouterModelOption,
  settingsDraftFromState,
  settingsSavePayloadFromDraft,
  type OpenRouterModelOption,
} from './settingsModel';
import {
  AgentRunSummary,
  AnyRecord,
  MetricModel,
  StatusBandModel,
  buildEmbeddingModel,
  buildMcpModel,
  buildMetricsModel,
  buildMetricsRollupPoints,
  buildMetricsRunTrendPoints,
  buildOverviewModel,
  buildScrapeModel,
  chartBarHeightPercent,
  formatChartMetricValue,
  formatCount,
  formatCompact,
  metricsChartRangeLabel,
  metricsTokenMixSegments,
  resolveWikiJobStatus,
  scrapeStartPayload,
  summarizePiBuildEvents,
  type MetricsChartPoint,
  titleCase,
  toneForStatus,
} from './viewModel';
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

async function apiForm<T>(path: string, method: string, body: FormData): Promise<T> {
  const res = await fetch(path, { method, body });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function apiDelete<T>(path: string): Promise<T> {
  const res = await fetch(path, { method: 'DELETE' });
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

const SCHOOL_ROOT_SEGMENTS = new Set([
  'cox',
  'dedman',
  'dedmanlaw',
  'law',
  'meadows',
  'lyle',
  'simmons',
  'perkins',
  'admission',
  'enrollment-services',
  'studentaffairs',
  'libraries',
  'oit',
  'businessfinance',
]);

function normalizeSubpath(value: unknown): string {
  const raw = String(value ?? '/').trim() || '/';
  return raw.startsWith('/') ? raw : `/${raw}`;
}

function groupCount(group: AnyRecord): number {
  return Number(group.count ?? 0);
}

function parentBucket(subpath: string): string {
  const parts = subpath.split('/').filter(Boolean);
  return parts.length ? `/${parts[0]}` : '/';
}

function isSchoolRoot(subpath: string): boolean {
  const parts = subpath.split('/').filter(Boolean);
  return parts.length > 0 && SCHOOL_ROOT_SEGMENTS.has(parts[0]);
}

function availableGroupRows(groups: AnyRecord[] = []): AnyRecord[] {
  return [...groups].sort(
    (left, right) =>
      Number(right.count ?? 0) - Number(left.count ?? 0) ||
      String(left.subpath ?? '').localeCompare(String(right.subpath ?? '')),
  );
}

function collectExampleLines(children: AnyRecord[]): string[] {
  const examples: string[] = [];
  for (const child of children) {
    for (const line of groupExampleLines(child)) {
      if (examples.length >= 3) return examples;
      if (!examples.includes(line)) examples.push(line);
    }
  }
  return examples;
}

function enrichLeaf(group: AnyRecord): AnyRecord {
  const subpath = normalizeSubpath(group.subpath);
  return {
    ...group,
    subpath,
    count: groupCount(group),
    examples: groupExampleLines(group),
    childSubpaths: [subpath],
    childCount: 1,
    collapsed: false,
  };
}

function mergeChildGroups(children: AnyRecord[], displaySubpath: string): AnyRecord {
  const childSubpaths = children.map((child) => normalizeSubpath(child.subpath));
  return {
    subpath: displaySubpath,
    count: children.reduce((sum, child) => sum + groupCount(child), 0),
    examples: collectExampleLines(children),
    childSubpaths,
    childCount: childSubpaths.length,
    collapsed: childSubpaths.length > 1,
  };
}

function sortParentBuckets(byParent: Map<string, AnyRecord[]>): string[] {
  return [...byParent.keys()].sort((left, right) => {
    const sum = (key: string) => (byParent.get(key) ?? []).reduce((total, group) => total + groupCount(group), 0);
    return sum(right) - sum(left) || left.localeCompare(right);
  });
}

function effectiveAreaGroups(rawGroups: AnyRecord[] = []): AnyRecord[] {
  const leaves = availableGroupRows(rawGroups);
  if (!leaves.length) return [];

  const byParent = new Map<string, AnyRecord[]>();
  for (const group of leaves) {
    const subpath = normalizeSubpath(group.subpath);
    const parent = parentBucket(subpath);
    byParent.set(parent, [...(byParent.get(parent) ?? []), { ...group, subpath }]);
  }

  const result: AnyRecord[] = [];
  for (const parent of sortParentBuckets(byParent)) {
    const sorted = availableGroupRows(byParent.get(parent) ?? []);
    if (sorted.length === 1) {
      result.push(enrichLeaf(sorted[0]));
      continue;
    }

    if (isSchoolRoot(parent)) {
      result.push(mergeChildGroups(sorted, parent));
      continue;
    }

    const heavy = sorted.filter((group) => groupCount(group) > 1);
    const light = sorted.filter((group) => groupCount(group) <= 1);

    if (light.length === sorted.length && sorted.length >= 3) {
      result.push(mergeChildGroups(sorted, parent));
      continue;
    }

    if (heavy.length === 1 && sorted.length === 2 && light.length === 1) {
      for (const group of sorted) result.push(enrichLeaf(group));
      continue;
    }

    if (light.length >= 2) {
      result.push(mergeChildGroups(light, parent));
    } else {
      for (const group of light) result.push(enrichLeaf(group));
    }
    for (const group of heavy) result.push(enrichLeaf(group));
  }

  return availableGroupRows(result);
}

function childSubpathsForGroup(group: AnyRecord): string[] {
  const raw = group.childSubpaths;
  if (Array.isArray(raw) && raw.length) {
    return raw.map((item) => normalizeSubpath(item));
  }
  return [normalizeSubpath(group.subpath)];
}

function effectiveGroupKey(group: AnyRecord): string {
  return childSubpathsForGroup(group).join('|');
}

function formatChildSummary(childSubpaths: string[], maxItems = 3): string {
  if (childSubpaths.length <= 1) return '';
  const shown = childSubpaths.slice(0, maxItems);
  const extra = childSubpaths.length > maxItems ? `, +${childSubpaths.length - maxItems} more` : '';
  return `Includes: ${shown.join(', ')}${extra}`;
}

function groupExampleLines(group: AnyRecord): string[] {
  const raw = group.examples;
  if (Array.isArray(raw)) {
    return raw.map((item) => String(item).trim()).filter(Boolean).slice(0, 3);
  }
  return [];
}

function formatExampleLine(value: string): { href: string; label: string } {
  const raw = value.trim();
  try {
    const url = new URL(raw);
    const path = `${url.pathname}${url.search}`;
    const label = path && path !== '/' ? path : url.hostname;
    return { href: raw, label: label.length > 72 ? `${label.slice(0, 69)}…` : label };
  } catch {
    return { href: raw, label: raw.length > 72 ? `${raw.slice(0, 69)}…` : raw };
  }
}

const AreaGroupExamples = memo(function AreaGroupExamples({
  group,
  listClassName = 'area-group-examples',
  fallbackClassName = 'area-group-examples-fallback',
  showFallback = true,
}: {
  group: AnyRecord;
  listClassName?: string;
  fallbackClassName?: string;
  showFallback?: boolean;
}) {
  const lines = groupExampleLines(group);
  if (!lines.length) {
    return showFallback ? <p className={fallbackClassName}>No examples captured for this group</p> : null;
  }
  return (
    <ul className={listClassName}>
      {lines.map((line) => {
        const { href, label } = formatExampleLine(line);
        const external = /^https?:\/\//i.test(href);
        return (
          <li key={line}>
            {external ? (
              <a href={href} target="_blank" rel="noreferrer" title={href}>
                {label}
              </a>
            ) : (
              <span title={href}>{label}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
});

const AreaGroupChildSummary = memo(function AreaGroupChildSummary({
  childSubpaths,
  className = 'area-group-child-summary',
}: {
  childSubpaths: string[];
  className?: string;
}) {
  const summary = formatChildSummary(childSubpaths);
  if (!summary) return null;
  return <p className={className}>{summary}</p>;
});

const AreaGroupList = memo(function AreaGroupList({
  groups,
  emptyMessage = 'No areas in this list.',
}: {
  groups: AnyRecord[];
  emptyMessage?: string;
}) {
  if (!groups.length) {
    return <p className="muted area-groups-empty">{emptyMessage}</p>;
  }
  return (
    <ul className="area-groups-list">
      {groups.map((group) => {
        const subpath = String(group.subpath ?? '/');
        const childSubpaths = childSubpathsForGroup(group);
        const childCount = Number(group.childCount ?? childSubpaths.length);
        const sectionLabel = childCount === 1 ? 'section' : 'sections';
        return (
          <li key={effectiveGroupKey(group)} className="area-group-item">
            <div className="area-group-head">
              <span className="area-group-name">{areaLabel(subpath)}</span>
              <span className="area-group-count">
                {formatCount(group.count)} URLs · {formatCount(childCount)} {sectionLabel}
              </span>
            </div>
            <div className="area-group-subpath">{subpath}</div>
            <AreaGroupChildSummary childSubpaths={childSubpaths} />
            <AreaGroupExamples group={group} />
          </li>
        );
      })}
    </ul>
  );
});

function approveMessageForSubpaths(subpaths: string[]): string {
  const terms = subpaths
    .map((subpath) => `path:${normalizeSubpath(subpath)}`)
    .filter(Boolean);
  return `approve ${terms.join(' ')}`;
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

function workspaceCardMeta(site: AnyRecord): { hasSources: boolean; hasWiki: boolean; runLabel: string } {
  const runs = Number(site.run_count ?? 0);
  const runLabel = runs === 1 ? '1 run' : `${formatCount(runs)} runs`;
  return {
    hasSources: Boolean(site.has_sources),
    hasWiki: Boolean(site.has_wiki),
    runLabel,
  };
}

function WorkspaceStrokeIcon({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

function WorkspaceSourcesIcon() {
  return (
    <WorkspaceStrokeIcon className="workspace-ui-icon workspace-ui-icon-inline">
      <path d="M12 3 3 7.5 12 12l9-4.5L12 3z" />
      <path d="M3 12.5 12 17l9-4.5" />
      <path d="M3 17.5 12 22l9-4.5" />
    </WorkspaceStrokeIcon>
  );
}

function WorkspaceWikiIcon() {
  return (
    <WorkspaceStrokeIcon className="workspace-ui-icon workspace-ui-icon-inline">
      <path d="M5 4h6a3.5 3.5 0 0 1 3.5 3.5V20H9.5A3.5 3.5 0 0 1 6 16.5V4z" />
      <path d="M13 4h6v16h-6a3.5 3.5 0 0 1-3.5-3.5V7.5A3.5 3.5 0 0 1 13 4z" />
    </WorkspaceStrokeIcon>
  );
}

function WorkspaceRunsIcon() {
  return (
    <WorkspaceStrokeIcon className="workspace-ui-icon workspace-ui-icon-inline">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </WorkspaceStrokeIcon>
  );
}

function formatDataRootDisplay(path: string): string {
  const trimmed = path.trim().replace(/\/$/, '');
  if (!trimmed) return '';
  const parts = trimmed.split(/[/\\]/).filter(Boolean);
  if (parts.length === 0) return 'data';
  if (parts.length === 1) return parts[0];
  return `${parts[parts.length - 2]}/${parts[parts.length - 1]}`;
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
    setSnapshot(null);
    setConnected(false);
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

  const stream = useSiteStream(siteId);
  const overviewHeader = useQuery({
    queryKey: ['overview-header', siteId],
    queryFn: () => api<AnyRecord>(`/api/sites/${encodeURIComponent(siteId)}/overview`),
    enabled: !!siteId,
    staleTime: 10_000,
  });
  const handleSiteSelected = useCallback((nextSiteId: string) => {
    if (!nextSiteId) return;
    setSiteId(nextSiteId);
    setActiveTab('Overview');
    queryClientHook.setQueryData(['app-state'], (current: AnyRecord | undefined) => ({
      ...(current ?? {}),
      state: { ...(current?.state ?? {}), active_workspace_id: nextSiteId, last_site_id: nextSiteId },
    }));
  }, [queryClientHook]);
  const handleReturnToDashboard = useCallback(() => {
    setSiteId('');
    setActiveTab('Overview');
  }, []);
  const handleWorkspaceDeleted = useCallback((deletedSiteId: string) => {
    if (siteId === deletedSiteId) {
      setSiteId('');
      setActiveTab('Overview');
    }
    queryClientHook.setQueryData(['sites'], (current: AnyRecord | undefined) => {
      const sites = Array.isArray(current?.sites)
        ? current.sites.filter((site: AnyRecord) => site.id !== deletedSiteId)
        : [];
      return { ...(current ?? {}), sites };
    });
    queryClientHook.setQueryData(['app-state'], (current: AnyRecord | undefined) => {
      const state = current?.state;
      if (!state || typeof state !== 'object') return current;
      const workspaces = Array.isArray(state.workspaces)
        ? state.workspaces.filter((item: AnyRecord) => item.id !== deletedSiteId)
        : [];
      const nextState = { ...state, workspaces };
      if (state.active_workspace_id === deletedSiteId) nextState.active_workspace_id = '';
      if (state.last_site_id === deletedSiteId) nextState.last_site_id = '';
      return { ...(current ?? {}), state: nextState };
    });
    queryClientHook.removeQueries({ predicate: (query) => {
      const key = query.queryKey;
      return key.length > 1 && key[1] === deletedSiteId;
    }});
    queryClientHook.invalidateQueries({ queryKey: ['sites'] });
    queryClientHook.invalidateQueries({ queryKey: ['app-state'] });
  }, [queryClientHook, siteId]);
  const handleSiteDiscovered = useCallback((payload: AnyRecord) => {
    const nextSiteId = String(payload.site_id ?? '');
    if (!nextSiteId) return;
    handleSiteSelected(nextSiteId);
    const discovery = {
      discovered_total: payload.discovered_total,
      eligible_total: payload.eligible_total,
      rejected_total: payload.rejected_total,
    };
    queryClientHook.setQueryData(['approved-urls', nextSiteId], (current: AnyRecord | undefined) => ({
      ...(current ?? {}),
      site_id: nextSiteId,
      discovery,
      count: current?.count ?? 0,
      markdown: current?.markdown ?? '# Approved URLs\n\n',
      urls: current?.urls ?? [],
      groups: current?.groups ?? [],
      available_groups: current?.available_groups ?? [],
      generated_at: payload.generated_at,
    }));
    queryClientHook.setQueryData(['sites'], (current: AnyRecord | undefined) => {
      const existing = Array.isArray(current?.sites) ? current.sites : [];
      const sites = existing.some((site: AnyRecord) => site.id === nextSiteId)
        ? existing.map((site: AnyRecord) => site.id === nextSiteId ? { ...site, has_sources: Boolean(site.has_sources), url: payload.site_url } : site)
        : [...existing, { id: nextSiteId, has_sources: false, has_wiki: false, run_count: 0, url: payload.site_url }];
      return { ...(current ?? {}), sites };
    });
    queryClientHook.invalidateQueries({ queryKey: ['sites'] });
    queryClientHook.invalidateQueries({ queryKey: ['app-state'] });
    queryClientHook.invalidateQueries({ queryKey: ['overview-header', nextSiteId] });
    queryClientHook.invalidateQueries({ queryKey: ['overview', nextSiteId] });
    queryClientHook.invalidateQueries({ queryKey: ['sources', nextSiteId] });
    queryClientHook.invalidateQueries({ queryKey: ['approved-urls', nextSiteId] });
    setActiveTab('Sources');
  }, [handleSiteSelected, queryClientHook]);
  const workspaceOpen = Boolean(siteId);
  const activeDisplay = workspaceOpen ? siteDisplay(siteId, appState.data) : { name: '—', url: '—', runId: '' };
  const selectedSite = sites.find((site: AnyRecord) => site.id === siteId);
  const activeStatus = workspaceOpen
    ? activeWorkspaceStatus(activeDisplay.runId, stream.snapshot ?? overviewHeader.data ?? null, activeTab)
    : { label: 'Status', detail: '—' };

  let bootstrapMessage: string | null = null;
  if (sitesQuery.isPending) {
    bootstrapMessage = 'Loading sites…';
  } else if (sitesQuery.isError) {
    const detail = sitesQuery.error instanceof Error ? sitesQuery.error.message : 'request failed';
    bootstrapMessage = `API unavailable (${detail}). Run ./start.sh from the repo root and confirm http://127.0.0.1:8000/api/health responds.`;
  } else if (!sites.length) {
    bootstrapMessage = 'No site data found. Set SCRAPE_PLANNER_DATA_ROOT to your data directory.';
  }

  return (
    <div className="app-shell">
      <main className="page">
        <Hero
          activeStatus={activeStatus}
          connected={workspaceOpen ? stream.connected : false}
          dataRoot={sitesQuery.data?.data_root}
          siteCount={sites.length}
          siteName={workspaceOpen ? activeDisplay.name : 'Workspaces'}
          siteUrl={workspaceOpen ? activeDisplay.url : 'Select a site below'}
          dashboardMode={!workspaceOpen}
        />
        {bootstrapMessage ? (
          <EmptyState message={bootstrapMessage} />
        ) : !workspaceOpen ? (
          <WorkspaceDashboard
            sites={sites}
            appState={appState.data}
            onOpen={handleSiteSelected}
            onSiteDiscovered={handleSiteDiscovered}
            onDeleted={handleWorkspaceDeleted}
          />
        ) : (
          <>
            <WorkspaceToolbar
              siteId={siteId}
              siteName={activeDisplay.name}
              siteUrl={activeDisplay.url}
              activeStatus={activeStatus}
              onSiteDiscovered={handleSiteDiscovered}
              onReturnToDashboard={handleReturnToDashboard}
              onDeleted={handleWorkspaceDeleted}
            />
            <WorkflowNav activeTab={activeTab} onTab={setActiveTab} />
            <TabView
              tab={activeTab}
              siteId={siteId}
              site={selectedSite}
              siteName={activeDisplay.name}
              siteUrl={activeDisplay.url}
              runId={activeDisplay.runId}
              liveSnapshot={stream.snapshot}
              streamConnected={stream.connected}
              piEvents={stream.piEvents}
              piSkill={stream.piSkill}
              onClearPiEvents={stream.clearPiEvents}
              appState={appState.data}
            />
          </>
        )}
      </main>
    </div>
  );
}

const WorkspaceDashboard = memo(function WorkspaceDashboard({
  sites,
  appState,
  onOpen,
  onSiteDiscovered,
  onDeleted,
}: {
  sites: AnyRecord[];
  appState?: AnyRecord;
  onOpen: (siteId: string) => void;
  onSiteDiscovered: (payload: AnyRecord) => void;
  onDeleted: (siteId: string) => void;
}) {
  const [showAdd, setShowAdd] = useState(false);
  const [discoverUrl, setDiscoverUrl] = useState('');
  const [discoverMessage, setDiscoverMessage] = useState('');
  const [discoverBusy, setDiscoverBusy] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState('');
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteMessage, setDeleteMessage] = useState('');

  const runDiscovery = useCallback(async () => {
    const target = discoverUrl.trim();
    if (!target) return;
    setDiscoverBusy(true);
    setDiscoverMessage('Reading robots.txt and sitemap.xml…');
    try {
      const payload = await apiJson<AnyRecord>('/api/discover', 'POST', { site_url: target, timeout: 30 });
      setDiscoverMessage(`Discovered ${formatCount(payload.discovered_total)} URLs from ${formatCount(payload.sitemap_sources?.length)} sitemap source(s).`);
      onSiteDiscovered(payload);
      setShowAdd(false);
    } catch (error) {
      setDiscoverMessage(error instanceof Error ? error.message : 'Discovery failed');
    } finally {
      setDiscoverBusy(false);
    }
  }, [discoverUrl, onSiteDiscovered]);

  const runDelete = useCallback(async (targetSiteId: string) => {
    setDeleteBusy(true);
    setDeleteMessage('');
    try {
      await apiDelete<AnyRecord>(`/api/sites/${encodeURIComponent(targetSiteId)}`);
      onDeleted(targetSiteId);
      setConfirmDeleteId('');
      setDeleteMessage(`Removed workspace ${targetSiteId}.`);
    } catch (error) {
      setDeleteMessage(error instanceof Error ? error.message : 'Delete failed');
    } finally {
      setDeleteBusy(false);
    }
  }, [onDeleted]);

  return (
    <section className="workspace-dashboard" aria-label="Workspace dashboard">
      <div className="workspace-dashboard-head">
        <div>
          <h2>All workspaces</h2>
          <p className="workspace-dashboard-copy">Open a site or add a new university URL.</p>
        </div>
        <button type="button" className="ghost workspace-add-toggle" onClick={() => setShowAdd((value) => !value)}>
          {showAdd ? 'Cancel' : 'Add workspace'}
        </button>
      </div>
      {showAdd && (
        <div className="workspace-add-panel">
          <label className="field-label" htmlFor="workspace-discover-url">University site URL</label>
          <div className="workspace-add-row">
            <input
              id="workspace-discover-url"
              value={discoverUrl}
              onChange={(event) => setDiscoverUrl(event.target.value)}
              placeholder="https://university.edu"
              aria-label="University URL"
            />
            <button type="button" onClick={() => void runDiscovery()} disabled={discoverBusy || !discoverUrl.trim()}>
              {discoverBusy ? 'Discovering…' : 'Discover / Add'}
            </button>
          </div>
          {discoverMessage && <p className="inline-status">{discoverMessage}</p>}
        </div>
      )}
      {deleteMessage && <p className="inline-status">{deleteMessage}</p>}
      {sites.length ? (
        <div className="workspace-card-grid">
          {sites.map((site) => {
            const display = siteDisplay(String(site.id), appState);
            const cardUrl = String(site.url ?? display.url);
            const meta = workspaceCardMeta(site);
            const domain = cardUrl.replace(/^https?:\/\//, '').replace(/\/$/, '');
            return (
              <article className="workspace-card" key={String(site.id)}>
                <div className="workspace-card-body">
                  <h3 className="workspace-card-title">{display.name}</h3>
                  {String(site.id) !== display.name && (
                    <p className="workspace-card-slug">{site.id}</p>
                  )}
                  <p className="workspace-card-host" title={cardUrl}>{domain || cardUrl}</p>
                  <div className="workspace-card-meta" aria-label="Workspace status">
                  <span className={`workspace-meta-chip ${meta.hasSources ? 'on' : 'off'}`}>
                    <WorkspaceSourcesIcon />
                    Sources
                  </span>
                  <span className={`workspace-meta-chip ${meta.hasWiki ? 'on' : 'off'}`}>
                    <WorkspaceWikiIcon />
                    Wiki
                  </span>
                  <span className="workspace-meta-chip">
                    <WorkspaceRunsIcon />
                    {meta.runLabel}
                  </span>
                  </div>
                </div>
                <div className="workspace-card-footer">
                  <button type="button" className="workspace-card-open" onClick={() => onOpen(String(site.id))}>
                    Open
                  </button>
                  {confirmDeleteId === String(site.id) ? (
                    <div className="workspace-delete-confirm">
                      <button
                        type="button"
                        className="danger"
                        disabled={deleteBusy}
                        onClick={() => void runDelete(String(site.id))}
                      >
                        {deleteBusy ? 'Deleting…' : 'Confirm'}
                      </button>
                      <button type="button" className="ghost" disabled={deleteBusy} onClick={() => setConfirmDeleteId('')}>
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      className="ghost workspace-card-delete"
                      onClick={() => setConfirmDeleteId(String(site.id))}
                    >
                      Delete
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <EmptyState message="No workspaces yet. Add a university URL to discover sitemap sources and create the first workspace." />
      )}
    </section>
  );
});

const Hero = memo(function Hero({
  activeStatus,
  connected,
  dashboardMode,
  dataRoot,
  siteCount,
  siteName,
  siteUrl,
}: {
  activeStatus: { label: string; detail: string };
  connected: boolean;
  dashboardMode: boolean;
  dataRoot?: string;
  siteCount: number;
  siteName: string;
  siteUrl: string;
}) {
  return (
    <section className={`design-shell${dashboardMode ? ' design-shell-dashboard' : ''}`}>
      <div className="design-shell-copy">
        <div>
          <div className="design-kicker">Ultra-fast RAG</div>
          <h1>{dashboardMode ? 'Workspaces' : siteName}</h1>
          <p>
            {dashboardMode
              ? 'Build and query student wiki indexes from university sources.'
              : 'Sources, wiki, embeddings, and metrics for this site.'}
          </p>
        </div>
        <div className="design-stat-row">
          <div className="design-stat">
            <div className="design-stat-label">Tabs</div>
            <div className="design-stat-value">{tabs.length}</div>
          </div>
          <div className="design-stat">
            <div className="design-stat-label">Sites</div>
            <div className="design-stat-value">{formatCount(siteCount)}</div>
          </div>
          {!dashboardMode && (
            <div className="design-stat wide">
              <div className="design-stat-label">{activeStatus.label}</div>
              <div className="design-stat-value mono">{activeStatus.detail}</div>
            </div>
          )}
        </div>
      </div>
      <div className={`hero-foot${dashboardMode ? ' hero-foot-dashboard' : ''}`}>
        {!dashboardMode && (
          <>
            <span className="hero-foot-site">{siteName}</span>
            <span className="hero-foot-url">{siteUrl}</span>
          </>
        )}
        <span className={connected ? 'live-pill' : 'live-pill muted'}>{connected ? 'Live' : 'Connecting'}</span>
        {dataRoot ? (
          <span className="data-root">
            <span className="data-root-path">{formatDataRootDisplay(dataRoot)}</span>
          </span>
        ) : null}
      </div>
    </section>
  );
});

const WorkspaceToolbar = memo(function WorkspaceToolbar({
  siteId,
  siteName,
  siteUrl,
  activeStatus,
  onSiteDiscovered,
  onReturnToDashboard,
  onDeleted,
}: {
  siteId: string;
  siteName: string;
  siteUrl: string;
  activeStatus: { label: string; detail: string };
  onSiteDiscovered: (payload: AnyRecord) => void;
  onReturnToDashboard: () => void;
  onDeleted: (siteId: string) => void;
}) {
  const [discoverUrl, setDiscoverUrl] = useState(siteUrl || '');
  const [discoverMessage, setDiscoverMessage] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteMessage, setDeleteMessage] = useState('');
  const autoDiscoverUrl = useRef(siteUrl || '');
  useEffect(() => {
    if (siteUrl && (!discoverUrl || discoverUrl === autoDiscoverUrl.current)) {
      setDiscoverUrl(siteUrl);
      autoDiscoverUrl.current = siteUrl;
    }
  }, [discoverUrl, siteUrl]);
  const runDiscovery = useCallback(async () => {
    const target = discoverUrl.trim();
    if (!target) return;
    setDiscoverMessage('Reading robots.txt and sitemap.xml…');
    try {
      const payload = await apiJson<AnyRecord>('/api/discover', 'POST', { site_url: target, timeout: 30 });
      setDiscoverMessage(`Discovered ${formatCount(payload.discovered_total)} URLs from ${formatCount(payload.sitemap_sources?.length)} sitemap source(s).`);
      onSiteDiscovered(payload);
    } catch (error) {
      setDiscoverMessage(error instanceof Error ? error.message : 'Discovery failed');
    }
  }, [discoverUrl, onSiteDiscovered]);
  const runDelete = useCallback(async () => {
    if (!siteId) return;
    setDeleteBusy(true);
    setDeleteMessage('');
    try {
      await apiDelete<AnyRecord>(`/api/sites/${encodeURIComponent(siteId)}`);
      onDeleted(siteId);
      setConfirmDelete(false);
    } catch (error) {
      setDeleteMessage(error instanceof Error ? error.message : 'Delete failed');
    } finally {
      setDeleteBusy(false);
    }
  }, [onDeleted, siteId]);
  return (
    <section className="workspace-row">
      <div className="workspace-toolbar">
        <div className="workspace-toolbar-head">
          <div className="workspace-toolbar-title">{siteName}</div>
          <button
            type="button"
            className="icon-button workspace-close"
            onClick={onReturnToDashboard}
            aria-label="Exit workspace"
          >
            ×
          </button>
        </div>
        <div className="workspace-toolbar-copy">{siteUrl}</div>
        <div className="workspace-toolbar-meta">
          <span>{activeStatus.label}</span>
          <strong>{activeStatus.detail}</strong>
        </div>
      </div>
      <div className="workspace-actions">
        <div className="workspace-actions-bar">
          <button type="button" className="ghost workspace-dashboard-link" onClick={onReturnToDashboard}>
            Exit workspace
          </button>
          {confirmDelete ? (
            <div className="workspace-delete-confirm">
              <span className="inline-status">Delete {siteId} and all site data?</span>
              <button type="button" className="danger" disabled={deleteBusy} onClick={() => void runDelete()}>
                {deleteBusy ? 'Deleting…' : 'Confirm delete'}
              </button>
              <button type="button" className="ghost" disabled={deleteBusy} onClick={() => setConfirmDelete(false)}>
                Cancel
              </button>
            </div>
          ) : (
            <button type="button" className="ghost danger workspace-delete" onClick={() => setConfirmDelete(true)}>
              Delete workspace
            </button>
          )}
        </div>
        <div className="workspace-discover-row">
          <input value={discoverUrl} onChange={(event) => setDiscoverUrl(event.target.value)} placeholder="https://university.edu" aria-label="University URL" />
          <button type="button" className="workspace-discover-btn" onClick={runDiscovery}>
            Discover
          </button>
        </div>
        {discoverMessage && <span className="inline-status workspace-actions-status">{discoverMessage}</span>}
        {deleteMessage && <span className="inline-status danger workspace-actions-status">{deleteMessage}</span>}
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
  if (tab === 'Overview') return <Overview siteId={siteId} siteName={siteName} siteUrl={siteUrl} runId={runId} liveSnapshot={liveSnapshot} streamConnected={streamConnected} appState={appState} />;
  if (tab === 'Sources') return <Sources siteId={siteId} hasSources={Boolean(site?.has_sources)} siteLabel={siteName} />;
  if (tab === 'Runs') return <Runs siteId={siteId} runId={runId} appState={appState} />;
  if (tab === 'Documents') return <Documents siteId={siteId} />;
  if (tab === 'Wiki') return <Wiki siteId={siteId} liveSnapshot={liveSnapshot} piEvents={piEvents} piSkill={piSkill} onClearPiEvents={onClearPiEvents} />;
  if (tab === 'Embeddings') return <Embeddings siteId={siteId} liveSnapshot={liveSnapshot} />;
  if (tab === 'MCP') return <McpServer />;
  if (tab === 'Metrics') return <Metrics siteId={siteId} />;
  if (tab === 'Settings') return <Settings appState={appState} />;
  return <EmptyState message={`${tab} is unavailable.`} />;
});

function scrapeSettingsFromAppState(appState?: AnyRecord) {
  const state = appState?.state ?? {};
  return {
    scrapeConcurrency: Number(state.scrape_concurrency ?? 4),
    scrapeBrowserMode: String(state.scrape_browser_mode ?? 'none'),
  };
}

function invalidateScrapeQueries(queryClientHook: ReturnType<typeof useQueryClient>, siteId: string) {
  queryClientHook.invalidateQueries({ queryKey: ['overview', siteId] });
  queryClientHook.invalidateQueries({ queryKey: ['overview-header', siteId] });
  queryClientHook.invalidateQueries({ queryKey: ['runs', siteId] });
  queryClientHook.invalidateQueries({ queryKey: ['sources', siteId] });
  queryClientHook.invalidateQueries({ queryKey: ['document-sources', siteId] });
  queryClientHook.invalidateQueries({ queryKey: ['approved-urls', siteId] });
}

const Overview = memo(function Overview({
  siteId,
  siteName,
  siteUrl,
  runId,
  liveSnapshot,
  streamConnected,
  appState,
}: {
  siteId: string;
  siteName: string;
  siteUrl: string;
  runId: string;
  liveSnapshot: AnyRecord | null;
  streamConnected: boolean;
  appState?: AnyRecord;
}) {
  const queryClientHook = useQueryClient();
  const [scrapeBusy, setScrapeBusy] = useState(false);
  const [scrapeMessage, setScrapeMessage] = useState('');
  const scrapeSettings = scrapeSettingsFromAppState(appState);
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
  const approved = useQuery({
    queryKey: ['approved-urls', siteId],
    queryFn: () => api<AnyRecord>(`/api/sites/${siteId}/approved-urls`),
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
    discovery: approved.data?.discovery,
    approvedCount: approved.data?.count,
    run: activeRun,
  });
  const scrapeModel = buildScrapeModel({
    approvedCount: approved.data?.count,
    ...scrapeSettings,
    busy: scrapeBusy,
  });
  const startScrape = useCallback(async () => {
    if (!siteId || !scrapeModel.canStart) return;
    setScrapeBusy(true);
    setScrapeMessage('Starting scrape…');
    try {
      const payload = scrapeStartPayload({ approvedCount: scrapeModel.approvedCount, ...scrapeSettings });
      const result = await apiJson<AnyRecord>(`/api/sites/${encodeURIComponent(siteId)}/scrape`, 'POST', payload);
      setScrapeMessage(`Scrape started · run ${String(result.run_id ?? 'unknown')} · ${formatCount(result.url_count)} URLs`);
      invalidateScrapeQueries(queryClientHook, siteId);
    } catch (error) {
      setScrapeMessage(error instanceof Error ? error.message : 'Scrape failed');
    } finally {
      setScrapeBusy(false);
    }
  }, [queryClientHook, scrapeModel.approvedCount, scrapeModel.canStart, scrapeSettings, siteId]);
  return (
    <section>
      <h2>Overview</h2>
      <StatusBand band={model.statusBand} />
      <MetricStrip metrics={model.essentialMetrics} />
      <div className="action-row embeddings-actions">
        <button type="button" className="primary" disabled={!scrapeModel.canStart} onClick={() => void startScrape()}>
          {scrapeModel.buttonLabel}
        </button>
        {(scrapeMessage || scrapeModel.disabledHint) && (
          <span className="inline-status">{scrapeMessage || scrapeModel.disabledHint}</span>
        )}
      </div>
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
        <JsonBlock value={{ overview: data ?? overview.error?.message ?? 'Loading', discovery: approved.data?.discovery, next_action: model.nextAction }} />
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
  const [selectedAvailableSubpaths, setSelectedAvailableSubpaths] = useState<string[]>([]);
  const [areaActionPending, setAreaActionPending] = useState(false);
  const [areaActionStatus, setAreaActionStatus] = useState('');
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
  const [selectedRawSource, setSelectedRawSource] = useState<AnyRecord | null>(null);
  const registryTableRows = useMemo(
    () => rows.map((row) => ({
      ...row,
      display_title: row.title || row.source_id || 'Untitled',
      display_path: row.markdown_path || row.original_url || row.original_path || '',
    })),
    [rows],
  );
  const selectedMarkdownPath = String(selectedRawSource?.markdown_path ?? '').trim();
  const rawSourcePreview = useQuery({
    queryKey: ['raw-source-preview', siteId, selectedMarkdownPath],
    queryFn: () => api<AnyRecord>(`/api/sites/${siteId}/document-preview?path=${encodeURIComponent(selectedMarkdownPath)}`),
    enabled: Boolean(siteId && selectedMarkdownPath),
  });
  useEffect(() => {
    setSelectedRawSource(null);
  }, [siteId]);
  const previewActive = Boolean(pendingProposal);
  const selectedPayload = pendingProposal ?? approved.data ?? {};
  const selectedGroups = useMemo(
    () => effectiveAreaGroups(selectedPayload.groups ?? []),
    [selectedPayload.groups],
  );
  const rawAvailableGroups = useMemo(
    () => availableGroupRows(selectedPayload.available_groups ?? []),
    [selectedPayload.available_groups],
  );
  const effectiveAvailableGroups = useMemo(
    () => effectiveAreaGroups(selectedPayload.available_groups ?? []),
    [selectedPayload.available_groups],
  );
  const hasAvailableGroups = effectiveAvailableGroups.length > 0;
  const availableLeafCount = rawAvailableGroups.length;
  const selectedAvailableCount = selectedAvailableSubpaths.length;
  useEffect(() => {
    const available = new Set(rawAvailableGroups.map((group) => normalizeSubpath(group.subpath)));
    setSelectedAvailableSubpaths((current) => {
      const next = current.filter((subpath) => available.has(normalizeSubpath(subpath)));
      return next.length === current.length ? current : next;
    });
  }, [rawAvailableGroups]);
  const pendingAddedGroups = useMemo(
    () => effectiveAreaGroups(pendingProposal?.added_groups ?? []),
    [pendingProposal?.added_groups],
  );
  const pendingRemovedGroups = useMemo(
    () => effectiveAreaGroups(pendingProposal?.removed_groups ?? []),
    [pendingProposal?.removed_groups],
  );
  const pendingRejectedGroups = useMemo(
    () => effectiveAreaGroups(pendingProposal?.rejected_groups ?? []),
    [pendingProposal?.rejected_groups],
  );
  const filteredRejectedUrlDetail = useCallback((payload: AnyRecord) => {
    const filtered = Array.isArray(payload.filtered_rejected_urls) ? payload.filtered_rejected_urls : [];
    const firstFiltered = filtered[0] as AnyRecord | undefined;
    if (!firstFiltered) return '';
    const reason = String(firstFiltered.reason ?? 'policy_rejected');
    const detail = firstFiltered.detail ? `; first detail: ${String(firstFiltered.detail)}` : '';
    return ` Filtered ${formatCount(filtered.length)} noisy URL${filtered.length === 1 ? '' : 's'}; first reason: ${reason}${detail}.`;
  }, []);
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
    setApprovalMessage(`Saved ${formatCount(payload.count)} approved URLs.${filteredRejectedUrlDetail(payload)} Future scrapes will use only this file.`);
  }, [approvedMarkdown, filteredRejectedUrlDetail, queryClientHook, siteId]);
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
  const toggleAvailableBucket = useCallback((childSubpaths: string[]) => {
    if (!childSubpaths.length) return;
    setSelectedAvailableSubpaths((current) => {
      const allSelected = childSubpaths.every((subpath) => current.includes(subpath));
      if (allSelected) {
        return current.filter((item) => !childSubpaths.includes(item));
      }
      const next = new Set(current);
      for (const subpath of childSubpaths) next.add(subpath);
      return [...next];
    });
  }, []);
  const isAvailableBucketSelected = useCallback(
    (childSubpaths: string[]) => childSubpaths.length > 0 && childSubpaths.every((subpath) => selectedAvailableSubpaths.includes(subpath)),
    [selectedAvailableSubpaths],
  );
  const applySelectedAreas = useCallback(async (subpaths: string[], mode: 'preview' | 'add') => {
    if (!subpaths.length || areaActionPending) return;
    const message = approveMessageForSubpaths(subpaths);
    setAreaActionPending(true);
    setAreaActionStatus(mode === 'preview' ? 'Building preview…' : 'Updating approved URLs…');
    try {
      const payload = await apiJson<AnyRecord>(`/api/sites/${siteId}/approved-urls/chat`, 'POST', {
        message,
        base_prompt: approvalPrompt,
        markdown: approvedMarkdown,
        limit: 30000,
        autosave: mode === 'add',
      });
      const reply = String(payload.assistant_message ?? message);
      if (mode === 'add' || payload.saved) {
        setApprovedMarkdown(String(payload.markdown ?? ''));
        setPendingProposal(null);
        queryClientHook.setQueryData(['approved-urls', siteId], payload);
        queryClientHook.removeQueries({ queryKey: ['approved-urls-preview', siteId] });
        setSelectedAvailableSubpaths((current) => current.filter((item) => !subpaths.includes(item)));
        setAreaActionStatus(`Saved ${formatCount(payload.count)} approved URLs (${formatCount(subpaths.length)} area${subpaths.length === 1 ? '' : 's'}).${filteredRejectedUrlDetail(payload)}`);
      } else {
        setPendingProposal(payload);
        queryClientHook.setQueryData(['approved-urls-preview', siteId], payload);
        setAreaActionStatus(`Preview ready — ${formatCount(payload.count)} URLs if you commit (${formatCount(subpaths.length)} selected).`);
      }
      setApprovalMessage(reply);
    } catch (error) {
      const reply = error instanceof Error ? error.message : 'URL update failed.';
      setAreaActionStatus(reply);
      setApprovalMessage(reply);
    } finally {
      setAreaActionPending(false);
    }
  }, [approvalPrompt, approvedMarkdown, areaActionPending, filteredRejectedUrlDetail, queryClientHook, siteId]);
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
          <strong>{siteLabel ?? siteId}</strong> has no scraped sources yet. Use the scrape workflow for this workspace, or switch to another workspace with prepared sources.
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
                <AreaGroupList groups={pendingAddedGroups} emptyMessage="No new areas in this proposal." />
              </div>
              <div className="approved-summary">
                <h3>Will reject or skip</h3>
                <AreaGroupList groups={pendingRejectedGroups} emptyMessage="No rejected areas in this proposal." />
              </div>
              {pendingRemovedGroups.length > 0 && (
                <div className="approved-summary">
                  <h3>Will remove</h3>
                  <AreaGroupList groups={pendingRemovedGroups} emptyMessage="No removals in this proposal." />
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
            <AreaGroupList
              groups={selectedGroups}
              emptyMessage={previewActive ? 'Preview has no selected areas yet.' : 'No areas in approved_urls.md yet.'}
            />
          </div>
          <div className="approved-summary available-areas-panel">
            <h3>Available areas</h3>
            <div className="available-areas-toolbar">
              <span className="available-areas-count">
                {hasAvailableGroups
                  ? `${formatCount(selectedAvailableCount)} of ${formatCount(availableLeafCount)} sections selected · ${formatCount(effectiveAvailableGroups.length)} grouped areas`
                  : 'No areas left to add'}
              </span>
              <div className="available-areas-actions">
                <button
                  type="button"
                  disabled={!selectedAvailableCount || areaActionPending || chatPending}
                  onClick={() => applySelectedAreas(selectedAvailableSubpaths, 'preview')}
                >
                  {areaActionPending ? 'Working…' : 'Preview selected'}
                </button>
                <button
                  type="button"
                  disabled={!selectedAvailableCount || areaActionPending || chatPending}
                  onClick={() => applySelectedAreas(selectedAvailableSubpaths, 'add')}
                >
                  {areaActionPending ? 'Working…' : 'Add selected'}
                </button>
              </div>
            </div>
            {areaActionStatus && <p className="available-areas-status">{areaActionStatus}</p>}
            {hasAvailableGroups ? (
              <ul className="available-areas-list">
                {effectiveAvailableGroups.map((group) => {
                  const subpath = String(group.subpath ?? '/');
                  const childSubpaths = childSubpathsForGroup(group);
                  const childCount = Number(group.childCount ?? childSubpaths.length);
                  const sectionLabel = childCount === 1 ? 'section' : 'sections';
                  const checked = isAvailableBucketSelected(childSubpaths);
                  const hasExamples = groupExampleLines(group).length > 0;
                  return (
                    <li key={effectiveGroupKey(group)} className={checked ? 'available-area-row selected' : 'available-area-row'}>
                      <label className="available-area-label">
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={areaActionPending || chatPending}
                          onChange={() => toggleAvailableBucket(childSubpaths)}
                        />
                        <span className="available-area-copy">
                          <span className="available-area-name">{areaLabel(subpath)}</span>
                          <span className="available-area-subpath">{subpath}</span>
                          <AreaGroupChildSummary
                            childSubpaths={childSubpaths}
                            className="available-area-child-summary"
                          />
                          <AreaGroupExamples
                            group={group}
                            listClassName="available-area-examples"
                            fallbackClassName="available-area-examples-fallback"
                            showFallback={!hasExamples}
                          />
                        </span>
                        <span className="available-area-count">
                          {formatCount(group.count)} URLs · {formatCount(childCount)} {sectionLabel}
                        </span>
                      </label>
                      <button
                        type="button"
                        className="available-area-add"
                        disabled={areaActionPending || chatPending}
                        onClick={() => applySelectedAreas(childSubpaths, 'add')}
                      >
                        Add
                      </button>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="muted available-areas-empty">Every eligible area is already in approved_urls.md.</p>
            )}
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
        <div className="raw-source-registry-shell">
          <DataTable
            columns={[
              ['display_title', 'Title'],
              ['source_kind', 'Kind'],
              ['status', 'Status'],
              ['wiki_status', 'Wiki'],
              ['display_path', 'Path'],
            ]}
            rows={registryTableRows}
            onRowClick={(row) => setSelectedRawSource(row)}
            isRowSelected={(row) => String(row.source_id ?? '') === String(selectedRawSource?.source_id ?? '')}
          />
          <aside className="raw-source-inspector" aria-label="Selected raw source inspector">
            {selectedRawSource ? (
              <>
                <div className="raw-source-inspector-header">
                  <h3>{fmt(selectedRawSource.title, String(selectedRawSource.source_id ?? 'Raw source'))}</h3>
                  <p className="muted">Inspect scraped markdown and registry metadata for this source.</p>
                </div>
                <dl className="raw-source-meta">
                  <div><dt>Kind</dt><dd>{fmt(selectedRawSource.source_kind)}</dd></div>
                  <div><dt>Status</dt><dd>{fmt(selectedRawSource.status)}</dd></div>
                  <div><dt>Wiki</dt><dd>{fmt(selectedRawSource.wiki_status)}</dd></div>
                  <div><dt>Source ID</dt><dd><code>{fmt(selectedRawSource.source_id)}</code></dd></div>
                  {selectedRawSource.original_url && (
                    <div><dt>URL</dt><dd><a href={String(selectedRawSource.original_url)} target="_blank" rel="noreferrer">{String(selectedRawSource.original_url)}</a></dd></div>
                  )}
                  {selectedRawSource.markdown_path && (
                    <div><dt>Markdown path</dt><dd><code>{String(selectedRawSource.markdown_path)}</code></dd></div>
                  )}
                  {!selectedRawSource.markdown_path && selectedRawSource.original_path && (
                    <div><dt>Original path</dt><dd><code>{String(selectedRawSource.original_path)}</code></dd></div>
                  )}
                </dl>
                {selectedMarkdownPath ? (
                  <MarkdownPreview
                    content={rawSourcePreview.data?.content}
                    label={selectedMarkdownPath}
                    loading={rawSourcePreview.isLoading}
                    error={rawSourcePreview.error?.message}
                  />
                ) : (
                  <div className="empty raw-source-inspector-empty">
                    No markdown artifact for this source yet. Inspect externally via{' '}
                    {selectedRawSource.original_url ? (
                      <a href={String(selectedRawSource.original_url)} target="_blank" rel="noreferrer">{String(selectedRawSource.original_url)}</a>
                    ) : (
                      <code>{fmt(selectedRawSource.original_path || selectedRawSource.source_id)}</code>
                    )}
                    .
                  </div>
                )}
              </>
            ) : (
              <div className="empty raw-source-inspector-empty">Click a registry row to preview the raw markdown and metadata.</div>
            )}
          </aside>
        </div>
      </Panel>
    </section>
  );
});

const Runs = memo(function Runs({ siteId, runId, appState }: { siteId: string; runId: string; appState?: AnyRecord }) {
  const queryClientHook = useQueryClient();
  const [openRun, setOpenRun] = useState(runId);
  const [scrapeBusy, setScrapeBusy] = useState(false);
  const [scrapeMessage, setScrapeMessage] = useState('');
  const scrapeSettings = scrapeSettingsFromAppState(appState);
  const approved = useQuery({
    queryKey: ['approved-urls', siteId],
    queryFn: () => api<AnyRecord>(`/api/sites/${siteId}/approved-urls`),
    enabled: !!siteId,
  });
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
  const scrapeModel = buildScrapeModel({
    approvedCount: approved.data?.count,
    ...scrapeSettings,
    busy: scrapeBusy,
  });
  const startScrape = useCallback(async () => {
    if (!siteId || !scrapeModel.canStart) return;
    setScrapeBusy(true);
    setScrapeMessage('Starting scrape…');
    try {
      const payload = scrapeStartPayload({ approvedCount: scrapeModel.approvedCount, ...scrapeSettings });
      const result = await apiJson<AnyRecord>(`/api/sites/${encodeURIComponent(siteId)}/scrape`, 'POST', payload);
      setScrapeMessage(`Scrape started · run ${String(result.run_id ?? 'unknown')} · ${formatCount(result.url_count)} URLs`);
      if (result.run_id) setOpenRun(String(result.run_id));
      invalidateScrapeQueries(queryClientHook, siteId);
    } catch (error) {
      setScrapeMessage(error instanceof Error ? error.message : 'Scrape failed');
    } finally {
      setScrapeBusy(false);
    }
  }, [queryClientHook, scrapeModel.approvedCount, scrapeModel.canStart, scrapeSettings, siteId]);
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
      <div className="action-row embeddings-actions">
        <button type="button" className="primary" disabled={!scrapeModel.canStart} onClick={() => void startScrape()}>
          {scrapeModel.buttonLabel}
        </button>
        {(scrapeMessage || scrapeModel.disabledHint) && (
          <span className="inline-status">{scrapeMessage || scrapeModel.disabledHint}</span>
        )}
      </div>
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
  const queryClientHook = useQueryClient();
  const [group, setGroup] = useState('PDF pages');
  const [query, setQuery] = useState('');
  const [selectedPath, setSelectedPath] = useState('');
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadStatus, setUploadStatus] = useState('');
  const [uploadError, setUploadError] = useState('');
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const uploadInputId = useId();
  const uploadFileSummary = useMemo(() => {
    if (!uploadFiles.length) return 'PDF only · select one or more files';
    if (uploadFiles.length === 1) return uploadFiles[0].name;
    const names = uploadFiles.map((file) => file.name);
    const preview = names.slice(0, 2).join(', ');
    return names.length > 2 ? `${preview} + ${formatCount(names.length - 2)} more` : preview;
  }, [uploadFiles]);
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
  const uploadDocuments = useCallback(async () => {
    if (!siteId || !uploadFiles.length || uploadBusy) return;
    setUploadBusy(true);
    setUploadError('');
    setUploadStatus('Extracting documents...');
    const form = new FormData();
    uploadFiles.forEach((file) => form.append('files', file));
    try {
      const payload = await apiForm<AnyRecord>(`/api/sites/${encodeURIComponent(siteId)}/documents/upload`, 'POST', form);
      setUploadStatus(
        `Uploaded ${formatCount(payload.uploaded_count)} document${Number(payload.uploaded_count) === 1 ? '' : 's'} · ${formatCount(payload.accepted_count)} accepted · ${formatCount(payload.chunk_count)} chunks`,
      );
      setUploadFiles([]);
      if (uploadInputRef.current) uploadInputRef.current.value = '';
      await queryClientHook.invalidateQueries({ queryKey: ['document-sources', siteId] });
      await queryClientHook.invalidateQueries({ queryKey: ['sources', siteId] });
      await queryClientHook.invalidateQueries({ queryKey: ['overview', siteId] });
      await queryClientHook.invalidateQueries({ queryKey: ['wiki-generation', siteId] });
      await queryClientHook.invalidateQueries({ queryKey: ['wiki-pages', siteId] });
      setGroup('PDF pages');
      setSelectedPath('');
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed');
      setUploadStatus('');
    } finally {
      setUploadBusy(false);
    }
  }, [queryClientHook, siteId, uploadBusy, uploadFiles]);
  return (
    <section>
      <h2>Documents</h2>
      <div className="review-shell">
        <Panel title="Add documents">
          <div className="document-upload">
            <p className="document-upload-lede">Upload PDFs to extract page markdown for wiki builds.</p>
            <div className="document-upload-zone">
              <input
                id={uploadInputId}
                ref={uploadInputRef}
                className="document-upload-input"
                type="file"
                accept="application/pdf,.pdf"
                multiple
                onChange={(event) => setUploadFiles(Array.from(event.target.files ?? []))}
              />
              <label htmlFor={uploadInputId} className="document-upload-picker">
                {uploadFiles.length ? 'Change PDFs' : 'Choose PDFs'}
              </label>
              <span className="document-upload-files" title={uploadFileSummary}>
                {uploadFileSummary}
              </span>
            </div>
            <div className="document-upload-actions">
              <button type="button" className="primary" disabled={!uploadFiles.length || uploadBusy} onClick={() => void uploadDocuments()}>
                {uploadBusy ? 'Extracting...' : 'Upload & extract'}
              </button>
              <span className={uploadError ? 'inline-status alert-inline' : 'inline-status'}>
                {uploadError || uploadStatus || (uploadFiles.length ? `${formatCount(uploadFiles.length)} ready` : 'No files selected')}
              </span>
            </div>
            <p className="document-upload-help">
              Extracted pages appear below as PDF pages. Use Wiki {'>'} Build wiki after upload to generate or refresh wiki pages.
            </p>
          </div>
        </Panel>
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
  const overview = liveSnapshot ?? {};
  const wikiReport = (wikiJob.data?.report ?? {}) as AnyRecord;
  const wikiStatus = resolveWikiJobStatus({
    liveStatus: overview.wiki?.job_status,
    reportStatus: wikiReport.job_status ?? wikiReport.status,
    generationStatus: wikiGeneration.data?.job_status,
    staleRunning: Boolean(wikiJob.data?.stale_running ?? wikiReport.stale_running),
  });
  const wikiJobRunning = ['running', 'starting', 'initializing'].includes(
    String(wikiReport.job_status ?? wikiReport.status ?? '').toLowerCase(),
  ) && !['archived', 'stale', 'failed'].includes(wikiStatus.label.toLowerCase());
  useEffect(() => {
    if (!selectedPath && pages.data?.pages?.[0]?.path) setSelectedPath(`wiki/${pages.data.pages[0].path}`);
  }, [pages.data, selectedPath]);
  const preview = useQuery({
    queryKey: ['wiki-preview', siteId, selectedPath],
    queryFn: () => api<AnyRecord>(`/api/sites/${siteId}/document-preview?path=${encodeURIComponent(selectedPath)}`),
    enabled: Boolean(siteId && selectedPath),
  });
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
      await queryClientHook.invalidateQueries({ queryKey: ['tmux-sessions', siteId] });
      await queryClientHook.invalidateQueries({ queryKey: ['wiki-job', siteId] });
    } catch (err) {
      setJobError(err instanceof Error ? err.message : 'Job launch failed');
    } finally {
      setJobBusy(false);
    }
  }, [siteId, jobBusy, onClearPiEvents, queryClientHook]);

  const displayBuildEvents = useMemo(() => {
    const polled = [
      ...(Array.isArray(wikiJob.data?.pi_events) ? (wikiJob.data.pi_events as PiStreamEvent[]) : []),
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
  }, [piEvents, wikiJob.data?.pi_events]);

  const buildText = useMemo(() => {
    const summary = summarizePiBuildEvents(displayBuildEvents);
    if (summary.length) return summary.join('\n');
    const chunks: string[] = [];
    for (const event of displayBuildEvents) {
      const label = piEventLabel(event);
      if (label) chunks.push(label);
    }
    return chunks.join('');
  }, [displayBuildEvents]);

  const buildStructured = useMemo(
    () => displayBuildEvents.filter((event) => {
      const type = String(event.type ?? '');
      return type && type !== 'message_update' && !type.startsWith('message_');
    }).slice(-40),
    [displayBuildEvents],
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
    await queryClientHook.invalidateQueries({ queryKey: ['wiki-generation', siteId] });
    await queryClientHook.invalidateQueries({ queryKey: ['overview-header', siteId] });
    await queryClientHook.invalidateQueries({ queryKey: ['overview', siteId] });
  }, [queryClientHook, siteId]);

  return (
    <section>
      <h2>Wiki</h2>
      <StatusBand
        band={{
          title: 'Wiki build',
          subtitle: String(wikiReport.last_error || 'Keep generated wiki pages synchronized with prepared web, PDF, and document sources.'),
          statusLabel: wikiStatus.label,
          tone: wikiStatus.tone,
          actionLabel: wikiStatus.label.toLowerCase().includes('complete') ? 'Wiki current' : 'Monitor wiki',
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
            LLM Wiki v2 compiles Karpathy-style semantic pages with citations, backlinks, source notes, then lints and rebuilds the query index.
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
          <p className="setting-help">This is a single noninteractive compile path. Poor pages should fail review or eval instead of being treated as finished.</p>
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
      <Panel title="Build event stream">
        <MetricStrip
          metrics={[
            { label: 'Skill', value: piSkill || 'llm-wiki-v2' },
            { label: 'Events', value: formatCount(displayBuildEvents.length) },
            { label: 'Job', value: wikiJobRunning ? 'running' : fmt(wikiReport.job_status ?? 'idle') },
            { label: 'Mode', value: fmt(wikiReport.runtime, 'pi compile') },
          ]}
        />
        {buildText ? (
          <pre className="pi-event-text">{buildText}</pre>
        ) : (
          <p className="setting-help">
            {wikiJobRunning
              ? 'Waiting for build log events. If this stays empty, check the tmux session archive for this wiki job.'
              : 'Start a wiki build to see status updates here.'}
          </p>
        )}
        {buildStructured.length > 0 && (
          <details className="operator-details">
            <summary>Structured events (latest {buildStructured.length})</summary>
            <pre className="json">{JSON.stringify(buildStructured, null, 2)}</pre>
          </details>
        )}
        {String(wikiReport.last_error ?? '').trim() && (
          <p className="embeddings-rebuild-line alert soft">{String(wikiReport.last_error)}</p>
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
        <MetricStrip
          metrics={[
            { label: 'Runtime', value: fmt(overview.wiki?.runtime ?? 'python') },
            { label: 'State', value: fmt(overview.wiki?.job_status ?? 'ready') },
            { label: 'Sources', value: formatCount(overview.wiki?.integrated_sources) },
            { label: 'Pages', value: formatCount(overview.wiki?.pages_created) },
          ]}
        />
        <details className="operator-details">
          <summary>Build report</summary>
          <pre className="json">{JSON.stringify(wikiReport, null, 2)}</pre>
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

function formatProgressUsd(value: unknown): string {
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount <= 0) return '$0.00';
  if (amount < 0.01) return `$${amount.toFixed(4)}`;
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(amount);
}

function formatProgressDuration(value: unknown): string {
  const totalSeconds = Math.max(0, Math.round(Number(value) || 0));
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return `${minutes}m ${seconds}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
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
  const progress = ((jobPoll.data?.progress as AnyRecord | undefined) ?? (liveEmbeddings.job_state as AnyRecord | undefined)?.progress ?? {}) as AnyRecord;
  const progressStage = String(progress.stage ?? '');
  const progressPercent = Math.max(0, Math.min(100, Number(progress.percent_complete ?? 0) || 0));
  const progressTotal = Number(progress.total_changed_document_count ?? progress.changed_document_count ?? 0) || 0;
  const progressEmbedded = Number(progress.embedded_document_count ?? 0) || 0;
  const hasProgress = Boolean(progressStage || progressTotal || progress.estimated_input_tokens);
  const progressLabel = String(progress.label ?? phaseLabel ?? 'Embedding rebuild');
  const progressMeta = [
    progressTotal > 0 ? `${formatCount(progressEmbedded)} / ${formatCount(progressTotal)} chunks` : '',
    progress.estimated_seconds_remaining != null && progressStage === 'embedding_batch' ? `ETA ${formatProgressDuration(progress.estimated_seconds_remaining)}` : '',
    progress.estimated_input_tokens != null ? `${formatCount(progress.estimated_input_tokens)} est. input tokens` : '',
    progress.estimated_embedding_cost_usd != null ? `${formatProgressUsd(progress.estimated_embedding_cost_usd)} est. cost` : '',
    progress.embedding_model ? String(progress.embedding_model) : '',
  ].filter(Boolean);

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
            {hasProgress && (
              <div className="progress-line embedding-progress">
                <div className="embedding-progress-head">
                  <span>{progressLabel}</span>
                  <strong>{progressPercent.toFixed(1)}%</strong>
                </div>
                <progress max={100} value={progressPercent} aria-label="Embedding rebuild progress" />
                <div className="embedding-progress-meta">{progressMeta.join(' · ')}</div>
              </div>
            )}
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

const McpServer = memo(function McpServer() {
  const queryClientHook = useQueryClient();
  const statusPoll = useQuery({
    queryKey: ['global-mcp-status'],
    queryFn: () => api<AnyRecord>('/api/mcp/status'),
    staleTime: 5_000,
    refetchInterval: 5000,
  });
  const payload = (statusPoll.data ?? {}) as AnyRecord;
  const mcp = (payload.mcp ?? {}) as AnyRecord;
  const universities = Array.isArray(payload.universities) ? payload.universities as AnyRecord[] : [];
  const model = buildMcpModel(mcp);
  const [message, setMessage] = useState('');
  const running = Boolean(mcp.running);
  const canStart = Boolean(mcp.server_available) && !running;
  const canStop = running;

  const refreshMcp = useCallback(() => {
    void statusPoll.refetch();
    queryClientHook.invalidateQueries({ queryKey: ['global-mcp-status'] });
  }, [queryClientHook, statusPoll]);

  const callMcp = useCallback(async (action: 'start' | 'stop' | 'restart') => {
    setMessage(action === 'start' ? 'Starting…' : action === 'stop' ? 'Stopping…' : 'Restarting…');
    try {
      const response = await fetch(`/api/mcp/${action}`, { method: 'POST' });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(String(result.detail ?? response.statusText));
      const status = String(result.status ?? action);
      if (status === 'already_running') setMessage('Global MCP gateway already running');
      else if (status === 'not_running') setMessage('Global MCP gateway was not running');
      else setMessage(status === 'started' ? 'Global MCP gateway started' : status === 'stopped' ? 'Global MCP gateway stopped' : titleCase(status));
      refreshMcp();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : `${titleCase(action)} failed`);
    }
  }, [refreshMcp]);

  return (
    <section>
      <h2>MCP Gateway</h2>
      <div className="embeddings-summary mcp-summary">
        <div className="embeddings-summary-top">
          <div className="embeddings-pills">
            <span className={`status-pill ${model.serverBand.tone}`}>
              Gateway · {model.serverBand.statusLabel}
            </span>
            {mcp.session_name && <span className="status-pill neutral">{String(mcp.session_name)}</span>}
          </div>
          <p className="embeddings-headline">
            {running
              ? 'One global MCP gateway is running and can route agent queries across all ready universities.'
              : 'Start one global MCP gateway so Cursor and other agents can discover and query every ready university workspace.'}
          </p>
          {mcp.last_error && <p className="embeddings-rebuild-line alert soft">{String(mcp.last_error)}</p>}
        </div>
        <dl className="embeddings-stats">
          <div>
            <dt>Universities</dt>
            <dd>{formatCount(mcp.ready_university_count ?? payload.ready_count)} / {formatCount(mcp.university_count ?? payload.count)} ready</dd>
          </div>
          <div>
            <dt>Command</dt>
            <dd>{mcp.server_available ? 'Ready' : 'Missing'}</dd>
          </div>
          <div>
            <dt>Scope</dt>
            <dd>{fmt(mcp.scope, 'global')}</dd>
          </div>
        </dl>
        <div className="action-row embeddings-actions">
          <button type="button" className="ghost" onClick={() => void callMcp('start')} disabled={!canStart}>Start MCP</button>
          <button type="button" onClick={() => void callMcp('stop')} disabled={!canStop}>Stop MCP</button>
          <button type="button" className="ghost" onClick={() => void callMcp('restart')}>Restart</button>
          {message && <span className="inline-status">{message}</span>}
        </div>
      </div>
      <Panel title="Universities exposed to MCP">
        <DataTable
          columns={[
            ['site_id', 'Workspace'],
            ['name', 'Name'],
            ['domain', 'Domain'],
            ['wiki_ready', 'Wiki'],
            ['index_ready', 'Index'],
            ['mcp_enabled', 'MCP'],
            ['mcp_block_reason', 'Block reason'],
          ]}
          rows={universities.map((row) => ({
            ...row,
            wiki_ready: row.wiki_ready ? 'ready' : 'missing',
            index_ready: row.index_ready ? 'ready' : 'missing',
            mcp_enabled: row.mcp_enabled ? 'enabled' : 'not ready',
            mcp_block_reason: row.mcp_enabled ? '—' : String(row.mcp_block_reason || 'rebuild index'),
          }))}
        />
      </Panel>
      <details className="operator-details">
        <summary>Raw MCP gateway state</summary>
        <JsonBlock value={payload || statusPoll.error?.message || 'Loading'} />
      </details>
    </section>
  );
});

const Metrics = memo(function Metrics({ siteId }: { siteId: string }) {
  const [windowLabel, setWindowLabel] = useState('30d');
  const [selectedRunId, setSelectedRunId] = useState('');
  const runs = useQuery({
    queryKey: ['agent-metrics-runs', siteId],
    queryFn: () => api<AnyRecord>(`/api/sites/${encodeURIComponent(siteId)}/metrics/runs`),
    enabled: !!siteId,
    refetchInterval: 5000,
  });
  const rollups = useQuery({
    queryKey: ['agent-metrics-rollups', siteId],
    queryFn: () =>
      api<AnyRecord>(
        `/api/sites/${encodeURIComponent(siteId)}/metrics/rollups?windows=30d,60d,90d,365d&include_all_time=true`,
      ),
    enabled: !!siteId,
    refetchInterval: 5000,
  });
  const rows: AgentRunSummary[] = Array.isArray(runs.data?.runs) ? (runs.data.runs as AgentRunSummary[]) : [];
  const selectedRun = selectedRunId ? rows.find((run) => run.run_id === selectedRunId) : rows[0];
  const rollup = rollups.data?.rollups?.[windowLabel] ?? rollups.data?.rollups?.['30d'];
  const model = buildMetricsModel({ runs: rows, rollup });
  const selectedModel = buildMetricsModel({ runs: selectedRun ? [selectedRun] : [] });
  const trendPoints = useMemo(() => buildMetricsRunTrendPoints(rows), [rows]);
  const rollupPoints = useMemo(() => buildMetricsRollupPoints(rollups.data?.rollups ?? {}), [rollups.data]);
  const mix = useMemo(() => metricsTokenMixSegments(rollup), [rollup]);
  const metricsError =
    runs.isError || rollups.isError
      ? [runs.error, rollups.error]
          .filter((error): error is Error => error instanceof Error)
          .map((error) => error.message)
          .join(' · ')
      : '';
  const trendUsesVectors = trendPoints.some((point) => point.vectors > 0 && point.tokens === point.vectors);
  const rollupUsesVectors = rollupPoints.some((point) => point.vectors > 0 && point.tokens === point.vectors);
  return (
    <section className="metrics-workspace">
      <h2>Metrics</h2>
      <p className="metrics-scope-note">{model.scopeNote}</p>
      {metricsError && <div className="alert">Metrics feed unavailable: {metricsError}</div>}
      {(runs.isLoading || rollups.isLoading) && !metricsError && <p className="inline-status">Loading Pi agent metrics…</p>}
      <Panel title="Pi Agent Metrics Overview">
        <div className="metrics-overview-head">
          <div>
            <p className="panel-copy">
              Aggregate health, spend, and token movement across Pi runs and embedding rebuilds. Charts refresh from the metrics API
              {trendUsesVectors ? ' and fall back to embedding vector counts when token totals are unavailable' : ''}.
            </p>
          </div>
          <div className="segmented">
            {['30d', '60d', '90d', '365d', 'all_time'].map((label) => (
              <button key={label} type="button" className={windowLabel === label ? 'active' : ''} onClick={() => setWindowLabel(label)}>
                {label === '365d' ? '1 year' : label.replace('_', ' ')}
              </button>
            ))}
          </div>
        </div>
        <MetricStrip metrics={model.aggregateMetrics} />
        <div className="metrics-dashboard-grid">
          <MiniBarChart
            title={trendUsesVectors ? 'Activity trend by run (vectors when tokens missing)' : 'Token trend by run'}
            points={trendPoints}
            valueKey="tokens"
            valueLabel={trendUsesVectors ? 'vectors' : 'tokens'}
          />
          <MiniLineChart title="Cost trend by run" points={trendPoints} valueKey="cost" valueLabel="USD" />
          <TokenMixChart title={`${windowLabel.replace('_', ' ')} usage mix`} segments={mix} />
          <MiniBarChart
            title={rollupUsesVectors ? 'Window comparison (vectors when tokens missing)' : 'Window comparison'}
            points={rollupPoints}
            valueKey="tokens"
            valueLabel={rollupUsesVectors ? 'vectors' : 'activity'}
          />
        </div>
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
      <details className="operator-details metrics-technical-details">
        <summary>Run-level technical details</summary>
        <DataTable
          columns={[
            ['run_id', 'Run'],
            ['status', 'State'],
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
      </details>
    </section>
  );
});

function chartMetricValue(point: MetricsChartPoint, valueKey: keyof MetricsChartPoint): number {
  const numeric = Number(point[valueKey] ?? 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function MiniBarChart({
  title,
  points,
  valueKey,
  valueLabel,
}: {
  title: string;
  points: MetricsChartPoint[];
  valueKey: keyof MetricsChartPoint;
  valueLabel: string;
}) {
  const values = points.map((point) => chartMetricValue(point, valueKey));
  const hasValues = values.some((value) => value > 0);
  const rangeLabel = metricsChartRangeLabel(values, valueKey);
  return (
    <article className="metric-chart-card">
      <div className="metric-chart-head">
        <div className="metric-chart-title">{title}</div>
        {rangeLabel ? <div className="metric-chart-range">{rangeLabel}</div> : null}
      </div>
      {points.length && hasValues ? (
        <div className="metric-bars" role="img" aria-label={title}>
          {points.map((point, index) => {
            const value = chartMetricValue(point, valueKey);
            const height = chartBarHeightPercent(value, values);
            const formatted = formatChartMetricValue(value, valueKey);
            const tooltipLead = point.detail?.trim() || point.label;
            return (
              <div
                className="metric-bar-column"
                key={`${title}-${point.label}-${point.detail ?? ''}`}
                title={`${tooltipLead}: ${formatted} ${valueLabel}`}
              >
                <div className="metric-bar-track">
                  {height > 0 ? (
                    <div
                      className="metric-bar-fill"
                      style={{ height: `${height}%`, opacity: 0.72 + (index % 3) * 0.08 }}
                    />
                  ) : null}
                </div>
                <div className="metric-bar-foot">
                  <strong className="metric-bar-value">{formatted}</strong>
                  <small className="metric-bar-label">{point.label}</small>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <EmptyState message="No Pi agent activity recorded for this view yet." />
      )}
    </article>
  );
}

function MiniLineChart({
  title,
  points,
  valueKey,
  valueLabel,
}: {
  title: string;
  points: MetricsChartPoint[];
  valueKey: keyof MetricsChartPoint;
  valueLabel: string;
}) {
  const values = points.map((point) => chartMetricValue(point, valueKey));
  const positives = values.filter((value) => value > 0);
  const max = Math.max(...positives, 0);
  const min = positives.length ? Math.min(...positives) : 0;
  const hasValues = positives.length > 0;
  const rangeLabel = metricsChartRangeLabel(values, valueKey);
  const plotY = (value: number) => {
    if (max <= 0) return 92;
    if (max === min) return 42;
    const floor = min > 0 ? min * 0.9 : 0;
    const span = Math.max(max - floor, max * 0.08);
    return 92 - ((value - floor) / span) * 78;
  };
  const path = points
    .map((point, index) => {
      const x = points.length <= 1 ? 50 : (index / (points.length - 1)) * 100;
      const y = plotY(chartMetricValue(point, valueKey));
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(' ');
  const yTicks =
    max > 0
      ? max === min
        ? [max]
        : [max, (max + min) / 2, min].filter((tick, index, ticks) => index === 0 || tick !== ticks[index - 1])
      : [];
  return (
    <article className="metric-chart-card">
      <div className="metric-chart-head">
        <div className="metric-chart-title">{title}</div>
        {rangeLabel ? <div className="metric-chart-range">{rangeLabel}</div> : null}
      </div>
      {points.length && hasValues ? (
        <div className="metric-line-panel" role="img" aria-label={title}>
          <div className="metric-line-yaxis">
            {yTicks
              .slice()
              .reverse()
              .map((tick) => (
                <span key={`${title}-tick-${tick}`}>{formatChartMetricValue(tick, valueKey)}</span>
              ))}
          </div>
          <div className="metric-line-wrap">
            <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              {[25, 50, 75].map((gridY) => (
                <line key={gridY} className="metric-line-grid" x1="0" y1={gridY} x2="100" y2={gridY} />
              ))}
              <path className="metric-line-fill" d={`${path} L 100 100 L 0 100 Z`} />
              <path className="metric-line" d={path} />
              {points.map((point, index) => {
                const x = points.length <= 1 ? 50 : (index / (points.length - 1)) * 100;
                const y = plotY(chartMetricValue(point, valueKey));
                return <circle key={`${title}-dot-${point.label}`} className="metric-line-dot" cx={x} cy={y} r="2.4" />;
              })}
            </svg>
            <div className="metric-line-points">
              {points.map((point) => {
                const value = chartMetricValue(point, valueKey);
                return (
                  <div className="metric-line-point" key={`${title}-${point.label}`} title={`${point.detail ?? point.label}: ${formatChartMetricValue(value, valueKey)}`}>
                    <strong>{formatChartMetricValue(value, valueKey)}</strong>
                    <small>{point.label}</small>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      ) : (
        <EmptyState message="No cost data yet. Rebuild the embedding index or run Pi to record spend." />
      )}
    </article>
  );
}

function TokenMixChart({
  title,
  segments,
}: {
  title: string;
  segments: { label: string; value: number; tone: 'llm' | 'embeddings' }[];
}) {
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);
  const rangeLabel = total > 0 ? `Total ${formatCount(total)}` : '';
  return (
    <article className="metric-chart-card">
      <div className="metric-chart-head">
        <div className="metric-chart-title">{title}</div>
        {rangeLabel ? <div className="metric-chart-range">{rangeLabel}</div> : null}
      </div>
      {total > 0 ? (
        <>
          <div className="token-mix-bar">
            {segments.map((segment) => (
              <span
                key={segment.label}
                className={`token-mix-${segment.tone}`}
                style={{ width: `${Math.max((segment.value / total) * 100, segment.value > 0 ? 8 : 0)}%` }}
                title={`${segment.label}: ${formatCount(segment.value)} (${Math.round((segment.value / total) * 100)}%)`}
              />
            ))}
          </div>
          <div className="token-mix-legend">
            {segments.map((segment) => (
              <span key={segment.label} className={`token-mix-${segment.tone}`}>
                <i />
                {segment.label} · {formatCount(segment.value)} ({Math.round((segment.value / total) * 100)}%)
              </span>
            ))}
          </div>
        </>
      ) : (
        <EmptyState message="No token mix for this window yet." />
      )}
    </article>
  );
}

function usd(value: number): string {
  return `$${value.toFixed(value >= 1 ? 2 : 4)}`;
}

function OpenRouterModelSelect({
  label,
  value,
  onChange,
  options = OPENROUTER_LLM_MODELS,
  inputTokens = 100_000,
  outputTokens = 25_000,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options?: OpenRouterModelOption[];
  inputTokens?: number;
  outputTokens?: number;
}) {
  const selected = openRouterModelOption(value, options);
  const estimate = estimateOpenRouterCost(value, options, inputTokens, outputTokens);
  return (
    <label className="setting-row model-select-row">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option.id} value={option.id}>{option.label}</option>
        ))}
      </select>
      <span className="model-cost-line">
        {selected.id} · {usd(selected.inputPerMTok)}/1M input{selected.outputPerMTok ? ` · ${usd(selected.outputPerMTok)}/1M output` : ''} · estimate {usd(estimate)}
      </span>
    </label>
  );
}

const Settings = memo(function Settings({ appState }: { appState?: AnyRecord }) {
  const state = appState?.state ?? {};
  const queryClientHook = useQueryClient();
  const [saveMessage, setSaveMessage] = useState('');
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState(() => settingsDraftFromState(state));

  useEffect(() => {
    setDraft(settingsDraftFromState(state));
  }, [appState]);

  const saveSettings = useCallback(async () => {
    setSaving(true);
    setSaveMessage('');
    try {
      const payload = settingsSavePayloadFromDraft(draft, state);
      await apiJson<AnyRecord>('/api/app-state', 'PUT', { payload });
      await queryClientHook.invalidateQueries({ queryKey: ['app-state'] });
      setSaveMessage('Settings saved.');
    } catch (error) {
      setSaveMessage(error instanceof Error ? error.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  }, [draft, queryClientHook]);

  return (
    <section>
      <h2>Settings</h2>
      <p>Configure OpenRouter models, scraping, retrieval, research, and wiki/tmux lifecycle.</p>
      <MetricStrip
        metrics={[
          { label: 'OpenRouter', value: state.openrouter_api_key ? 'set' : 'missing' },
          { label: 'Scraper', value: fmt(state.scrape_browser_mode, 'none') },
          { label: 'Wiki build', value: 'LLM Wiki compile' },
          { label: 'Tmux grace', value: `${formatCount(Math.round((state.tmux_session_grace_seconds ?? 1800) / 60))} min` },
        ]}
      />
      <div className="settings-grid">
        <Panel title="Keys">
          <label className="setting-row">
            <span>OpenRouter key</span>
            <input
              type="password"
              autoComplete="off"
              placeholder={draft.openrouter_api_key === SECRET_UNCHANGED ? 'Saved key present — enter a new key to replace' : 'Paste OpenRouter key'}
              value={draft.openrouter_api_key === SECRET_UNCHANGED ? '' : draft.openrouter_api_key}
              onChange={(event) => setDraft((current) => ({ ...current, openrouter_api_key: event.target.value }))}
            />
          </label>
          <label className="setting-row">
            <span>Tavily key</span>
            <input
              type="password"
              autoComplete="off"
              placeholder={draft.tavily_api_key === SECRET_UNCHANGED ? 'Saved key present — enter a new key to replace' : 'Paste Tavily key'}
              value={draft.tavily_api_key === SECRET_UNCHANGED ? '' : draft.tavily_api_key}
              onChange={(event) => setDraft((current) => ({ ...current, tavily_api_key: event.target.value }))}
            />
          </label>
        </Panel>
        <Panel title="URL model / cost">
          <OpenRouterModelSelect
            label="URL reasoning"
            value={draft.url_reasoning_openrouter_model}
            onChange={(value) => setDraft((current) => ({ ...current, url_reasoning_openrouter_model: value }))}
          />
          <p className="setting-help">Estimates use 100k input + 25k output tokens per run. Actual costs are recorded in Metrics.</p>
        </Panel>
        <Panel title="Scraping">
          <label className="setting-row">
            <span>Scrape concurrency</span>
            <input
              type="number"
              min={1}
              max={16}
              step={1}
              value={draft.scrape_concurrency}
              onChange={(event) => setDraft((current) => ({ ...current, scrape_concurrency: Number(event.target.value) }))}
            />
          </label>
          <label className="setting-row">
            <span>Browser fallback</span>
            <select
              value={draft.scrape_browser_mode}
              onChange={(event) => setDraft((current) => ({ ...current, scrape_browser_mode: event.target.value }))}
            >
              <option value="none">None</option>
              <option value="lightpanda">Lightpanda</option>
            </select>
          </label>
          <label className="setting-row">
            <span>Lightpanda CDP URL</span>
            <input
              value={draft.lightpanda_cdp_url}
              onChange={(event) => setDraft((current) => ({ ...current, lightpanda_cdp_url: event.target.value }))}
            />
          </label>
        </Panel>
        <Panel title="Indexing">
          <label className="setting-row setting-row-inline">
            <span>Embeddings enabled</span>
            <input
              type="checkbox"
              checked={draft.embedding_enabled}
              onChange={(event) => setDraft((current) => ({ ...current, embedding_enabled: event.target.checked }))}
            />
          </label>
          <OpenRouterModelSelect
            label="Embedding model"
            value={draft.embedding_model}
            options={OPENROUTER_EMBEDDING_MODELS}
            inputTokens={1_000_000}
            outputTokens={0}
            onChange={(value) => setDraft((current) => ({ ...current, embedding_model: value }))}
          />
          <label className="setting-row">
            <span>Zvec collection</span>
            <input
              value={draft.zvec_collection}
              onChange={(event) => setDraft((current) => ({ ...current, zvec_collection: event.target.value }))}
            />
          </label>
        </Panel>
        <Panel title="Research">
          <label className="setting-row setting-row-inline">
            <span>Use Tavily for university map</span>
            <input
              type="checkbox"
              checked={draft.use_tavily_for_map}
              onChange={(event) => setDraft((current) => ({ ...current, use_tavily_for_map: event.target.checked }))}
            />
          </label>
        </Panel>
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
          <p className="setting-help">Finished wiki tmux sessions stay open this long for log review, then auto-close. Wiki builds always run the LLM Wiki compile path (Pi).</p>
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

function DataTable({
  columns,
  rows,
  onRowClick,
  isRowSelected,
}: {
  columns: [string, string][];
  rows: AnyRecord[];
  onRowClick?: (row: AnyRecord) => void;
  isRowSelected?: (row: AnyRecord) => boolean;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{columns.map(([, label]) => <th key={label}>{label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, 250).map((row, idx) => {
            const selected = Boolean(isRowSelected?.(row));
            const className = [onRowClick ? 'table-row-clickable' : '', selected ? 'table-row-selected' : ''].filter(Boolean).join(' ') || undefined;
            return (
              <tr
                key={row.source_id ?? row.run_id ?? row.path ?? idx}
                className={className}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {columns.map(([key]) => <td key={key}>{fmt(row[key])}</td>)}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function normalizeMarkdownContent(content: string): string {
  let text = content;
  const trimmed = text.trimStart();
  if (trimmed.startsWith('---\n')) {
    const frontmatterEnd = trimmed.indexOf('\n---', 4);
    if (frontmatterEnd >= 0) {
      text = trimmed.slice(frontmatterEnd + 4).trimStart();
    }
  }
  if (!text.includes('\n') && text.includes('\\n')) {
    text = text.replace(/\\r\\n/g, '\n').replace(/\\n/g, '\n');
  }
  return text;
}

function MarkdownPreview({ content, label, loading, error }: { content?: string; label?: string; loading?: boolean; error?: string }) {
  const renderedContent = useMemo(() => normalizeMarkdownContent(content ?? ''), [content]);
  if (loading) return <div className="empty">Loading selected source…</div>;
  if (error) return <div className="alert">{error}</div>;
  if (!renderedContent) return <div className="empty">Choose a source to preview rendered Markdown.</div>;
  return (
    <article className="markdown-preview">
      {label && <div className="preview-label">{label}</div>}
      <div className="markdown-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{renderedContent}</ReactMarkdown>
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

const rootElement = document.getElementById('root')! as HTMLElement & {
  __uopsReactRoot__?: ReturnType<typeof ReactDOM.createRoot>;
};
const reactRoot = rootElement.__uopsReactRoot__ ?? ReactDOM.createRoot(rootElement);
rootElement.__uopsReactRoot__ = reactRoot;
reactRoot.render(
  <QueryClientProvider client={queryClient}>
    <App />
  </QueryClientProvider>,
);
