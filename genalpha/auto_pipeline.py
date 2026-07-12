#!/usr/bin/env python3
"""
Auto-Cycling Alpha Mining Pipeline — Continuously cycles through
operator-aware research domains, generates alpha ideas via LLM (with an
actor-critic review pass), pre-screens with an ML model (plus a 5%
epsilon-greedy bypass), and simulates quality candidates on WQ BRAIN with
Chain-of-Alpha feedback: exact compiler errors trigger bounded rewrites,
near-misses trigger one targeted refinement.

Usage:
    python auto_pipeline.py              # Run continuously
    python auto_pipeline.py --cycles 1   # Run one cycle through all domains
    python auto_pipeline.py --test       # Dry-run: generate + ML screen only, no BRAIN submission
"""

import argparse
import json
import os
import random
import signal
import tempfile
import time

from genalpha import config
from genalpha.pipeline_logging import log
from genalpha.arxiv_pipeline import process_paper, load_existing_templates, load_field_index, validate_expression
from genalpha.alpha_bot import screen_queue_item
from genalpha.alpha_store import AlphaStore
from genalpha.llm_client import GroqClient
from genalpha.scrape_brain import AuthError
from genalpha.paper_funnel import select_top_papers

import arxiv

# ─── Operator-Aware Research Domains ──────────────────────────────
DOMAINS = [
    {
        "id": "momentum_trend",
        "label": "Price Momentum & Trend",
        "query": "cat:q-fin.TR AND (cross-sectional momentum equity returns)",
        "target_fields": ["close", "returns", "vwap", "volume"],
        "key_operators": ["ts_rank", "ts_delta", "ts_mean", "ts_zscore"],
    },
    {
        "id": "stat_arb",
        "label": "Statistical Arbitrage & Pairs",
        "query": "cat:q-fin.TR AND (statistical arbitrage OR pairs trading OR cointegration)",
        "target_fields": ["close", "returns", "vwap"],
        "key_operators": ["ts_corr", "ts_covariance", "group_rank", "ts_zscore"],
    },
    {
        "id": "earnings_surprise",
        "label": "Earnings Surprise & PEAD",
        "query": "cat:q-fin.ST AND (post-earnings announcement drift OR earnings surprise)",
        "target_fields": ["anl4_", "operating_income", "est_eps"],
        "key_operators": ["ts_delta", "ts_av_diff", "group_zscore"],
    },
    {
        "id": "news_sentiment",
        "label": "News Sentiment & NLP",
        "query": "cat:q-fin.ST AND (news sentiment OR social media stock returns)",
        "target_fields": ["nws12_", "rp_css_", "rp_ess_"],
        "key_operators": ["vec_avg", "ts_sum", "rank", "ts_rank"],
    },
    {
        "id": "implied_volatility",
        "label": "Options-Implied Volatility",
        "query": "cat:q-fin.PR AND (implied volatility skew OR options-implied information)",
        "target_fields": ["implied_volatility", "unsystematic_risk", "beta_"],
        "key_operators": ["ts_rank", "ts_zscore", "ts_delta"],
    },
    {
        "id": "market_microstructure",
        "label": "Market Microstructure",
        "query": "cat:q-fin.TR AND (market microstructure OR liquidity anomaly)",
        "target_fields": ["volume", "close", "vwap", "high", "low"],
        "key_operators": ["ts_sum", "ts_std_dev", "rank", "ts_corr"],
    }
]

# ─── Configuration ────────────────────────────────────────────────
ML_THRESHOLD = 0.02          # 2% success probability minimum
EPSILON_EXPLORE = 0.05       # 5% of candidates bypass the ML gate (unbiased feedback)
PAPERS_PER_DOMAIN = 2        # Papers to fetch per domain per cycle
FUNNEL_POOL = 12             # Candidate abstracts scored locally per domain
ARXIV_MAX_RESULTS = 100      # Hard cap on paging through arXiv per domain
MAX_PAPER_RETRIES = 3        # Failed papers retry at most this many times
REWRITE_ATTEMPTS = 2         # Chain-of-Alpha generation-chain depth (BRAIN 400s)
NEAR_MISS_RANGE = (0.7, 1.1) # Fitness band that triggers one refinement round
LOG_FILE = config.PIPELINE_LOG
STATE_FILE = config.PIPELINE_STATE
RECOVERY_FILE = config.RECOVERY_FILE
LEGACY_PAPERS_FILE = config.LEGACY_PAPERS_FILE

