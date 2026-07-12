import React, { useMemo, useState } from 'react';
import { ChevronDown, Library as LibraryIcon, Search } from 'lucide-react';
import { cn, fmt2, fmtPct } from '../lib/utils';
import { Card } from './ui/card';
import { Input } from './ui/input';
import { Tabs, TabsList, TabsTrigger } from './ui/tabs';
import { EmptyState, Skeleton } from './ui/skeleton';
import { GradeBadge, SourceBadge } from './atoms';

function Metric({ label, value, tone }) {
  return (
    <div className="min-w-16 text-right">
      <p className="text-[10px] font-medium text-subtle">{label}</p>
      <p className={cn('tnum text-[13px] font-medium', tone)}>{value}</p>
    </div>
  );
}

function SettingItem({ label, value }) {
  return (
    <div>
      <p className="text-[10px] font-medium text-subtle">{label}</p>
      <p className="tnum mt-0.5 font-mono text-xs">{String(value)}</p>
    </div>
  );
}

function AlphaRow({ alpha, expanded, onToggle }) {
  const s = alpha.settings || {};
  return (
    <div className="border-b last:border-0">
      <button
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full items-center gap-4 px-5 py-3 text-left transition-colors hover:bg-accent"
      >
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex items-center gap-2">
            <span className="font-mono text-xs font-medium">{alpha.alpha_id}</span>
            <SourceBadge source={alpha.source} paperTitle={alpha.paper_title} />
            <GradeBadge grade={alpha.grade} failedChecks={alpha.failed_checks} />
          </div>
          <p className="truncate font-mono text-[11px] text-muted-foreground">{alpha.expression}</p>
        </div>
        <div className="hidden items-center gap-5 sm:flex">
          <Metric
            label="Sharpe"
            value={fmt2(alpha.sharpe)}
            tone={
              alpha.sharpe >= 1.3
                ? 'text-status-good-ink'
                : alpha.sharpe < 0
                  ? 'text-status-crit'
                  : undefined
            }
          />
          <Metric label="Fitness" value={fmt2(alpha.fitness)} />
          <Metric label="Turnover" value={fmtPct(alpha.turnover)} />
        </div>
        <ChevronDown
          className={cn('h-4 w-4 shrink-0 text-subtle transition-transform', expanded && 'rotate-180')}
        />
      </button>

      {expanded && (
        <div className="space-y-4 border-t bg-background/60 px-5 py-4">
          <div>
            <p className="mb-1 text-[10px] font-medium text-subtle">Expression</p>
            <pre className="overflow-x-auto whitespace-pre-wrap rounded-md border bg-card p-3 font-mono text-xs leading-relaxed">
              {alpha.expression}
            </pre>
          </div>

          {(alpha.anomaly || alpha.rationale) && (
            <div className="rounded-md border-l-2 border-l-chart-1 bg-card py-2 pl-3 pr-3">
              {alpha.anomaly && <p className="text-xs text-foreground">{alpha.anomaly}</p>}
              {alpha.rationale && (
                <p className="mt-1 text-xs text-muted-foreground">{alpha.rationale}</p>
              )}
              {alpha.paper_title && (
                <p className="mt-1 text-[11px] italic text-subtle">— {alpha.paper_title}</p>
              )}
            </div>
          )}

          <div className="grid grid-cols-3 gap-x-6 gap-y-3 sm:grid-cols-6">
            <SettingItem label="Universe" value={s.universe ?? 'TOP3000'} />
            <SettingItem label="Neutralization" value={s.neutralization ?? '—'} />
            <SettingItem label="Decay" value={s.decay ?? '—'} />
            <SettingItem label="Truncation" value={s.truncation ?? '—'} />
            <SettingItem label="Delay" value={s.delay ?? 1} />
            <SettingItem label="Drawdown" value={fmtPct(alpha.drawdown)} />
          </div>

          {alpha.failed_checks?.length > 0 && (
            <p className="text-xs text-status-crit">
              Failed platform checks: {alpha.failed_checks.join(', ')}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function Library({ alphas, loading }) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [expanded, setExpanded] = useState(null);

  const filtered = useMemo(() => {
    let list = alphas;
    if (filter === 'submittable') list = list.filter((a) => a.grade === 'submittable');
    if (filter === 'arxiv') list = list.filter((a) => a.source === 'arxiv');
    if (filter === 'template') list = list.filter((a) => a.source !== 'arxiv');
    const q = query.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (a) =>
          a.expression?.toLowerCase().includes(q) ||
          a.alpha_id?.toLowerCase().includes(q) ||
          a.paper_title?.toLowerCase().includes(q),
      );
    }
    return list;
  }, [alphas, query, filter]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-subtle" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search expressions, ids, papers…"
            className="pl-8"
            aria-label="Search alphas"
          />
        </div>
        <Tabs value={filter} onValueChange={setFilter}>
          <TabsList>
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="submittable">Submittable</TabsTrigger>
            <TabsTrigger value="arxiv">arXiv</TabsTrigger>
            <TabsTrigger value="template">Template</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      <Card>
        {loading ? (
          <div className="space-y-2 p-5">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={LibraryIcon}
            title={query || filter !== 'all' ? 'Nothing matches' : 'Library is empty'}
            description={
              query || filter !== 'all'
                ? 'Try a different search or filter.'
                : 'Discovered alphas appear here after the pipeline runs.'
            }
          />
        ) : (
          filtered.map((a, i) => (
            <AlphaRow
              key={`${a.alpha_id ?? 'a'}-${i}`}
              alpha={a}
              expanded={expanded === i}
              onToggle={() => setExpanded(expanded === i ? null : i)}
            />
          ))
        )}
      </Card>

      {!loading && filtered.length > 0 && (
        <p className="text-xs text-subtle">
          {filtered.length} of {alphas.length} alphas
        </p>
      )}
    </div>
  );
}
