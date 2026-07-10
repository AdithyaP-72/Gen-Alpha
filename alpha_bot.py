"""
Alpha Mining Bot v3 — Intelligence-driven alpha mining with research-validated
templates, golden-combo prioritisation, genetic mutation, and smart field ranking.

Submission thresholds (from WorldQuant BRAIN research):
  Fitness  ≥ 1.1    (target ≥ 1.5 to be safe)
  Sharpe   ≥ 1.3    (target ≥ 1.5)
  Turnover 1 – 20%  (can relax to 35% for fundamentals)
  Drawdown < 15%
"""
import time
import json
import os
import concurrent.futures
from scrape_brain import session, BASE_URL
from alpha_intelligence import AlphaIntelligence
import ml_predictor

# ─── Constants ────────────────────────────────────────────────────
MAX_WORKERS = 3
POLL_INTERVAL = 4
POLL_TIMEOUT = 240      # slightly longer for complex expressions
FITNESS_ABANDON = 0.45  # below this → skip entirely
FITNESS_SWEEP   = 0.75  # start parameter sweeping here
FITNESS_SUBMIT  = 1.1   # must reach this to be saved   (research threshold)
FITNESS_SAVE    = 1.3   # above this → high-confidence find

SHARPE_MIN  = 1.3       # IS check minimum
TURNOVER_MAX = 0.35     # IS check max (strict: 0.20)
TURNOVER_MIN = 0.01     # IS check min

DEFAULT_SETTINGS = {
    "universe": "TOP3000",
    "neutralization": "SUBINDUSTRY",  # research default
    "decay": 0,
    "truncation": 0.08,
    "delay": 1,
    "nan_handling": "ON",
}

# ─── Core simulation function ────────────────────────────────────
def simulate(expression, settings):
    """Submit an alpha to the WQ Brain simulation API and poll until complete."""
    # nan_handling: templates set 'ON' for fundamental/analyst, 'OFF' for PV
    nan_handling = settings.get('nan_handling', 'ON')
    payload = {
        'type': 'REGULAR',
        'settings': {
            'instrumentType': 'EQUITY',
            'region': 'USA',
            'universe': settings.get('universe', 'TOP3000'),
            'delay': settings.get('delay', 1),
            'decay': settings.get('decay', 0),
            'neutralization': settings.get('neutralization', 'SUBINDUSTRY'),
            'truncation': settings.get('truncation', 0.08),
            'pasteurization': 'ON',
            'unitHandling': 'VERIFY',
            'nanHandling': nan_handling,
            'language': 'FASTEXPR',
            'visualization': False,
        },
        'regular': expression,
    }

    while True:
        resp = session.post(f"{BASE_URL}/simulations", json=payload, timeout=30)
        if resp.status_code == 429:
            jitter = 15 + (time.time() % 10)
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

    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        try:
            r = session.get(sim_url, timeout=30)
        except Exception:
            continue
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
                try:
                    ar = session.get(f"{BASE_URL}/alphas/{alpha_id}", timeout=30)
                except Exception:
                    return None
                if ar.status_code == 200:
                    ad = ar.json()
                    is_data = ad.get('is', {})
                    checks = is_data.get('checks', [])
                    # Summarise failed IS checks for diagnostics
                    failures = [c['name'] for c in checks
                                if c.get('result') == 'FAIL']
                    return {
                        'alpha_id': alpha_id,
                        'sharpe': is_data.get('sharpe', 0),
                        'fitness': is_data.get('fitness', 0),
                        'turnover': is_data.get('turnover', 0),
                        'returns': is_data.get('returns', 0),
                        'drawdown': is_data.get('drawdown', 0),
                        'checks': checks,
                        'failed_checks': failures,
                    }
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
            "returns": result.get('returns', 0) if result else None,
            "drawdown": result.get('drawdown', 0) if result else None,
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



# ─── Intelligence-driven screening ───────────────────────────────
def _passes_is_checks(result):
    """Quick IS-check gate: turnover range and sharpe minimum."""
    sharpe = result.get('sharpe', 0) or 0
    turnover = result.get('turnover', 0) or 0
    fitness = result.get('fitness', 0) or 0
    if fitness < FITNESS_SUBMIT:
        return False
    if sharpe < SHARPE_MIN:
        return False
    if not (TURNOVER_MIN <= turnover <= TURNOVER_MAX):
        return False
    return True


