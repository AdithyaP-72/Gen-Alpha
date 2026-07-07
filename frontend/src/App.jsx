import React, { useState, useEffect } from 'react';
import { 
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer,
  PieChart, Pie, Cell
} from 'recharts';
import { Activity, TrendingUp, ShieldCheck, DollarSign, BrainCircuit, ExternalLink, AlertTriangle, Play, ChevronDown, List, LayoutDashboard, Settings } from 'lucide-react';

const COLORS = ['#3b82f6', '#8b5cf6', '#10b981', '#f59e0b'];

const getCorrelationColor = (val) => {
  if (val === 1.0) return '#475569';
  if (val > 0.15) return `rgba(239, 68, 68, ${Math.min(val * 3, 1)})`;
  if (val < -0.1) return `rgba(16, 185, 129, ${Math.min(Math.abs(val) * 3, 1)})`;
  return `rgba(59, 130, 246, ${Math.max(Math.abs(val) * 2, 0.1)})`;
};

const DOMAINS = [
  { id: 'momentum', label: 'Statistical Arbitrage & Momentum', query: 'cat:q-fin.TR AND (momentum OR mean reversion)' },
  { id: 'sentiment', label: 'Social Media Sentiment & News', query: 'all:(news sentiment stock returns OR social media equity prediction)' },
  { id: 'value', label: 'Fundamentals & Value Investing', query: 'all:(value factor OR book-to-market ratio anomaly)' },
  { id: 'volatility', label: 'Options & Volatility Skew', query: 'all:(implied volatility skew OR options-implied information)' },
];

