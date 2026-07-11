#!/usr/bin/env python3
"""
Fetch all alphas from the WorldQuant BRAIN account and merge into
simulation_history.json for ML model retraining.
"""

import json
import time
import os
from dotenv import load_dotenv

load_dotenv()

from scrape_brain import _build_session, BASE_URL, _get_with_retry

def fetch_all_alphas():
    """Paginate through GET /users/self/alphas and return all alpha objects."""
    session = _build_session()
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


def load_existing_history(path="simulation_history.json"):
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


def merge_and_save(new_entries, path="simulation_history.json"):
    """Merge new entries into simulation_history.json, deduplicating by expression+settings."""
    existing = load_existing_history(path)

    # Build a set of existing expression strings for dedup
    existing_map = {}
    for i, e in enumerate(existing):
        expr = e.get('expression', '')
        if isinstance(expr, dict):
            expr = json.dumps(expr, sort_keys=True)
        if expr:
            existing_map[expr] = i

    added = 0
    updated = 0
    for entry in new_entries:
        expr = entry.get('expression', '')
        if isinstance(expr, dict):
            expr = json.dumps(expr, sort_keys=True)
        if expr:
            if expr in existing_map:
                idx = existing_map[expr]
                # Update if the new entry has valid fitness but the old one didn't
                if existing[idx].get('fitness') is None and entry.get('fitness') is not None:
                    # Preserve template_name and source if existing has it
                    if 'template_name' in existing[idx]:
                        entry['template_name'] = existing[idx]['template_name']
                    if 'source' in existing[idx]:
                        entry['source'] = existing[idx]['source']
                    # Keep original timestamp
                    if 'timestamp' in existing[idx]:
                        entry['timestamp'] = existing[idx]['timestamp']
                    existing[idx] = entry
                    updated += 1
            else:
                existing_map[expr] = len(existing)
                existing.append(entry)
                added += 1

    # Write back as JSON Lines
    with open(path, 'w') as f:
        for entry in existing:
            json.dump(entry, f)
            f.write('\n')

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
