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

### 2. Auto-Cycling Pipeline (`auto_pipeline.py`)
This is the core execution loop.
- **Round-Robin Cycling**: Continuously loops through the domains.
- **Extraction**: Fetches 2 abstract payloads per domain and queries `llama-3.3-70b-versatile`.
- **Validation**: Ensures the generated FASTEXPR expressions use only valid operators from `brain_operators.json`.
- **ML Pre-Screening**: Passes each expression to the Gradient Boosting model. Only expressions with a `> 2%` predicted probability of success are accepted.
- **Simulation**: Accepted expressions are queued and submitted to the WorldQuant BRAIN API one-by-one to avoid rate-limit exhaustion.

### 3. ML Predictor (`ml_predictor.py` & `fitness_model.pkl`)
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
# Terminal 1: Backend API
python3 api_server.py

# Terminal 2: Frontend
cd frontend
npm run dev
```
In the browser dashboard, simply click **Trigger Pipeline** to begin the autonomous mining cycle.

## Future Upgrades & Roadmap

### Phase 1: Immediate Pipeline Enhancements
- **Guidance Layer**: Pass Gradient Boosting feature importance weights into the LLM prompt to provide soft mathematical guidance during alpha generation.
- **Optimization Worker**: Implement a background "Exploiter" worker to perform hyper-parameter grid searches on near-miss alphas (Fitness 0.8–0.99) to push them over the submittable threshold.
- **UI Sync Indicators**: Add a visual syncing status indicator in the React dashboard for the retraining/fetching phase.

### Phase 2: Next-Gen Architecture & Intelligence
- **Evolutionary Template Bank**: Instead of static few-shot examples, promote highly successful alphas (Fitness > 1.2) into the `research_templates.json` bank to replace lower-performing ones, allowing the system to cross-breed its own historical discoveries.
- **Semantic RAG for Datasets**: Move away from hardcoded field prefixes by embedding all 7,400+ WorldQuant data fields in a lightweight vector DB (like FAISS), allowing the LLM to semantically search for obscure predictive datasets based on paper hypotheses.
- **Multi-Agent Peer Review**: Introduce an "Actor-Critic" framework where Agent A (Researcher) generates an expression and Agent B (Risk Manager) audits it for math errors, look-ahead bias, and logic flaws before submission.
- **Synthetic Theory Generation**: Once ArXiv anomalies hit a ceiling, transition the LLM to hallucinate entirely novel, unpublished financial hypotheses by reading raw datasets.

### Phase 3: Mitigating Bottlenecks & Failure Modes
- **ML Pessimism (Mode Collapse)**: Since 95% of alphas fail, the Gradient Boosting model may become overly pessimistic. We will implement SMOTE or strict class-balancing during retraining to prevent the model from rejecting all ideas.
- **Epsilon-Greedy Exploration**: Institute a 5% random simulation rate to bypass the ML predictor, ensuring the model's biases are constantly stress-tested against fresh data.
- **SQLite Migration**: As `simulation_history.json` approaches 10-20MB, the system must be migrated to `alpha_lab.db` (SQLite) to prevent JSON RAM bottlenecking during load and append cycles.
- **Adaptive Sleep Budgets**: To prevent WorldQuant account bans from 24/7 API hammering, the pipeline will monitor HTTP 429 rates and dynamically throttle itself (e.g., simulating "sleep" hours).
