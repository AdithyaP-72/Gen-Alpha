import React, { useEffect, useRef, useState } from 'react';
import {
  Activity, BookOpen, Check, CircleAlert, FileText, FlaskConical, Microscope, ScanSearch,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from './ui/card';
import { Badge } from './ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from './ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';
import { EmptyState } from './ui/skeleton';

const PHASES = [
  { id: 'researching', label: 'Research', icon: BookOpen },
  { id: 'screening', label: 'ML Screen', icon: ScanSearch },
  { id: 'simulating', label: 'Simulate', icon: FlaskConical },
];

function PhaseStepper({ phase, running }) {
  const activeIdx = PHASES.findIndex((p) => p.id === phase);
  return (
    <ol className="flex items-center gap-2" aria-label="Pipeline phase">
      {PHASES.map((p, i) => {
        const isActive = running && i === activeIdx;
        const isDone = running && activeIdx > -1 && i < activeIdx;
        return (
          <React.Fragment key={p.id}>
            {i > 0 && <span className="h-px w-6 bg-border-strong sm:w-10" aria-hidden />}
            <li
              className={cn(
                'flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium',
                isActive
                  ? 'border-transparent bg-primary text-primary-foreground'
                  : isDone
                    ? 'text-secondary-ink'
                    : 'text-subtle',
              )}
            >
              {isDone ? <Check className="h-3 w-3" /> : <p.icon className="h-3 w-3" />}
              {p.label}
            </li>
          </React.Fragment>
        );
      })}
    </ol>
  );
}

function RunStat({ label, value, emphasis }) {
  return (
    <div className="flex flex-col gap-0.5 border-l pl-4 first:border-0 first:pl-0">
      <span className="text-[10px] font-medium text-subtle">{label}</span>
      <span className={cn('tnum text-lg font-semibold leading-6', emphasis && 'text-status-good-ink')}>
        {value}
      </span>
    </div>
  );
}

const LOG_TONE = [
  { test: /(FATAL|\[ERROR\]|Exception|Traceback|Simulation failed|✗)/, cls: 'text-status-crit' },
  { test: /(REJECT)/, cls: 'text-status-warn' },
  { test: /(★|PASSED|Submittable|ACCEPT|✓|successful)/, cls: 'text-status-good-ink' },
  { test: /(\[ML Predictor\]|\[chain\]|EPSILON)/, cls: 'text-chart-1-strong' },
  { test: /(═|━|─)/, cls: 'text-subtle' },
];

function LogConsole({ logs }) {
  const ref = useRef(null);
  const [pinned, setPinned] = useState(true);

  useEffect(() => {
    if (pinned && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [logs, pinned]);

  const onScroll = () => {
    const el = ref.current;
    if (!el) return;
    setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
  };

  const lines = (logs || '').split('\n');
  return (
    <div
      ref={ref}
      onScroll={onScroll}
      className="console-scroll h-96 overflow-y-auto rounded-lg border bg-background p-4 font-mono text-[11.5px] leading-[1.7]"
      aria-label="Pipeline log"
    >
      {logs ? (
        lines.map((line, i) => {
          const tone = LOG_TONE.find((t) => t.test.test(line));
          return (
            <div key={i} className={cn('whitespace-pre-wrap text-secondary-ink', tone?.cls)}>
              {line || ' '}
            </div>
          );
        })
      ) : (
        <span className="text-subtle">Waiting for pipeline output…</span>
      )}
    </div>
  );
}

export function Pipeline({ state, logs, running }) {
  const [tab, setTab] = useState('log');
  const s = state || {};

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-4 py-4">
          <PhaseStepper phase={s.phase} running={running} />
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Activity className={cn('h-3.5 w-3.5', running ? 'text-status-good' : 'text-subtle')} />
            {running
              ? `Cycle ${s.cycle_count || 1} · ${s.current_domain || 'initializing'}`
              : s.error
                ? 'Stopped with an error'
                : 'Idle — start a run from the header'}
          </div>
        </CardContent>
        <CardContent className="grid grid-cols-2 gap-y-4 border-t py-4 sm:grid-cols-5">
          <RunStat label="Papers read" value={s.papers_processed ?? 0} />
          <RunStat label="Generated" value={s.alphas_generated ?? 0} />
          <RunStat label="ML accepted" value={s.alphas_accepted ?? 0} />
          <RunStat label="Simulated" value={s.alphas_simulated ?? 0} />
          <RunStat label="Submittable" value={s.alphas_passed ?? s.alphas_submitted ?? 0} emphasis />
        </CardContent>
        {s.error && (
          <CardContent className="border-t py-3">
            <p className="flex items-start gap-2 text-xs text-status-crit">
              <CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {s.error}
            </p>
          </CardContent>
        )}
      </Card>

      {s.current_expression && (
        <Card className="border-l-2 border-l-chart-1">
          <CardContent className="py-3">
            <p className="text-[10px] font-medium text-subtle">Currently simulating</p>
            <p className="mt-1 truncate font-mono text-xs">{s.current_expression}</p>
          </CardContent>
        </Card>
      )}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="log">
            <FileText /> Live log
          </TabsTrigger>
          <TabsTrigger value="papers">
            <BookOpen /> Papers ({s.papers?.length || 0})
          </TabsTrigger>
          <TabsTrigger value="screening">
            <Microscope /> ML screening ({s.ml_results?.length || 0})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="log" className="mt-3">
          <LogConsole logs={logs} />
        </TabsContent>

        <TabsContent value="papers" className="mt-3">
          {s.papers?.length ? (
            <div className="grid gap-3 lg:grid-cols-2">
              {[...s.papers].reverse().map((p, i) => (
                <Card key={i}>
                  <CardContent className="py-4">
                    <div className="mb-2 flex items-start justify-between gap-3">
                      <p className="text-[13px] font-medium leading-snug">{p.title}</p>
                      <Badge variant="info" className="shrink-0">
                        {p.domain}
                      </Badge>
                    </div>
                    <p className="mb-2 text-[11px] text-subtle">
                      {p.expressions_valid}/{p.expressions_generated} expressions passed
                      validation + review
                    </p>
                    {p.anomalies?.length > 0 && (
                      <ul className="space-y-1 border-l-2 border-l-grid pl-3">
                        {p.anomalies.map((a, j) => (
                          <li key={j} className="text-xs text-muted-foreground">
                            {a}
                          </li>
                        ))}
                      </ul>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <Card>
              <EmptyState
                icon={BookOpen}
                title="No papers processed in this run"
                description="Fetched arXiv papers and their extracted anomalies appear here."
              />
            </Card>
          )}
        </TabsContent>

        <TabsContent value="screening" className="mt-3">
          <Card>
            {s.ml_results?.length ? (
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Expression</TableHead>
                    <TableHead className="w-32 text-right">Success prob.</TableHead>
                    <TableHead className="w-28">Verdict</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {[...s.ml_results].reverse().map((r, i) => (
                    <TableRow key={i}>
                      <TableCell className="max-w-0">
                        <p className={cn('truncate font-mono text-xs', !r.accepted && 'text-subtle')}>
                          {r.expression}
                        </p>
                      </TableCell>
                      <TableCell className="tnum text-right text-secondary-ink">
                        {r.note === 'epsilon_explore' ? '—' : `${(r.success_prob ?? 0).toFixed(1)}%`}
                      </TableCell>
                      <TableCell>
                        {r.accepted ? (
                          <Badge variant={r.note === 'epsilon_explore' ? 'info' : 'success'}>
                            <Check />
                            {r.note === 'epsilon_explore' ? 'Explore' : 'Accept'}
                          </Badge>
                        ) : (
                          <Badge variant="danger">
                            <CircleAlert /> Reject
                          </Badge>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <EmptyState
                icon={Microscope}
                title="No screening results yet"
                description="Each generated expression is scored by the Gradient-Boosting gate before simulation; 5% bypass it for unbiased exploration."
              />
            )}
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