# ─── State Management ────────────────────────────────────────────
class PipelineState:
    """State tracking for the auto pipeline (single-writer, atomic saves)."""
    def __init__(self):
        self.phase = "idle"           # idle | researching | screening | simulating
        self.current_domain = None
        self.current_domain_idx = 0
        self.cycle_count = 0
        self.papers_processed = 0
        self.alphas_generated = 0
        self.alphas_accepted = 0      # Passed ML threshold
        self.alphas_simulated = 0
        self.alphas_passed = 0        # Passed BRAIN IS checks (nothing is auto-submitted)
        self.current_expression = ""
        self.ml_results = []          # List of {expr, pred_fit, pred_prob, accepted}
        self.simulation_results = []  # List of {expr, sharpe, fitness, status}
        self.papers = []              # List of {title, anomalies, expressions}
        self.running = False
        self.error = None

    def to_dict(self):
        return {
            "phase": self.phase,
            "current_domain": self.current_domain,
            "current_domain_idx": self.current_domain_idx,
            "cycle_count": self.cycle_count,
            "papers_processed": self.papers_processed,
            "alphas_generated": self.alphas_generated,
            "alphas_accepted": self.alphas_accepted,
            "alphas_simulated": self.alphas_simulated,
            "alphas_passed": self.alphas_passed,
            # legacy key kept for older dashboard builds
            "alphas_submitted": self.alphas_passed,
            "current_expression": self.current_expression,
            "ml_results": self.ml_results[-50:],       # Keep last 50
            "simulation_results": self.simulation_results[-50:],
            "papers": self.papers[-20:],                # Keep last 20
            "running": self.running,
            "error": self.error,
            "domains": [d["label"] for d in DOMAINS],
            "total_domains": len(DOMAINS),
        }

    def save(self):
        """Atomic write so readers (the Flask server) never see a torn file."""
        try:
            fd, tmp = tempfile.mkstemp(dir=str(config.RUNTIME_DIR), suffix=".state.tmp")
            with os.fdopen(fd, "w") as f:
                json.dump(self.to_dict(), f, indent=2)
            os.replace(tmp, STATE_FILE)
        except OSError as e:
            log(f"  [state] save failed: {e}")


pipeline_state = PipelineState()
_stop_flag = False


def load_simulated_expressions():
    """Load set of already-simulated (expression, settings) keys to avoid re-testing."""
    simulated = set()
    for path in [config.SIM_HISTORY, config.FOUND_ALPHAS]:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    for line in f:
                        if line.strip():
                            try:
                                entry = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            expr = entry.get("expression", "")
                            if expr and isinstance(expr, str):
                                simulated.add(expr)
            except OSError:
                pass
    return simulated


def _import_legacy_processed_papers(store):
    """One-time import of processed_papers.json into the papers table."""
    if not os.path.exists(LEGACY_PAPERS_FILE):
        return
    try:
        with open(LEGACY_PAPERS_FILE) as f:
            ids = json.load(f)
        for entry_id in ids:
            if not store.get_paper(entry_id):
                store.record_paper(entry_id, status="processed")
        os.replace(LEGACY_PAPERS_FILE, str(LEGACY_PAPERS_FILE) + ".imported")
        log(f"  Imported {len(ids)} legacy processed-paper ids into the store.")
    except Exception as e:
        log(f"  Legacy paper import failed: {e}")


def _simulate_item(item, simulated_exprs):
    """Run one queue item through BRAIN, updating counters/state. Returns outcome dict."""
    pipeline_state.current_expression = item["expression"][:60]
    pipeline_state.save()

    outcome = screen_queue_item(item)  # raises AuthError if auth is irrecoverable
    simulated_exprs.add(item["expression"])
    pipeline_state.alphas_simulated += 1

    sim_result = {
        "expression": item["expression"][:80],
        "ml_prob": round(item.get("ml_pred_prob", 0) * 100, 2),
    }
    res = outcome.get("result") or {}
    if outcome["status"] == "passed":
        sim_result.update({
            "sharpe": round(res.get("sharpe", 0), 2),
            "fitness": round(res.get("fitness", 0), 2),
            "turnover": round(res.get("turnover", 0) * 100, 1),
            "status": "PASSED",
        })
        pipeline_state.alphas_passed += 1
    elif outcome["status"] == "failed_checks":
        sim_result.update({
            "sharpe": round(res.get("sharpe", 0), 2),
            "fitness": round(res.get("fitness", 0), 2),
            "turnover": round(res.get("turnover", 0) * 100, 1),
            "status": "BELOW_THRESHOLD",
        })
    else:
        sim_result["status"] = "FAILED"

    pipeline_state.simulation_results.append(sim_result)
    pipeline_state.save()
    return outcome


