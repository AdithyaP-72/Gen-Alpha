import React from 'react';
import { ArrowDownRight, ArrowUpRight, BadgeCheck, CircleAlert, CircleDashed } from 'lucide-react';
import { cn, fmt2 } from '../lib/utils';
import { Badge } from './ui/badge';
import { Card } from './ui/card';
import { Skeleton } from './ui/skeleton';

/** Sequential single-hue meter (thin mark, rounded data end, hairline track). */
export function FitnessMeter({ value, max = 2 }) {
  const v = value ?? 0;
  const pct = Math.max(0, Math.min((v / max) * 100, 100));
  return (
    <div className="flex w-full min-w-24 items-center gap-2" title={`Fitness ${fmt2(value)} (scale 0–${max})`}>
      <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-grid">
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-chart-1"
          style={{ width: `${pct}%` }}
        />
        {/* submittable threshold tick at 1.1 */}
        <div
          className="absolute inset-y-0 w-px bg-axis"
          style={{ left: `${(1.1 / max) * 100}%` }}
        />
      </div>
      <span className="tnum w-9 text-right text-xs text-secondary-ink">{fmt2(value)}</span>
    </div>
  );
}

/** Grade — status color never travels alone: icon + label. */
export function GradeBadge({ grade, failedChecks }) {
  if (grade === 'submittable') {
    return (
      <Badge variant="success">
        <BadgeCheck /> Submittable
      </Badge>
    );
  }
  if (grade === 'marginal') {
    return (
      <Badge variant="warning">
        <CircleAlert /> Marginal
      </Badge>
    );
  }
  if (failedChecks?.length) {
    return (
      <Badge variant="danger" title={failedChecks.join(', ')}>
        <CircleAlert /> {failedChecks.length} check{failedChecks.length > 1 ? 's' : ''}
      </Badge>
    );
  }
  // Found before checks-gating existed — metrics are measured, checks weren't recorded.
  return (
    <Badge variant="outline" title="Discovered before platform-check gating; verify checks before submitting.">
      <CircleDashed /> Legacy
    </Badge>
  );
}

export function SourceBadge({ source, paperTitle }) {
  const isArxiv = source === 'arxiv';
  return (
    <Badge variant={isArxiv ? 'info' : 'default'} title={paperTitle || undefined}>
      {isArxiv ? 'arXiv' : 'Template'}
    </Badge>
  );
}

/** KPI stat tile — hero number, quiet label, optional delta. */
export function StatCard({ label, value, hint, delta, loading, icon: Icon }) {
  return (
    <Card className="px-5 py-4">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium text-subtle">{label}</span>
        {Icon && <Icon className="h-3.5 w-3.5 text-subtle" />}
      </div>
      {loading ? (
        <Skeleton className="mt-2 h-8 w-20" />
      ) : (
        <div className="mt-1.5 flex items-baseline gap-2">
          <span className="text-[26px] font-semibold leading-8 tracking-[-0.02em]">{value}</span>
          {delta != null && (
            <span
              className={cn(
                'flex items-center gap-0.5 text-xs font-medium',
                delta >= 0 ? 'text-status-good-ink' : 'text-status-crit',
              )}
            >
              {delta >= 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
              {Math.abs(delta).toFixed(1)}%
            </span>
          )}
        </div>
      )}
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </Card>
  );
}

/** Section heading with optional trailing slot. */
export function SectionHeading({ title, description, children }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 className="font-display text-[19px] font-bold tracking-[-0.01em]">{title}</h2>
        {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
      </div>
      {children}
    </div>
  );
}
