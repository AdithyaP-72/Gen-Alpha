# Intelligent Alpha Mining Architecture

## Overview
The Gen-Alpha v3 pipeline is a fully autonomous quantitative research engine. It continually loops over highly viable quantitative research domains, reads papers from ArXiv, uses LLaMA 3.3 to extract mathematical anomalies, pre-screens them using a custom Gradient Boosting model, and executes them on the WorldQuant BRAIN API.

## Core Components

### 1. Research Domains
The system cycles through 6 carefully curated research domains that have strong historical viability in academic literature (ArXiv):
1. **Price Momentum & Trend**: `cat:q-fin.TR AND (cross-sectional momentum equity returns)`
2. **Statistical Arbitrage & Pairs**: `cat:q-fin.TR AND (statistical arbitrage OR pairs trading OR cointegration)`
3. **Earnings Surprise & PEAD**: `cat:q-fin.ST AND (post-earnings announcement drift OR earnings surprise)`
4. **News Sentiment & NLP**: `cat:q-fin.ST AND (news sentiment OR social media stock returns)`
5. **Options-Implied Volatility**: `cat:q-fin.PR AND (implied volatility skew OR options-implied information)`
6. **Market Microstructure**: `cat:q-fin.TR AND (market microstructure OR liquidity anomaly)`

### 2. Auto-Cycling Pipeline (`genalpha/auto_pipeline.py`)
This is the core execution loop.
- **Round-Robin Cycling**: Continuously loops through the domains.
- **Extraction**: Fetches 2 abstract payloads per domain and queries `llama-3.3-70b-versatile`.
- **Validation**: Ensures the generated FASTEXPR expressions use only valid operators from `brain_operators.json`.
- **ML Pre-Screening**: Passes each expression to the Gradient Boosting model. Only expressions with a `> 2%` predicted probability of success are accepted.
- **Simulation**: Accepted expressions are queued and submitted to the WorldQuant BRAIN API one-by-one to avoid rate-limit exhaustion.

### 3. ML Predictor (`genalpha/ml_predictor.py` & `runtime/fitness_model.pkl`)
- Trained on 620+ historical API evaluations (including failed ones).
- Predicts absolute `fitness` and the probability of passing the 1.1 fitness threshold.
- Recommends the optimal decay, truncation, and neutralization settings per alpha.

### 4. React Dashboard (`frontend/src/App.jsx`)
Provides real-time monitoring of the autonomous agent.
- **Unified Pipeline Popup**: Visualizes the live research queue, showing parsed papers, extracted anomalies, ML pass/fail probabilities, and live simulation logs.
- **Portfolio Analytics**: Evaluates cross-sectional correlations to ensure discovered signals are orthogonal.
- **Growth Simulator**: Estimates compound yields of an equal-weighted portfolio of the best discovered signals.

## System Limits
- **WorldQuant API Rate Limits**: The pipeline respects the `429 Too Many Requests` responses with exponential backoff.
- **Groq API Rate Limits**: Key rotation spreads the load across 3 keys to prevent exhaustion.

## Running the System
```bash
# Terminal 1: Backend API (port 5001 by default)
python3 api_server.py

# Terminal 2: Frontend
cd frontend
npm run dev

# Headless alternative
python3 -m genalpha.auto_pipeline --cycles 1
```
In the browser dashboard, simply click **Trigger Pipeline** to begin the autonomous mining cycle.

## Shipped Upgrades (formerly roadmap)

- ✅ **Optimization Worker → Chain-of-Alpha optimization chain**: near-misses (fitness 0.7–1.1, or ≥1.1 with failed platform checks) get one LLM refinement round driven by their *measured* metrics and failed checks (`auto_pipeline._chain_of_alpha`). Compile errors (BRAIN 400s) feed the exact FASTEXPR error back for ≤2 rewrites.
- ✅ **Multi-Agent Peer Review (Actor-Critic)**: Agent A (70B) generates; Agent B (8B, one batched call per paper) audits for look-ahead bias, neutralization mismatches, vector wrapping, and rationale/math mismatch; ≤1 revision round. All exchanges are logged to the `llm_interactions` table.
- ✅ **Evolutionary Template Bank**: survivors with fitness > 1.2 are AST-generalized (fields → `{FIELD}`) and appended to `research_templates.json` (`alpha_intelligence.promote_to_template_bank`).
- ✅ **Expression Trees**: FASTEXPR parser + typed node mutations (operator swaps constrained by arity, window ladder, category-safe field substitution, subtree crossover between parents) in `alpha_ast.py`.
- ✅ **ML Pessimism fix**: class-balanced sample weights in `train_recommender.py`; **epsilon-greedy** 5% ML-gate bypass in `auto_pipeline.py`.
- ✅ **SQLite Migration**: `alpha_lab.db` (WAL mode) is the experiment store — candidates, runs (incl. failures), papers, LLM interactions, promotions. `migrate_history.py` imports legacy JSONL atomically; JSONL remains as an export.
- ✅ **Data funnel**: local abstract-relevance scoring (`paper_funnel.py`; sentence-transformers optional, keyword fallback) triages ~12 candidates/domain down to the 2 sent to the 70B extractor.
- ✅ **Real analytics**: `/api/correlation` and `/api/portfolio` are measured from per-alpha PnL recordsets (inverse-volatility weighting baseline); nothing synthetic is shown as real.

## Remaining Roadmap

### Phase 1
- **Guidance Layer**: Pass Gradient Boosting feature importance weights into the LLM prompt to provide soft mathematical guidance during alpha generation.
- **UI Sync Indicators**: Add a visual syncing status indicator in the React dashboard for the retraining/fetching phase.

### Phase 2
- **Semantic RAG for Datasets**: Embed all 7,400+ data fields in a lightweight vector DB (FAISS) so the LLM can semantically search for obscure predictive datasets per paper hypothesis.
- **MCTS mutation policy** (RiskMiner, 2024): replace random mutation selection with risk-seeking Monte Carlo Tree Search over the expression ASTs.
- **PPO adaptive alpha weighting**: RL portfolio weights over the cached PnL matrix, benchmarked against the shipped inverse-volatility baseline.
- **Synthetic Theory Generation**: Once ArXiv anomalies hit a ceiling, transition the LLM to propose novel hypotheses grounded in dataset descriptions.

### Phase 3
- **Adaptive Sleep Budgets**: monitor HTTP 429 rates and dynamically throttle (e.g., simulated "sleep" hours) to protect the account from 24/7 hammering.
- **Pool-marginal objective** (AlphaGen): score candidates by marginal contribution to the existing pool rather than standalone fitness, making orthogonality the search objective rather than a dashboard metric.
