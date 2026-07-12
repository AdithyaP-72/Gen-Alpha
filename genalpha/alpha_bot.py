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
import threading
import concurrent.futures

from genalpha import config
from genalpha.scrape_brain import BASE_URL, AuthError, request_with_retry
from genalpha.alpha_validation import analyze_expression
from genalpha.alpha_selection import should_promote
from genalpha.alpha_store import AlphaStore
from genalpha import ml_predictor

# ─── Constants ────────────────────────────────────────────────────
MAX_WORKERS = 3
POLL_INTERVAL = 4
POLL_TIMEOUT = 480      # slightly longer for complex expressions
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

HISTORY_FILE = config.SIM_HISTORY
FOUND_FILE = config.FOUND_ALPHAS

_write_lock = threading.Lock()
_store = AlphaStore()

_FIELD_INDEX = None


def _get_field_index():
    global _FIELD_INDEX
    if _FIELD_INDEX is None:
        try:
            with open(config.BRAIN_FIELDS) as f:
                _FIELD_INDEX = {fl["id"]: fl for fl in json.load(f)}
        except Exception:
            _FIELD_INDEX = {}
    return _FIELD_INDEX


# ─── Core simulation function ────────────────────────────────────
def simulate(expression, settings):
    """
    Submit an alpha simulation and poll to completion.

    Returns a dict that always carries a 'status' key:
      'COMPLETE'    → sharpe/fitness/turnover/returns/drawdown/checks/failed_checks
      'BAD_REQUEST' → 'error' holds the exact FASTEXPR compiler message
      'ERROR' / 'TIMEOUT' / 'HTTP_ERROR' / 'EXHAUSTED' → 'error' describes the failure

    Raises AuthError when authentication cannot be restored — callers must
    abort the run rather than march through the queue unauthenticated.
    """
    payload = {
        'type': 'REGULAR',
        'settings': {
            'instrumentType': 'EQUITY',
            'region': 'USA',
            'universe': settings.get('universe', 'TOP3000'),
            'delay': settings.get('delay', 1),
            'decay': settings.get('decay', 0),
            'neutralization': settings.get('neutralization', 'SUBINDUSTRY'),
            'truncation': settings.get('truncation', 0.05),
            'pasteurization': 'ON',
            'unitHandling': 'VERIFY',
            'nanHandling': settings.get('nan_handling', 'ON'),
            'language': 'FASTEXPR',
            'visualization': False,
        },
        'regular': expression,
    }

    resp = request_with_retry('POST', f"{BASE_URL}/simulations", json=payload, max_retries=8)
    if resp is None:
        return {'status': 'EXHAUSTED', 'error': 'rate-limit/network retries exhausted on POST'}
    if resp.status_code == 400:
        print(f"  [!] Bad Request for '{expression[:50]}...': {resp.text[:200]}")
        return {'status': 'BAD_REQUEST', 'error': resp.text[:500]}
    if resp.status_code != 201:
        print(f"  [!] HTTP {resp.status_code} for '{expression[:50]}...': {resp.text[:200]}")
        return {'status': 'HTTP_ERROR', 'error': f"HTTP {resp.status_code}: {resp.text[:300]}"}

    sim_url = resp.headers.get('Location')
    if not sim_url:
        return {'status': 'ERROR', 'error': 'simulation created but no Location header returned'}

    start_time = time.time()
    while time.time() - start_time < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        r = request_with_retry('GET', sim_url, max_retries=3)
        if r is None or r.status_code != 200:
            continue
        try:
            data = r.json()
        except ValueError:
            continue
        status = data.get('status')
        if status == 'COMPLETE':
            alpha_id = data.get('alpha')
            if not alpha_id:
                return {'status': 'ERROR', 'error': 'simulation COMPLETE but no alpha id'}
            ar = request_with_retry('GET', f"{BASE_URL}/alphas/{alpha_id}", max_retries=4, timeout=60)
            if ar is None or ar.status_code != 200:
                return {'status': 'ERROR', 'error': f'could not fetch alpha {alpha_id} details'}
            is_data = ar.json().get('is', {})
            checks = is_data.get('checks', [])
            failures = [c['name'] for c in checks if c.get('result') == 'FAIL']
            return {
                'status': 'COMPLETE',
                'alpha_id': alpha_id,
                'sharpe': is_data.get('sharpe', 0),
                'fitness': is_data.get('fitness', 0),
                'turnover': is_data.get('turnover', 0),
                'returns': is_data.get('returns', 0),
                'drawdown': is_data.get('drawdown', 0),
                'checks': checks,
                'failed_checks': failures,
            }
        elif status in ('ERROR', 'FAIL'):
            msg = data.get('message', 'simulation ERROR')
            print(f"  [!] Simulation ERROR for '{expression[:50]}...': {msg[:120]}")
            return {'status': 'ERROR', 'error': str(msg)[:500]}

    print(f"  [!] Simulation TIMEOUT for '{expression[:50]}...' after {POLL_TIMEOUT}s")
    return {'status': 'TIMEOUT', 'error': f'no COMPLETE status within {POLL_TIMEOUT}s'}