def _chain_of_alpha(client, item, outcome, simulated_exprs, field_index):
    """Feedback chains on a finished simulation:

    - Generation chain: BRAIN 400 → feed the exact compiler error back for a
      rewrite (≤ REWRITE_ATTEMPTS), then simulate the fixed expression.
    - Optimization chain: near-miss fitness or failed platform checks → one
      targeted refinement round using the measured metrics.
    Returns True if a chained candidate ultimately passed.
    """
    store = AlphaStore()
    res = outcome.get("result") or {}

    # ── Generation chain: exact compiler error → rewrite ──
    if outcome["status"] == "sim_failed" and res.get("status") == "BAD_REQUEST":
        expr = item["expression"]
        error = outcome.get("error") or "unknown error"
        for attempt in range(REWRITE_ATTEMPTS):
            if _stop_flag:
                return False
            rewrite = client.rewrite_expression(expr, error, item.get("rationale"))
            store.record_llm_interaction("refiner", rewrite, round_idx=attempt)
            if not rewrite:
                return False
            new_expr = rewrite["expression"]
            if new_expr in simulated_exprs or new_expr == expr:
                return False
            is_valid, reason = validate_expression(new_expr, field_index)
            if not is_valid:
                expr, error = new_expr, str(reason)
                continue
            log(f"    [chain] Rewritten after compile error → {new_expr[:55]}")
            chained = dict(item, expression=new_expr, skip_ml=True,
                           template_name=f"{item.get('template_name','?')}+rewrite")
            chained_outcome = _simulate_item(chained, simulated_exprs)
            if chained_outcome["status"] == "passed":
                return True
            if chained_outcome["status"] == "sim_failed" and \
                    (chained_outcome.get("result") or {}).get("status") == "BAD_REQUEST":
                expr, error = new_expr, chained_outcome.get("error") or "unknown error"
                continue
            return False
        return False

    # ── Optimization chain: near-miss → one targeted refinement ──
    if outcome["status"] == "failed_checks":
        fitness = res.get("fitness") or 0
        lo, hi = NEAR_MISS_RANGE
        if not (lo <= fitness < hi or (fitness >= hi and res.get("failed_checks"))):
            return False
        refine = client.refine_expression(
            item["expression"],
            {k: res.get(k) for k in ("sharpe", "fitness", "turnover", "drawdown")},
            failed_checks=res.get("failed_checks"),
            rationale=item.get("rationale"),
        )
        store.record_llm_interaction("refiner", refine, round_idx=0)
        if not refine:
            return False
        new_expr = refine["expression"]
        if new_expr in simulated_exprs or new_expr == item["expression"]:
            return False
        is_valid, _reason = validate_expression(new_expr, field_index)
        if not is_valid:
            return False
        log(f"    [chain] Near-miss (fitness {fitness:.2f}) refined: {refine.get('change','')[:70]}")
        chained = dict(item, expression=new_expr, skip_ml=True,
                       template_name=f"{item.get('template_name','?')}+refine")
        return _simulate_item(chained, simulated_exprs)["status"] == "passed"

    return False


