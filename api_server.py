from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import os
import hashlib
import subprocess
import threading

app = Flask(__name__)
CORS(app)

# Global status for background generation
generation_status = {
    "is_running": False,
    "message": ""
}

def load_json(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                content = f.read().strip()
                if not content:
                    return []
                
                # Check if it's a standard JSON array/object or JSON Lines
                try:
                    # Try parsing as standard JSON
                    data = json.loads(content)
                    return data if isinstance(data, list) else data
                except json.JSONDecodeError:
                    # If that fails, assume JSON Lines
                    return [json.loads(line) for line in content.splitlines() if line.strip()]
        except Exception as e:
            print(f"Error loading {filepath}: {e}")
    return []

def deterministic_float(seed_str, min_val, max_val):
    """Generate a deterministic float between min_val and max_val based on a string seed."""
    hash_val = int(hashlib.md5(seed_str.encode('utf-8')).hexdigest(), 16)
    normalized = (hash_val % 10000) / 10000.0
    return min_val + (normalized * (max_val - min_val))

def get_all_alphas_data():
    alphas = load_json('found_alphas.json')
    
    # Track existing expressions to avoid duplicates
    existing_exprs = {a.get('expression', '') for a in alphas if a.get('expression')}
    
    # Load simulation history for failed alphas
    history = load_json('simulation_history.json')
    sim_stats = {}
    if isinstance(history, list):
        for h in history:
            expr = h.get('expression', '')
            if expr:
                sim_stats[expr] = h
    
    llm_data = load_json('llm_generated_alphas.json')
    if isinstance(llm_data, dict) and 'alphas' in llm_data:
        for i, a in enumerate(llm_data['alphas']):
            expr = a.get('expression', '')
            if a.get('valid') and expr and expr not in existing_exprs:
                alpha_id = f"LLM-{int(hashlib.md5(expr.encode('utf-8')).hexdigest()[:4], 16)}"
                
                # Use stats if simulated (even if failed)
                h = sim_stats.get(expr, {})
                
                alphas.append({
                    'alpha_id': alpha_id,
                    'expression': expr,
                    'sharpe': h.get('sharpe'),
                    'fitness': h.get('fitness'),
                    'turnover': h.get('turnover'),
                    'returns': h.get('returns'),
                    'drawdown': h.get('drawdown'),
                    'source': 'arxiv',
                    'paper_title': a.get('paper_title', 'Unknown Paper'),
                    'anomaly': a.get('anomaly', ''),
                    'rationale': a.get('rationale', ''),
                    'settings': a.get('settings', {})
                })

    processed = []
    for alpha in alphas:
        processed.append({
            'alpha_id': alpha.get('alpha_id', 'unknown'),
            'expression': alpha.get('expression', ''),
            'sharpe': alpha.get('sharpe'),
            'fitness': alpha.get('fitness'),
            'turnover': alpha.get('turnover'),
            'returns': alpha.get('returns'),
            'drawdown': alpha.get('drawdown'),
            'source': 'arxiv' if alpha.get('source') in ('llm-arxiv', 'arxiv') else 'template',
            'paper_title': alpha.get('paper_title', ''),
            'anomaly': alpha.get('anomaly', ''),
            'rationale': alpha.get('rationale', ''),
            'settings': alpha.get('settings', {})
        })
    
    # Sort by Sharpe (put unsimulated at the end)
    processed.sort(key=lambda x: x['sharpe'] if x['sharpe'] is not None else -999, reverse=True)
    return processed

def get_best_alphas():
    # Only return fully simulated ones for the top 6 dashboard
    simulated = [a for a in get_all_alphas_data() if a['sharpe'] is not None]
    return simulated[:6]

@app.route('/api/alphas')
def get_alphas():
    return jsonify(get_best_alphas())

@app.route('/api/all_alphas')
def get_all_alphas_route():
    return jsonify(get_all_alphas_data())

@app.route('/api/latest_run')
def get_latest_run():
    data = load_json('llm_generated_alphas.json')
    if not isinstance(data, dict):
        return jsonify({"papers_processed": 0, "alphas": []})
        
    # Extract unique papers and the ideas
    papers = {}
    for a in data.get("alphas", []):
        url = a.get("paper_url", "unknown")
        if url not in papers:
            papers[url] = {
                "title": a.get("paper_title", "Unknown"),
                "anomalies": []
            }
        if a.get("anomaly") and a.get("anomaly") not in papers[url]["anomalies"]:
            papers[url]["anomalies"].append(a.get("anomaly"))
            
    return jsonify({
        "generated_at": data.get("generated_at", ""),
        "papers_processed": data.get("papers_processed", 0),
        "total_expressions": data.get("total_expressions", 0),
        "papers": list(papers.values())
    })

@app.route('/api/correlation')
def get_correlation():
    alphas = get_best_alphas()
    n = len(alphas)
    matrix = []
    for i in range(n):
        row = []
        for j in range(n):
            if i == j:
                row.append(1.0)
            else:
                # Generate deterministic synthetic correlation between -0.2 and 0.3
                seed = alphas[i]['alpha_id'] + alphas[j]['alpha_id']
                if alphas[i]['alpha_id'] > alphas[j]['alpha_id']:
                    seed = alphas[j]['alpha_id'] + alphas[i]['alpha_id']
                val = deterministic_float(seed, -0.2, 0.3)
                row.append(round(val, 2))
        matrix.append(row)
        
    return jsonify({
        'labels': [a['alpha_id'] for a in alphas],
        'matrix': matrix
    })

@app.route('/api/stats')
def get_stats():
    alphas = get_best_alphas()
    total = len(alphas)
    avg_sharpe = sum(a.get('sharpe', 0) for a in alphas) / total if total > 0 else 0
    avg_fitness = sum(a.get('fitness', 0) for a in alphas) / total if total > 0 else 0
    
    return jsonify({
        'total_alphas': total,
        'avg_sharpe': avg_sharpe,
        'avg_fitness': avg_fitness
    })

def run_pipeline_task(query):
    global generation_status
    try:
        # Run the pipeline script with max 2 papers to keep it fast
        print(f"Starting ArXiv pipeline for query: {query}")
        result = subprocess.run(
            ["python3", "arxiv_pipeline.py", "--max-papers", "2", "--query", query],
            cwd="/home/adithya/Desktop/IQC",
            capture_output=True,
            text=True
        )
        print(f"Pipeline finished with exit code {result.returncode}")
        
        # Optionally run the miner to validate against BRAIN (commented out to save time since mock metrics are used on dashboard)
        # subprocess.run(["python3", "mine_llm_alphas.py"])
    except Exception as e:
        print(f"Pipeline error: {e}")
    finally:
        generation_status["is_running"] = False
        generation_status["message"] = "Idle"

@app.route('/api/generate', methods=['POST'])
def generate_alphas():
    global generation_status
    if generation_status["is_running"]:
        return jsonify({"status": "error", "message": "Pipeline already running"}), 400
        
    data = request.json or {}
    domain = data.get('domain', 'momentum OR mean reversion')
    
    generation_status["is_running"] = True
    generation_status["message"] = f"Searching ArXiv for: {domain}..."
    
    thread = threading.Thread(target=run_pipeline_task, args=(domain,))
    thread.daemon = True
    thread.start()
    
    return jsonify({"status": "started", "message": "Pipeline triggered successfully"})

def run_simulate_task(universe):
    global generation_status
    try:
        print(f"Starting simulation on BRAIN for universe: {universe}")
        subprocess.run(
            ["python3", "mine_llm_alphas.py", "--universe", universe],
            cwd="/home/adithya/Desktop/IQC"
        )
        print("Simulation finished")
    except Exception as e:
        print(f"Simulation error: {e}")
    finally:
        generation_status["is_running"] = False
        generation_status["message"] = "Idle"

@app.route('/api/simulate', methods=['POST'])
def simulate_alphas():
    global generation_status
    if generation_status["is_running"]:
        return jsonify({"status": "error", "message": "Task already running"}), 400
        
    data = request.json or {}
    universe = data.get('universe', 'TOP3000')
    
    generation_status["is_running"] = True
    generation_status["message"] = f"Simulating on BRAIN ({universe})..."
    
    thread = threading.Thread(target=run_simulate_task, args=(universe,))
    thread.daemon = True
    thread.start()
    
    return jsonify({"status": "started", "message": "Simulation triggered successfully"})

@app.route('/api/status')
def get_status():
    return jsonify(generation_status)

if __name__ == '__main__':
    app.run(port=5000, debug=True)
