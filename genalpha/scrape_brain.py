#!/usr/bin/env python3
"""
WorldQuant BRAIN API access: authentication, retrying HTTP helpers, and
the data-field / operator scrapers.

Auth priority (tries each in order until one works):
  1. HTTP Basic Auth from env vars WQ_BRAIN_USERNAME / WQ_BRAIN_PASSWORD (.env supported)
  2. HTTP Basic Auth from local credential.txt  (JSON array: ["user","pass"])
  3. Session cookie string from env var WQ_SESSION_COOKIE (manual fallback)

If none of these authenticate, AuthError is raised — callers must not
silently continue with an unauthenticated session.
"""

import json
import os
import random
import threading
import time
import requests
from requests.auth import HTTPBasicAuth
from collections import defaultdict
from genalpha import config

# ──────────────────────────────────────────────────────────────────
# Authentication
# ──────────────────────────────────────────────────────────────────
BASE_URL = 'https://api.worldquantbrain.com'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:150.0) Gecko/20100101 Firefox/150.0',
    'Accept': 'application/json;version=3.0',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Referer': 'https://platform.worldquantbrain.com/',
    'Origin': 'https://platform.worldquantbrain.com',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
}


class AuthError(RuntimeError):
    """Raised when no authentication method succeeds."""


# Authenticated cookie jar shared across threads; each thread gets its own
# requests.Session built from it (requests.Session is not thread-safe).
_auth_lock = threading.Lock()
_auth_state = {"cookies": None, "generation": 0}
_thread_local = threading.local()


def _load_credentials():
    username = os.getenv('WQ_BRAIN_USERNAME')
    password = os.getenv('WQ_BRAIN_PASSWORD')
    if not (username and password) and os.path.exists(config.CREDENTIALS_FILE):
        try:
            with open(config.CREDENTIALS_FILE) as f:
                creds = json.load(f)
                if isinstance(creds, list) and len(creds) == 2:
                    username, password = creds[0], creds[1]
                elif isinstance(creds, dict):
                    username = creds.get('username') or creds.get('user')
                    password = creds.get('password') or creds.get('pass')
        except Exception as e:
            print(f"[auth] credential.txt parse error: {e}")
    return username, password


def _authenticate():
    """Authenticate against the BRAIN API and return a cookie dict.

    Raises AuthError if every method fails.
    """
    username, password = _load_credentials()

    if username and password:
        sess = requests.Session()
        sess.headers.update(HEADERS)
        sess.auth = HTTPBasicAuth(username, password)
        try:
            resp = sess.post(f'{BASE_URL}/authentication', timeout=15)
            if resp.status_code == 201:
                print(f"[auth] ✅ HTTP Basic Auth successful as '{username}'")
                return sess.cookies.get_dict()
            print(f"[auth] ⚠️  Basic Auth returned {resp.status_code}: {resp.text[:120]}")
        except requests.RequestException as e:
            print(f"[auth] Basic Auth request failed: {e}")

    cookie_str = os.getenv('WQ_SESSION_COOKIE')
    if cookie_str:
        cookies = {}
        for part in cookie_str.split(';'):
            if '=' in part:
                k, v = part.strip().split('=', 1)
                cookies[k] = v
        sess = requests.Session()
        sess.headers.update(HEADERS)
        sess.cookies.update(cookies)
        try:
            resp = sess.get(f'{BASE_URL}/users/self', timeout=15)
            if resp.status_code == 200:
                print("[auth] ✅ WQ_SESSION_COOKIE accepted")
                return cookies
            print(f"[auth] ⚠️  WQ_SESSION_COOKIE rejected (HTTP {resp.status_code})")
        except requests.RequestException as e:
            print(f"[auth] Cookie auth request failed: {e}")

    raise AuthError(
        "Could not authenticate with WorldQuant BRAIN. Set WQ_BRAIN_USERNAME / "
        "WQ_BRAIN_PASSWORD in .env (or credential.txt / WQ_SESSION_COOKIE)."
    )


def get_session() -> requests.Session:
    """Return a per-thread authenticated Session, authenticating on first use."""
    with _auth_lock:
        if _auth_state["cookies"] is None:
            _auth_state["cookies"] = _authenticate()
            _auth_state["generation"] += 1
        generation = _auth_state["generation"]
        cookies = _auth_state["cookies"]

    if getattr(_thread_local, "generation", None) != generation:
        sess = requests.Session()
        sess.headers.update(HEADERS)
        sess.cookies.update(cookies)
        _thread_local.session = sess
        _thread_local.generation = generation
    return _thread_local.session