def run_domain(client, domain, all_templates, field_index, simulated_exprs, store, dry_run=False):
    """Process a single research domain: fetch papers → LLM → ML screen → simulate."""
    global _stop_flag

    domain_label = domain["label"]
    query = domain["query"]

    log("")
    log(f"{'═'*60}")
    log(f"  DOMAIN: {domain_label}")
    log(f"{'═'*60}")

    pipeline_state.phase = "researching"
    pipeline_state.current_domain = domain_label
    pipeline_state.save()

    # Step 1: Fetch candidate papers from ArXiv (skip anything already handled)
    log(f"  Searching ArXiv: {query[:60]}...")
    arxiv_client = arxiv.Client(delay_seconds=1.0)
    search = arxiv.Search(
        query=query,
        max_results=ARXIV_MAX_RESULTS,
        sort_by=arxiv.SortCriterion.Relevance,
    )

    handled = store.get_paper_ids()
    candidates = []
    try:
        for paper in arxiv_client.results(search):
            if paper.entry_id in handled:
                continue
            candidates.append(paper)
            if len(candidates) >= FUNNEL_POOL:
                break
    except Exception as e:
        log(f"  ArXiv error: {e}")
        if not candidates:
            return

    # Step 1b: Data funnel — score abstracts locally, send only the best to the LLM
    papers = select_top_papers(candidates, domain, PAPERS_PER_DOMAIN)
    log(f"  Funnel: {len(candidates)} novel candidates → {len(papers)} selected for extraction")

    # Step 2: Process each paper (extract anomaly → generate expressions).
    # A paper is only recorded as handled AFTER processing finishes — LLM
    # failures stay retryable (capped at MAX_PAPER_RETRIES).
    all_alphas = []
    for paper in papers:
        if _stop_flag:
            return

        title = paper.title.strip()
        try:
            alphas = process_paper(client, paper, all_templates, field_index)
        except Exception as e:
            log(f"  Error processing paper: {e}")
            alphas = None

        if alphas is None:
            store.record_paper(paper.entry_id, domain=domain["id"], title=title[:120],
                               status="failed")
            continue

        status = "processed" if alphas else "not_tradeable"
        store.record_paper(paper.entry_id, domain=domain["id"], title=title[:120],
                           status=status)

        valid_alphas = [a for a in alphas if a.get("valid")]
        all_alphas.extend(valid_alphas)

        pipeline_state.papers.append({
            "title": title[:80],
            "domain": domain_label,
            "anomalies": list(set(a.get("anomaly", "")[:80] for a in alphas if a.get("anomaly"))),
            "expressions_generated": len(alphas),
            "expressions_valid": len(valid_alphas),
        })
        pipeline_state.papers_processed += 1
        time.sleep(0.5)

    pipeline_state.alphas_generated += len(all_alphas)
    log(f"  Generated {len(all_alphas)} valid expressions from {len(papers)} papers")

    # Step 3: ML Pre-Screening (with epsilon-greedy bypass)
    pipeline_state.phase = "screening"
    pipeline_state.save()
    log(f"  Running ML pre-screening (threshold: {ML_THRESHOLD:.1%}, epsilon: {EPSILON_EXPLORE:.0%})...")

    try:
        from genalpha import ml_predictor
        ml_available = ml_predictor.regressor is not None
    except ImportError:
        ml_available = False
    if not ml_available:
        log(f"  [WARNING] ML predictor not available, submitting all")

    simulation_queue = []
    for alpha in all_alphas:
        if _stop_flag:
            return

        expr = alpha["expression"]
        if expr in simulated_exprs:
            log(f"    SKIP (already simulated): {expr[:50]}...")
            continue

        pred_fit, pred_prob = 0.0, 0.0
        settings = dict(alpha.get("settings", {}))
        epsilon_pick = random.random() < EPSILON_EXPLORE

        if ml_available and not epsilon_pick:
            try:
                opt_settings, pred_fit, pred_prob = ml_predictor.optimize_settings(expr, settings)
                ml_result = {
                    "expression": expr[:80],
                    "pred_fitness": round(float(pred_fit), 3),
                    "success_prob": round(float(pred_prob) * 100, 2),
                    "accepted": bool(pred_prob >= ML_THRESHOLD),
                    "settings": {
                        "decay": opt_settings.get("decay"),
                        "neutralization": opt_settings.get("neutralization"),
                        "truncation": opt_settings.get("truncation"),
                    },
                }
                pipeline_state.ml_results.append(ml_result)

                if pred_prob < ML_THRESHOLD:
                    log(f"    REJECT ({pred_prob:.1%} < {ML_THRESHOLD:.0%}): {expr[:50]}...")
                    continue

                log(f"    ACCEPT ({pred_prob:.1%}): {expr[:50]}...")
                settings = dict(opt_settings)
            except Exception as e:
                # An ML failure must not zero the pipeline — fall back to base settings.
                log(f"    ML error ({e}) → falling back to base settings for {expr[:40]}...")
                pipeline_state.ml_results.append({
                    "expression": expr[:80], "pred_fitness": 0, "success_prob": 0,
                    "accepted": True, "note": "ml_error_fallback",
                })
        else:
            note = "epsilon_explore" if (ml_available and epsilon_pick) else "no_ml_model"
            if note == "epsilon_explore":
                log(f"    EPSILON-EXPLORE (bypassing ML gate): {expr[:50]}...")
            pipeline_state.ml_results.append({
                "expression": expr[:80], "pred_fitness": 0, "success_prob": 0,
                "accepted": True, "note": note,
            })

        settings["universe"] = "TOP3000"
        settings["delay"] = 1
        settings.setdefault("nan_handling", "ON")

        simulation_queue.append({
            "expression": expr,
            "settings": settings,
            "source": "llm-arxiv",
            "template_name": f"arxiv:{alpha.get('paper_title', '?')[:30]}",
            "rationale": alpha.get("rationale", ""),
            "priority": alpha.get("llm_confidence", 0.5) * alpha.get("anomaly_confidence", 0.5),
            "skip_ml": True,
            "ml_pred_fit": pred_fit,
            "ml_pred_prob": pred_prob,
        })

    pipeline_state.alphas_accepted += len(simulation_queue)
    pipeline_state.save()

    log(f"  ML screening: {len(simulation_queue)}/{len(all_alphas)} accepted")

    if dry_run:
        log(f"  [DRY RUN] Skipping BRAIN simulation")
        return

    # Step 4: Submit to BRAIN one-at-a-time (respecting rate limits)
    if not simulation_queue:
        log(f"  No expressions to simulate for this domain.")
        return

    pipeline_state.phase = "simulating"
    pipeline_state.save()
    log(f"  Submitting {len(simulation_queue)} expressions to BRAIN...")

    for item in simulation_queue:
        if _stop_flag:
            save_recovery_queue(simulation_queue)
            return
        try:
            outcome = _simulate_item(item, simulated_exprs)
            _chain_of_alpha(client, item, outcome, simulated_exprs, field_index)
        except AuthError:
            raise
        except Exception as e:
            log(f"  Simulation error: {e}")

    pipeline_state.current_expression = ""


