import time
import json
import concurrent.futures
from scrape_brain import session, BASE_URL

HISTORICAL_ALPHAS = [
    {
        "name": "Complex PV Reversion",
        "expression": "lookback = 10; avg_ret = power(ts_product(returns+1, lookback), 1/lookback); comp_avg = power(ts_product(rel_ret_comp+1, lookback), 1/lookback); a = zscore(comp_avg / avg_ret); when = ts_rank(ts_std_dev(returns, 60), 126) > 0.55; b = trade_when(when, a, -1); group_vector_neut(b, ts_mean(returns, 120), subindustry)",
        "settings": {"universe": "TOP3000", "decay": 3, "neutralization": "NONE", "truncation": 0.05, "delay": 1}
    },
    {
        "name": "EPSFX / Close",
        "expression": "rank( ts_rank( fnd6_epsfx /close, 40) )",
        "settings": {"universe": "TOP1000", "decay": 9, "neutralization": "SUBINDUSTRY", "truncation": 0.1, "delay": 0} # delay 0 might be hard
    },
    {
        "name": "EBIT / Shares / Close",
        "expression": "rank(ts_rank( ebit/sharesout /close, 40))",
        "settings": {"universe": "TOP1000", "decay": 10, "neutralization": "SUBINDUSTRY", "truncation": 0.1, "delay": 1}
    },
    {
        "name": "Cash / Debt ZScore",
        "expression": "zscore(cash_st/debt_st)",
        "settings": {"universe": "TOP200", "decay": 0, "neutralization": "SECTOR", "truncation": 0.01, "delay": 1}
    },
    {
        "name": "EV / EBITDA ZScore (Short)",
        "expression": "-ts_zscore(enterprise_value/ebitda,63)",
        "settings": {"universe": "TOP3000", "decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.1, "delay": 0}
    },
    {
        "name": "MDF NPS Av Diff",
        "expression": "ts_av_diff(mdf_nps,500)",
        "settings": {"universe": "TOP3000", "decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08, "delay": 1}
    },
    {
        "name": "MDF GRY ZScore",
        "expression": "group_zscore( ts_zscore(mdf_gry, 20), sector )",
        "settings": {"universe": "TOP3000", "decay": 8, "neutralization": "SECTOR", "truncation": 0.01, "delay": 1}
    },
    {
        "name": "Simple Delta Reversion",
        "expression": "-delta(close, 5)",
        "settings": {"universe": "TOP3000", "decay": 20, "neutralization": "MARKET", "truncation": 0.01, "delay": 1}
    },
    {
        "name": "High Low Close Reversion",
        "expression": "(high + low)/2 - close",
        "settings": {"universe": "TOP3000", "decay": 10, "neutralization": "MARKET", "truncation": 0.01, "delay": 1}
    },
    {
        "name": "Complex Rank Reversion 1",
        "expression": "decay_days = 1; rel_days_since_max = rank(ts_arg_max(close, 30)); decline_pct = (vwap - close) / close; decline_pct / min( ts_decay_linear(rel_days_since_max, decay_days), 0.15)",
        "settings": {"universe": "TOP200", "decay": 10, "neutralization": "MARKET", "truncation": 0.05, "delay": 1}
    },
    {
        "name": "Change Day Exp Window",
        "expression": "change_day = (vwap - close) / close; ts_decay_exp_window(rank(change_day), 4)",
        "settings": {"universe": "TOP3000", "decay": 10, "neutralization": "NONE", "truncation": 0.01, "delay": 1}
    },
    {
        "name": "Complex Rank Reversion 2",
        "expression": "decay_days = 2; rel_days_since_max = rank(ts_arg_max(close, 30)); decline_pct = (vwap - close) / close; decline_pct / min( ts_decay_linear(rel_days_since_max, decay_days), 0.20)",
        "settings": {"universe": "TOP3000", "decay": 10, "neutralization": "SUBINDUSTRY", "truncation": 0.01, "delay": 1}
    }
]

def simulate_historical(alpha_def):
    expression = alpha_def["expression"]
    settings = alpha_def["settings"]
    payload = {
        'type': 'REGULAR',
        'settings': {
            'instrumentType': 'EQUITY',
            'region': 'USA',
            'universe': settings.get('universe', 'TOP3000'),
            'delay': settings.get('delay', 1),
            'decay': settings.get('decay', 5),
            'neutralization': settings.get('neutralization', 'SECTOR'),
            'truncation': settings.get('truncation', 0.05),
            'pasteurization': 'ON',
            'unitHandling': 'VERIFY',
            'nanHandling': 'OFF',
            'language': 'FASTEXPR',
            'visualization': False,
        },
        'regular': expression,
    }

    while True:
        resp = session.post(f"{BASE_URL}/simulations", json=payload)
        if resp.status_code == 429:
            print(f"[-] HTTP 429 for {alpha_def['name']}, sleeping 15s...")
            time.sleep(15)
            continue
        elif resp.status_code != 201:
            print(f"[-] HTTP {resp.status_code} for {alpha_def['name']}: {resp.text[:100]}")
            return None
        break

    sim_url = resp.headers.get('Location')
    
    for _ in range(60):
        time.sleep(4)
        r = session.get(sim_url)
        if r.status_code == 200:
            data = r.json()
            if data.get('status') == 'COMPLETE':
                alpha_id = data.get('alpha')
                if alpha_id:
                    ar = session.get(f"{BASE_URL}/alphas/{alpha_id}")
                    if ar.status_code == 200:
                        ad = ar.json()
                        is_data = ad.get('is', {})
                        res = {
                            "name": alpha_def["name"],
                            "sharpe": is_data.get('sharpe'),
                            "fitness": is_data.get('fitness'),
                            "turnover": is_data.get('turnover')
                        }
                        print(f"[★] {alpha_def['name']} -> Sharpe: {res['sharpe']}, Fitness: {res['fitness']}, Turnover: {res['turnover']}")
                        return res
            elif data.get('status') in ('ERROR', 'FAIL'):
                print(f"[-] ERROR for {alpha_def['name']}")
                return None
    return None

def main():
    print(f"Testing {len(HISTORICAL_ALPHAS)} Historical Alphas with 2 concurrent workers...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        executor.map(simulate_historical, HISTORICAL_ALPHAS)

if __name__ == "__main__":
    main()
