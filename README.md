# Gen-Alpha: Autonomous Quantitative Research System

Gen-Alpha is an end-to-end alpha-mining pipeline: it sources academic literature from ArXiv, synthesizes tradeable WorldQuant BRAIN expressions with an LLM actor-critic pair (Llama 3.3 70B generator + Llama 3.1 8B reviewer via Groq), pre-screens candidates with a Gradient-Boosting model, simulates them on the BRAIN API with Chain-of-Alpha feedback (compiler errors and near-miss metrics are fed back to the LLM for bounded rewrites), and manages everything from a React dashboard.

Nothing is ever auto-submitted to WorldQuant — the bot *finds* submittable candidates; submission stays human-in-the-loop to avoid correlation bans.

## Repository Layout

```
Gen-Alpha/
├── api_server.py        # entry point: Flask backend (launches the pipeline)
├── genalpha/            # core package
│   ├── config.py        #   every path & env setting in one place
│   ├── auto_pipeline.py #   autonomous domain-cycling loop (run with -m)
│   ├── alpha_bot.py     #   BRAIN simulation engine + screening
│   ├── arxiv_pipeline.py, llm_client.py, paper_funnel.py   # research → LLM
│   ├── alpha_intelligence.py, alpha_ast.py                 # templates + AST mutations
│   ├── alpha_store.py, alpha_validation.py, alpha_selection.py
│   ├── ml_predictor.py, train_recommender.py               # ML gate
│   └── scrape_brain.py, scrape_research.py                 # auth + scrapers
├── scripts/             # utilities: migrate_history, fetch_brain_history,
│                        #   mine_llm_alphas, plot_fitness, pipeline runner, probes
├── data/                # tracked: brain_fields/operators, research_templates,
│                        #   simulation_history.json, found_alphas.json
├── runtime/             # gitignored: alpha_lab.db, logs, pipeline state,
│                        #   PnL cache, trained models, plots
├── docs/architecture.md
└── frontend/            # React dashboard (Vite)
```

Storage locations are configurable in `.env` (`ALPHA_DB_PATH`, `GENALPHA_DATA_DIR`, `GENALPHA_RUNTIME_DIR`) — see `genalpha/config.py`.

## Architecture

1. **Auto-Cycling Pipeline (`genalpha/auto_pipeline.py`)** — cycles 6 research domains (momentum, stat-arb, PEAD, news sentiment, implied volatility, microstructure). Per domain: fetch novel arXiv papers → local relevance funnel (`paper_funnel.py`) → LLM anomaly extraction & expression generation with critic review (`arxiv_pipeline.py`, `llm_client.py`) → ML pre-screen with a 5% epsilon-greedy bypass (`ml_predictor.py`) → BRAIN simulation with feedback chains (`alpha_bot.py`).
2. **Validation (`alpha_validation.py`)** — every expression is checked locally (operators, vector wrappers, syntax) before any API call. Mutations and LLM output that fail validation never reach BRAIN.
3. **Experiment Store (`alpha_store.py` → `runtime/alpha_lab.db`)** — SQLite (WAL mode) records every candidate, simulation run (including failures), paper, and LLM interaction, with lineage. `data/simulation_history.json` (JSON Lines) is kept as a human-readable export. Override the DB location with `ALPHA_DB_PATH` in `.env`.
4. **Intelligence (`alpha_intelligence.py`, `alpha_ast.py`)** — field ranking from learned stats, golden-combo templates, and typed AST mutations (operator swaps, window changes, field substitution, subtree crossover). Survivors with fitness > 1.2 are generalized into `data/research_templates.json` (evolutionary template bank).
5. **ML Recommender (`train_recommender.py`)** — Gradient-Boosting fitness regressor + class-balanced success classifier; auto-retrains when the dataset grows 30%.
6. **API Server (`api_server.py`)** — Flask backend that launches/stops the pipeline and serves alphas, live pipeline state, **measured** PnL correlations, and inverse-volatility portfolio stats.
7. **React Dashboard (`frontend/`)** — leaderboard, alpha library, live pipeline terminal, correlation heatmap and yield projection (all figures are measured or clearly labeled projections).

## Setup

### Prerequisites
- Python 3.9+
- Node.js & npm (v16+)
- A WorldQuant BRAIN account and at least one Groq API key

### 1. Environment
Copy the template and fill in your credentials (never commit `.env`):
```bash
cp .env.example .env
```
Required entries:
```env
WQ_BRAIN_USERNAME=your.email@example.com   # BRAIN login — enables automatic (re)authentication
WQ_BRAIN_PASSWORD=your_password
GROQ_API_KEY_1=gsk_...                     # add GROQ_API_KEY_2..9 for round-robin rotation
```
If you can't use password auth, set `WQ_SESSION_COOKIE` with a browser cookie instead (expires ~24h; password auth re-logins automatically and is strongly preferred).

### 2. Dependencies
```bash
pip install -r requirements.txt
cd frontend && npm install && cd ..
```

### 3. One-time data & migration
```bash
python3 -m genalpha.scrape_brain    # builds data/brain_fields.json / brain_operators.json
python3 scripts/migrate_history.py  # imports data/simulation_history.json into runtime/alpha_lab.db
```

## Running

### Dashboard (recommended)
```bash
# Terminal 1 — backend (port 5001 by default; 5000 collides with macOS AirPlay)
python3 api_server.py

# Terminal 2 — frontend (proxies /api to the backend)
cd frontend && npm run dev
```
Open http://localhost:5173 and click **Trigger Auto Pipeline**. The terminal popup shows papers → ML screening → live simulations. First stop click interrupts gracefully (in-flight work is saved to `recovery_queue.json` and drained on the next run); a second click force-kills.

### Headless
```bash
python3 -m genalpha.auto_pipeline                # continuous
python3 -m genalpha.auto_pipeline --cycles 1     # one pass over all 6 domains
python3 -m genalpha.auto_pipeline --test         # dry run: generate + ML screen, no simulations
python3 scripts/pipeline.py mine                 # template/mutation mining (no LLM)
python3 scripts/mine_llm_alphas.py --limit 10    # simulate previously generated LLM alphas
python3 scripts/fetch_brain_history.py           # sync account history from BRAIN, then:
python3 -m genalpha.train_recommender            # retrain the ML screener
python3 scripts/plot_fitness.py                  # fitness progression chart
```

## Outputs
- `data/found_alphas.json` — candidates that passed the IS thresholds **and** the platform's own checks; each entry carries `failed_checks` and a `grade` (`submittable` / `marginal`). Verify correlation on the platform before submitting.
- `runtime/alpha_lab.db` — full experiment store (candidates, runs, papers, LLM interactions, promoted alphas). Location configurable via `ALPHA_DB_PATH`.
- `runtime/pipeline_progress.log`, `runtime/pipeline_state.json` — live run telemetry (gitignored).

## Notes
- BRAIN rate limits are handled with `Retry-After`-aware backoff; expired sessions re-authenticate automatically (and the run aborts loudly if credentials are wrong, instead of looping).
- The correlation heatmap is computed from real per-alpha PnL recordsets and reports "insufficient data" honestly when they can't be fetched.
- The 5-year yield figures are projections compounded from *measured* in-sample returns and are labeled as such.
