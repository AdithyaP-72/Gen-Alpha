#!/usr/bin/env python3
"""
Gen-Alpha Pipeline — Run the full research → train → mine pipeline.
Usage (from the repo root):
    python scripts/pipeline.py scrape     # Scrape Brain API data fields
    python scripts/pipeline.py research   # ArXiv → LLM → validated expressions
    python scripts/pipeline.py train      # Train ML models on simulation history
    python scripts/pipeline.py mine       # Run intelligence-driven alpha mining
    python scripts/pipeline.py mine-llm   # Mine only LLM-generated expressions
    python scripts/pipeline.py all        # Run everything in sequence
    python scripts/pipeline.py plot       # Plot fitness progression
"""
import sys
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_step(name, target, extra_args=None):
    """target: 'genalpha.module' (run with -m) or 'scripts/foo.py'."""
    print(f"\n{'#'*60}")
    print(f"  STEP: {name}")
    print(f"{'#'*60}\n")
    if target.endswith(".py"):
        cmd = [sys.executable, str(REPO_ROOT / target)]
    else:
        cmd = [sys.executable, "-m", target]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        print(f"  WARNING: {name} exited with code {result.returncode}")
    return result.returncode


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    step = sys.argv[1].lower()
    extra = sys.argv[2:]  # Pass remaining args through

    if step == "scrape":
        run_step("Scrape Brain API", "genalpha.scrape_brain")
        run_step("Scrape Web Research", "genalpha.scrape_research")
    elif step == "research":
        run_step("ArXiv Research Pipeline", "genalpha.arxiv_pipeline", extra)
    elif step == "train":
        run_step("Train Intelligence Models", "genalpha.train_recommender")
    elif step == "mine":
        run_step("Mine Alphas", "genalpha.alpha_bot")
    elif step == "mine-llm":
        run_step("Mine LLM-Generated Alphas", "scripts/mine_llm_alphas.py")
    elif step == "all":
        run_step("Scrape Brain API", "genalpha.scrape_brain")
        run_step("ArXiv Research Pipeline", "genalpha.arxiv_pipeline", ["--max-papers", "10"])
        run_step("Mine Alphas", "genalpha.alpha_bot")
    elif step == "plot":
        run_step("Plot Fitness", "scripts/plot_fitness.py")
    else:
        print(f"Unknown step: {step}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
