"""
Alpha Mining Bot — Implements the Phase 1/Phase 2 decision tree.
Logs all simulations to simulation_history.json.
Saves submittable alphas to found_alphas.json.
"""
import time
import json
import concurrent.futures
from scrape_brain import session, BASE_URL

# ─── Constants ────────────────────────────────────────────────────
MAX_WORKERS = 3
POLL_INTERVAL = 4        # seconds between status checks
POLL_TIMEOUT  = 200      # seconds max wait per simulation (~3.3 min)
FITNESS_ABANDON = 0.5
FITNESS_SWEEP   = 0.8
FITNESS_SUBMIT  = 1.0
FITNESS_SAVE    = 1.15   # IS fitness threshold before running checker

DEFAULT_SETTINGS = {
    "universe": "TOP3000",
    "neutralization": "SECTOR",
    "decay": 5,
    "truncation": 0.05,
    "delay": 1,
}

CONFIRMED_EXPRESSIONS = [
    # EV/EBITDA Short (Confirmed Fitness 0.98)
    ("-ts_zscore(enterprise_value/ebitda,63)",
     {"universe": "TOP3000", "neutralization": "SUBINDUSTRY", "decay": 0, "truncation": 0.1, "delay": 1}),
    
    # Complex Rank Reversion 2 (Confirmed Fitness 1.02)
    ("decay_days = 2; rel_days_since_max = rank(ts_arg_max(close, 30)); decline_pct = (vwap - close) / close; decline_pct / min( ts_decay_linear(rel_days_since_max, decay_days), 0.20)",
     {"universe": "TOP3000", "neutralization": "SUBINDUSTRY", "decay": 10, "truncation": 0.01, "delay": 1}),
     
    # High Low Close Reversion (Confirmed Fitness 0.85)
    ("(high + low)/2 - close",
     {"universe": "TOP3000", "neutralization": "MARKET", "decay": 10, "truncation": 0.01, "delay": 1}),
    
    # News sentiment conditional (Confirmed Sharpe 2.18, Fitness 0.83)
    ("avg_news = vec_avg(nws12_afterhsz_sl); rank(ts_sum(avg_news, 60)) > 0.5 ? 1 : rank(-ts_delta(close, 2))",
     {"universe": "TOP3000", "neutralization": "SUBINDUSTRY", "decay": 0, "truncation": 0.08, "delay": 1}),
    
    # Volatility regime (Confirmed Sharpe 0.92, Fitness 0.52)
    ("trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.55, -ts_regression(returns, ts_delay(returns,1), 252), -1)",
     {"universe": "TOP3000", "neutralization": "SUBINDUSTRY", "decay": 5, "truncation": 0.1, "delay": 1})
]

# ─── Template hierarchy (Phase 1) ────────────────────────────────
def make_templates(field):
    """Return expression templates in priority order for a given field."""
    return [
        field,                                          # Template 1: raw
        f"-{field}",                                    # Template 2: negated
        f"ts_rank({field}, 252)",                       # Template 3
        f"-ts_rank({field}, 252)",                      # Template 4
        f"ts_rank({field}, 63)",                        # Template 5
        f"{field} - ts_mean({field}, 252)",             # Template 6: deviation
        f"ts_av_diff({field}, 63)",                     # Template 7: confirmed operator
        f"-ts_av_diff({field}, 63)",                    # Template 8
    ]

