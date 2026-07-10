#!/usr/bin/env python3
"""
Auto-Cycling Alpha Mining Pipeline — Continuously cycles through
operator-aware research domains, generates alpha ideas via LLM,
pre-screens with ML model, and auto-submits quality ones to WQ BRAIN.

Usage:
    python auto_pipeline.py              # Run continuously
    python auto_pipeline.py --cycles 1   # Run one cycle through all domains
    python auto_pipeline.py --test       # Dry-run: generate + ML screen only, no BRAIN submission
"""

import argparse
import json
import time
import os
import signal
import sys
from pathlib import Path

from arxiv_pipeline import process_paper, load_existing_templates, load_field_index
from alpha_bot import screen_queue_item
from llm_client import GroqClient

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
PAPERS_PER_DOMAIN = 2        # Papers to fetch per domain per cycle
LOG_FILE = "pipeline_progress.log"
STATE_FILE = "pipeline_state.json"
RECOVERY_FILE = "recovery_queue.json"

# ─── State Management ────────────────────────────────────────────
class PipelineState:
    """Thread-safe state tracking for the auto pipeline."""
    def __init__(self):
        self.phase = "idle"           # idle | researching | screening | simulating
        self.current_domain = None
        self.current_domain_idx = 0
        self.cycle_count = 0
        self.papers_processed = 0
        self.alphas_generated = 0
        self.alphas_accepted = 0      # Passed ML threshold
        self.alphas_simulated = 0
        self.alphas_submitted = 0     # Passed BRAIN IS checks
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
            "alphas_submitted": self.alphas_submitted,
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
        with open(STATE_FILE, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)


pipeline_state = PipelineState()
_stop_flag = False


def log(msg):
    """Write to both stdout and the pipeline log file."""
    timestamp = time.strftime("[%H:%M:%S]")
    line = f"{timestamp} {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_simulated_expressions():
    """Load set of already-simulated expressions to avoid re-testing."""
    simulated = set()
    for path in ["simulation_history.json", "found_alphas.json"]:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    for line in f:
                        if line.strip():
                            entry = json.loads(line)
                            expr = entry.get("expression", "")
                            if expr:
                                simulated.add(expr)
                                # Also add negated versions
                                simulated.add(f"-({expr})")
                                simulated.add(f"-{expr}")
            except Exception:
                pass
    return simulated