def reauthenticate() -> requests.Session:
    """Force a fresh login (e.g. after a 401). Raises AuthError on failure.

    Only one thread re-authenticates; others pick up the new cookie jar
    via the generation counter in get_session().
    """
    with _auth_lock:
        _auth_state["cookies"] = _authenticate()
        _auth_state["generation"] += 1
    return get_session()


# ──────────────────────────────────────────────────────────────────
# API helpers
# ──────────────────────────────────────────────────────────────────
def request_with_retry(method, url, max_retries=5, base_sleep=2.0, max_auth_retries=2, **kwargs):
    """HTTP request with Retry-After-aware backoff on 429 and capped re-auth on 401/403.

    Returns the final Response, or None if retries were exhausted on 429/network
    errors. Raises AuthError if re-authentication fails or 401s persist.
    """
    kwargs.setdefault('timeout', 30)
    sleep = base_sleep
    auth_retries = 0
    for attempt in range(max_retries):
        try:
            resp = get_session().request(method, url, **kwargs)
        except requests.RequestException as e:
            print(f"  [http] {method} {url.split('?')[0]} failed: {e} (attempt {attempt+1}/{max_retries})")
            time.sleep(sleep + random.uniform(0, 1))
            sleep = min(sleep * 2, 120)
            continue

        if resp.status_code == 429:
            try:
                retry_after = float(resp.headers.get('Retry-After', sleep))
            except (TypeError, ValueError):
                retry_after = sleep
            wait = max(retry_after, sleep) + random.uniform(0, 3)
            print(f"  [rate limit] 429 — sleeping {wait:.1f}s (attempt {attempt+1}/{max_retries})")
            time.sleep(wait)
            sleep = min(sleep * 2, 120)
            continue

        if resp.status_code in (401, 403):
            auth_retries += 1
            if auth_retries > max_auth_retries:
                raise AuthError(f"Still HTTP {resp.status_code} after {max_auth_retries} re-auth attempts.")
            print(f"  [auth] HTTP {resp.status_code} — re-authenticating ({auth_retries}/{max_auth_retries})...")
            reauthenticate()
            continue

        return resp
    return None  # exhausted


def _get_with_retry(url, params=None, max_retries=5, base_sleep=2.0):
    """GET with backoff (kept for backward compatibility)."""
    return request_with_retry('GET', url, max_retries=max_retries,
                              base_sleep=base_sleep, params=params)


# ──────────────────────────────────────────────────────────────────
# Scraping
# ──────────────────────────────────────────────────────────────────
def scrape_data_fields():
    """Scrape all data fields with pagination and by category."""
    all_fields = []
    limit = 50
    categories = ['model', 'fundamental', 'analyst', 'news', 'pv', 'option']

    print("=" * 60)
    print("SCRAPING DATA FIELDS BY CATEGORY")
    print("=" * 60)

    for category in categories:
        offset = 0
        cat_fields = []
        total = None
        print(f"\nScraping category: {category}")

        while True:
            params = {
                'delay': 1,
                'instrumentType': 'EQUITY',
                'limit': limit,
                'offset': offset,
                'region': 'USA',
                'universe': 'TOP3000',
                'category': category,
            }

            response = _get_with_retry(f'{BASE_URL}/data-fields', params=params)
            if response is None:
                print(f"  [!] Exhausted retries for {category} at offset {offset}")
                break

            if response.status_code != 200:
                print(f"  Error at offset {offset} for {category}: HTTP {response.status_code}")
                print(response.text[:500])
                break

            data = response.json()
            if total is None:
                total = data.get('count', 0)
                print(f"  Total fields to fetch in {category}: {total}")

            fields = data.get('results', [])
            if not fields:
                break

            cat_fields.extend(fields)
            print(f"  Fetched {len(cat_fields)}/{total} fields in {category}...")

            offset += limit
            if offset >= total:
                break

            time.sleep(1.5)  # polite rate limit

        all_fields.extend(cat_fields)

    return all_fields


def scrape_operators():
    """Scrape all FASTEXPR operators."""
    print("\n" + "=" * 60)
    print("SCRAPING OPERATORS")
    print("=" * 60)

    response = _get_with_retry(f'{BASE_URL}/operators', params={'language': 'FASTEXPR'})
    if response and response.status_code == 200:
        operators = response.json()
        print(f"Fetched {len(operators)} operators")
        return operators
    else:
        code = response.status_code if response else 'timeout'
        print(f"Error fetching operators: HTTP {code}")
        return []


