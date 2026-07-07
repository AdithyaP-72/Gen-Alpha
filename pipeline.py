#!/usr/bin/env python3
"""
Gen-Alpha Pipeline — Run the full research → train → mine pipeline.
Usage:
    python pipeline.py scrape     # Scrape Brain API data fields
    python pipeline.py research   # ArXiv → LLM → validated expressions
    python pipeline.py train      # Train ML models on simulation history
    python pipeline.py mine       # Run intelligence-driven alpha mining
    python pipeline.py mine-llm   # Mine only LLM-generated expressions
    python pipeline.py all        # Run everything in sequence
    python pipeline.py plot       # Plot fitness progression
"""
import sys
import subprocess


def run_step(name, module, extra_args=None):
    print(f"\n{'#'*60}")
    print(f"  STEP: {name}")
    print(f"{'#'*60}\n")
    cmd = [sys.executable, module]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, cwd=".")
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
        run_step("Scrape Brain API", "scrape_brain.py")
        run_step("Scrape Web Research", "scrape_research.py")
    elif step == "research":
        run_step("ArXiv Research Pipeline", "arxiv_pipeline.py", extra)
    elif step == "train":
        run_step("Train Intelligence Models", "train_recommender.py")
    elif step == "mine":
        run_step("Mine Alphas", "alpha_bot.py")
    elif step == "mine-llm":
        run_step("Mine LLM-Generated Alphas", "mine_llm_alphas.py")
    elif step == "all":
        run_step("Scrape Brain API", "scrape_brain.py")
        run_step("ArXiv Research Pipeline", "arxiv_pipeline.py", ["--max-papers", "10"])
        run_step("Mine Alphas", "alpha_bot.py")
    elif step == "plot":
        run_step("Plot Fitness", "plot_fitness.py")
    else:
        print(f"Unknown step: {step}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
