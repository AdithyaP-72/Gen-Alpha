import json
import os
import sys
import hashlib
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS
from genalpha import config

app = Flask(__name__)
# Restrict CORS to the local dev frontend (the Vite proxy makes even this
# unnecessary for normal use, but direct calls during development still work).
CORS(app, origins=[
    "http://localhost:5173", "http://127.0.0.1:5173",
])

REPO_DIR = config.REPO_ROOT
PNL_CACHE_DIR = config.PNL_CACHE_DIR

# Global status for background generation
generation_status = {
    "is_running": False,
    "message": ""
}

# Reference to the auto-pipeline process
_pipeline_proc = None
_pipeline_lock = threading.Lock()
_stop_clicks = 0

# mtime-based cache so growing JSONL files aren't re-parsed on every request
_file_cache = {}


def load_json(filepath):
    filepath = str(filepath)
    if not os.path.exists(filepath):
        return []
    try:
        mtime = os.path.getmtime(filepath)
        cached = _file_cache.get(filepath)
        if cached and cached[0] == mtime:
            return cached[1]

        with open(filepath, 'r') as f:
            content = f.read().strip()
        if not content:
            data = []
        else:
            try:
                data = json.loads(content)  # standard JSON array/object
            except json.JSONDecodeError:
                # JSON Lines — skip unparseable lines instead of failing the file
                data = []
                for line in content.splitlines():
                    if line.strip():
                        try:
                            data.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        _file_cache[filepath] = (mtime, data)
        return data
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
    return []


def get_all_alphas_data():
    alphas = list(load_json(config.FOUND_ALPHAS))

    # Track existing expressions to avoid duplicates
    existing_exprs = {a.get('expression', '') for a in alphas if a.get('expression')}

    # Load simulation history for best-effort stats on unpromoted LLM alphas
    history = load_json(config.SIM_HISTORY)
    sim_stats = {}
    if isinstance(history, list):
        for h in history:
            expr = h.get('expression', '')
            if expr and isinstance(expr, str):
                if expr not in sim_stats or (h.get('fitness', 0) or 0) > (sim_stats[expr].get('fitness', 0) or 0):
                    sim_stats[expr] = h

    llm_data = load_json(config.LLM_ALPHAS)
    if isinstance(llm_data, dict) and 'alphas' in llm_data:
        for a in llm_data['alphas']:
            expr = a.get('expression', '')
            if a.get('valid') and expr and expr not in existing_exprs:
                alpha_id = f"LLM-{int(hashlib.md5(expr.encode('utf-8')).hexdigest()[:4], 16)}"

                # Check for original or negated versions in sim_stats
                candidates = [(expr, sim_stats.get(expr, {})),
                              (f"-({expr})", sim_stats.get(f"-({expr})", {})),
                              (f"-{expr}", sim_stats.get(f"-{expr}", {}))]
                best_expr, best_h = max(
                    candidates, key=lambda c: c[1].get('fitness', -99) or -99
                )
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
            'grade': alpha.get('grade'),
            'failed_checks': alpha.get('failed_checks', []),
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
    data = load_json(config.LATEST_RUN)
    if not data or not isinstance(data, dict):
        data = load_json(config.LLM_ALPHAS)
        if not data or not isinstance(data, dict):
            return jsonify({'papers_processed': 0, 'alphas_generated': 0, 'ideas': []})

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


# ── Real PnL-based correlation & portfolio analytics ───────────────
def _fetch_pnl_series(alpha_id):
    """Daily PnL series for a real platform alpha, cached on disk.

    Returns list of (date, pnl) or None. Never raises — analytics must not
    take the dashboard down.
    """
    if not alpha_id or str(alpha_id).startswith(('LLM-', 'inv_', 'unknown')):
        return None
    cache_file = PNL_CACHE_DIR / f"{alpha_id}.json"
    if cache_file.exists():
        try:
            with open(cache_file) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass

    try:
        from genalpha.scrape_brain import request_with_retry, BASE_URL
        records = []
        # BRAIN generates recordsets asynchronously: the first response can be
        # 200 with empty records + a Retry-After header while it computes.
        for _ in range(4):
            resp = request_with_retry('GET', f"{BASE_URL}/alphas/{alpha_id}/recordsets/pnl",
                                      max_retries=3)
            if resp is None or resp.status_code != 200:
                return None
            data = resp.json()
            records = data.get('records') or []
            if records:
                break
            retry_after = resp.headers.get('Retry-After')
            if not retry_after:
                break
            time.sleep(min(float(retry_after), 10))
        if not records:
            return None
        # Locate the pnl column from the schema (fall back to the last column)
        pnl_idx = -1
        props = (data.get('schema') or {}).get('properties') or []
        for i, prop in enumerate(props):
            if prop.get('name') == 'pnl':
                pnl_idx = i
                break
        series = [[row[0], row[pnl_idx]] for row in records
                  if row and row[pnl_idx] is not None]
        if len(series) < 30:
            return None
        PNL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_file, 'w') as f:
            json.dump(series, f)
        return series
    except Exception as e:
        print(f"PnL fetch failed for {alpha_id}: {e}")
        return None


