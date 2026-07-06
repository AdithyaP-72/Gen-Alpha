#!/usr/bin/env python3
"""
Gen-Alpha Pipeline — Run the full research → train → mine pipeline.
Usage:
    python pipeline.py scrape     # Scrape web research + Brain API data
    python pipeline.py train      # Train ML models on simulation history
    python pipeline.py mine       # Run intelligence-driven alpha mining
    python pipeline.py all        # Run everything in sequence
"""
import sys
import subprocess


def run_step(name, module):
    print(f"\n{'#'*60}")
    print(f"  STEP: {name}")
    print(f"{'#'*60}\n")
    result = subprocess.run([sys.executable, module], cwd=".")
    if result.returncode != 0:
        print(f"  WARNING: {name} exited with code {result.returncode}")
    return result.returncode


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    step = sys.argv[1].lower()

    if step == "scrape":
        run_step("Scrape Brain API", "scrape_brain.py")
        run_step("Scrape Web Research", "scrape_research.py")
    elif step == "train":
        run_step("Train Intelligence Models", "train_recommender.py")
    elif step == "mine":
        run_step("Mine Alphas", "alpha_bot.py")
    elif step == "all":
        run_step("Scrape Brain API", "scrape_brain.py")
        run_step("Scrape Web Research", "scrape_research.py")
        run_step("Train Intelligence Models", "train_recommender.py")
        run_step("Mine Alphas", "alpha_bot.py")
    elif step == "plot":
        run_step("Plot Fitness", "plot_fitness.py")
    else:
        print(f"Unknown step: {step}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