def save_recovery_queue(queue):
    """Save high-confidence items (>50% prob) to recovery file on interrupt."""
    high_conf = [q for q in queue if q.get("ml_pred_prob", 0) >= 0.5]
    if high_conf:
        with open(RECOVERY_FILE, 'w') as f:
            json.dump(high_conf, f, indent=2)
        log(f"  Saved {len(high_conf)} high-confidence items to {RECOVERY_FILE}")


def drain_recovery_queue(client, simulated_exprs, field_index):
    """Simulate items saved by a previous interrupted run, then clear the file."""
    if not os.path.exists(RECOVERY_FILE):
        return
    try:
        with open(RECOVERY_FILE) as f:
            items = json.load(f)
    except (OSError, json.JSONDecodeError):
        return
    if not items:
        os.unlink(RECOVERY_FILE)
        return
    log(f"  Draining {len(items)} items from {RECOVERY_FILE} (previous interrupted run)...")
    pipeline_state.phase = "simulating"
    pipeline_state.save()
    for item in items:
        if _stop_flag:
            return
        if item.get("expression") in simulated_exprs:
            continue
        try:
            outcome = _simulate_item(item, simulated_exprs)
            _chain_of_alpha(client, item, outcome, simulated_exprs, field_index)
        except AuthError:
            raise
        except Exception as e:
            log(f"  Recovery simulation error: {e}")
    os.unlink(RECOVERY_FILE)


