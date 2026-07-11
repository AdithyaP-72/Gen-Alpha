import re

with open('alpha_bot.py', 'r') as f:
    content = f.read()

new_simulate = """
class TimeoutException(Exception): pass

def _alarm_handler(signum, frame):
    raise TimeoutException("Hard Timeout Reached (5 minutes)")

def simulate(expression, settings):
    import signal
    try:
        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(300)
    except:
        pass
        
    try:
        return _simulate_inner(expression, settings)
    finally:
        try: signal.alarm(0)
        except: pass

def _simulate_inner(expression, settings):
    nan_handling = settings.get('nan_handling', 'ON')
    payload = {
        'type': 'REGULAR',
        'settings': {
            'instrumentType': 'EQUITY',
            'region': 'USA',
            'universe': settings.get('universe', 'TOP3000'),
            'delay': settings.get('delay', 1),
            'decay': settings.get('decay', 0),
            'neutralization': settings.get('neutralization', 'SUBINDUSTRY'),
            'truncation': settings.get('truncation', 0.05),
            'pasteurization': 'ON',
            'unitHandling': 'VERIFY',
            'nanHandling': nan_handling,
            'language': 'FASTEXPR',
            'visualization': False,
        },
        'regular': expression,
    }

    import time
    while True:
        try:
            resp = session.post(f"{BASE_URL}/simulations", json=payload, timeout=15)
        except Exception as e:
            print(f"  [!] POST Timeout/Error: {e}")
            return None
            
        if resp.status_code == 429:
            jitter = 15 + (time.time() % 10)
            print(f"  [!] Rate limited. Sleeping {jitter:.1f}s...")
            time.sleep(jitter)
            continue
        if resp.status_code == 400:
            print(f"  [!] Bad Request for '{expression[:50]}...': {resp.text[:200]}")
            return None
        if resp.status_code in (401, 403):
            print(f"  [!] Session invalid (HTTP {resp.status_code}). Re-authenticating...")
            import scrape_brain
            scrape_brain.session = scrape_brain._build_session()
            global session
            session = scrape_brain.session
            continue
        if resp.status_code != 201:
            print(f"  [!] HTTP {resp.status_code} for '{expression[:50]}...': {resp.text[:200]}")
            return None
        break

    sim_url = resp.headers.get('Location')
    if not sim_url: return None

    start_time = time.time()
    while time.time() - start_time < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        try:
            r = session.get(sim_url, timeout=15)
        except Exception:
            continue
        if r.status_code == 429:
            time.sleep(10)
            continue
        if r.status_code in (401, 403):
            print(f"  [!] Session invalid during polling. Re-authenticating...")
            import scrape_brain
            scrape_brain.session = scrape_brain._build_session()
            session = scrape_brain.session
            continue
        if r.status_code != 200:
            continue
        data = r.json()
        status = data.get('status')
        if status == 'COMPLETE':
            alpha_id = data.get('alpha')
            if alpha_id:
                try:
                    ar = session.get(f"{BASE_URL}/alphas/{alpha_id}", timeout=30)
                except:
                    return None
                if ar.status_code == 200:
                    ad = ar.json()
                    is_data = ad.get('is', {})
                    checks = is_data.get('checks', [])
                    failures = [c['name'] for c in checks if c.get('result') == 'FAIL']
                    return {
                        'alpha_id': alpha_id,
                        'sharpe': is_data.get('sharpe', 0),
                        'fitness': is_data.get('fitness', 0),
                        'turnover': is_data.get('turnover', 0),
                        'returns': is_data.get('returns', 0),
                        'drawdown': is_data.get('drawdown', 0),
                        'checks': checks,
                        'failed_checks': failures,
                    }
            return None
        elif status in ('ERROR',):
            print(f"  [!] Simulation ERROR for '{expression[:50]}...'")
            return None

    print(f"  [!] Simulation TIMEOUT for '{expression[:50]}...' after {POLL_TIMEOUT}s")
    return None
"""

content = re.sub(r'def simulate\(expression, settings\):.*?def log_simulation', new_simulate + '\n\ndef log_simulation', content, flags=re.DOTALL)

with open('alpha_bot.py', 'w') as f:
    f.write(content)
