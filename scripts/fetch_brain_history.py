#!/usr/bin/env python3
"""
Fetch all alphas from the WorldQuant BRAIN account and merge into
simulation_history.json for ML model retraining.
"""

import json
import time
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from genalpha import config
from genalpha.scrape_brain import get_session, BASE_URL, _get_with_retry

def fetch_all_alphas():
    """Paginate through GET /users/self/alphas and return all alpha objects."""
    session = get_session()
    all_alphas = []
    offset = 0
    limit = 100
    total = None

    print("=" * 60)
    print("  FETCHING ALL ALPHAS FROM WQ BRAIN")
    print("=" * 60)

    while True:
        params = {
            'limit': limit,
            'offset': offset,
            'order': '-dateCreated',
        }
        resp = session.get(f'{BASE_URL}/users/self/alphas', params=params, timeout=30)

        if resp.status_code == 429:
            wait = int(resp.headers.get('Retry-After', 10))
            print(f"  [rate limit] Sleeping {wait}s...")
            time.sleep(wait)
            continue

        if resp.status_code != 200:
            print(f"  [error] HTTP {resp.status_code}: {resp.text[:200]}")
            break

        data = resp.json()
        if total is None:
            total = data.get('count', 0)
            print(f"  Total alphas on account: {total}")

        results = data.get('results', [])
        if not results:
            break

        all_alphas.extend(results)
        print(f"  Fetched {len(all_alphas)}/{total}...")

        offset += limit
        if offset >= total:
            break

        time.sleep(1.5)  # polite rate limiting

    print(f"  Done. Retrieved {len(all_alphas)} alpha records.")
    return all_alphas, session


def fetch_alpha_details(session, alpha_id):
    """Fetch IS metrics for a single alpha."""
    resp = session.get(f'{BASE_URL}/alphas/{alpha_id}', timeout=30)
    if resp.status_code == 429:
        wait = int(resp.headers.get('Retry-After', 10))
        time.sleep(wait)
        resp = session.get(f'{BASE_URL}/alphas/{alpha_id}', timeout=30)

    if resp.status_code != 200:
        return None

    data = resp.json()
    is_data = data.get('is', {})
    return {
        'alpha_id': alpha_id,
        'expression': data.get('regular', data.get('code', '')),
        'settings': {
            'universe': data.get('settings', {}).get('universe', 'TOP3000'),
            'neutralization': data.get('settings', {}).get('neutralization', 'SUBINDUSTRY'),
            'decay': data.get('settings', {}).get('decay', 0),
            'truncation': data.get('settings', {}).get('truncation', 0.08),
            'delay': data.get('settings', {}).get('delay', 1),
            'nan_handling': data.get('settings', {}).get('nanHandling', 'ON'),
        },
        'sharpe': is_data.get('sharpe'),
        'fitness': is_data.get('fitness'),
        'turnover': is_data.get('turnover'),
        'returns': is_data.get('returns'),
        'drawdown': is_data.get('drawdown'),
    }


def load_existing_history(path=None):
    path = str(path or config.SIM_HISTORY)
    """Load existing simulation history (JSON Lines format)."""
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path) as f:
        for line in f:
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def _entry_key(entry):
    """Dedup key: (expression, settings). Expression-only dedup would collapse
    the same expression tested under different sweep/mutation settings."""
    expr = entry.get('expression', '')
    if isinstance(expr, dict):
        expr = json.dumps(expr, sort_keys=True)
    settings = entry.get('settings', {}) or {}
    return expr, json.dumps(settings, sort_keys=True)


def merge_and_save(new_entries, path=None):
    """Merge new entries into simulation_history.json, deduplicating by (expression, settings)."""
    import shutil
    import tempfile

    path = str(path or config.SIM_HISTORY)
    existing = load_existing_history(path)

    existing_map = {}
    for i, e in enumerate(existing):
        key = _entry_key(e)
        if key[0]:
            existing_map[key] = i

    added = 0
    updated = 0
    for entry in new_entries:
        key = _entry_key(entry)
        if not key[0]:
            continue
        if key in existing_map:
            idx = existing_map[key]
            # Update if the new entry has valid fitness but the old one didn't
            if existing[idx].get('fitness') is None and entry.get('fitness') is not None:
                for field in ('template_name', 'source', 'timestamp'):
                    if field in existing[idx]:
                        entry[field] = existing[idx][field]
                existing[idx] = entry
                updated += 1
        else:
            existing_map[key] = len(existing)
            existing.append(entry)
            added += 1

    # Atomic write: back up, write to a temp file, then rename over the original.
    # This runs unattended inside auto-retraining — a crash mid-write must not
    # destroy the history.
    if os.path.exists(path):
        shutil.copy2(path, path + '.bak')
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            for entry in existing:
                json.dump(entry, f)
                f.write('\n')
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    print(f"  Merged: {added} new, {updated} updated entries. Total: {len(existing)}.")
    return len(existing)


def main():
    alphas, session = fetch_all_alphas()

    existing = load_existing_history()
    known_ids = set(e.get('alpha_id') for e in existing if e.get('alpha_id'))
    print(f"  Found {len(known_ids)} known alpha IDs in local history.")

    print(f"\n  Fetching IS metrics for up to {len(alphas)} alphas...")
    detailed = []
    
    # Filter out already known alphas
    alphas_to_fetch = [a for a in alphas if a.get('id') and a.get('id') not in known_ids]
    print(f"  Only need to fetch details for {len(alphas_to_fetch)} new alphas.")

    for i, alpha in enumerate(alphas_to_fetch):
        aid = alpha.get('id')
        detail = fetch_alpha_details(session, aid)
        if detail and detail.get('expression'):
            detailed.append(detail)

        if (i + 1) % 25 == 0:
            print(f"    {i+1}/{len(alphas_to_fetch)} processed...")
            time.sleep(1)  # rate limit
        else:
            time.sleep(0.3)

    print(f"  Got details for {len(detailed)} new alphas.")

    total = merge_and_save(detailed)
    print(f"\n  simulation_history.json now has {total} entries.")
    print("  Run `python3 train_recommender.py` to retrain the model.")


if __name__ == '__main__':
    main()