def run_pipeline(max_cycles=None, dry_run=False):
    """Main entry point: cycle through domains continuously."""
    global _stop_flag
    pipeline_state.running = True
    pipeline_state.error = None

    # Clear the log
    with open(LOG_FILE, "w") as f:
        f.write("")

    log("╔══════════════════════════════════════════════════════════╗")
    log("║      AUTO-CYCLING ALPHA MINING PIPELINE                 ║")
    log("╚══════════════════════════════════════════════════════════╝")
    log(f"  Domains: {len(DOMAINS)}")
    log(f"  ML Threshold: {ML_THRESHOLD:.0%} (epsilon-explore {EPSILON_EXPLORE:.0%})")
    log(f"  Papers per domain: {PAPERS_PER_DOMAIN} (funnel pool {FUNNEL_POOL})")
    log(f"  Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    if max_cycles:
        log(f"  Max cycles: {max_cycles}")
    else:
        log(f"  Mode: CONTINUOUS (Ctrl+C to stop)")

    # Initialize
    client = GroqClient()
    store = AlphaStore()
    _import_legacy_processed_papers(store)
    all_templates = load_existing_templates()
    field_index = load_field_index()
    simulated_exprs = load_simulated_expressions()

    log(f"  Templates: {len(all_templates)}")
    log(f"  Field index: {len(field_index)}")
    log(f"  Already simulated: {len(simulated_exprs)} expressions")

    last_trained_size = 0
    try:
        with open(config.SIM_HISTORY) as f:
            last_trained_size = sum(1 for line in f if line.strip())
    except OSError:
        pass

    try:
        if not dry_run:
            drain_recovery_queue(client, simulated_exprs, field_index)

        cycle = 0
        while not _stop_flag:
            cycle += 1
            pipeline_state.cycle_count = cycle

            log(f"\n{'━'*60}")
            log(f"  CYCLE {cycle}" + (f" / {max_cycles}" if max_cycles else ""))
            log(f"{'━'*60}")

            for idx, domain in enumerate(DOMAINS):
                if _stop_flag:
                    break

                pipeline_state.current_domain_idx = idx
                run_domain(client, domain, all_templates, field_index,
                           simulated_exprs, store, dry_run)

            if not _stop_flag:
                current_size = 0
                try:
                    with open(config.SIM_HISTORY) as f:
                        current_size = sum(1 for line in f if line.strip())
                except OSError:
                    pass

                target_size = int(last_trained_size * 1.3)
                if current_size >= target_size and last_trained_size > 0:
                    log(f"\n  [AUTO-RETRAINING] Dataset grew from {last_trained_size} to {current_size} (+>30%). Triggering retraining...")
                    try:
                        import subprocess
                        import sys
                        log(f"  [AUTO-RETRAINING] Syncing timed-out alphas from WorldQuant API...")
                        subprocess.run([sys.executable, str(config.REPO_ROOT / 'scripts' / 'fetch_brain_history.py')], check=True)
                        log(f"  [AUTO-RETRAINING] Retraining Gradient Boosting Classifier...")
                        subprocess.run([sys.executable, '-m', 'genalpha.train_recommender'], cwd=str(config.REPO_ROOT), check=True)
                        log(f"  [AUTO-RETRAINING] Model successfully updated!")
                        last_trained_size = current_size
                    except Exception as e:
                        log(f"  [AUTO-RETRAINING] Failed: {e}")
                else:
                    log(f"\n  [AUTO-RETRAINING] Dataset size is {current_size} (need {target_size} to retrain). Skipping.")

                log(f"\n  Cycle {cycle} complete. Pausing 30s before next cycle...")
                for _ in range(30):
                    if _stop_flag:
                        break
                    time.sleep(1)

            if max_cycles and cycle >= max_cycles:
                break
    except AuthError as e:
        pipeline_state.error = f"BRAIN authentication failed: {e}"
        log(f"\n  [FATAL] {pipeline_state.error}")
        log("  Fix WQ_BRAIN_USERNAME / WQ_BRAIN_PASSWORD in .env and restart the pipeline.")

    pipeline_state.phase = "idle"
    pipeline_state.running = False
    pipeline_state.current_expression = ""
    pipeline_state.save()
    log(f"\n  Pipeline stopped. Total: {pipeline_state.alphas_simulated} simulated, "
        f"{pipeline_state.alphas_passed} passed IS checks.")


def signal_handler(sig, frame):
    global _stop_flag
    log("\n  [INTERRUPT] Gracefully stopping after current operation...")
    _stop_flag = True


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    parser = argparse.ArgumentParser(description="Auto-Cycling Alpha Mining Pipeline")
    parser.add_argument("--cycles", type=int, default=None, help="Number of cycles (default: run forever)")
    parser.add_argument("--test", action="store_true", help="Dry run: no BRAIN simulation")
    args = parser.parse_args()

    run_pipeline(max_cycles=args.cycles, dry_run=args.test)
