import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from genalpha import config
import json

total = 0
successful = 0
failed = 0
sum_fitness = 0
max_fitness = 0

with open(config.SIM_HISTORY, 'r') as f:
    lines = f.readlines()
    total = len(lines)
    for line in lines:
        if line.strip():
            data = json.loads(line)
            fitness = data.get('fitness')
            if fitness is not None:
                successful += 1
                sum_fitness += fitness
                if fitness > max_fitness:
                    max_fitness = fitness
            else:
                failed += 1

print(f"Total simulations in history: {total}")
print(f"Failed / Timeout simulations: {failed} ({failed/total*100:.1f}%)")
print(f"Completed simulations: {successful} ({successful/total*100:.1f}%)")
print(f"Average fitness (completed): {sum_fitness/successful if successful else 0:.3f}")
print(f"Max fitness: {max_fitness:.3f}")