def _daily_returns_matrix(alphas):
    """Aligned daily-PnL-diff series for alphas that have real platform ids.

    Returns (labels, {date: [diffs]}-derived column matrix) as (labels, list-of-lists).
    """
    series_by_alpha = []
    for a in alphas:
        series = _fetch_pnl_series(a.get('alpha_id'))
        if series:
            daily = {}
            prev = None
            for date, pnl in series:
                if prev is not None:
                    daily[date] = pnl - prev[1]
                prev = (date, pnl)
            series_by_alpha.append((a['alpha_id'], daily))

    if len(series_by_alpha) < 2:
        return [lbl for lbl, _ in series_by_alpha], []

    common = set.intersection(*[set(d.keys()) for _, d in series_by_alpha])
    common = sorted(common)
    if len(common) < 30:
        return [lbl for lbl, _ in series_by_alpha], []

    labels = [lbl for lbl, _ in series_by_alpha]
    columns = [[d[date] for date in common] for _, d in series_by_alpha]
    return labels, columns


@app.route('/api/correlation')
def get_correlation():
    """Pearson correlation of daily PnL between the top alphas.

    Computed from real platform recordsets (cached). If fewer than two alphas
    have retrievable PnL, reports insufficient data instead of inventing numbers.
    """
    import numpy as np

    alphas = get_best_alphas()
    labels, columns = _daily_returns_matrix(alphas)

    if len(columns) < 2:
        return jsonify({
            'labels': [], 'matrix': [], 'synthetic': False,
            'insufficient': True,
            'note': 'Need ≥2 alphas with retrievable PnL recordsets (and BRAIN auth) to measure correlation.',
        })

    matrix = np.corrcoef(np.array(columns))
    return jsonify({
        'labels': labels,
        'matrix': [[round(float(v), 2) for v in row] for row in matrix],
        'synthetic': False,
        'insufficient': False,
    })


@app.route('/api/portfolio')
def get_portfolio():
    """Inverse-volatility weighted portfolio stats over the top alphas' real PnL.

    Falls back to the average of measured per-alpha IS returns when PnL series
    are unavailable, and says so.
    """
    import numpy as np

    alphas = get_best_alphas()
    labels, columns = _daily_returns_matrix(alphas)

    if len(columns) >= 2:
        arr = np.array(columns)
        vols = arr.std(axis=1)
        vols[vols == 0] = vols[vols > 0].min() if (vols > 0).any() else 1.0
        weights = (1.0 / vols) / (1.0 / vols).sum()
        port_daily = (weights[:, None] * arr).sum(axis=0)
        # Annualized return: inverse-vol weights applied to each alpha's
        # platform-measured IS annual return (raw PnL dollars aren't normalized
        # to book size, so they can't be converted to a return directly).
        returns_by_id = {a.get('alpha_id'): a.get('returns') for a in alphas}
        known = [(w, returns_by_id.get(lbl)) for w, lbl in zip(weights, labels)
                 if returns_by_id.get(lbl) is not None]
        ann_return = (float(sum(w * r for w, r in known) / (sum(w for w, _ in known) or 1))
                      if known else 0.0)
        sharpe = float(port_daily.mean() / (port_daily.std() or 1e-9) * np.sqrt(252))
        return jsonify({
            'measured': True,
            'labels': labels,
            'weights': [round(float(w), 3) for w in weights],
            'ann_return': round(ann_return, 4),
            'sharpe': round(sharpe, 2),
            'note': 'Inverse-volatility weights over real daily PnL recordsets.',
        })

    returns = [a.get('returns') for a in alphas if a.get('returns') is not None]
    avg_ret = sum(returns) / len(returns) if returns else 0.0
    return jsonify({
        'measured': False,
        'labels': [a['alpha_id'] for a in alphas],
        'weights': [],
        'ann_return': round(avg_ret, 4),
        'sharpe': None,
        'note': 'PnL recordsets unavailable — using equal-weighted average of per-alpha IS returns.',
    })


