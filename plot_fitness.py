import json
import matplotlib.pyplot as plt
from datetime import datetime
import os

def plot_fitness_history():
    history_file = "simulation_history.json"
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
                    times.append(len(fitness_scores)) 
            except Exception as e:
                print(f"Skipping malformed line: {e}")
                
    if not fitness_scores:
        print("No valid fitness data to plot.")
        return

    # Calculate a moving average
    window_size = min(10, len(fitness_scores))
    if window_size > 0:
        moving_averages = []
        for i in range(len(fitness_scores)):
            start_idx = max(0, i - window_size + 1)
            ma = sum(fitness_scores[start_idx:i+1]) / (i - start_idx + 1)
            moving_averages.append(ma)

    plt.figure(figsize=(10, 6))
    
    # Plot individual simulation fitness scores
    plt.scatter(times, fitness_scores, alpha=0.6, label='Individual Simulation Fitness', color='blue')
    
    # Plot the moving average
    if window_size > 0:
        plt.plot(times, moving_averages, color='red', linewidth=2, label=f'Moving Average (window={window_size})')
    
    # Plot the 1.15 Submittable threshold line
    plt.axhline(y=1.15, color='green', linestyle='--', linewidth=2, label='Submittable Threshold (1.15)')

    plt.title('Alpha Simulation Fitness Over Time')
    plt.xlabel('Simulation Run Number')
    plt.ylabel('Fitness Score')
    plt.legend()
    plt.grid(True, linestyle=':', alpha=0.7)
    
    output_file = "fitness_progression.png"
    plt.savefig(output_file)
    print(f"Plot successfully saved to {output_file}")

if __name__ == "__main__":
    plot_fitness_history()