def analyze_fields(fields):
    """Analyze and categorize all fields."""
    categories = defaultdict(list)
    datasets = defaultdict(list)
    subcategories = defaultdict(list)

    for f in fields:
        cat = f.get('category', {}).get('name', 'Unknown')
        ds = f.get('dataset', {}).get('name', 'Unknown')
        subcat = f.get('subcategory', {}).get('name', 'Unknown')
        categories[cat].append(f)
        datasets[ds].append(f)
        subcategories[subcat].append(f)

    print("\n" + "=" * 60)
    print("FIELD ANALYSIS")
    print("=" * 60)

    print("\n--- BY CATEGORY ---")
    for cat, flds in sorted(categories.items(), key=lambda x: -len(x[1])):
        print(f"  {cat}: {len(flds)} fields")

    print("\n--- BY DATASET ---")
    for ds, flds in sorted(datasets.items(), key=lambda x: -len(x[1])):
        print(f"  {ds}: {len(flds)} fields")

    print("\n--- BY SUBCATEGORY ---")
    for sub, flds in sorted(subcategories.items(), key=lambda x: -len(x[1])):
        print(f"  {sub}: {len(flds)} fields")

    print("\n" + "=" * 60)
    print("FIELDS FOR TARGET SIGNAL FAMILIES")
    print("=" * 60)

    target_keywords = {
        'sentiment': ['sentiment', 'buzz', 'news', 'raven', 'event', 'earnings_surprise'],
        'options': ['option', 'put', 'call', 'implied_vol', 'iv_', 'skew', 'strike'],
        'analyst': ['analyst', 'eps_', 'revision', 'estimate', 'consensus', 'recommend', 'upgrade', 'downgrade', 'forecast'],
        'volatility': ['volatil', 'vol_', 'realized_vol', 'hist_vol', 'iv_spread'],
    }

    for family, keywords in target_keywords.items():
        print(f"\n--- {family.upper()} ---")
        matches = []
        for f in fields:
            fid = f.get('id', '').lower()
            fdesc = f.get('description', '').lower()
            for kw in keywords:
                if kw in fid or kw in fdesc:
                    matches.append(f)
                    break

        seen = set()
        for m in matches:
            mid = m['id']
            if mid not in seen:
                seen.add(mid)
                coverage = m.get('coverage', 0)
                user_count = m.get('userCount', 0)
                alpha_count = m.get('alphaCount', 0)
                ds = m.get('dataset', {}).get('name', '?')
                desc = m.get('description', '')[:80]
                print(f"  {mid}")
                print(f"    Dataset: {ds} | Coverage: {coverage:.1%} | Users: {user_count} | Alphas: {alpha_count}")
                print(f"    Desc: {desc}")

    return categories, datasets, subcategories


def analyze_operators(operators):
    """Analyze operators by category."""
    if isinstance(operators, list):
        op_list = operators
    elif isinstance(operators, dict):
        op_list = operators.get('results', operators.get('operators', []))
        if not op_list and 'count' not in operators:
            print("\nOperator response structure:")
            for key in operators:
                val = operators[key]
                if isinstance(val, list):
                    print(f"  {key}: {len(val)} items")
                else:
                    print(f"  {key}: {type(val).__name__}")
            return operators
    else:
        print(f"Unexpected operators type: {type(operators)}")
        return operators

    print("\n" + "=" * 60)
    print("OPERATOR ANALYSIS")
    print("=" * 60)

    op_categories = defaultdict(list)
    for op in op_list:
        if isinstance(op, dict):
            cat = op.get('category', op.get('type', 'Unknown'))
            op_categories[cat].append(op)
        else:
            print(f"  Operator (raw): {op}")

    for cat, ops in sorted(op_categories.items()):
        print(f"\n--- {cat} ---")
        for op in ops:
            name = op.get('name', op.get('id', '?'))
            desc = op.get('description', '')[:100]
            print(f"  {name}: {desc}")

    return op_list


if __name__ == '__main__':
    fields = scrape_data_fields()
    operators = scrape_operators()

    with open(config.BRAIN_FIELDS, 'w') as f:
        json.dump(fields, f, indent=2)
    print(f"\nSaved {len(fields)} fields to brain_fields.json")

    with open(config.BRAIN_OPERATORS, 'w') as f:
        json.dump(operators, f, indent=2)
    print(f"Saved operators to brain_operators.json")

    categories, datasets, subcategories = analyze_fields(fields)
    analyze_operators(operators)

    summary = {
        'total_fields': len(fields),
        'categories': {k: len(v) for k, v in categories.items()},
        'datasets': {k: len(v) for k, v in datasets.items()},
        'subcategories': {k: len(v) for k, v in subcategories.items()},
    }
    with open(config.BRAIN_SUMMARY, 'w') as f:
        json.dump(summary, f, indent=2)
    print("\nSaved summary to brain_summary.json")