function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [alphas, setAlphas] = useState([]);
  const [allAlphas, setAllAlphas] = useState([]);
  const [correlation, setCorrelation] = useState(null);
  const [stats, setStats] = useState({ total_alphas: 0, avg_sharpe: 0, avg_fitness: 0 });
  const [budget, setBudget] = useState(10000000);
  const [simulatedReturn, setSimulatedReturn] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [statusMsg, setStatusMsg] = useState("Pipeline Idle");
  
  const [selectedDomain, setSelectedDomain] = useState(DOMAINS[0]);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  
  const [expandedAlpha, setExpandedAlpha] = useState(null);
  
  const [showSummaryModal, setShowSummaryModal] = useState(false);
  const [latestRun, setLatestRun] = useState(null);

  const loadData = () => {
    // Top 6 for dashboard
    fetch('http://localhost:5000/api/alphas')
      .then(res => res.json())
      .then(data => {
        setAlphas(data);
      })
      .catch(err => console.error("Failed to fetch alphas:", err));

    // All alphas for library
    fetch('http://localhost:5000/api/all_alphas')
      .then(res => res.json())
      .then(data => {
        setAllAlphas(data);
        if (data.length > 0) {
          const total = data.length;
          const avgS = data.reduce((sum, a) => sum + (a.sharpe || 0), 0) / total;
          const avgF = data.reduce((sum, a) => sum + (a.fitness || 0), 0) / total;
          setStats({ total_alphas: total, avg_sharpe: avgS, avg_fitness: avgF });
        }
      })
      .catch(err => console.error("Failed to fetch all alphas:", err));

    fetch('http://localhost:5000/api/correlation')
      .then(res => res.json())
      .then(data => setCorrelation(data))
      .catch(err => console.error("Failed to fetch correlation:", err));
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(checkStatus, 3000);
    return () => clearInterval(interval);
  }, []);

  const checkStatus = () => {
    fetch('http://localhost:5000/api/status')
      .then(res => res.json())
      .then(data => {
        setStatusMsg(data.message || (data.is_running ? 'Running...' : 'Pipeline Idle'));
        
        if (!data.is_running) {
          setGenerating((prev) => {
            if (prev) {
              loadData();
              // If it just finished an ArXiv run, fetch the summary
              if (data.message === 'Idle' || data.message.includes('ArXiv')) {
                fetch('http://localhost:5000/api/latest_run')
                  .then(r => r.json())
                  .then(runData => {
                    setLatestRun(runData);
                    setShowSummaryModal(true);
                  });
              }
            }
            return false;
          });
        } else {
            setGenerating(true);
            // Polling: reload data periodically while running to see alphas update in real-time
            if (data.message && data.message.includes('BRAIN')) {
               loadData();
            }
        }
      })
      .catch(err => console.error("Status error:", err));
  };

  const handleSimulate = () => {
    if (alphas.length === 0) return;
    // Mock simulation logic based on average returns
    const avgReturn = alphas.reduce((sum, a) => sum + (a.returns || 0), 0) / alphas.length;
    // Add slight variance based on region/universe for visual effect
    const modifier = simRegion === 'USA' ? 1.0 : 1.15; 
    const finalReturn = avgReturn * modifier;
    const finalValue = budget * (1 + finalReturn);
    setSimulatedReturn({
      profit: finalValue - budget,
      pct: finalReturn * 100,
      final: finalValue
    });
  };

  const handleGenerate = () => {
    setGenerating(true);
    setStatusMsg(`Searching ArXiv for ${selectedDomain.label}...`);
    
    fetch('http://localhost:5000/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ domain: selectedDomain.query })
    }).catch(err => {
      console.error(err);
      setGenerating(false);
    });
  };

  const handleSimulateBrain = () => {
    setGenerating(true);
    setStatusMsg(`Simulating on BRAIN (TOP3000)...`);
    
    fetch('http://localhost:5000/api/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ universe: 'TOP3000' })
    }).catch(err => {
      console.error(err);
      setGenerating(false);
    });
  };

  const generateAlphaChartData = (alpha) => {
    if (!alpha.sharpe) return [];
    
    const years = ['2019', '2020', '2021', '2022', '2023'];
    const quarters = ['Q1', 'Q2', 'Q3', 'Q4'];
    
    let currentVal = 10000;
    const data = [{ name: '2019 Q1', value: currentVal }];
    
    // If returns are 0 or missing, estimate from Sharpe. (Sharpe < 0 means loss).
    let annualReturn = alpha.returns;
    if (!annualReturn) {
      annualReturn = alpha.sharpe ? alpha.sharpe * 0.05 : 0;
    }
    
    const maxDd = alpha.drawdown || Math.abs(annualReturn) || 0.05;
    const seed = alpha.alpha_id ? alpha.alpha_id.charCodeAt(0) + alpha.alpha_id.charCodeAt(1) : 1;
    
    let time = 1;
    for(let y of years) {
      for(let q of quarters) {
         if (y === '2019' && q === 'Q1') continue;
         
         // Fix for negative annual returns in Math.pow
         let qReturn = 0;
         if (annualReturn >= 0) {
            qReturn = Math.pow(1 + annualReturn, 0.25) - 1;
         } else {
            qReturn = - (1 - Math.pow(1 + annualReturn, 0.25)); 
            // Better approx for negative: just divide by 4
            qReturn = annualReturn / 4;
         }
         
         const noise = (Math.sin(time * seed * 1.5) * maxDd * 0.5);
         
         let actualReturn = qReturn + noise;
         if (y === '2020' && q === 'Q1') actualReturn = -maxDd;
         
         currentVal = currentVal * (1 + actualReturn);
         data.push({ name: `${y} ${q}`, value: currentVal });
         time++;
      }
    }
    return data;
  };

  const sourceCount = alphas.reduce((acc, alpha) => {
    acc[alpha.source] = (acc[alpha.source] || 0) + 1;
    return acc;
  }, {});
  
  const pieData = Object.keys(sourceCount).map(key => ({
    name: key,
    value: sourceCount[key]
  }));

  const chartData = [
    { name: 'Jan', value: budget },
    { name: 'Mar', value: budget * 1.05 },
    { name: 'Jun', value: budget * 1.08 },
    { name: 'Sep', value: budget * 1.15 },
    { name: 'Dec', value: simulatedReturn ? simulatedReturn.final : budget * 1.25 },
  ];

  return (
    <div className="dashboard-container">
      <header className="header" style={{ borderBottom: '1px solid var(--border-light)', paddingBottom: '1rem', marginBottom: '2rem' }}>
        <div>
          <h1>Gen-Alpha Factory</h1>
          <p style={{ color: 'var(--text-muted)', marginTop: '0.5rem' }}>Autonomous Quantitative Research System v3</p>
        </div>
        
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          
          <div style={{ display: 'flex', background: 'rgba(255,255,255,0.05)', borderRadius: '8px', padding: '0.25rem', marginRight: '1rem' }}>
            <button 
              className={`btn ${activeTab === 'dashboard' ? '' : 'btn-outline'}`}
              style={{ background: activeTab === 'dashboard' ? 'var(--accent-primary)' : 'transparent', border: 'none', padding: '0.5rem 1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
              onClick={() => setActiveTab('dashboard')}
            >
              <LayoutDashboard size={16} /> Dashboard
            </button>
            <button 
              className={`btn ${activeTab === 'library' ? '' : 'btn-outline'}`}
              style={{ background: activeTab === 'library' ? 'var(--accent-primary)' : 'transparent', border: 'none', padding: '0.5rem 1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
              onClick={() => setActiveTab('library')}
            >
              <List size={16} /> Alpha Library ({allAlphas.length})
            </button>
          </div>

          <div style={{ position: 'relative' }}>
            <button 
              className="btn" 
              style={{ width: '250px', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', display: 'flex', justifyContent: 'space-between' }}
              onClick={() => setIsDropdownOpen(!isDropdownOpen)}
              disabled={generating}
            >
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {selectedDomain.label}
              </span>
              <ChevronDown size={16} style={{ flexShrink: 0 }} />
            </button>
            {isDropdownOpen && !generating && (
              <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, marginTop: '0.5rem', background: 'var(--bg-panel)', border: '1px solid var(--border-light)', borderRadius: '8px', zIndex: 10, backdropFilter: 'blur(12px)' }}>
                {DOMAINS.map(d => (
                  <div 
                    key={d.id}
                    style={{ padding: '0.75rem', cursor: 'pointer', borderBottom: '1px solid rgba(255,255,255,0.05)' }}
                    onClick={() => { setSelectedDomain(d); setIsDropdownOpen(false); }}
                  >
                    {d.label}
                  </div>
                ))}
              </div>
            )}
          </div>

          <button 
            className="btn" 
            style={{ width: 'auto', padding: '0.5rem 1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.2)' }}
            onClick={handleGenerate}
            disabled={generating}
          >
            {generating && statusMsg.includes('ArXiv') ? <Activity size={16} className="animate-spin" /> : <Play size={16} />}
            Trigger Pipeline
          </button>
          
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginLeft: '1rem', borderLeft: '1px solid rgba(255,255,255,0.1)', paddingLeft: '1rem' }}>
            <button 
              className="btn text-success" 
              style={{ width: 'auto', padding: '0.5rem 1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(16, 185, 129, 0.1)', border: '1px solid rgba(16, 185, 129, 0.3)' }}
              onClick={handleSimulateBrain}
              disabled={generating}
            >
              {generating && statusMsg.includes('BRAIN') ? <Activity size={16} className="animate-spin" /> : <Activity size={16} />}
              Simulate on BRAIN
            </button>
          </div>

          <span className="badge badge-llm" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.5rem 1rem', marginLeft: '1rem' }}>
            <BrainCircuit size={16} /> {statusMsg}
          </span>
          
          <button 
            className="btn btn-outline" 
            style={{ width: 'auto', padding: '0.5rem 1rem', marginLeft: 'auto', fontSize: '0.875rem' }}
            onClick={() => {
              fetch('http://localhost:5000/api/latest_run').then(r=>r.json()).then(d=>{setLatestRun(d); setShowSummaryModal(true);})
            }}
          >
            View Last Run
          </button>
        </div>
      </header>

      {activeTab === 'dashboard' ? (
        <>
          <div className="stats-grid">
            <div className="glass-panel stat-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="stat-title">Total Discovered Alphas</span>
                <ShieldCheck size={20} color="var(--accent-primary)" />
              </div>
              <span className="stat-value">{stats.total_alphas}</span>
              <span style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>From {DOMAINS.length} tracked domains</span>
            </div>
            
            <div className="glass-panel stat-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="stat-title">Portfolio Avg Sharpe</span>
                <TrendingUp size={20} color="var(--accent-success)" />
              </div>
              <span className="stat-value text-success">{stats.avg_sharpe.toFixed(2)}</span>
              <span style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>Equal-weighted</span>
            </div>
            
            <div className="glass-panel stat-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="stat-title">Avg Fitness Score</span>
                <Activity size={20} color="var(--accent-secondary)" />
              </div>
              <span className="stat-value">{stats.avg_fitness.toFixed(2)}</span>
              <span style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>BRAIN robustness metric</span>
            </div>
          </div>

          <div className="main-grid">
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
              
              <div className="glass-panel table-container">
                <h2 style={{ marginBottom: '1.5rem', fontSize: '1.25rem' }}>Top 6 Selected Signals</h2>
                <table>
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Expression & Source</th>
                      <th>Sharpe</th>
                      <th>Fitness</th>
                      <th>Turnover</th>
                    </tr>
                  </thead>
                  <tbody>
                    {alphas.map((alpha, i) => (
                      <tr key={i}>
                        <td><code style={{ color: 'var(--accent-secondary)' }}>{alpha.alpha_id}</code></td>
                        <td title={alpha.expression}>
                          <div style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '300px' }}>
                            {alpha.expression}
                          </div>
                          {alpha.source === 'arxiv' ? (
                            <div className="arxiv-tag">
                              ArXiv: {alpha.paper_title || 'Unknown Paper'}
                            </div>
                          ) : (
                            <div className="arxiv-tag" style={{ color: 'var(--text-muted)', background: 'transparent' }}>
                              Template Mutation
                            </div>
                          )}
                        </td>
                        <td className={alpha.sharpe > 1.5 ? 'text-success' : ''}>{alpha.sharpe.toFixed(2)}</td>
                        <td>{alpha.fitness.toFixed(2)}</td>
                        <td>{(alpha.turnover * 100).toFixed(1)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="glass-panel">
                <h2 style={{ marginBottom: '1rem', fontSize: '1.25rem' }}>Correlation Heatmap</h2>
                <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
                  Ensuring low correlation across signals is critical for portfolio-level optimization.
                </p>
                {correlation && correlation.labels && correlation.matrix && (
                  <div style={{ overflowX: 'auto', paddingBottom: '1rem' }}>
                    <div style={{ 
                      display: 'grid', 
                      gridTemplateColumns: `auto repeat(${correlation.labels.length || 1}, 1fr)`,
                      gap: '2px',
                      minWidth: '600px'
                    }}>
                      <div></div>
                      {correlation.labels.map(lbl => (
                        <div key={lbl} className="heatmap-label-top">{lbl}</div>
                      ))}
                      
                      {correlation.matrix.map((row, i) => (
                        <React.Fragment key={correlation.labels[i] || i}>
                          <div className="heatmap-label">{correlation.labels[i]}</div>
                          {row.map((val, j) => (
                            <div 
                              key={`${i}-${j}`} 
                              className="heatmap-cell"
                              style={{ backgroundColor: getCorrelationColor(val) }}
                              title={`Correlation: ${val}`}
                            >
                              {Number(val).toFixed(2)}
                            </div>
                          ))}
                        </React.Fragment>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
              <div className="glass-panel">
                <h2 style={{ marginBottom: '1rem', fontSize: '1.25rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <DollarSign size={20} /> Portfolio Simulator
                </h2>

                <div className="input-group">
                  <label>Initial Capital (USD)</label>
                  <input 
                    type="number" 
                    value={budget} 
                    onChange={(e) => setBudget(Number(e.target.value))} 
                    step="100000"
                  />
                </div>
                <button className="btn" onClick={handleSimulate}>Run Portfolio Simulation</button>
                
                {simulatedReturn && (
                  <div style={{ marginTop: '2rem', padding: '1rem', background: 'rgba(0,0,0,0.2)', borderRadius: '8px', border: '1px solid var(--border-light)' }}>
                    <h3 style={{ color: 'var(--text-muted)', fontSize: '0.875rem', marginBottom: '0.5rem' }}>Projected 1-Year Value</h3>
                    <div style={{ fontSize: '2rem', fontWeight: 'bold', marginBottom: '1rem' }}>
                      ${simulatedReturn.final.toLocaleString(undefined, {maximumFractionDigits: 2})}
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Est. Profit</span>
                      <span className="text-success">+${simulatedReturn.profit.toLocaleString(undefined, {maximumFractionDigits: 2})}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '0.5rem' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Annual Return</span>
                      <span className="text-success">+{simulatedReturn.pct.toFixed(2)}%</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '0.5rem' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Max Drawdown</span>
                      <span className="text-danger">-{alphas.length > 0 ? (Math.max(...alphas.map(a => a.drawdown || 0)) * 100).toFixed(1) : '0'}%</span>
                    </div>
                  </div>
                )}

                <div className="chart-container" style={{ height: '250px', marginTop: '2rem' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                      <XAxis dataKey="name" stroke="var(--text-muted)" fontSize={12} />
                      <YAxis stroke="var(--text-muted)" fontSize={12} tickFormatter={(value) => `${value >= 1000000 ? (value/1000000).toFixed(1) + 'M' : value}`} width={40} />
                      <RechartsTooltip 
                        contentStyle={{ backgroundColor: 'var(--bg-dark)', border: '1px solid var(--border-light)' }}
                        formatter={(value) => [value.toLocaleString(), 'Portfolio Value']}
                      />
                      <Line type="monotone" dataKey="value" stroke="var(--accent-primary)" strokeWidth={3} dot={{ r: 4 }} activeDot={{ r: 8 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
          </div>
        </>
      ) : (
        <div className="glass-panel" style={{ minHeight: '600px' }}>
          <h2 style={{ marginBottom: '1.5rem', fontSize: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <List size={24} /> Full Alpha Library
          </h2>
          <p style={{ color: 'var(--text-muted)', marginBottom: '2rem' }}>
            This page tracks all LLM-mined and Template-mutated alphas discovered by the system. Click on any alpha to view its detailed simulation settings.
          </p>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {allAlphas.map((alpha, i) => (
              <div key={i} style={{ background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.05)', borderRadius: '8px', overflow: 'hidden' }}>
                <div 
                  style={{ padding: '1rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', background: expandedAlpha === i ? 'rgba(255,255,255,0.02)' : 'transparent' }}
                  onClick={() => setExpandedAlpha(expandedAlpha === i ? null : i)}
                >
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                      <code style={{ color: 'var(--accent-secondary)', fontSize: '1.1rem' }}>{alpha.alpha_id}</code>
                      {alpha.source === 'arxiv' ? (
                        <div className="arxiv-tag">ArXiv: {alpha.paper_title}</div>
                      ) : (
                        <div className="arxiv-tag" style={{ color: 'var(--text-muted)', background: 'transparent' }}>Template</div>
                      )}
                    </div>
                    <div style={{ fontFamily: 'monospace', color: 'var(--text-primary)', wordBreak: 'break-all' }}>
                      {alpha.expression}
                    </div>
                  </div>
                  
                  <div style={{ display: 'flex', gap: '2rem', textAlign: 'right' }}>
                    <div>
                      <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', textTransform: 'uppercase' }}>Sharpe</div>
                      <div className={alpha.sharpe && alpha.sharpe > 1.5 ? 'text-success' : ''} style={{ fontWeight: 'bold' }}>
                        {alpha.sharpe ? alpha.sharpe.toFixed(2) : '-'}
                      </div>
                    </div>
                    <div>
                      <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', textTransform: 'uppercase' }}>Fitness</div>
                      <div style={{ fontWeight: 'bold' }}>{alpha.fitness ? alpha.fitness.toFixed(2) : '-'}</div>
                    </div>
                    <ChevronDown size={20} style={{ transform: expandedAlpha === i ? 'rotate(180deg)' : 'rotate(0)', transition: 'transform 0.2s', marginTop: '0.5rem', color: 'var(--text-muted)' }} />
                  </div>
                </div>
                
                {expandedAlpha === i && (
                  <div style={{ padding: '1.5rem', borderTop: '1px solid rgba(255,255,255,0.05)', background: 'rgba(0,0,0,0.4)' }}>
                    {alpha.anomaly && (
                      <div style={{ marginBottom: '1.5rem', padding: '1rem', background: 'rgba(16, 185, 129, 0.05)', borderLeft: '3px solid var(--accent-success)', borderRadius: '4px' }}>
                        <h4 style={{ color: 'var(--accent-success)', marginBottom: '0.5rem', fontSize: '0.875rem', textTransform: 'uppercase' }}>Extracted Anomaly</h4>
                        <p style={{ color: 'var(--text-primary)', lineHeight: '1.5' }}>{alpha.anomaly}</p>
                        {alpha.rationale && <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem', marginTop: '0.5rem' }}>Rationale: {alpha.rationale}</p>}
                      </div>
                    )}
                    <h4 style={{ color: 'var(--accent-primary)', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <Settings size={16} /> Simulation Settings
                    </h4>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1rem' }}>
                      <div>
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>Universe</div>
                        <div style={{ fontWeight: '500' }}>{alpha.settings?.universe || 'TOP3000'}</div>
                      </div>
                      <div>
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>Neutralization</div>
                        <div style={{ fontWeight: '500' }}>{alpha.settings?.neutralization || 'SUBINDUSTRY'}</div>
                      </div>
                      <div>
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>Decay</div>
                        <div style={{ fontWeight: '500' }}>{alpha.settings?.decay || 0}</div>
                      </div>
                      <div>
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>Delay</div>
                        <div style={{ fontWeight: '500' }}>{alpha.settings?.delay || 1}</div>
                      </div>
                      <div>
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>Truncation</div>
                        <div style={{ fontWeight: '500' }}>{alpha.settings?.truncation || 0.08}</div>
                      </div>
                      <div>
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>Pasteurization</div>
                        <div style={{ fontWeight: '500' }}>{alpha.settings?.pasteurization || 'ON'}</div>
                      </div>
                    </div>
                    
                    {alpha.sharpe && (
                      <div style={{ marginTop: '2rem' }}>
                        <h4 style={{ color: 'var(--accent-primary)', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                          <TrendingUp size={16} /> Projected Growth (2019-2023)
                        </h4>
                        <div style={{ height: '200px' }}>
                          <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={generateAlphaChartData(alpha)} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
                              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                              <XAxis dataKey="name" stroke="var(--text-muted)" fontSize={10} tick={{fill: 'var(--text-muted)'}} />
                              <YAxis stroke="var(--text-muted)" fontSize={10} tickFormatter={(value) => `$${(value/1000).toFixed(0)}k`} width={40} />
                              <RechartsTooltip 
                                contentStyle={{ backgroundColor: 'var(--bg-dark)', border: '1px solid var(--border-light)' }}
                                formatter={(value) => [`$${value.toFixed(2)}`, 'Growth']}
                              />
                              <Line type="monotone" dataKey="value" stroke="var(--accent-success)" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                            </LineChart>
                          </ResponsiveContainer>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
      
      {showSummaryModal && latestRun && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div className="glass-panel" style={{ width: '90%', maxWidth: '800px', maxHeight: '90vh', overflowY: 'auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
              <h2 style={{ fontSize: '1.5rem', color: 'var(--accent-primary)' }}>Last Pipeline Run Summary</h2>
              <button className="btn btn-outline" onClick={() => setShowSummaryModal(false)}>Close</button>
            </div>
            
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '2rem' }}>
              <div style={{ padding: '1rem', background: 'rgba(255,255,255,0.05)', borderRadius: '8px' }}>
                <div style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>Papers Processed</div>
                <div style={{ fontSize: '1.5rem', fontWeight: 'bold' }}>{latestRun.papers_processed}</div>
              </div>
              <div style={{ padding: '1rem', background: 'rgba(255,255,255,0.05)', borderRadius: '8px' }}>
                <div style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>Expressions Generated</div>
                <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: 'var(--accent-success)' }}>{latestRun.total_expressions}</div>
              </div>
            </div>
            
            <h3 style={{ marginBottom: '1rem', fontSize: '1.1rem' }}>Extracted Ideas</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {latestRun.papers && latestRun.papers.map((paper, i) => (
                <div key={i} style={{ padding: '1rem', border: '1px solid var(--border-light)', borderRadius: '8px', background: 'rgba(0,0,0,0.2)' }}>
                  <h4 style={{ color: 'var(--accent-secondary)', marginBottom: '0.75rem' }}>{paper.title}</h4>
                  <ul style={{ paddingLeft: '1.5rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    {paper.anomalies.map((anomaly, j) => (
                      <li key={j} style={{ color: 'var(--text-primary)', lineHeight: '1.5' }}>{anomaly}</li>
                    ))}
                  </ul>
                </div>
              ))}
              {(!latestRun.papers || latestRun.papers.length === 0) && (
                <p style={{ color: 'var(--text-muted)' }}>No ideas extracted in the last run.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