# ─── Core simulation function ────────────────────────────────────
def simulate(expression, settings):
    """
    Submit an alpha to the WQ Brain simulation API and poll until complete.
    Returns dict with 'sharpe', 'fitness', 'turnover', 'alpha_id', etc. or None.
    """
    payload = {
        'type': 'REGULAR',
        'settings': {
            'instrumentType': 'EQUITY',
            'region': 'USA',
            'universe': settings.get('universe', 'TOP3000'),
            'delay': settings.get('delay', 1),
            'decay': settings.get('decay', 5),
            'neutralization': settings.get('neutralization', 'SECTOR'),
            'truncation': settings.get('truncation', 0.05),
            'pasteurization': 'ON',
            'unitHandling': 'VERIFY',
            'nanHandling': 'OFF',
            'language': 'FASTEXPR',
            'visualization': False,
        },
        'regular': expression,
    }

    while True:
        resp = session.post(f"{BASE_URL}/simulations", json=payload)

        if resp.status_code == 429:
            jitter = 15 + (time.time() % 10) # random-ish jitter between 15-25s
            print(f"  [!] Rate limited. Sleeping {jitter:.1f}s...")
            time.sleep(jitter)
            continue
        if resp.status_code == 400:
            print(f"  [!] Bad Request for '{expression[:50]}...': {resp.text[:200]}")
            return None
        if resp.status_code != 201:
            print(f"  [!] HTTP {resp.status_code} for '{expression[:50]}...': {resp.text[:200]}")
            return None
        break

    sim_url = resp.headers.get('Location')
    if not sim_url:
        return None

    # Poll until COMPLETE
    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        r = session.get(sim_url)
        if r.status_code == 429:
            time.sleep(10)
            elapsed += 10
            continue
        if r.status_code != 200:
            continue
        data = r.json()
        status = data.get('status')
        if status == 'COMPLETE':
            alpha_id = data.get('alpha')
            if alpha_id:
                ar = session.get(f"{BASE_URL}/alphas/{alpha_id}")
                if ar.status_code == 200:
                    ad = ar.json()
                    is_data = ad.get('is', {})
                    result = {
                        'alpha_id': alpha_id,
                        'sharpe': is_data.get('sharpe', 0),
                        'fitness': is_data.get('fitness', 0),
                        'turnover': is_data.get('turnover', 0),
                        'returns': is_data.get('returns', 0),
                        'drawdown': is_data.get('drawdown', 0),
                        'checks': is_data.get('checks', []),
                    }
                    return result
            return None
        elif status in ('ERROR',):
            print(f"  [!] Simulation ERROR for '{expression[:50]}...'")
            return None

    print(f"  [!] Simulation TIMEOUT for '{expression[:50]}...' after {POLL_TIMEOUT}s")
    return None

def log_simulation(expression, settings, result):
    """Append every simulation result to simulation_history.json."""
    with open("simulation_history.json", "a") as f:
        entry = {
            "timestamp": time.time(),
            "expression": expression,
            "settings": settings,
            "sharpe": result.get('sharpe', 0) if result else None,
            "fitness": result.get('fitness', 0) if result else None,
            "turnover": result.get('turnover', 0) if result else None,
        }
        json.dump(entry, f)
        f.write("\n")

def save_submittable(expression, settings, result):
    """Save a passing alpha to found_alphas.json."""
    with open("found_alphas.json", "a") as f:
        entry = {
            "expression": expression,
            "settings": settings,
            "alpha_id": result.get('alpha_id'),
            "sharpe": result.get('sharpe'),
            "fitness": result.get('fitness'),
            "turnover": result.get('turnover'),
            "returns": result.get('returns'),
        }
        json.dump(entry, f)
        f.write("\n")

