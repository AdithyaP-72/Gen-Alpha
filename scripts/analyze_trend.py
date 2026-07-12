import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from genalpha import config
import json

fitness_scores = []
with open(config.SIM_HISTORY, 'r') as f:
    for line in f:
        if line.strip():
            entry = json.loads(line)
            if entry.get('fitness') is not None:
                fitness_scores.append(entry['fitness'])

window = 100
mas = []
for i in range(len(fitness_scores)):
    start_idx = max(0, i - window + 1)
    ma = sum(fitness_scores[start_idx:i+1]) / (i - start_idx + 1)
    mas.append(ma)

print(f"Total valid scores: {len(fitness_scores)}")
print("Moving average (window 100) trend:")
step = max(1, len(mas) // 10)
for i in range(0, len(mas), step):
    print(f"Index {i:4d}: MA = {mas[i]:.4f}")
print(f"Final MA: {mas[-1]:.4f}")

