import json
import matplotlib.pyplot as plt
from datetime import datetime
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from genalpha import config

def plot_fitness_history():
    history_file = config.SIM_HISTORY
    if not os.path.exists(history_file):
        print(f"No simulation history found at {history_file}. Run alpha_bot.py first.")
        return

    fitness_scores = []
    times = []

    with open(history_file, 'r') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                fitness = entry.get('fitness')
                if fitness is not None:
                    fitness_scores.append(fitness)
                    ts = entry.get('timestamp')
                    times.append(datetime.fromtimestamp(ts) if ts else None)
            except Exception as e:
                print(f"Skipping malformed line: {e}")

    if not fitness_scores:
        print("No valid fitness data to plot.")
        return

    # Fall back to run index if any timestamps are missing
    if any(t is None for t in times):
        times = list(range(1, len(fitness_scores) + 1))
        x_label = 'Simulation Run Number'
    else:
        x_label = 'Date'

    # Calculate a moving average
    window_size = min(10, len(fitness_scores))
    moving_averages = []
    for i in range(len(fitness_scores)):
        start_idx = max(0, i - window_size + 1)
        ma = sum(fitness_scores[start_idx:i+1]) / (i - start_idx + 1)
        moving_averages.append(ma)

    plt.figure(figsize=(10, 6))

    # Plot individual simulation fitness scores
    plt.scatter(times, fitness_scores, alpha=0.6, label='Individual Simulation Fitness', color='blue')

    # Plot the moving average
    plt.plot(times, moving_averages, color='red', linewidth=2, label=f'Moving Average (window={window_size})')

    # Decision-tree thresholds
    plt.axhline(y=1.1, color='green', linestyle='--', linewidth=2, label='Submittable Threshold (1.1)')
    plt.axhline(y=0.7, color='orange', linestyle=':', linewidth=1.5, label='Near-miss Band (0.7)')

    plt.title('Alpha Simulation Fitness Over Time')
    plt.xlabel(x_label)
    plt.ylabel('Fitness Score')
    plt.legend()
    plt.grid(True, linestyle=':', alpha=0.7)
    if x_label == 'Date':
        plt.gcf().autofmt_xdate()

    output_file = config.FITNESS_PLOT
    plt.savefig(output_file)
    print(f"Plot successfully saved to {output_file}")

if __name__ == "__main__":
    plot_fitness_history()