# ─── Phase 2: Parameter sweep ────────────────────────────────────
def parameter_sweep(expression, base_settings, initial_fitness, initial_result):
    """
    Decision tree:
      < 0.5        → ABANDON
      0.5 – 0.8    → Neutralization sweep first, then decay sweep
      0.8 – 1.0    → Decay sweep
      > 1.0        → Save as submittable
    Returns best (settings, result) or None.
    """
    if initial_fitness < FITNESS_ABANDON:
        print(f"  [✗] Fitness {initial_fitness:.2f} < {FITNESS_ABANDON} → ABANDON")
        return None

    best_fitness = initial_fitness
    best_settings = base_settings.copy()
    best_result = initial_result

    # ── Round 1: Neutralization sweep (if fitness 0.5 – 0.8) ──
    if initial_fitness < FITNESS_SWEEP:
        print(f"  [~] Fitness {initial_fitness:.2f} in [0.5, 0.8) → Neutralization sweep")
        for neut in ["SUBINDUSTRY", "INDUSTRY", "MARKET"]:
            if neut == base_settings.get('neutralization'):
                continue
            trial = base_settings.copy()
            trial['neutralization'] = neut
            print(f"    Trying neutralization={neut}...")
            res = simulate(expression, trial)
            if res:
                log_simulation(expression, trial, res)
                print(f"    → Sharpe={res['sharpe']:.2f}, Fitness={res['fitness']:.2f}")
                if res['fitness'] > best_fitness:
                    best_fitness = res['fitness']
                    best_settings = trial
                    best_result = res
        # No early exit here. Fall through to decay sweep.

    # ── Round 2: Decay sweep (if fitness 0.8 – 1.0) ──
    if best_fitness < FITNESS_SUBMIT:
        print(f"  [~] Fitness {best_fitness:.2f} in [0.8, 1.0) → Decay sweep")
        for decay in [0, 3, 8, 15]:
            if decay == best_settings.get('decay'):
                continue
            trial = best_settings.copy()
            trial['decay'] = decay
            print(f"    Trying decay={decay}...")
            res = simulate(expression, trial)
            if res:
                log_simulation(expression, trial, res)
                print(f"    → Sharpe={res['sharpe']:.2f}, Fitness={res['fitness']:.2f}")
                if res['fitness'] > best_fitness:
                    best_fitness = res['fitness']
                    best_settings = trial
                    best_result = res
                if best_fitness >= FITNESS_SUBMIT:
                    print(f"  [✓] Crossed 1.0 with decay={decay}!")
                    break

        # Last resort: try truncation 0.08
        if best_fitness < FITNESS_SUBMIT:
            trial = best_settings.copy()
            trial['truncation'] = 0.08
            print(f"    Last resort: truncation=0.08...")
            res = simulate(expression, trial)
            if res:
                log_simulation(expression, trial, res)
                print(f"    → Sharpe={res['sharpe']:.2f}, Fitness={res['fitness']:.2f}")
                if res['fitness'] > best_fitness:
                    best_fitness = res['fitness']
                    best_settings = trial
                    best_result = res

        if best_fitness < FITNESS_SUBMIT:
            print(f"  [✗] Best fitness after all sweeps: {best_fitness:.2f} < {FITNESS_SUBMIT} → ABANDON")
            return None

    # ── Fitness > 1.0: check if saveable ──
    if best_fitness >= FITNESS_SAVE:
        print(f"  [★] FITNESS {best_fitness:.2f} >= {FITNESS_SAVE} → SUBMITTABLE!")
        return (best_settings, best_result)
    elif best_fitness >= FITNESS_SUBMIT:
        print(f"  [◆] FITNESS {best_fitness:.2f} > 1.0 but < {FITNESS_SAVE}. Marginal — saving for review.")
        return (best_settings, best_result)

    return None

# ─── Phase 1: Initial screening ──────────────────────────────────
def screen_field(field_name):
    """
    Apply template hierarchy to a field. Start with raw field, 
    escalate only if needed. Returns list of (expression, settings, result).
    """
    print(f"\n{'='*60}")
    print(f"SCREENING: {field_name}")
    print(f"{'='*60}")

    settings = DEFAULT_SETTINGS.copy()
    templates = make_templates(field_name)

    # Template 1: raw field
    expr = templates[0]
    print(f"\n  Template 1 (raw): {expr}")
    res = simulate(expr, settings)
    if res:
        log_simulation(expr, settings, res)
        print(f"  → Sharpe={res['sharpe']:.2f}, Fitness={res['fitness']:.2f}, Turnover={res['turnover']:.2%}")

        # If Sharpe is negative, try Template 2 (negated) before doing anything else
        if res['sharpe'] < 0:
            print(f"  Sharpe negative → trying negated...")
            expr = templates[1]
            res = simulate(expr, settings)
            if res:
                log_simulation(expr, settings, res)
                print(f"  → Sharpe={res['sharpe']:.2f}, Fitness={res['fitness']:.2f}")

        # If fitness > 0.6 with raw/negated, go straight to parameter sweep
        if res and res['fitness'] >= 0.6:
            print(f"  Raw/negated fitness {res['fitness']:.2f} >= 0.6 → parameter sweep")
            sweep_result = parameter_sweep(expr, settings, res['fitness'], res)
            if sweep_result:
                best_settings, best_result = sweep_result
                save_submittable(expr, best_settings, best_result)
                return [(expr, best_settings, best_result)]

        # If raw fitness < 0.6, try templates 3+
        if res and res['fitness'] < 0.6:
            print(f"  Raw fitness < 0.6 → trying other templates...")
            for i, tmpl_expr in enumerate(templates[2:], start=3):
                print(f"\n  Template {i}: {tmpl_expr}")
                res = simulate(tmpl_expr, settings)
                if res:
                    log_simulation(tmpl_expr, settings, res)
                    print(f"  → Sharpe={res['sharpe']:.2f}, Fitness={res['fitness']:.2f}")
                    if res['fitness'] >= FITNESS_ABANDON:
                        sweep_result = parameter_sweep(tmpl_expr, settings, res['fitness'], res)
                        if sweep_result:
                            best_settings, best_result = sweep_result
                            save_submittable(tmpl_expr, best_settings, best_result)
                            return [(tmpl_expr, best_settings, best_result)]
    else:
        print(f"  → Simulation failed (None returned)")

    print(f"\n  [✗] All templates exhausted for {field_name}")
    return []