@app.route('/api/stats')
def get_stats():
    alphas = get_best_alphas()
    total = len(alphas)
    avg_sharpe = sum(a.get('sharpe') or 0 for a in alphas) / total if total > 0 else 0
    avg_fitness = sum(a.get('fitness') or 0 for a in alphas) / total if total > 0 else 0

    return jsonify({
        'total_alphas': total,
        'avg_sharpe': avg_sharpe,
        'avg_fitness': avg_fitness
    })


@app.route('/api/pipeline_logs')
def get_pipeline_logs():
    try:
        with open(config.PIPELINE_LOG, 'r') as f:
            return jsonify({"logs": f.read()})
    except FileNotFoundError:
        return jsonify({"logs": ""})


@app.route('/api/pipeline_state')
def get_pipeline_state():
    """Return the current auto-pipeline state for the frontend popup."""
    try:
        state_path = config.PIPELINE_STATE
        if state_path.exists():
            with open(state_path, 'r') as f:
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
        "alphas_passed": 0,
        "alphas_submitted": 0,
        "ml_results": [],
        "simulation_results": [],
        "papers": [],
        "domains": [],
        "total_domains": 0,
    })


def run_auto_pipeline_task():
    """Run the auto-cycling pipeline as a subprocess."""
    global generation_status, _pipeline_proc, _stop_clicks
    try:
        with open(config.PIPELINE_LOG, 'w') as f:
            f.write("")

        import subprocess as sp
        _pipeline_proc = sp.Popen(
            [sys.executable, "-u", "-m", "genalpha.auto_pipeline"],
            cwd=str(REPO_DIR),
            stdout=sp.PIPE,
            stderr=sp.STDOUT,
            text=True,
            bufsize=1
        )

        for line in _pipeline_proc.stdout:
            print(line.rstrip('\n'))

        _pipeline_proc.wait()

    except Exception as e:
        print(f"Pipeline error: {e}")
        generation_status["message"] = f"Pipeline error: {e}"
    finally:
        generation_status["is_running"] = False
        if not generation_status["message"].startswith("Pipeline error"):
            generation_status["message"] = "Idle"
        _pipeline_proc = None
        _stop_clicks = 0


@app.route('/api/trigger_pipeline', methods=['POST'])
def trigger_pipeline():
    """Single endpoint to trigger the full auto-cycling pipeline."""
    global generation_status, _stop_clicks
    with _pipeline_lock:
        if generation_status["is_running"]:
            return jsonify({"status": "error", "message": "Pipeline already running"}), 400

        if not (REPO_DIR / "genalpha" / "auto_pipeline.py").exists():
            return jsonify({"status": "error",
                            "message": f"genalpha/auto_pipeline.py not found in {REPO_DIR}"}), 500

        generation_status["is_running"] = True
        generation_status["message"] = "Auto-cycling pipeline running..."
        _stop_clicks = 0

        thread = threading.Thread(target=run_auto_pipeline_task)
        thread.daemon = True
        thread.start()

    return jsonify({"status": "started", "message": "Auto-cycling pipeline triggered"})


@app.route('/api/stop_pipeline', methods=['POST'])
def stop_pipeline():
    """Stop the running pipeline gracefully (second click force-kills)."""
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

    # No process exists but UI may be out of sync — reset our own flag only.
    # (pipeline_state.json is owned by the pipeline process; we don't write it.)
    generation_status["is_running"] = False
    return jsonify({"status": "reset", "message": "No pipeline running. State reset."})


@app.route('/api/clear_queue', methods=['POST'])
def clear_queue():
    """Clear the pending alphas queue."""
    try:
        with open(config.LLM_ALPHAS, 'w') as f:
            json.dump({"alphas": [], "generated_at": "", "papers_processed": 0,
                       "total_expressions": 0, "valid_expressions": 0}, f)
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
    # Port 5000 collides with macOS AirPlay Receiver; default to 5001.
    app.run(port=config.API_PORT, debug=config.FLASK_DEBUG)