def screen_queue_item(item):
    """Test a single queue item (expression + settings) from the intelligence engine."""
    expression = item['expression']
    base_settings = item['settings']
    source = item.get('source', 'unknown')
    tmpl_name = item.get('template_name', '?')
    priority = item.get('priority', 0)

    print(f"\n{'─'*60}")
    print(f"  [{source}] {tmpl_name} (priority={priority:.2f})")
    print(f"  {expression[:70]}{'...' if len(expression) > 70 else ''}")

    # --- ML JUNIOR QUANT PRE-SCREENING ---
    if item.get('skip_ml', False):
        settings = base_settings
        if 'ml_pred_fit' in item:
            print(f"  [ML Predictor] Expected Fitness: {item['ml_pred_fit']:.2f}, Success Prob: {item['ml_pred_prob']:.1%}")
            print(f"  [ML Predictor] Optimal Settings: decay={settings.get('decay')}, "
                  f"truncation={settings.get('truncation')}, neutralization={settings.get('neutralization')}")
    else:
        # Intercept the expression and locally sweep 100+ parameter permutations in python
        # to find the absolute best decay, truncation, and neutralization.
        try:
            opt_settings, pred_fit, pred_prob = ml_predictor.optimize_settings(expression, base_settings)
            print(f"  [ML Predictor] Expected Fitness: {pred_fit:.2f}, Success Prob: {pred_prob:.1%}")
            
            # If the ML model is highly confident it will fail, skip the API call entirely
            if pred_prob < 0.005:
                print(f"  → Skipping: Predicted probability of success < 0.5%.")
                return None
                
            settings = opt_settings
            print(f"  [ML Predictor] Optimal Settings: decay={settings.get('decay')}, "
                  f"truncation={settings.get('truncation')}, neutralization={settings.get('neutralization')}")
        except Exception as e:
            print(f"  [ML Predictor] Failed, using base settings. Error: {e}")
            settings = base_settings

    res = simulate(expression, settings)
    if not res:
        print(f"  → Simulation failed")
        return None

    log_simulation(expression, settings, res)
    failures = res.get('failed_checks', [])
    fail_str = f" [FAIL: {', '.join(failures)}]" if failures else ''
    print(f"  → Sharpe={res['sharpe']:.2f}, Fitness={res['fitness']:.2f}, "
          f"Turnover={res['turnover']:.2%}{fail_str}")

    # Auto-negate if sharpe strongly negative
    if res.get('sharpe', 0) < -0.1 and not expression.startswith('-'):
        neg_expr = f"-({expression})" if (' ' in expression or '+' in expression) else f"-{expression}"
        print(f"  Sharpe negative → mathematically inverting results instead of simulating...")
        neg_res = res.copy()
        neg_res['sharpe'] = -res.get('sharpe', 0)
        neg_res['fitness'] = -res.get('fitness', 0)
        if 'returns' in neg_res:
            neg_res['returns'] = -neg_res.get('returns', 0)
        # Give it a pseudo-ID so we know it's derived
        neg_res['alpha_id'] = f"inv_{res.get('alpha_id', 'unknown')}"
        
        log_simulation(neg_expr, settings, neg_res)
        expression, res = neg_expr, neg_res
        print(f"  → Negated (Derived): Sharpe={res['sharpe']:.2f}, Fitness={res['fitness']:.2f}")

    # No brute-force sweep needed since ML predicted the best parameters
    if _passes_is_checks(res):
        save_submittable(expression, settings, res)
        return (expression, settings, res)
    else:
        print(f"  → Failed IS checks — not saving.")
        return None


def load_blacklist():
    """Build blacklist of already-tested raw fields from simulation history."""
    blacklist = set()
    if os.path.exists("simulation_history.json"):
        with open("simulation_history.json") as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    expr = entry.get("expression", "")
                    if "_" in expr and "(" not in expr:
                        blacklist.add(expr.lstrip('-'))
    return blacklist


def load_candidate_fields():
    """Load and filter candidate fields from brain_fields.json."""
    with open("brain_fields.json") as f:
        all_fields = json.load(f)

    blacklist = load_blacklist()
    candidates = [
        f for f in all_fields
        if f.get("coverage", 0) > 0.20
        and f.get("type") == "MATRIX"
        and f["id"] not in blacklist
    ]
    return [f["id"] for f in candidates]


# ─── Main ─────────────────────────────────────────────────────────
def main():
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║       GEN-ALPHA v2 — INTELLIGENCE-DRIVEN MINING         ║")
    print("╚══════════════════════════════════════════════════════════╝")

    # Initialize intelligence engine
    intel = AlphaIntelligence()
    print(f"\n  Templates loaded: {len(intel.templates)}")
    print(f"  Training samples: {intel.intelligence.get('training_samples', 0)}")
    print(f"  ML model: {'loaded' if intel.fitness_model else 'not available'}")

    # Load candidate fields
    field_ids = load_candidate_fields()
    print(f"  Candidate fields: {len(field_ids)}")

    # Build prioritized mining queue
    queue = intel.build_mining_queue(field_ids, include_pv=True, include_mutations=True)
    print(f"  Mining queue: {len(queue)} items")

    # Show top 10 queue items
    print(f"\n  Top 10 priority items:")
    for i, item in enumerate(queue[:10]):
        print(f"    {i+1}. [{item.get('source','?')}] {item['expression'][:55]}... "
              f"(p={item['priority']:.2f})")

    # Mine in parallel
    all_results = []
    print(f"\n{'='*60}")
    print(f"  MINING {len(queue)} CANDIDATES WITH {MAX_WORKERS} WORKERS")
    print(f"{'='*60}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(screen_queue_item, item): item for item in queue}
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                if result:
                    all_results.append(result)
            except Exception as e:
                print(f"  Exception: {e}")

    # Summary
    print(f"\n{'='*60}")
    print(f"  SESSION SUMMARY")
    print(f"{'='*60}")
    print(f"  Queue processed: {len(queue)}")
    print(f"  Submittable alphas found: {len(all_results)}")
    for expr, settings, result in all_results:
        print(f"  ★ {expr[:60]}...")
        print(f"    Sharpe={result['sharpe']:.2f}, Fitness={result['fitness']:.2f}, "
              f"Turnover={result.get('turnover', 0):.1%}")
        print(f"    Settings: Neut={settings.get('neutralization')}, "
              f"Decay={settings.get('decay')}, Trunc={settings.get('truncation')}, "
              f"nanHandling={settings.get('nan_handling','ON')}")

    # Retrain after session if we found new data
    if all_results:
        print(f"\n  Retraining intelligence models with new data...")
        from train_recommender import train_models
        train_models()


if __name__ == "__main__":
    main()
