# Gen-Alpha: WorldQuant Brain Alpha Mining Engine

Gen-Alpha is an automated, high-throughput, multithreaded alpha-mining pipeline designed for the WorldQuant Brain platform. It programmatically generates expressions, tests them against historical market data, optimizes their parameters via decision-tree sweeping, and harvests institutional-grade, submittable alphas (Fitness > 1.15).

## 🚀 Core Features

- **Parallelized Mining Engine**: Runs a 3-thread concurrent executor to bypass single-request bottlenecks, drastically increasing alpha discovery rates.
- **Dynamic Data Discovery**: Parses thousands of `MATRIX` datasets (`brain_fields.json`), ranking them by historical `alphaCount` to prioritize the most proven Fundamental, PV, and Analyst datasets.
- **Autonomous Parameter Sweeping**: Automatically catches expressions with marginal potential (Fitness > 0.6) and sweeps them through various Neutralization (Sector, Industry, Market) and Decay algorithms to push them over the 1.15 submission threshold.
- **Thundering Herd Jitter & Rate Limiting**: Gracefully handles WorldQuant's strict API burst limits (`HTTP 429`) by applying randomized backoff jitter to desynchronize threads.
- **Dynamic Blacklisting**: Parses `simulation_history.json` on startup to ensure no API cycles are ever wasted re-testing a previously mined data stream.

### 🧪 The Template Hierarchy
When the bot selects a new data field, it sequentially tests it against an escalating hierarchy of mathematical templates. If a template generates a Sharpe < 0, it automatically attempts the negated version. If a template achieves Fitness > 0.6, it immediately halts template escalation and routes the expression into the Parameter Sweep engine.

The current escalation tree is:
1. `[field]` (Raw Field)
2. `-[field]` (Negated Raw Field)
3. `ts_rank([field], 252)` (1-year Time-Series Rank)
4. `-ts_rank([field], 252)` (Negated 1-year Rank)
5. `ts_rank([field], 63)` (1-quarter Time-Series Rank)
6. `[field] - ts_mean([field], 252)` (Deviation from 1-year Mean)
7. `ts_av_diff([field], 63)` (Average Time-Series Difference)
8. `-ts_av_diff([field], 63)` (Negated Average Difference)

---

## 📂 Project Structure

- `alpha_bot.py`: The main autonomous mining engine.
- `scrape_brain.py`: Handles API initialization, session authentication, and raw dataset scraping.
- `test_historical_alphas.py`: A standalone script used for bulk-testing hardcoded, verified historical strategies.
- `plot_fitness.py`: Generates a visual progression graph (`fitness_progression.png`) of your alpha discovery journey.
- `brain_fields.json`: Local cache of WorldQuant's massive dataset directory.
- `simulation_history.json`: The complete log of every simulation ever run by the bot.
- `found_alphas.json`: **The Holy Grail.** A JSON array of fully parameterized, submittable alphas with Fitness > 1.15.

---

## 🛠️ Setup & Execution

### 1. Updating the Session Token (Authentication)
WorldQuant Brain uses rotating JWT session tokens. Your session will periodically expire (usually after 24 hours), causing the bot to fail. When this happens, you must update the token in `scrape_brain.py`.

**How to update:**
1. Log into [WorldQuant Brain](https://platform.worldquantbrain.com/) in your web browser.
2. Press `F12` to open Developer Tools and navigate to the **Network** tab.
3. Perform any action on the platform (e.g., hit "Simulate" on an alpha).
4. Click on any network request going to `api.worldquantbrain.com` (usually named `simulations`).
5. Scroll down to **Request Headers** and locate the `Cookie:` field.
6. Copy the entire string (it will contain `cookieyes-consent=...` and `t=eyJ0...`).
7. Open `scrape_brain.py`, locate the `COOKIES` dictionary, and paste the entire string into the `'cookieyes-consent'` value.

### 2. Running the Mining Bot
Once your session is authenticated, simply run the bot:
```bash
python3 alpha_bot.py
```
The bot will load all remaining unmined fields, queue them up, and begin autonomous testing. 

### 3. Monitoring Progress
While `alpha_bot.py` is running, you can open a new terminal tab and run:
```bash
python3 plot_fitness.py
```
This will read your `simulation_history.json` file and generate a line graph showing the fitness distribution of your discovered alphas over time.

---

## 📈 Manual Submission

Currently, the bot does not automatically submit alphas to the platform (to avoid accidental correlation bans). 
Once the bot finishes a batch, open `found_alphas.json`. Copy the expressions and settings into the WorldQuant Brain web interface, run a quick simulation to verify, check for correlation against your existing portfolio, and hit **Submit**!
