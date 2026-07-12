import React, { useCallback, useEffect, useRef, useState } from 'react';
import { CircleAlert, Layers, Sigma, Sparkles, X } from 'lucide-react';
import { fmt2 } from './lib/utils';
import { Backdrop } from './components/Backdrop';
import { Header } from './components/Header';
import { StatCard, SectionHeading } from './components/atoms';
import { Leaderboard } from './components/Leaderboard';
import { CorrelationCard } from './components/CorrelationCard';
import { ProjectionCard } from './components/ProjectionCard';
import { Library } from './components/Library';
import { Pipeline } from './components/Pipeline';

const getJSON = (url) => fetch(url).then((r) => r.json());

export default function App() {
  const [tab, setTab] = useState('overview');
  const [theme, setTheme] = useState(() =>
    document.documentElement.classList.contains('dark') ? 'dark' : 'light',
  );

  // ── data ──
  const [alphas, setAlphas] = useState([]);
  const [allAlphas, setAllAlphas] = useState([]);
  const [correlation, setCorrelation] = useState(null);
  const [portfolio, setPortfolio] = useState(null);
  const [loading, setLoading] = useState(true);

  // ── pipeline ──
  const [pipelineState, setPipelineState] = useState(null);
  const [logs, setLogs] = useState('');
  const [running, setRunning] = useState(false);
  const [statusMsg, setStatusMsg] = useState('Connecting…');
  const [errorMsg, setErrorMsg] = useState('');
  const wasRunning = useRef(false);

  const loadData = useCallback(() => {
    getJSON('/api/alphas').then(setAlphas).catch(() => {});
    getJSON('/api/all_alphas')
      .then((d) => {
        setAllAlphas(Array.isArray(d) ? d : []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
    getJSON('/api/correlation').then(setCorrelation).catch(() => {});
    getJSON('/api/portfolio').then(setPortfolio).catch(() => {});
  }, []);

  const checkStatus = useCallback(() => {
    getJSON('/api/pipeline_state')
      .then((d) => {
        setPipelineState(d);
        setRunning(!!d.running);
        setStatusMsg(
          d.running
            ? d.current_domain
              ? `Running · ${d.current_domain}`
              : 'Running · initializing'
            : d.error
              ? 'Stopped with error'
              : 'Idle',
        );
        // refresh result data when a run finishes
        if (wasRunning.current && !d.running) loadData();
        wasRunning.current = !!d.running;
      })
      .catch(() => setStatusMsg('Backend unreachable'));
  }, [loadData]);

  // status polling: 2s while running, 10s idle
  useEffect(() => {
    loadData();
    let timer;
    const tick = () => {
      checkStatus();
      timer = setTimeout(tick, wasRunning.current ? 2000 : 10000);
    };
    tick();
    return () => clearTimeout(timer);
  }, [checkStatus, loadData]);

  // log polling only while the pipeline tab is visible or a run is live
  useEffect(() => {
    if (tab !== 'pipeline' && !running) return undefined;
    const fetchLogs = () =>
      getJSON('/api/pipeline_logs')
        .then((d) => setLogs(d.logs || ''))
        .catch(() => {});
    fetchLogs();
    const id = setInterval(fetchLogs, running ? 1500 : 8000);
    return () => clearInterval(id);
  }, [tab, running]);

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    document.documentElement.classList.toggle('dark', next === 'dark');
    localStorage.setItem('theme', next);
  };

  const handleTrigger = () => {
    setErrorMsg('');
    if (running) {
      fetch('/api/stop_pipeline', { method: 'POST' })
        .then((r) => r.json())
        .then((d) => setStatusMsg(d.message || 'Stopping…'))
        .catch((e) => setErrorMsg(`Stop failed: ${e.message}`));
    } else {
      setStatusMsg('Starting…');
      setTab('pipeline');
      fetch('/api/trigger_pipeline', { method: 'POST' })
        .then(async (r) => {
          const d = await r.json().catch(() => ({}));
          if (!r.ok || d.status === 'error') {
            setErrorMsg(d.message || `Trigger failed (HTTP ${r.status})`);
            setStatusMsg('Idle');
          } else {
            setRunning(true);
            wasRunning.current = true;
          }
        })
        .catch((e) => setErrorMsg(`Backend unreachable: ${e.message}`));
    }
  };

  const submittableCount = allAlphas.filter((a) => a.grade === 'submittable').length;
  const simulated = allAlphas.filter((a) => a.sharpe != null);
  const avgSharpe = simulated.length
    ? simulated.reduce((s, a) => s + (a.sharpe || 0), 0) / simulated.length
    : null;
  const bestFitness = simulated.length ? Math.max(...simulated.map((a) => a.fitness || 0)) : null;

  return (
    <div className="min-h-screen">
      <Backdrop />
      <Header
        tab={tab}
        setTab={setTab}
        running={running}
        statusMsg={statusMsg}
        onTrigger={handleTrigger}
        onOpenPipeline={() => setTab('pipeline')}
        theme={theme}
        onToggleTheme={toggleTheme}
      />

      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6 sm:py-8">
        {errorMsg && (
          <div
            role="alert"
            className="flex items-start justify-between gap-3 rounded-lg border border-status-crit/30 bg-status-crit/8 px-4 py-3"
          >
            <p className="flex items-start gap-2 text-[13px] text-status-crit">
              <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />
              {errorMsg}
            </p>
            <button
              onClick={() => setErrorMsg('')}
              aria-label="Dismiss error"
              className="text-status-crit/70 hover:text-status-crit"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {tab === 'overview' && (
          <>
            <SectionHeading
              title="Overview"
              description="Measured results across the discovered alpha pool."
            />
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <StatCard
                label="Alphas in library"
                value={allAlphas.length}
                hint={`${simulated.length} simulated on BRAIN`}
                loading={loading}
                icon={Layers}
              />
              <StatCard
                label="Submittable"
                value={submittableCount}
                hint="Passed all platform checks"
                loading={loading}
                icon={Sparkles}
              />
              <StatCard
                label="Avg Sharpe"
                value={fmt2(avgSharpe)}
                hint="Across simulated alphas"
                loading={loading}
                icon={Sigma}
              />
              <StatCard
                label="Best fitness"
                value={fmt2(bestFitness)}
                hint="Threshold for submission: 1.1"
                loading={loading}
                icon={Sigma}
              />
            </div>

            <Leaderboard alphas={alphas} loading={loading} onSelect={() => setTab('library')} />

            <div className="grid gap-4 lg:grid-cols-2">
              <CorrelationCard correlation={correlation} />
              <ProjectionCard portfolio={portfolio} />
            </div>
          </>
        )}

        {tab === 'library' && (
          <>
            <SectionHeading
              title="Alpha library"
              description="Every discovered expression with its measured metrics and settings."
            />
            <Library alphas={allAlphas} loading={loading} />
          </>
        )}

        {tab === 'pipeline' && (
          <>
            <SectionHeading
              title="Pipeline monitor"
              description="arXiv research → actor-critic generation → ML screening → BRAIN simulation."
            />
            <Pipeline state={pipelineState} logs={logs} running={running} />
          </>
        )}
      </main>

      <footer className="border-t">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-4 text-[11px] text-subtle sm:px-6">
          <span>Gen-Alpha · autonomous quantitative research</span>
          <span>
            Metrics are measured in-sample on WorldQuant BRAIN · nothing is auto-submitted
          </span>
        </div>
      </footer>
    </div>
  );
}
