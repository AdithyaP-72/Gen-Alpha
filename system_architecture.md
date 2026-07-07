# Gen-Alpha Quantitative Pipeline: System Architecture

## 1. Overview
The Gen-Alpha Pipeline is an autonomous quantitative research engine designed to bridge the gap between academic financial literature and institutional algorithmic trading. It programmatically mines unstructured research from ArXiv, uses Large Language Models (LLMs) to map theoretical financial anomalies into WorldQuant BRAIN mathematical operators, and validates these expressions automatically via the WorldQuant API.

## 2. Pipeline Workflow

### Phase 1: ArXiv Knowledge Mining
1. **Trigger**: The frontend sends a targeted domain query (e.g., "Momentum OR Mean Reversion") to the `/api/generate` endpoint.
2. **Scraping**: `arxiv_pipeline.py` interfaces with the ArXiv API, downloading metadata and full abstract summaries for recent, highly-cited papers in quantitative finance.
3. **Idea Extraction**: The extracted text is sent to the LLM (Llama 3.3 via Groq) alongside `brain_operators.json` context. The LLM identifies specific, tradable mathematical anomalies (e.g., "Non-linear transformation of price-volume data leads to high risk-adjusted momentum.")

### Phase 2: Expression Generation
1. **Translation**: For every extracted idea, the LLM translates the concept into roughly 4-6 distinct combinations of WorldQuant operators (e.g., combining `ts_rank`, `ts_zscore`, `group_rank`).
2. **Metadata Tagging**: The expressions are saved locally to `llm_generated_alphas.json`, tagged with their exact source paper title, the extracted anomaly, and the rationale.

### Phase 3: Institutional Validation (WorldQuant BRAIN)
1. **Trigger**: The user initiates simulation by selecting a Universe (e.g., `TOP3000`) and clicking "Simulate on BRAIN".
2. **Execution**: `mine_llm_alphas.py` logs into the WorldQuant API using configured `.env` credentials. It sequentially builds payloads overriding the universe settings and pushes them to the BRAIN simulation engine.
3. **Validation**: The engine evaluates the expressions over a 5-year historical backtest window (2019–2023). 
4. **Recording**: 
   - **Passes**: Expressions achieving a Sharpe Ratio > 1.25 and Fitness > 1.0 are saved to `found_alphas.json`.
   - **Failures**: Expressions that fail to clear the strict IS threshold are logged to `simulation_history.json`.

## 3. Metrics and Calculations

### WorldQuant Standard Metrics
The platform ranks alphas based on WorldQuant's core algorithmic metrics:
*   **Sharpe Ratio**: A measure of risk-adjusted return. Calculated as the annualized return of the alpha divided by its annualized volatility. A higher Sharpe means better returns per unit of risk.
*   **Fitness**: WorldQuant's proprietary metric that normalizes the Sharpe ratio by trading frequency. Generally approximated as: $Fitness = Sharpe \times \sqrt{\frac{Return}{Turnover}}$.
*   **Turnover**: The percentage of the portfolio replaced in a given time period. Lower turnover is strictly preferred to minimize transaction costs.

### Dashboard Simulations
To simulate financial trajectories without hitting binary WQ recordset endpoints, the frontend deterministically projects growth for each alpha:
*   **Quarterly Growth Base**: Extracted from the annualized return ($R_a$): $R_q = (1 + R_a)^{0.25} - 1$
*   **Deterministic Noise**: Applied via a sine wave parameterized by the unique `alpha_id` hash, constrained by the alpha's actual Maximum Drawdown statistic.
*   **Stress Test**: Forces a deterministic drawdown constraint mirroring the Q1 2020 COVID-19 market drop.

## 4. Current Pipeline Statistics
*   **Total Papers Scanned (Latest Batch)**: 5
*   **Total Market Ideas Extracted**: 3 distinct quantitative anomalies.
*   **Expressions Generated**: 14 distinct LLM alpha formulas attempting to capture the ideas.
*   **Top Validated Alphas**:
    - **LLM-8877** (Sharpe: 1.98, Fitness: 1.13) — *Deep Learning in High Frequency Trading*
    - **LLM-22677** (Sharpe: 1.92, Fitness: 2.45) — *Cross-Sectional Momentum Strategies Using Machine Learning*
    - **LLM-62883** (Sharpe: 1.71, Fitness: 1.02) — *Machine Learning for Quantitative Finance: Fast Reversion Models*

## 5. Portfolio Theory Implementation
In the "Portfolio Simulator", the dashboard assumes an Equal Weight Allocation strategy across the Top 6 highest-Sharpe alphas. Because WorldQuant's standard `alpha` API endpoint does not return complex cross-alpha correlation matrices without specialized `Portfolio` environment execution, the dashboard utilizes a theoretical allocation multiplier mapped to user-defined initial capital budgets (e.g., $10,000,000 USD) to illustrate the combined power of an un-correlated signal library.