def run_domain(client, domain, all_templates, field_index, simulated_exprs, dry_run=False):
    """Process a single research domain: fetch papers → LLM → ML screen → simulate."""
    global _stop_flag

    domain_label = domain["label"]
    query = domain["query"]

    log(f"")
    log(f"{'═'*60}")
    log(f"  DOMAIN: {domain_label}")
    log(f"{'═'*60}")

    pipeline_state.phase = "researching"
    pipeline_state.current_domain = domain_label
    pipeline_state.save()

    # Step 1: Fetch papers from ArXiv
    log(f"  Searching ArXiv: {query[:60]}...")
    arxiv_client = arxiv.Client(delay_seconds=1.0)
    search = arxiv.Search(
        query=query,
        max_results=PAPERS_PER_DOMAIN * 3,
        sort_by=arxiv.SortCriterion.Relevance,
    )

    # Load previously processed papers to ensure we don't research the same paper twice
    processed_papers = set()
    if os.path.exists("processed_papers.json"):
        try:
            with open("processed_papers.json", "r") as f:
                processed_papers = set(json.load(f))
        except Exception:
            pass

    papers = []
    try:
        for paper in arxiv_client.results(search):
            if paper.entry_id in processed_papers:
                continue
                
            papers.append(paper)
            processed_papers.add(paper.entry_id)
            if len(papers) >= PAPERS_PER_DOMAIN:
                break
    except Exception as e:
        log(f"  ArXiv error: {e}")
        return

    # Save updated processed papers
    with open("processed_papers.json", "w") as f:
        json.dump(list(processed_papers), f)

    log(f"  Found {len(papers)} novel papers (skipped already processed)")

    # Step 2: Process each paper (extract anomaly → generate expressions)
    all_alphas = []
    for paper in papers:
        if _stop_flag:
            return

        try:
            alphas = process_paper(client, paper, all_templates, field_index)
            valid_alphas = [a for a in alphas if a.get("valid")]
            all_alphas.extend(valid_alphas)

            # Track paper in state
            pipeline_state.papers.append({
                "title": paper.title.strip()[:80],
                "domain": domain_label,
                "anomalies": list(set(a.get("anomaly", "")[:80] for a in alphas if a.get("anomaly"))),
                "expressions_generated": len(alphas),
                "expressions_valid": len(valid_alphas),
            })
            pipeline_state.papers_processed += 1

        except Exception as e:
            log(f"  Error processing paper: {e}")

        time.sleep(0.5)

    pipeline_state.alphas_generated += len(all_alphas)
    log(f"  Generated {len(all_alphas)} valid expressions from {len(papers)} papers")

    # Step 3: ML Pre-Screening
    pipeline_state.phase = "screening"
    pipeline_state.save()
    log(f"  Running ML pre-screening (threshold: {ML_THRESHOLD:.1%})...")

    try:
        import ml_predictor
        ml_available = True
    except ImportError:
        ml_available = False
        log(f"  [WARNING] ML predictor not available, submitting all")

    simulation_queue = []
    for alpha in all_alphas:
        if _stop_flag:
            return

        expr = alpha["expression"]
        if expr in simulated_exprs:
            log(f"    SKIP (already simulated): {expr[:50]}...")
            continue

        if ml_available:
            try:
                opt_settings, pred_fit, pred_prob = ml_predictor.optimize_settings(
                    expr, alpha.get("settings", {})
                )

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
                alpha["settings"] = opt_settings
                alpha["settings"]["universe"] = "TOP3000"
                alpha["settings"]["delay"] = 1
                alpha["settings"]["nan_handling"] = "ON"

            except Exception as e:
                log(f"    ML error: {e}")
                continue
        else:
            ml_result = {
                "expression": expr[:80],
                "pred_fitness": 0,
                "success_prob": 0,
                "accepted": True,
            }
            pipeline_state.ml_results.append(ml_result)

        simulation_queue.append({
            "expression": expr,
            "settings": alpha.get("settings", {}),
            "source": "llm-arxiv",
            "template_name": f"arxiv:{alpha.get('paper_title', '?')[:30]}",
            "priority": alpha.get("llm_confidence", 0.5) * alpha.get("anomaly_confidence", 0.5),
            "skip_ml": True,
            "ml_pred_fit": pred_fit if ml_available else 0,
            "ml_pred_prob": pred_prob if ml_available else 0,
        })
        simulated_exprs.add(expr)

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
            # Save high-confidence items to recovery file on interrupt
            save_recovery_queue(simulation_queue)
            return

        pipeline_state.current_expression = item["expression"][:60]
        pipeline_state.save()

        try:
            result = screen_queue_item(item)
            pipeline_state.alphas_simulated += 1

            sim_result = {
                "expression": item["expression"][:80],
                "ml_prob": round(item.get("ml_pred_prob", 0) * 100, 2),
            }

            if result:
                expr, settings, res = result
                sim_result["sharpe"] = round(res.get("sharpe", 0), 2)
                sim_result["fitness"] = round(res.get("fitness", 0), 2)
                sim_result["turnover"] = round(res.get("turnover", 0) * 100, 1)
                sim_result["status"] = "SUBMITTED"
                pipeline_state.alphas_submitted += 1
            else:
                sim_result["status"] = "FAILED"

            pipeline_state.simulation_results.append(sim_result)
            pipeline_state.save()

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
    log(f"  ML Threshold: {ML_THRESHOLD:.0%}")
    log(f"  Papers per domain: {PAPERS_PER_DOMAIN}")
    log(f"  Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    if max_cycles:
        log(f"  Max cycles: {max_cycles}")
    else:
        log(f"  Mode: CONTINUOUS (Ctrl+C to stop)")

    # Initialize
    client = GroqClient()
    all_templates = load_existing_templates()
    field_index = load_field_index()
    simulated_exprs = load_simulated_expressions()

    log(f"  Templates: {len(all_templates)}")
    log(f"  Field index: {len(field_index)}")
    log(f"  Already simulated: {len(simulated_exprs)} expressions")

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
            run_domain(client, domain, all_templates, field_index, simulated_exprs, dry_run)

        if max_cycles and cycle >= max_cycles:
            break

        if not _stop_flag:
            log(f"\n  Cycle {cycle} complete. Pausing 30s before next cycle...")
            for _ in range(30):
                if _stop_flag:
                    break
                time.sleep(1)

    pipeline_state.phase = "idle"
    pipeline_state.running = False
    pipeline_state.current_expression = ""
    pipeline_state.save()
    log(f"\n  Pipeline stopped. Total: {pipeline_state.alphas_simulated} simulated, "
        f"{pipeline_state.alphas_submitted} submitted.")


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
