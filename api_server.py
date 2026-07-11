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

# Reference to the auto-pipeline process
_pipeline_proc = None
_pipeline_lock = threading.Lock()

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
                # Keep the best fitness for each expression
                if expr not in sim_stats or (h.get('fitness', 0) or 0) > (sim_stats[expr].get('fitness', 0) or 0):
                    sim_stats[expr] = h
    
    llm_data = load_json('llm_generated_alphas.json')
    if isinstance(llm_data, dict) and 'alphas' in llm_data:
        for i, a in enumerate(llm_data['alphas']):
            expr = a.get('expression', '')
            if a.get('valid') and expr and expr not in existing_exprs:
                alpha_id = f"LLM-{int(hashlib.md5(expr.encode('utf-8')).hexdigest()[:4], 16)}"
                
                # Check for original or auto-negated versions in sim_stats
                h = sim_stats.get(expr, {})
                neg_expr1 = f"-({expr})"
                neg_expr2 = f"-{expr}"
                
                h_neg1 = sim_stats.get(neg_expr1, {})
                h_neg2 = sim_stats.get(neg_expr2, {})
                
                best_h = h
                best_expr = expr
                
                if h_neg1.get('fitness', -99) != -99 and (h_neg1.get('fitness', -99) or -99) > (best_h.get('fitness', -99) or -99):
                    best_h = h_neg1
                    best_expr = neg_expr1
                
                if h_neg2.get('fitness', -99) != -99 and (h_neg2.get('fitness', -99) or -99) > (best_h.get('fitness', -99) or -99):
                    best_h = h_neg2
                    best_expr = neg_expr2
                
                if best_h:
                    alphas.append({
                        'alpha_id': alpha_id,
                        'expression': best_expr,
                        'sharpe': best_h.get('sharpe'),
                        'fitness': best_h.get('fitness'),
                        'turnover': best_h.get('turnover'),
                        'returns': best_h.get('returns'),
                        'drawdown': best_h.get('drawdown'),
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
    data = load_json('latest_run.json')
    if not data or not isinstance(data, dict):
        # Fallback if latest_run doesn't exist yet
        data = load_json('llm_generated_alphas.json')
        if not data or not isinstance(data, dict):
            return jsonify({'papers_processed': 0, 'alphas_generated': 0, 'ideas': []})
            
    alphas = data.get('alphas', [])
    papers_processed = data.get('papers_processed', 0)
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

@app.route('/api/pipeline_logs')
def get_pipeline_logs():
    try:
        with open('pipeline_progress.log', 'r') as f:
            logs = f.read()
            return jsonify({"logs": logs})
    except FileNotFoundError:
        return jsonify({"logs": ""})

@app.route('/api/pipeline_state')
def get_pipeline_state():
    """Return the current auto-pipeline state for the frontend popup."""
    try:
        if os.path.exists('pipeline_state.json'):
            with open('pipeline_state.json', 'r') as f:
                state = json.load(f)
                state["running"] = generation_status["is_running"]
                return jsonify(state)
    except Exception:
        pass
    
    return jsonify({
        "phase": "idle",
        "running": generation_status["is_running"],
        "current_domain": None,
        "papers_processed": 0,
        "alphas_generated": 0,
        "alphas_accepted": 0,
        "alphas_simulated": 0,
        "alphas_submitted": 0,
        "ml_results": [],
        "simulation_results": [],
        "papers": [],
        "domains": [],
        "total_domains": 0,
    })

def run_auto_pipeline_task():
    """Run the auto-cycling pipeline as a subprocess."""
    global generation_status, _pipeline_proc
    try:
        # Clear previous logs
        with open('pipeline_progress.log', 'w') as f:
            f.write("")
        
        import subprocess as sp
        _pipeline_proc = sp.Popen(
            ["python3", "-u", "auto_pipeline.py"],
            cwd="/home/adithya/Desktop/IQC",
            stdout=sp.PIPE,
            stderr=sp.STDOUT,
            text=True,
            bufsize=1
        )

        for line in _pipeline_proc.stdout:
            line = line.rstrip('\n')
            # Don't double-print (auto_pipeline.py already logs to file)
            print(line)
        
        _pipeline_proc.wait()
        
    except Exception as e:
        print(f"Pipeline error: {e}")
    finally:
        generation_status["is_running"] = False
        generation_status["message"] = "Idle"
        _pipeline_proc = None

@app.route('/api/trigger_pipeline', methods=['POST'])
def trigger_pipeline():
    """Single endpoint to trigger the full auto-cycling pipeline."""
    global generation_status
    if generation_status["is_running"]:
        return jsonify({"status": "error", "message": "Pipeline already running"}), 400
    
    generation_status["is_running"] = True
    generation_status["message"] = "Auto-cycling pipeline running..."
    
    thread = threading.Thread(target=run_auto_pipeline_task)
    thread.daemon = True
    thread.start()
    
    return jsonify({"status": "started", "message": "Auto-cycling pipeline triggered"})

_stop_clicks = 0

@app.route('/api/stop_pipeline', methods=['POST'])
def stop_pipeline():
    """Stop the running pipeline gracefully."""
    global _pipeline_proc, _stop_clicks
    if _pipeline_proc:
        _stop_clicks += 1
        if _stop_clicks >= 2:
            _pipeline_proc.kill()
            _pipeline_proc = None
            _stop_clicks = 0
            return jsonify({"status": "stopped", "message": "Pipeline forcefully killed."})
        else:
            import signal
            _pipeline_proc.send_signal(signal.SIGINT)
            return jsonify({"status": "stopping", "message": "Stopping gracefully... (Click again to force kill)"})
    
    # If no process exists but UI is out of sync, force reset
    generation_status["is_running"] = False
    try:
        if os.path.exists('pipeline_state.json'):
            with open('pipeline_state.json', 'r+') as f:
                state = json.load(f)
                state["running"] = False
                f.seek(0)
                json.dump(state, f)
                f.truncate()
    except Exception:
        pass
    return jsonify({"status": "error", "message": "No pipeline running. State forcefully reset."}), 400


@app.route('/api/clear_queue', methods=['POST'])
def clear_queue():
    """Clear the pending alphas queue."""
    try:
        with open('llm_generated_alphas.json', 'w') as f:
            json.dump({"alphas": [], "generated_at": "", "papers_processed": 0, "total_expressions": 0, "valid_expressions": 0}, f)
        return jsonify({"status": "ok", "message": "Queue cleared"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# Keep legacy endpoints for backward compatibility
@app.route('/api/generate', methods=['POST'])
def generate_alphas():
    return trigger_pipeline()

@app.route('/api/simulate', methods=['POST'])
def simulate_alphas():
    return trigger_pipeline()

@app.route('/api/status')
def get_status():
    return jsonify(generation_status)

if __name__ == '__main__':
    app.run(port=5000, debug=True)
