import React from 'react';
import { Trophy } from 'lucide-react';
import { cn, fmt2, fmtPct } from '../lib/utils';
import { Card, CardHeader, CardTitle, CardDescription } from './ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';
import { Skeleton, EmptyState } from './ui/skeleton';
import { FitnessMeter, GradeBadge, SourceBadge } from './atoms';

const sharpeTone = (s) => {
  if (s == null) return 'text-muted-foreground';
  if (s >= 1.3) return 'text-status-good-ink';
  if (s < 0) return 'text-status-crit';
  return 'text-foreground';
};

export function Leaderboard({ alphas, loading, onSelect }) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div className="space-y-1">
          <CardTitle>Leaderboard</CardTitle>
          <CardDescription>
            Top simulated alphas by in-sample Sharpe. Tick on the meter marks the 1.1 submittable
            threshold.
          </CardDescription>
        </div>
        <Trophy className="h-4 w-4 text-subtle" />
      </CardHeader>

      {loading ? (
        <div className="space-y-2 p-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : alphas.length === 0 ? (
        <EmptyState
          icon={Trophy}
          title="No simulated alphas yet"
          description="Run the pipeline to start populating the leaderboard with measured results."
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-10">#</TableHead>
              <TableHead>Alpha</TableHead>
              <TableHead>Source</TableHead>
              <TableHead className="w-44">Fitness</TableHead>
              <TableHead className="text-right">Sharpe</TableHead>
              <TableHead className="text-right">Turnover</TableHead>
              <TableHead className="text-right">Returns</TableHead>
              <TableHead>Grade</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {alphas.map((a, i) => (
              <TableRow
                key={`${a.alpha_id ?? 'a'}-${i}`}
                className="cursor-pointer"
                onClick={() => onSelect?.(a)}
              >
                <TableCell className="tnum text-subtle">{i + 1}</TableCell>
                <TableCell>
                  <div className="flex flex-col">
                    <span className="font-mono text-xs font-medium">{a.alpha_id}</span>
                    <span className="max-w-72 truncate font-mono text-[11px] text-subtle">
                      {a.expression}
                    </span>
                  </div>
                </TableCell>
                <TableCell>
                  <SourceBadge source={a.source} paperTitle={a.paper_title} />
                </TableCell>
                <TableCell>
                  <FitnessMeter value={a.fitness} />
                </TableCell>
                <TableCell className={cn('tnum text-right font-medium', sharpeTone(a.sharpe))}>
                  {fmt2(a.sharpe)}
                </TableCell>
                <TableCell className="tnum text-right text-secondary-ink">
                  {fmtPct(a.turnover)}
                </TableCell>
                <TableCell className="tnum text-right text-secondary-ink">
                  {fmtPct(a.returns)}
                </TableCell>
                <TableCell>
                  <GradeBadge grade={a.grade} failedChecks={a.failed_checks} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}