def run_confirmed(confirmed_list):
    """Run confirmed, fully-parameterized expressions immediately and sweep them."""
    print("=== RUNNING CONFIRMED EXPRESSIONS ===")
    all_res = []
    for expr, settings in confirmed_list:
        print(f"\nRunning confirmed: {expr[:60]}...")
        res = simulate(expr, settings)
        if res:
            log_simulation(expr, settings, res)
            print(f"  Sharpe={res['sharpe']:.2f}, Fitness={res['fitness']:.2f}")
            if res['fitness'] >= FITNESS_SAVE:
                save_submittable(expr, settings, res)
                all_res.append((expr, settings, res))
            elif res['fitness'] >= FITNESS_ABANDON:
                # Need to sweep it if it didn't cross 1.15
                print("  Running parameter sweep on confirmed expression...")
                sweep_result = parameter_sweep(expr, settings, res['fitness'], res)
                if sweep_result:
                    best_settings, best_result = sweep_result
                    save_submittable(expr, best_settings, best_result)
                    all_res.append((expr, best_settings, best_result))
    return all_res

# ─── Main ─────────────────────────────────────────────────────────
def main():
    all_results = []
    
    # Step 1: Run confirmed expressions (Skipped - already completed and saved to found_alphas.json)
    # conf_results = run_confirmed(CONFIRMED_EXPRESSIONS)
    # all_results.extend(conf_results)

    # Step 2: Load fields from scrape
    print("\nLoading fields from brain_fields.json...")
    with open("brain_fields.json") as f:
        all_fields = json.load(f)
        
    # Get top 10 highest coverage MATRIX fields, excluding pv and fundamental
    # Dynamically build blacklist from previously screened fields
    BLACKLIST_FIELDS = set([
        "anl4_adjusted_netincome_ft",
        "unsystematic_risk_last_360_days"
    ])
    
    try:
        with open("simulation_history.json", "r") as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    # The raw template (Template 1) is just the field name itself
                    expr = entry.get("expression", "")
                    if "_" in expr and "(" not in expr: 
                        BLACKLIST_FIELDS.add(expr)
    except FileNotFoundError:
        pass
    
    candidates = [
        f for f in all_fields
        if f.get("coverage", 0) > 0.20
        and f.get("type") == "MATRIX"
        and f["id"] not in BLACKLIST_FIELDS
    ]
    # Sort by alpha count to get the most proven fields
    candidates.sort(key=lambda x: x.get("alphaCount", 0), reverse=True)
    priority_fields = [f["id"] for f in candidates]

    print(f"\n╔{'═'*58}╗")
    print(f"║  ALPHA MINING BOT — {len(priority_fields)} candidates queued  {'':>15}║")
    print(f"╚{'═'*58}╝")

    # Step 3: Mine fields in parallel
    print(f"\n=== FIELD MINING: {len(priority_fields)} candidates ===")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(screen_field, field): field for field in priority_fields}
        for future in concurrent.futures.as_completed(futures):
            try:
                results = future.result()
                if results:
                    all_results.extend(results)
            except Exception as e:
                print(f"Exception during screen_field: {e}")

    # Summary
    print(f"\n{'='*60}")
    print(f"SESSION SUMMARY")
    print(f"{'='*60}")
    print(f"Total Submittable Alphas found: {len(all_results)}")
    for expr, settings, result in all_results:
        print(f"  ★ {expr[:60]}...")
        print(f"    Sharpe={result['sharpe']:.2f}, Fitness={result['fitness']:.2f}, "
              f"Neutralization={settings['neutralization']}, Decay={settings['decay']}")


if __name__ == "__main__":
    main()
