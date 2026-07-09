import React, { useState, useEffect } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip as RechartsTip, ResponsiveContainer
} from 'recharts';

// ────────────────────────────────────────────────────────────
// CONFIG
// ────────────────────────────────────────────────────────────
const DOMAINS = [
  { id: 'momentum', label: 'Cross-Sectional Momentum', query: 'cat:q-fin.TR AND (momentum OR ranking)' },
  { id: 'arbitrage', label: 'Statistical Arbitrage & Pairs', query: 'all:(pairs trading OR statistical arbitrage cointegration)' },
  { id: 'event', label: 'Event-Driven & AI Sentiment', query: 'all:(news sentiment AI OR event-driven anomaly)' },
  { id: 'volatility', label: 'Options-Implied Volatility Skew', query: 'all:(implied volatility skew OR options-implied information)' },
  { id: 'ml', label: 'Deep Learning & Non-linear', query: 'all:(neural networks stock prediction OR reinforcement learning trading)' },
];

const API = 'http://localhost:5000';

// ────────────────────────────────────────────────────────────
// SVG ICONS  (avoid any broken lucide-react exports)
// ────────────────────────────────────────────────────────────
const GithubIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5a5.4 5.4 0 0 0-1-3.5 5.4 5.4 0 0 0 0-3.5s-1 0-3 1.5a13.4 13.4 0 0 0-7 0C6 2 5 2 5 2a5.4 5.4 0 0 0 0 3.5A5.4 5.4 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.4.5-.7 1-.85 1.65-.17.6-.22 1.23-.15 1.85v4" />
    <path d="M9 18c-4.51 2-5-2-7-2" />
  </svg>
);
const ChevronDown = ({ open }) => (
  <svg className={`chevron ${open ? 'open' : ''}`} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="6 9 12 15 18 9" />
  </svg>
);
const PlayIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3" /></svg>
);
const BrainIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96-.46 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2Z" />
    <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96-.46 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2Z" />
  </svg>
);

// ────────────────────────────────────────────────────────────
// HELPERS
// ────────────────────────────────────────────────────────────
const fmt2 = v => (v != null ? Number(v).toFixed(2) : '–');
const fmtPct = v => (v != null ? (Number(v) * 100).toFixed(1) + '%' : '–');

const sharpeClass = s => {
  if (!s) return '';
  if (s >= 1.5) return 'val-good';
  if (s >= 0.8) return 'val-ok';
  return 'val-bad';
};