def _completed(res):
    return bool(res) and res.get('status') == 'COMPLETE'


def _append_jsonl(path, entry):
    """Thread-safe single-write JSONL append."""
    line = json.dumps(entry) + "\n"
    with _write_lock:
        with open(path, "a") as f:
            f.write(line)
            f.flush()


def log_simulation(expression, settings, result, item=None):
    """Append every simulation outcome (including failures) to simulation_history.json."""
    ok = _completed(result)
    entry = {
        "timestamp": time.time(),
        "expression": expression,
        "settings": settings,
        "source": item.get('source', 'unknown') if item else 'unknown',
        "template_name": item.get('template_name', '?') if item else '?',
        "status": result.get('status') if result else 'ERROR',
        "error": (result.get('error') or '')[:300] if result and not ok else None,
        "sharpe": result.get('sharpe', 0) if ok else None,
        "fitness": result.get('fitness', 0) if ok else None,
        "turnover": result.get('turnover', 0) if ok else None,
        "returns": result.get('returns', 0) if ok else None,
        "drawdown": result.get('drawdown', 0) if ok else None,
    }
    _append_jsonl(HISTORY_FILE, entry)


def save_submittable(expression, settings, result, item=None):
    """Save a passing alpha (with its platform check results) to found_alphas.json."""
    failures = result.get('failed_checks', [])
    entry = {
        "expression": expression,
        "settings": settings,
        "alpha_id": result.get('alpha_id'),
        "sharpe": result.get('sharpe'),
        "fitness": result.get('fitness'),
        "turnover": result.get('turnover'),
        "returns": result.get('returns'),
        "drawdown": result.get('drawdown'),
        "failed_checks": failures,
        "grade": "submittable" if not failures and result.get('fitness', 0) >= FITNESS_SAVE else "marginal",
        "source": item.get('source', 'unknown') if item else 'unknown',
    }
    _append_jsonl(FOUND_FILE, entry)

    # Evolutionary template bank: strong survivors seed future generations.
    try:
        from genalpha.alpha_intelligence import promote_to_template_bank
        if promote_to_template_bank(expression, settings, result.get('fitness')):
            print(f"  [bank] Promoted to research_templates.json (fitness {result.get('fitness'):.2f})")
    except Exception:
        pass


# ─── Intelligence-driven screening ───────────────────────────────
def _passes_is_checks(result):
    """Gate on our thresholds AND the platform's own IS checks."""
    sharpe = result.get('sharpe', 0) or 0
    turnover = result.get('turnover', 0) or 0
    fitness = result.get('fitness', 0) or 0
    if fitness < FITNESS_SUBMIT:
        return False
    if sharpe < SHARPE_MIN:
        return False
    if not (TURNOVER_MIN <= turnover <= TURNOVER_MAX):
        return False
    if result.get('failed_checks'):
        return False
    return True


def _record_to_store(expression, settings, item, result):
    """Persist candidate + run (and promotion, if earned) to the SQLite store."""
    try:
        canonical, metadata = analyze_expression(expression, _get_field_index())
        candidate_id = _store.upsert_candidate({
            "canonical_expression": canonical,
            "expression": expression,
            "settings": settings,
            "source": item.get('source') if item else None,
            "template_name": item.get('template_name') if item else None,
            "hypothesis_family": metadata.get('hypothesis_family'),
            "field": metadata.get('field_id'),
            "mutation_type": item.get('mutation_type', 'none') if item else 'none',
            "priority": item.get('priority', 0) if item else 0,
            "status": "simulated",
            "metadata": metadata,
        })
        ok = _completed(result)
        _store.record_simulation(
            candidate_id,
            'complete' if ok else (result.get('status') or 'error').lower(),
            result=result if ok else None,
            error_text=None if ok else (result or {}).get('error'),
        )
        if ok and _passes_is_checks(result):
            promote, reasons = should_promote(
                canonical, result, metadata,
                neighboring_results=[],
                promoted_rows=_store.get_promoted_signatures(),
                fitness_save=FITNESS_SUBMIT,
            )
            if promote:
                _store.promote_candidate(
                    candidate_id, expression, canonical, settings, result,
                    reasons.get('novelty_score'), reasons.get('robustness_score'), reasons,
                )
        return candidate_id
    except Exception as e:
        print(f"  [store] Failed to record candidate: {e}")
        return None


