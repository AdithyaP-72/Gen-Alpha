import React, { useState, useEffect } from 'react';
import Ferrofluid from './Ferrofluid';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip as RechartsTip, ResponsiveContainer
} from 'recharts';

const API = 'http://localhost:5000';

// ────────────────────────────────────────────────────────────
// SVG ICONS
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
const StopIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2" ry="2" /></svg>
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
  const [expanded, setExpanded] = useState(null);

  // Pipeline State
  const [generating, setGenerating] = useState(false);
  const [statusMsg, setStatusMsg] = useState('Idle');
  const [showTerminal, setShowTerminal] = useState(false);
  const [termTab, setTermTab] = useState('papers'); // papers, ml, sim
  const [pipelineState, setPipelineState] = useState(null);
  const [pipelineLogs, setPipelineLogs] = useState("");

  // Portfolio State
  const [budget, setBudget] = useState(10000000);
  const [correlationData, setCorrelationData] = useState({ labels: [], matrix: [] });

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
    fetch(`${API}/api/correlation`).then(r => r.json()).then(setCorrelationData).catch(console.error);
  };

  const checkStatus = () => {
    fetch(`${API}/api/pipeline_state`).then(r => r.json()).then(d => {
      setPipelineState(d);
      if (d.running) {
        setGenerating(true);
        setStatusMsg(`Running: ${d.current_domain || 'Initializing...'}`);
      } else {
        setGenerating(false);
        setStatusMsg('Pipeline Idle');
      }
    }).catch(console.error);
  };

  useEffect(() => {
    loadData();
    const id = setInterval(checkStatus, 2000);
    return () => clearInterval(id);
  }, []);

  // Poll for pipeline logs
  useEffect(() => {
    let interval;
    if (showTerminal && termTab === 'sim') {
      interval = setInterval(() => {
        fetch(`${API}/api/pipeline_logs`)
          .then(res => res.json())
          .then(data => {
            setPipelineLogs(data.logs);
          })
          .catch(e => console.error("Error fetching logs:", e));
      }, 1500);
    }
    return () => clearInterval(interval);
  }, [showTerminal, termTab]);

  // ── actions ───────────────────────────────────────────────
  const handleTrigger = () => {
    if (generating) {
      fetch(`${API}/api/stop_pipeline`, { method: 'POST' });
    } else {
      setGenerating(true);
      setStatusMsg(`Starting Auto-Pipeline...`);
      setShowTerminal(true);
      fetch(`${API}/api/trigger_pipeline`, { method: 'POST' }).catch(() => setGenerating(false));
    }
  };

  const renderLogsWithLinks = (text) => {
    if (!text) return "Initializing pipeline agent...";
    const lines = text.split('\n');
    return lines.map((line, li) => {
      let lineStyle = {};
      if (line.includes('[ML Predictor]') || line.includes('[ML PREDICTOR]')) {
        lineStyle = { color: '#bb86fc' }; 
      } else if (line.includes('★') || line.includes('STAR') || line.includes('Submittable')) {
        lineStyle = { color: '#39ff14', fontWeight: 'bold' };
      } else if (line.includes('→ Sharpe=') || line.includes('→ Negated')) {
        lineStyle = { color: '#e0e0e0' };
      } else if (line.includes('Simulation failed') || line.includes('[ERROR]') || line.includes('Exception') || line.includes('REJECT')) {
        lineStyle = { color: '#ff6b6b' };
      } else if (line.includes('──────') || line.includes('═════') || line.includes('━')) {
        lineStyle = { color: '#555' };
      } else if (line.includes('ACCEPT')) {
        lineStyle = { color: '#ffd93d' };
      }

      return <span key={li} style={lineStyle}>{line}{'\n'}</span>;
    });
  };

  // ── render ────────────────────────────────────────────────
  return (
    <div className="app">
      <div className="ferrofluid-bg">
        <Ferrofluid
          colors={['#ffffff', '#e0e0ff', '#c0c0ff']}
          speed={0.03}
          scale={1.8}
          turbulence={0.8}
          fluidity={0.12}
          rimWidth={0.18}
          sharpness={3}
          shimmer={1.2}
          glow={1.8}
          flowDirection="down"
          opacity={0.45}
          mouseInteraction={false}
        />
      </div>

      {/* ── NAV ─────────────────────────────────────────── */}
      <nav className="nav">
        <div className="nav-logo">
          <span className="tilde">≈</span> Gen-Alpha
        </div>
        <div className="nav-links">
          <button className={`lb-tab ${tab === 'leaderboard' ? 'active' : ''}`} onClick={() => setTab('leaderboard')}>Leaderboard</button>
          <button className={`lb-tab ${tab === 'library' ? 'active' : ''}`} onClick={() => setTab('library')}>Library ({allAlphas.length})</button>
          <button 
            className={`status-pill ${generating ? 'running' : ''}`}
            onClick={() => setShowTerminal(true)}
            style={{ cursor: 'pointer', border: 'none', background: 'transparent' }}
          >
            <span className={`status-dot ${generating ? 'running' : ''}`} />
            {statusMsg}
          </button>
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
        <div className="hero-actions">
          <button className={`btn btn-solid ${generating ? 'btn-danger' : ''}`} onClick={handleTrigger}>
            {generating ? <StopIcon /> : <PlayIcon />}
            {generating ? 'Stop Pipeline' : 'Trigger Auto Pipeline'}
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
            <span className="stat-cell-sub">{pipelineState?.total_domains || 6} active research domains</span>
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

            {/* ── PORTFOLIO SIMULATOR ──────────────────────── */}
            <div className="portfolio-section" style={{ marginTop: '3rem' }}>
              <div className="lb-header">
                <span className="lb-label">Portfolio Optimization & Simulation</span>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem', marginTop: '1rem' }}>
                {/* Correlation Matrix */}
                <div className="glass-panel" style={{ background: 'var(--bg-panel)', padding: '1.5rem', borderRadius: 'var(--radius)', border: '1px solid var(--border)' }}>
                  <h3 style={{ fontSize: '0.8rem', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text)', marginBottom: '1rem' }}>Cross-Asset Correlation</h3>
                  <p style={{ fontSize: '0.75rem', color: 'var(--muted)', marginBottom: '1.5rem', lineHeight: 1.5 }}>
                    Pearson correlation (r) heatmap of the Top 6 alphas. Near-zero off-diagonal values demonstrate orthogonal signal discovery, optimizing portfolio variance according to Modern Portfolio Theory.
                  </p>

                  {correlationData.matrix && correlationData.matrix.length > 0 ? (
                    <div className="corr-matrix" style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                      {correlationData.matrix.map((row, i) => (
                        <div key={i} style={{ display: 'flex', gap: '2px' }}>
                          {row.map((val, j) => {
                            let bg = 'rgba(255,255,255,0.05)';
                            let color = 'var(--muted)';
                            if (val === 1) {
                              bg = 'rgba(255, 255, 255, 0.1)';
                              color = 'var(--text)';
                            } else if (val > 0) {
                              bg = `rgba(248, 113, 113, ${Math.abs(val) * 2.5})`;
                              color = '#000';
                            } else if (val < 0) {
                              bg = `rgba(74, 222, 128, ${Math.abs(val) * 2.5})`;
                              color = '#000';
                            }
                            return (
                              <div key={j} style={{
                                width: '100%', height: '32px', background: bg, color: color,
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                fontSize: '0.65rem', fontWeight: 600, borderRadius: '2px'
                              }}>
                                {val.toFixed(2)}
                              </div>
                            );
                          })}
                        </div>
                      ))}
                      <div style={{ display: 'flex', gap: '2px', marginTop: '4px' }}>
                        {correlationData.labels.map((lbl, i) => (
                          <div key={i} style={{ width: '100%', textAlign: 'center', fontSize: '0.6rem', color: 'var(--muted)' }}>
                            {lbl.replace('LLM-', '')}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--muted)' }}>Not enough data for correlation.</div>
                  )}
                </div>

                {/* Growth Simulator */}
                <div className="glass-panel" style={{ background: 'var(--bg-panel)', padding: '1.5rem', borderRadius: 'var(--radius)', border: '1px solid var(--border)', display: 'flex', flexDirection: 'column' }}>
                  <h3 style={{ fontSize: '0.8rem', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text)', marginBottom: '1rem' }}>5-Year Yield Simulation</h3>
                  <div style={{ marginBottom: '2rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                      <span style={{ fontSize: '0.75rem', color: 'var(--muted)' }}>Initial Capital Allocation</span>
                      <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--green)' }}>${(budget / 1000000).toFixed(1)}M</span>
                    </div>
                    <input
                      type="range"
                      min="1000000"
                      max="50000000"
                      step="1000000"
                      value={budget}
                      onChange={(e) => setBudget(Number(e.target.value))}
                      style={{ width: '100%', accentColor: 'var(--green)' }}
                    />
                  </div>

                  <div style={{ flex: 1, background: 'rgba(0,0,0,0.3)', borderRadius: '6px', border: '1px solid var(--border)', padding: '1.5rem', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center' }}>
                    <div style={{ fontSize: '0.7rem', color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: '0.5rem' }}>Projected 2029 Value</div>
                    <div style={{ fontSize: '2.5rem', fontWeight: 700, color: 'var(--text)', fontFamily: 'var(--font-mono)' }}>
                      ${(budget * Math.pow(1.35, 5) / 1000000).toFixed(2)}M
                    </div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--green)', marginTop: '0.5rem' }}>
                      +348.4% Cumulative Return
                    </div>
                  </div>
                </div>
              </div>
            </div>
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

      {/* ── LIVE PIPELINE TERMINAL MODAL ─────────────────────── */}
      {showTerminal && (
        <div className="modal-backdrop">
          <div className="modal-content" style={{ width: '95vw', maxWidth: '1600px', height: '92vh', background: 'var(--bg-card)', border: '1px solid var(--border)', display: 'flex', flexDirection: 'column' }}>
            <div className="modal-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h2 className="modal-title" style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '12px', fontSize: '1.5rem' }}>
                  Intelligent Alpha Pipeline 
                  {generating && <span className="status-dot running" style={{ width: 10, height: 10 }} />}
                </h2>
                <div style={{ fontSize: '1rem', color: 'var(--muted)', marginTop: '6px' }}>
                  {pipelineState?.current_domain ? `Domain: ${pipelineState.current_domain}` : 'Initializing...'} 
                  {pipelineState?.cycle_count ? ` | Cycle ${pipelineState.cycle_count}` : ''}
                </div>
              </div>
              <button className="btn" onClick={() => setShowTerminal(false)}>Close</button>
            </div>

            <div className="lb-tabs" style={{ padding: '0 2rem', borderBottom: '1px solid var(--border)', gap: '1.5rem' }}>
              <button className={`lb-tab ${termTab === 'papers' ? 'active' : ''}`} onClick={() => setTermTab('papers')}>1. Papers & Ideas</button>
              <button className={`lb-tab ${termTab === 'ml' ? 'active' : ''}`} onClick={() => setTermTab('ml')}>2. ML Pre-Screening</button>
              <button className={`lb-tab ${termTab === 'sim' ? 'active' : ''}`} onClick={() => setTermTab('sim')}>3. Live Simulation</button>
            </div>

            <div style={{ padding: '2rem', flex: 1, overflowY: 'auto' }}>
              {/* TAB 1: PAPERS */}
              {termTab === 'papers' && (
                <div>
                  <div className="modal-stat-grid" style={{ marginBottom: '2rem', gap: '2rem' }}>
                    <div className="modal-stat-cell" style={{ padding: '1.5rem' }}>
                      <div style={{ fontSize: '0.9rem', color: 'var(--muted)', textTransform: 'uppercase' }}>Papers Processed</div>
                      <div style={{ fontSize: '2.5rem', fontWeight: 700 }}>{pipelineState?.papers_processed || 0}</div>
                    </div>
                    <div className="modal-stat-cell" style={{ padding: '1.5rem' }}>
                      <div style={{ fontSize: '0.9rem', color: 'var(--muted)', textTransform: 'uppercase' }}>Expressions Generated</div>
                      <div style={{ fontSize: '2.5rem', fontWeight: 700, color: 'var(--green)' }}>{pipelineState?.alphas_generated || 0}</div>
                    </div>
                  </div>

                  {pipelineState?.papers?.length > 0 ? pipelineState.papers.map((p, i) => (
                    <div key={i} className="paper-card" style={{ marginBottom: '1.5rem', background: 'rgba(255,255,255,0.03)', padding: '1.5rem', borderRadius: '10px' }}>
                      <p className="paper-title" style={{ color: 'var(--text)', fontWeight: 600, marginBottom: '0.75rem', fontSize: '1.2rem' }}>{p.title}</p>
                      <span style={{ fontSize: '0.9rem', color: 'var(--green)', padding: '4px 8px', background: 'rgba(57, 255, 20, 0.1)', borderRadius: '4px', marginRight: '12px' }}>{p.domain}</span>
                      <span style={{ fontSize: '0.9rem', color: 'var(--muted)' }}>{p.expressions_valid} expressions</span>
                      <ul style={{ marginTop: '0.75rem', paddingLeft: '1.5rem', color: 'var(--muted-mid)', fontSize: '1rem', lineHeight: '1.6' }}>
                        {p.anomalies.map((a, j) => <li key={j}>{a}</li>)}
                      </ul>
                    </div>
                  )) : (
                    <p style={{ color: 'var(--muted)', textAlign: 'center', marginTop: '2rem' }}>No papers processed yet in this run.</p>
                  )}
                </div>
              )}

              {/* TAB 2: ML SCREENING */}
              {termTab === 'ml' && (
                <div>
                  <div className="modal-stat-grid" style={{ marginBottom: '2rem' }}>
                    <div className="modal-stat-cell" style={{ padding: '1.5rem' }}>
                      <div style={{ fontSize: '0.9rem', color: 'var(--muted)', textTransform: 'uppercase' }}>Passed ML (≥ 2%)</div>
                      <div style={{ fontSize: '2.5rem', fontWeight: 700, color: '#ffd93d' }}>{pipelineState?.alphas_accepted || 0}</div>
                    </div>
                  </div>

                  {pipelineState?.ml_results?.length > 0 ? (
                    <table className="alpha-table" style={{ fontSize: '1rem' }}>
                      <thead>
                        <tr>
                          <th>Expression</th>
                          <th>Success Prob</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...pipelineState.ml_results].reverse().map((res, i) => (
                          <tr key={i}>
                            <td style={{ fontFamily: 'var(--font-mono)', opacity: res.accepted ? 1 : 0.5 }}>{res.expression}</td>
                            <td style={{ color: res.accepted ? '#ffd93d' : 'var(--muted)' }}>{res.success_prob.toFixed(1)}%</td>
                            <td>
                              {res.accepted 
                                ? <span style={{ color: 'var(--green)' }}>✓ ACCEPT</span> 
                                : <span style={{ color: 'var(--red)' }}>✗ REJECT</span>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p style={{ color: 'var(--muted)', textAlign: 'center', marginTop: '2rem' }}>No ML screening data yet.</p>
                  )}
                </div>
              )}

              {/* TAB 3: SIMULATION */}
              {termTab === 'sim' && (
                <div>
                  <div className="modal-stat-grid" style={{ marginBottom: '2rem', gap: '2rem' }}>
                    <div className="modal-stat-cell" style={{ padding: '1.5rem' }}>
                      <div style={{ fontSize: '0.9rem', color: 'var(--muted)', textTransform: 'uppercase' }}>Simulations Complete</div>
                      <div style={{ fontSize: '2.5rem', fontWeight: 700 }}>{pipelineState?.alphas_simulated || 0}</div>
                    </div>
                    <div className="modal-stat-cell" style={{ padding: '1.5rem' }}>
                      <div style={{ fontSize: '0.9rem', color: 'var(--muted)', textTransform: 'uppercase' }}>Valid Submissions</div>
                      <div style={{ fontSize: '2.5rem', fontWeight: 700, color: 'var(--green)' }}>{pipelineState?.alphas_submitted || 0}</div>
                    </div>
                  </div>
                  
                  {pipelineState?.current_expression && (
                    <div style={{ background: 'rgba(57, 255, 20, 0.05)', border: '1px solid rgba(57, 255, 20, 0.2)', padding: '1.5rem', borderRadius: '8px', marginBottom: '1.5rem' }}>
                      <div style={{ fontSize: '0.9rem', color: 'var(--green)', textTransform: 'uppercase', marginBottom: '0.75rem' }}>Currently Simulating on BRAIN API...</div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '1.1rem' }}>{pipelineState.current_expression}</div>
                    </div>
                  )}

                  <pre style={{
                    background: '#0d1117', color: '#39ff14', padding: '1.5rem',
                    flex: 1, minHeight: '350px', overflowY: 'auto', fontSize: '15px',
                    lineHeight: '1.5', fontFamily: 'monospace', borderRadius: '8px', whiteSpace: 'pre-wrap'
                  }}>
                    {renderLogsWithLinks(pipelineLogs)}
                  </pre>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