function DomBar({ value, max = 10 }) {
  const pct = Math.min(Math.round((value / max) * 100), 100);
  const isGood = pct >= 50;
  return (
    <div className="dom-wrap">
      <span className={`dom-pct ${isGood ? 'val-good' : ''}`}>{pct}%</span>
      <div className="dom-bar-bg">
        <div className={`dom-bar-fill ${isGood ? '' : 'dim'}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function buildChartData(alpha) {
  if (!alpha?.sharpe) return [];
  let val = 10000;
  const pts = [{ name: '2019 Q1', value: val }];
  const seed = alpha.alpha_id ? alpha.alpha_id.charCodeAt(0) : 42;
  const annRet = alpha.returns || alpha.sharpe * 0.05;
  let t = 1;
  for (const y of ['2019', '2020', '2021', '2022', '2023']) {
    for (const q of ['Q1', 'Q2', 'Q3', 'Q4']) {
      if (y === '2019' && q === 'Q1') continue;
      const base = annRet / 4;
      const noise = Math.sin(t * seed * 0.3) * (alpha.drawdown || 0.04);
      const crash = (y === '2020' && q === 'Q1') ? -(alpha.drawdown || 0.12) : 0;
      val *= (1 + base + noise + crash);
      pts.push({ name: `${y} ${q}`, value: +val.toFixed(2) });
      t++;
    }
  }
  return pts;
}

// ────────────────────────────────────────────────────────────
// APP
// ────────────────────────────────────────────────────────────
export default function App() {
  const [tab, setTab] = useState('leaderboard');
  const [alphas, setAlphas] = useState([]);
  const [allAlphas, setAllAlphas] = useState([]);
  const [stats, setStats] = useState({ total: 0, avgSharpe: 0, avgFitness: 0 });
  const [generating, setGenerating] = useState(false);
  const [statusMsg, setStatusMsg] = useState('Pipeline Idle');
  const [domain, setDomain] = useState(DOMAINS[0]);
  const [dropOpen, setDropOpen] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const [showModal, setShowModal] = useState(false);
  const [latestRun, setLatestRun] = useState(null);

  // ── data loading ──────────────────────────────────────────
  const loadData = () => {
    fetch(`${API}/api/alphas`).then(r => r.json()).then(setAlphas).catch(console.error);
    fetch(`${API}/api/all_alphas`).then(r => r.json()).then(data => {
      setAllAlphas(data);
      if (data.length) {
        const total = data.length;
        const avgSharpe = data.reduce((s, a) => s + (a.sharpe || 0), 0) / total;
        const avgFitness = data.reduce((s, a) => s + (a.fitness || 0), 0) / total;
        setStats({ total, avgSharpe, avgFitness });
      }
    }).catch(console.error);
  };

  const checkStatus = () => {
    fetch(`${API}/api/status`).then(r => r.json()).then(d => {
      setStatusMsg(d.message || (d.is_running ? 'Running…' : 'Pipeline Idle'));
      if (!d.is_running) {
        setGenerating(prev => { if (prev) loadData(); return false; });
      } else {
        setGenerating(true);
        if (d.message?.includes('BRAIN')) loadData();
      }
    }).catch(console.error);
  };

  useEffect(() => {
    loadData();
    const id = setInterval(checkStatus, 3000);
    return () => clearInterval(id);
  }, []);

  // ── actions ───────────────────────────────────────────────
  const handleGenerate = () => {
    setGenerating(true);
    setStatusMsg(`Searching ArXiv…`);
    fetch(`${API}/api/generate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ domain: domain.query }) })
      .catch(() => setGenerating(false));
  };

  const handleBrain = () => {
    setGenerating(true);
    setStatusMsg('Simulating on BRAIN…');
    fetch(`${API}/api/simulate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ universe: 'TOP3000' }) })
      .catch(() => setGenerating(false));
  };

  const handleLastRun = () => {
    fetch(`${API}/api/latest_run`).then(r => r.json()).then(d => { setLatestRun(d); setShowModal(true); });
  };

  // ── render ────────────────────────────────────────────────
  return (
    <div className="app">

      {/* ── NAV ─────────────────────────────────────────── */}
      <nav className="nav">
        <div className="nav-logo">
          <span className="tilde">≈</span> Gen-Alpha
        </div>
        <div className="nav-links">
          <button className={`lb-tab ${tab === 'leaderboard' ? 'active' : ''}`} onClick={() => setTab('leaderboard')}>Leaderboard</button>
          <button className={`lb-tab ${tab === 'library' ? 'active' : ''}`} onClick={() => setTab('library')}>Library ({allAlphas.length})</button>
          <span className={`status-pill ${generating ? 'running' : ''}`}>
            <span className={`status-dot ${generating ? 'running' : ''}`} />
            {statusMsg}
          </span>
          <button className="btn" onClick={handleLastRun}>Last Run</button>
          <a href="https://github.com/AdithyaP-72/Gen-Alpha" target="_blank" rel="noreferrer" style={{ color: 'var(--muted-mid)', display: 'flex', alignItems: 'center' }}><GithubIcon /></a>
        </div>
      </nav>

      {/* ── HERO ─────────────────────────────────────────── */}
      <div className="hero">
        <h1 className="hero-title">Gen-Alpha</h1>
        <p className="hero-sub">
          Benchmarking autonomous quantitative intelligence<br />
          at the edge of machine ability.
        </p>
        <p className="hero-by">By <strong>≈ PROXIMAL</strong></p>

        <div className="hero-actions">
          <button className="btn btn-solid" onClick={handleGenerate} disabled={generating}>
            <PlayIcon /> {generating ? 'Running…' : 'Trigger Pipeline'}
          </button>

          <div className="dropdown-wrap">
            <button className="btn" onClick={() => setDropOpen(o => !o)} disabled={generating}>
              {domain.label} <ChevronDown open={dropOpen} />
            </button>
            {dropOpen && !generating && (
              <div className="dropdown-menu">
                {DOMAINS.map(d => (
                  <div key={d.id} className="dropdown-item" onClick={() => { setDomain(d); setDropOpen(false); }}>
                    {d.label}
                  </div>
                ))}
              </div>
            )}
          </div>

          <button className="btn btn-green" onClick={handleBrain} disabled={generating}>
            <BrainIcon /> Simulate on BRAIN
          </button>
        </div>
      </div>

      {/* ── MAIN ─────────────────────────────────────────── */}
      <main className="main">

        {/* Stats strip */}
        <div className="stats-strip">
          <div className="stat-cell">
            <span className="stat-cell-label">Total Alphas</span>
            <span className="stat-cell-value">{stats.total}</span>
            <span className="stat-cell-sub">{DOMAINS.length} research domains</span>
          </div>
          <div className="stat-cell">
            <span className="stat-cell-label">Avg Sharpe</span>
            <span className="stat-cell-value" style={{ color: stats.avgSharpe >= 1 ? 'var(--green)' : 'inherit' }}>
              {fmt2(stats.avgSharpe)}
            </span>
            <span className="stat-cell-sub">Equal-weighted portfolio</span>
          </div>
          <div className="stat-cell">
            <span className="stat-cell-label">Avg Fitness</span>
            <span className="stat-cell-value">{fmt2(stats.avgFitness)}</span>
            <span className="stat-cell-sub">BRAIN robustness score</span>
          </div>
        </div>

        {/* ── TAB: LEADERBOARD ─────────────────────────── */}
        {tab === 'leaderboard' && (
          <>
            <div className="lb-header">
              <span className="lb-label">Leaderboard</span>
              <div className="lb-tabs">
                <button className="lb-tab active">MEAN@5</button>
                <button className="lb-tab">BEST@5</button>
              </div>
            </div>

            <table className="alpha-table">
              <thead>
                <tr>
                  <th className="rank-num">#</th>
                  <th>Alpha ID</th>
                  <th>Source</th>
                  <th>Avg Rank ↑</th>
                  <th>Dominance</th>
                  <th>Sharpe</th>
                  <th>Fitness</th>
                  <th>Turnover</th>
                </tr>
              </thead>
              <tbody>
                {alphas.length === 0 && (
                  <tr className="empty-row">
                    <td colSpan="8">No alphas yet — trigger the pipeline above.</td>
                  </tr>
                )}
                {alphas.map((a, i) => (
                  <tr key={i}>
                    <td className="rank-num">{i + 1}</td>
                    <td>
                      <span className="alpha-id">{a.alpha_id}</span>
                    </td>
                    <td>
                      <span className={`source-tag ${a.source === 'arxiv' ? 'arxiv' : ''}`}>
                        {a.source === 'arxiv' ? (a.paper_title?.slice(0, 28) + '…' || 'ArXiv') : 'Template Mutation'}
                      </span>
                    </td>
                    <td className={sharpeClass(a.sharpe)} style={{ fontWeight: 700 }}>
                      {fmt2(a.sharpe)}
                    </td>
                    <td>
                      <DomBar value={a.fitness || 0} max={10} />
                    </td>
                    <td className={sharpeClass(a.sharpe)}>{fmt2(a.sharpe)}</td>
                    <td style={{ color: 'var(--muted-mid)' }}>{fmt2(a.fitness)}</td>
                    <td style={{ color: 'var(--muted-mid)' }}>{fmtPct(a.turnover)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}

        {/* ── TAB: LIBRARY ─────────────────────────────── */}
        {tab === 'library' && (
          <>
            <div className="lb-header">
              <span className="lb-label">Full Alpha Library</span>
              <span style={{ fontSize: '0.75rem', color: 'var(--muted)' }}>Click any row to expand</span>
            </div>

            {allAlphas.length === 0 && (
              <p style={{ color: 'var(--muted)', padding: '2rem 0', fontSize: '0.85rem' }}>
                No alphas in library yet. Run the pipeline to start discovering signals.
              </p>
            )}

            {allAlphas.map((a, i) => (
              <div key={a.alpha_id || i} className="alpha-card">
                <div className="alpha-card-header" onClick={() => setExpanded(expanded === i ? null : i)}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.3rem' }}>
                      <span className="alpha-id">{a.alpha_id}</span>
                      <span className={`source-tag ${a.source === 'arxiv' ? 'arxiv' : ''}`}>
                        {a.source === 'arxiv' ? 'ArXiv' : 'Template'}
                      </span>
                    </div>
                    <div className="alpha-card-expr">{a.expression}</div>
                  </div>
                  <div className="alpha-card-metrics">
                    <div>
                      <div className="alpha-card-metric-label">Sharpe</div>
                      <div className={sharpeClass(a.sharpe)}>{fmt2(a.sharpe)}</div>
                    </div>
                    <div>
                      <div className="alpha-card-metric-label">Fitness</div>
                      <div style={{ fontWeight: 600 }}>{fmt2(a.fitness)}</div>
                    </div>
                    <div>
                      <div className="alpha-card-metric-label">Turnover</div>
                      <div style={{ fontWeight: 600, color: 'var(--muted-mid)' }}>{fmtPct(a.turnover)}</div>
                    </div>
                    <ChevronDown open={expanded === i} />
                  </div>
                </div>

                {expanded === i && (
                  <div className="alpha-card-detail">
                    {a.anomaly && (
                      <div className="anomaly-block">
                        <h4>Extracted Anomaly</h4>
                        <p>{a.anomaly}</p>
                        {a.rationale && <p style={{ marginTop: '0.4rem', opacity: 0.7 }}>Rationale: {a.rationale}</p>}
                      </div>
                    )}

                    <p style={{ fontSize: '0.7rem', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: '0.75rem' }}>Simulation Settings</p>
                    <div className="settings-grid" style={{ marginBottom: '1.5rem' }}>
                      {[
                        ['Universe', a.settings?.universe || 'TOP3000'],
                        ['Neutralization', a.settings?.neutralization || 'SUBINDUSTRY'],
                        ['Decay', a.settings?.decay ?? 0],
                        ['Delay', a.settings?.delay ?? 1],
                        ['Truncation', a.settings?.truncation ?? 0.08],
                        ['Pasteurization', a.settings?.pasteurization || 'ON'],
                      ].map(([lbl, val]) => (
                        <div key={lbl}>
                          <div className="setting-item-label">{lbl}</div>
                          <div className="setting-item-value">{String(val)}</div>
                        </div>
                      ))}
                    </div>

                    {a.sharpe && (() => {
                      const data = buildChartData(a);
                      return (
                        <>
                          <p style={{ fontSize: '0.7rem', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: '0.75rem' }}>Projected Growth (2019–2023)</p>
                          <div style={{ height: 200 }}>
                            <ResponsiveContainer width="100%" height="100%">
                              <LineChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                                <XAxis dataKey="name" stroke="var(--muted)" fontSize={9} tick={{ fill: 'var(--muted)' }} />
                                <YAxis stroke="var(--muted)" fontSize={9} tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} width={38} />
                                <RechartsTip
                                  contentStyle={{ background: '#0c0c0c', border: '1px solid var(--border)', fontSize: 11 }}
                                  formatter={v => [`$${Number(v).toFixed(0)}`, 'Value']}
                                />
                                <Line type="monotone" dataKey="value" stroke="var(--green)" strokeWidth={2} dot={false} activeDot={{ r: 3 }} />
                              </LineChart>
                            </ResponsiveContainer>
                          </div>
                        </>
                      );
                    })()}
                  </div>
                )}
              </div>
            ))}
          </>
        )}
      </main>

      {/* ── LAST RUN MODAL ───────────────────────────────── */}
      {showModal && latestRun && (
        <div className="modal-backdrop" onClick={() => setShowModal(false)}>
          <div className="modal-box" onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
              <h2 className="modal-title" style={{ margin: 0 }}>Last Pipeline Run</h2>
              <button className="btn" onClick={() => setShowModal(false)}>Close</button>
            </div>
            <div className="modal-stat-grid">
              <div className="modal-stat-cell">
                <div style={{ fontSize: '0.7rem', color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.3rem' }}>Papers Processed</div>
                <div style={{ fontSize: '1.6rem', fontWeight: 700 }}>{latestRun.papers_processed ?? '–'}</div>
              </div>
              <div className="modal-stat-cell">
                <div style={{ fontSize: '0.7rem', color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.3rem' }}>Expressions Generated</div>
                <div style={{ fontSize: '1.6rem', fontWeight: 700, color: 'var(--green)' }}>{latestRun.total_expressions ?? '–'}</div>
              </div>
            </div>

            <p style={{ fontSize: '0.7rem', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: '0.75rem' }}>Extracted Ideas</p>
            {latestRun.papers?.length > 0
              ? latestRun.papers.map((p, i) => (
                <div key={i} className="paper-card">
                  <p className="paper-title">{p.title}</p>
                  <ul>{p.anomalies.map((a, j) => <li key={j}>{a}</li>)}</ul>
                </div>
              ))
              : <p style={{ color: 'var(--muted)', fontSize: '0.82rem' }}>No ideas extracted in the last run.</p>
            }
          </div>
        </div>
      )}
    </div>
  );
}
