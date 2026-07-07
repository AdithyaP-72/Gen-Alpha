#!/usr/bin/env python3
"""
Mine LLM-Generated Alphas — Feed expressions from arxiv_pipeline.py
into the BRAIN simulation engine.

Usage:
    python mine_llm_alphas.py                    # Mine all valid LLM alphas
    python mine_llm_alphas.py --limit 10         # Limit to first N
"""

import argparse
import json
import os
from dotenv import load_dotenv

# Load env variables so WQ_BRAIN_USERNAME/PASSWORD are available to scrape_brain
load_dotenv()

from alpha_bot import screen_queue_item


def load_llm_alphas(path="llm_generated_alphas.json", universe=None):
    """Load LLM-generated alphas and convert to mining queue format."""
    if not os.path.exists(path):
        print(f"  No {path} found. Run arxiv_pipeline.py first.")
        return []

    with open(path) as f:
        data = json.load(f)

    # Load already simulated alphas to avoid re-simulating
    simulated_exprs = set()
    if os.path.exists("found_alphas.json"):
        try:
            with open("found_alphas.json") as f:
                for line in f:
                    if line.strip():
                        simulated_exprs.add(json.loads(line).get("expression", ""))
        except Exception:
            pass

    queue = []
    for alpha in data.get("alphas", []):
        if not alpha.get("valid", False):
            continue  # Skip expressions that failed validation
            
        if alpha["expression"] in simulated_exprs:
            continue  # Skip already simulated

        settings = alpha["settings"].copy()
        if universe:
            settings["universe"] = universe

        queue.append({
            "expression": alpha["expression"],
            "settings": settings,
            "source": "llm-arxiv",
            "template_name": f"arxiv:{alpha.get('paper_title', '?')[:30]}",
            "priority": alpha.get("llm_confidence", 0.5) * alpha.get("anomaly_confidence", 0.5),
        })

    # Sort by priority descending
    queue.sort(key=lambda x: -x.get("priority", 0))
    return queue


def main():
    parser = argparse.ArgumentParser(description="Mine LLM-generated alphas")
    parser.add_argument("--limit", type=int, default=None, help="Max alphas to test")
    parser.add_argument("--universe", type=str, default=None, help="Override universe (e.g. TOP3000)")
    args = parser.parse_args()

    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║       LLM-ALPHA MINER — ARXIV → BRAIN PIPELINE         ║")
    print("╚══════════════════════════════════════════════════════════╝")

    queue = load_llm_alphas(universe=args.universe)
    if not queue:
        print("  No valid LLM alphas to mine.")
        return

    if args.limit:
        queue = queue[:args.limit]

    print(f"\n  LLM-generated alphas to test: {len(queue)}")
    for i, item in enumerate(queue[:10]):
        print(f"    {i+1}. {item['expression'][:60]}... (p={item['priority']:.2f})")

    results = []
    for item in queue:
        try:
            result = screen_queue_item(item)
            if result:
                results.append(result)
        except Exception as e:
            print(f"  Exception: {e}")

    # Summary
    print(f"\n{'='*60}")
    print(f"  LLM MINING SESSION COMPLETE")
    print(f"{'='*60}")
    print(f"  Tested: {len(queue)}")
    print(f"  Submittable: {len(results)}")
    for expr, settings, result in results:
        print(f"  ★ {expr[:60]}...")
        print(f"    Sharpe={result['sharpe']:.2f}, Fitness={result['fitness']:.2f}")


if __name__ == "__main__":
    main()