def screen_queue_item(item):
    """Test a single queue item (expression + settings).

    Returns a dict: {'status': 'passed'|'failed_checks'|'sim_failed'|'ml_rejected',
                     'expression', 'settings', 'result', 'error'}
    Raises AuthError when BRAIN authentication is irrecoverable.
    """
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
    else:
        try:
            opt_settings, pred_fit, pred_prob = ml_predictor.optimize_settings(expression, base_settings)
            print(f"  [ML Predictor] Expected Fitness: {pred_fit:.2f}, Success Prob: {pred_prob:.1%}")
            if pred_prob < 0.005:
                print(f"  → Skipping: Predicted probability of success < 0.5%.")
                return {'status': 'ml_rejected', 'expression': expression,
                        'settings': base_settings, 'result': None, 'error': None}
            settings = opt_settings
            print(f"  [ML Predictor] Optimal Settings: decay={settings.get('decay')}, "
                  f"truncation={settings.get('truncation')}, neutralization={settings.get('neutralization')}")
        except Exception as e:
            print(f"  [ML Predictor] Failed, using base settings. Error: {e}")
            settings = base_settings

    res = simulate(expression, settings)
    log_simulation(expression, settings, res, item)
    _record_to_store(expression, settings, item, res)

    if not _completed(res):
        print(f"  → Simulation failed ({res.get('status')}): {str(res.get('error'))[:120]}")
        return {'status': 'sim_failed', 'expression': expression, 'settings': settings,
                'result': res, 'error': res.get('error')}

    failures = res.get('failed_checks', [])
    fail_str = f" [FAIL: {', '.join(failures)}]" if failures else ''
    print(f"  → Sharpe={res['sharpe']:.2f}, Fitness={res['fitness']:.2f}, "
          f"Turnover={res['turnover']:.2%}{fail_str}")

    # If Sharpe is strongly negative, actually simulate the negated expression.
    # (Sign-flipping locally would fabricate drawdown/checks — see review C2a.)
    if (res.get('sharpe') or 0) < -0.1 and not expression.startswith('-'):
        neg_expr = f"-({expression})" if (' ' in expression or '+' in expression) else f"-{expression}"
        print(f"  Sharpe negative → simulating negated expression for real...")
        neg_res = simulate(neg_expr, settings)
        log_simulation(neg_expr, settings, neg_res, item)
        _record_to_store(neg_expr, settings, item, neg_res)
        if _completed(neg_res) and (neg_res.get('fitness') or 0) > (res.get('fitness') or 0):
            expression, res = neg_expr, neg_res
            print(f"  → Negated: Sharpe={res['sharpe']:.2f}, Fitness={res['fitness']:.2f}")

    if _passes_is_checks(res):
        save_submittable(expression, settings, res, item)
        return {'status': 'passed', 'expression': expression, 'settings': settings,
                'result': res, 'error': None}

    print(f"  → Failed IS checks — not saving.")
    return {'status': 'failed_checks', 'expression': expression, 'settings': settings,
            'result': res, 'error': None}


def load_blacklist():
    """Build blacklist of already-tested raw fields from simulation history."""
    blacklist = set()
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    expr = entry.get("expression", "")
                    if isinstance(expr, str) and "_" in expr and "(" not in expr:
                        blacklist.add(expr.lstrip('-'))
    return blacklist


def load_candidate_fields():
    """Load and filter candidate fields from brain_fields.json."""
    with open(config.BRAIN_FIELDS) as f:
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
    from genalpha.alpha_intelligence import AlphaIntelligence

    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║       GEN-ALPHA v3 — INTELLIGENCE-DRIVEN MINING         ║")
    print("╚══════════════════════════════════════════════════════════╝")

    intel = AlphaIntelligence()
    print(f"\n  Templates loaded: {len(intel.templates)}")
    print(f"  Training samples: {intel.intelligence.get('training_samples', 0)}")
    print(f"  ML model: {'loaded' if intel.fitness_model else 'not available'}")

    field_ids = load_candidate_fields()
    print(f"  Candidate fields: {len(field_ids)}")

    queue = intel.build_mining_queue(field_ids, include_pv=True, include_mutations=True)
    print(f"  Mining queue: {len(queue)} items")

    print(f"\n  Top 10 priority items:")
    for i, item in enumerate(queue[:10]):
        print(f"    {i+1}. [{item.get('source','?')}] {item['expression'][:55]}... "
              f"(p={item['priority']:.2f})")

    all_results = []
    print(f"\n{'='*60}")
    print(f"  MINING {len(queue)} CANDIDATES WITH {MAX_WORKERS} WORKERS")
    print(f"{'='*60}")

    auth_failed = threading.Event()

    def _worker(item):
        if auth_failed.is_set():
            return None
        try:
            return screen_queue_item(item)
        except AuthError as e:
            auth_failed.set()
            print(f"\n  [FATAL] {e}")
            return None

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
    try:
        futures = {executor.submit(_worker, item): item for item in queue}
        for future in concurrent.futures.as_completed(futures):
            try:
                outcome = future.result()
                if outcome and outcome['status'] == 'passed':
                    all_results.append((outcome['expression'], outcome['settings'], outcome['result']))
            except Exception as e:
                print(f"  Exception: {e}")
            if auth_failed.is_set():
                break
    except KeyboardInterrupt:
        print("\n  [INTERRUPT] Cancelling queued work...")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    if auth_failed.is_set():
        print("\n  Run aborted: BRAIN authentication failed. Fix credentials in .env and re-run.")

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

    if all_results:
        print(f"\n  Retraining intelligence models with new data...")
        from genalpha.train_recommender import train_models
        train_models()


if __name__ == "__main__":
    main()
