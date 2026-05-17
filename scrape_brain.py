#!/usr/bin/env python3
"""
Scrape all WorldQuant BRAIN data fields and operators via API.
Uses the authenticated session cookie for access.
"""

import json
import time
import requests
from collections import defaultdict

# Session setup with auth headers
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

COOKIES = {
    'cookieyes-consent': 'consentid:M3pmNmFzcTlySGVtNnRjRTBMeFJaMWsyZFB2VTdsZEo,consent:yes,action:yes,necessary:yes,functional:yes,analytics:yes,performance:yes,advertisement:yes,other:yes; __zlcmid=1XXoVcSsAg7JjWA; t=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJqdGkiOiJlUkdNU3FJeW1vS0toNFhBa0xUekVhYUk3YWdhamNrdyIsImV4cCI6MTc3OTAzODk3MH0.iT5J7C24QbnV4WTfLNPhzKgr_atAKw_7wfVbqVQed4k'
}

BASE_URL = 'https://api.worldquantbrain.com'

session = requests.Session()
session.headers.update(HEADERS)
session.cookies.update(COOKIES)


def scrape_data_fields():
    """Scrape all data fields with pagination and by category."""
    all_fields = []
    limit = 50  # max per page
    
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
                'dataset.category': category
            }
            
            # Use 'dataset.category' or just 'category' parameter? The user suggested 'category=news'
            params['category'] = category
            
            response = session.get(
                f'{BASE_URL}/data-fields',
                params=params
            )

            if response.status_code != 200:
                print(f"Error at offset {offset} for {category}: HTTP {response.status_code}")
                print(response.text[:500])
                break

            data = response.json()

            if total is None:
                total = data.get('count', 0)
                print(f"Total fields to fetch in {category}: {total}")

            fields = data.get('results', [])
            if not fields:
                break

            cat_fields.extend(fields)
            print(f"  Fetched {len(cat_fields)}/{total} fields in {category}...")

            offset += limit

            if offset >= total:
                break

            time.sleep(2.0)  # Rate limiting
            
        all_fields.extend(cat_fields)

    return all_fields


def scrape_operators():
    """Scrape all operators."""
    print("\n" + "=" * 60)
    print("SCRAPING OPERATORS")
    print("=" * 60)

    # Try FASTEXPR language first
    response = session.get(
        f'{BASE_URL}/operators',
        params={'language': 'FASTEXPR'}
    )

    if response.status_code == 200:
        operators = response.json()
        print(f"Fetched {len(operators)} operators")
        return operators
    else:
        print(f"Error fetching operators: HTTP {response.status_code}")
        print(response.text[:500])
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

    # Find fields relevant to our target signal types
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
        
        # Deduplicate
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
            # might be a dict of categories
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
    # Scrape
    fields = scrape_data_fields()
    operators = scrape_operators()

    # Save raw data
    with open('brain_fields.json', 'w') as f:
        json.dump(fields, f, indent=2)
    print(f"\nSaved {len(fields)} fields to brain_fields.json")

    with open('brain_operators.json', 'w') as f:
        json.dump(operators, f, indent=2)
    print(f"Saved operators to brain_operators.json")

    # Analyze
    categories, datasets, subcategories = analyze_fields(fields)
    analyze_operators(operators)

    # Save summary
    summary = {
        'total_fields': len(fields),
        'categories': {k: len(v) for k, v in categories.items()},
        'datasets': {k: len(v) for k, v in datasets.items()},
        'subcategories': {k: len(v) for k, v in subcategories.items()},
    }
    with open('brain_summary.json', 'w') as f:
        json.dump(summary, f, indent=2)
    print("\nSaved summary to brain_summary.json")
