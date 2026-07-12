#!/usr/bin/env python3
"""
Scrape alpha research from public web sources and build an expanded template library.
Sources: WorldQuant seminar notes, 101 Formulaic Alphas patterns, GitHub repos.
"""

import json
import re
import time
import requests
from pathlib import Path

RESEARCH_SOURCES = [
    {
        "name": "worldquant_seminar",
        "url": "https://raw.githubusercontent.com/jglazar/notes/main/quant_interview/worldquant_seminar.md",
        "type": "markdown",
    },
    {
        "name": "wq_alpha_examples",
        "url": "https://raw.githubusercontent.com/zhutoutoutousan/worldquant-miner/main/agent/alpha_templates.json",
        "type": "json",
    },
]

# Curated high-quality alpha patterns from 101 Formulaic Alphas + WQ seminars
# These are proven signal families with parameterized field slots
CURATED_TEMPLATES = [
    # ── Price/Volume Reversion ──
    {"name": "pv_mean_reversion_5d", "category": "pv", "expression": "-(close - ts_mean(close, 5))",
     "settings": {"neutralization": "MARKET", "decay": 5, "truncation": 0.01}, "field_slot": None},
    {"name": "pv_vwap_reversion", "category": "pv", "expression": "rank(vwap / close)",
     "settings": {"neutralization": "MARKET", "decay": 5, "truncation": 0.01}, "field_slot": None},
    {"name": "pv_candlestick", "category": "pv", "expression": "group_zscore(-(close - open) / (high - low), subindustry)",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 3, "truncation": 0.01}, "field_slot": None},
    {"name": "pv_vwap_zscore_rank", "category": "pv", "expression": "group_rank(ts_zscore(vwap/close, 250), subindustry)",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 3, "truncation": 0.01}, "field_slot": None},
    {"name": "pv_regression_residual", "category": "pv", "expression": "-ts_regression(returns, ts_delay(returns, 1), 252)",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 5, "truncation": 0.01}, "field_slot": None},
    {"name": "pv_vol_regime_reversion", "category": "pv",
     "expression": "trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.55, -ts_regression(returns, ts_delay(returns,1), 252), -1)",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 5, "truncation": 0.1}, "field_slot": None},
    {"name": "pv_high_low_reversion", "category": "pv", "expression": "(high + low)/2 - close",
     "settings": {"neutralization": "MARKET", "decay": 10, "truncation": 0.01}, "field_slot": None},
    {"name": "pv_delta_reversion", "category": "pv", "expression": "-ts_delta(close, 5)",
     "settings": {"neutralization": "MARKET", "decay": 20, "truncation": 0.01}, "field_slot": None},
    {"name": "pv_volume_price_corr", "category": "pv",
     "expression": "-ts_corr(ts_rank(volume, 10), ts_rank(vwap, 10), 20)",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 3, "truncation": 0.1}, "field_slot": None},
    {"name": "pv_volume_spike_reversion", "category": "pv",
     "expression": "trade_when(ts_arg_max(volume, 5) == 0, -rank(ts_delta(close, 3)), -1)",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 3, "truncation": 0.1}, "field_slot": None},
    {"name": "pv_zscore_combo", "category": "pv",
     "expression": "zscore(vwap / close) * (1 - rank(high / low))",
     "settings": {"neutralization": "MARKET", "decay": 15, "truncation": 0.01}, "field_slot": None},
    {"name": "pv_complex_reversion", "category": "pv",
     "expression": "decay_days = 2; rel_days_since_max = rank(ts_arg_max(close, 30)); decline_pct = (vwap - close) / close; decline_pct / min(ts_decay_linear(rel_days_since_max, decay_days), 0.20)",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 10, "truncation": 0.01}, "field_slot": None},
    {"name": "pv_sma_reversion", "category": "pv",
     "expression": "signal = ts_mean(close, 20) / ts_mean(close, 5); signed_power(ts_zscore(signal, 480), 2)",
     "settings": {"neutralization": "MARKET", "decay": 5, "truncation": 0.01}, "field_slot": None},

    # ── Fundamental / Valuation ──
    {"name": "fnd_ts_rank_ratio", "category": "fundamental", "expression": "ts_rank({FIELD}/cap, 252)",
     "settings": {"neutralization": "INDUSTRY", "decay": 5, "truncation": 0.1}, "field_slot": "FIELD"},
    {"name": "fnd_zscore_short", "category": "fundamental", "expression": "-ts_zscore({FIELD}, 63)",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 0, "truncation": 0.1}, "field_slot": "FIELD"},
    {"name": "fnd_ts_rank_long", "category": "fundamental", "expression": "ts_rank({FIELD}, 252)",
     "settings": {"neutralization": "INDUSTRY", "decay": 0, "truncation": 0.01}, "field_slot": "FIELD"},
    {"name": "fnd_ts_rank_short", "category": "fundamental", "expression": "-ts_rank({FIELD}, 63)",
     "settings": {"neutralization": "INDUSTRY", "decay": 5, "truncation": 0.01}, "field_slot": "FIELD"},
    {"name": "fnd_av_diff", "category": "fundamental", "expression": "ts_av_diff({FIELD}, 500)",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 0, "truncation": 0.08}, "field_slot": "FIELD"},
    {"name": "fnd_group_zscore", "category": "fundamental", "expression": "group_zscore(ts_zscore({FIELD}, 20), sector)",
     "settings": {"neutralization": "SECTOR", "decay": 8, "truncation": 0.01}, "field_slot": "FIELD"},
    {"name": "fnd_delta_rank", "category": "fundamental", "expression": "rank(ts_delta({FIELD}, 90))",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 5, "truncation": 0.01}, "field_slot": "FIELD"},
    {"name": "fnd_pb_reversion", "category": "fundamental", "expression": "rank(-({FIELD} - ts_max({FIELD}, 10)))",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 3, "truncation": 0.01}, "field_slot": "FIELD"},

    # ── Analyst ──
    {"name": "anl_ts_rank", "category": "analyst", "expression": "ts_rank({FIELD}, 252)",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 0, "truncation": 0.01}, "field_slot": "FIELD"},
    {"name": "anl_ts_rank_short", "category": "analyst", "expression": "-ts_rank({FIELD}, 63)",
     "settings": {"neutralization": "SECTOR", "decay": 5, "truncation": 0.05}, "field_slot": "FIELD"},
    {"name": "anl_raw_flag", "category": "analyst", "expression": "{FIELD}",
     "settings": {"neutralization": "SECTOR", "decay": 5, "truncation": 0.05}, "field_slot": "FIELD"},
    {"name": "anl_negated_flag", "category": "analyst", "expression": "-{FIELD}",
     "settings": {"neutralization": "SECTOR", "decay": 5, "truncation": 0.05}, "field_slot": "FIELD"},
    {"name": "anl_zscore", "category": "analyst", "expression": "zscore({FIELD})",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 5, "truncation": 0.01}, "field_slot": "FIELD"},

    # ── News / Sentiment ──
    {"name": "news_sentiment_conditional", "category": "news",
     "expression": "avg_news = vec_avg({FIELD}); rank(ts_sum(avg_news, 60)) > 0.5 ? 1 : rank(-ts_delta(close, 2))",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 3, "truncation": 0.01}, "field_slot": "FIELD"},
    {"name": "news_regression", "category": "news",
     "expression": "-ts_regression(returns, ts_delay(vec_avg({FIELD}), 1), 120)",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 15, "truncation": 0.1}, "field_slot": "FIELD"},
    {"name": "news_backfill_diff", "category": "news",
     "expression": "buzz = ts_backfill(-vec_sum({FIELD}), 20); ts_av_diff(buzz, 60)",
     "settings": {"neutralization": "INDUSTRY", "decay": 15, "truncation": 0.08}, "field_slot": "FIELD"},
    {"name": "news_vec_backfill", "category": "news",
     "expression": "ts_backfill(-vec_avg({FIELD}), 20)",
     "settings": {"neutralization": "INDUSTRY", "decay": 10, "truncation": 0.01}, "field_slot": "FIELD"},

    # ── Options ──
    {"name": "opt_delay_ratio", "category": "option", "expression": "ts_delay({FIELD}, 7) / close",
     "settings": {"neutralization": "INDUSTRY", "decay": 0, "truncation": 0.03}, "field_slot": "FIELD"},
    {"name": "opt_iv_spread", "category": "option",
     "expression": "zscore(implied_volatility_call_720 - implied_volatility_put_720)",
     "settings": {"neutralization": "MARKET", "decay": 3, "truncation": 0.01}, "field_slot": None},
    {"name": "opt_iv_decay", "category": "option",
     "expression": "ts_decay_linear(ts_delta(implied_volatility_call_60, 25) > 0, 20)",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 0, "truncation": 0.03}, "field_slot": None},
    {"name": "opt_ts_rank", "category": "option", "expression": "ts_rank({FIELD}, 252)",
     "settings": {"neutralization": "SECTOR", "decay": 3, "truncation": 0.05}, "field_slot": "FIELD"},

    # ── Model / Risk ──
    {"name": "mdl_ts_rank", "category": "model", "expression": "ts_rank({FIELD}, 250)",
     "settings": {"neutralization": "INDUSTRY", "decay": 0, "truncation": 0.01}, "field_slot": "FIELD"},
    {"name": "mdl_group_zscore", "category": "model", "expression": "group_zscore(ts_zscore({FIELD}, 20), sector)",
     "settings": {"neutralization": "SECTOR", "decay": 8, "truncation": 0.1}, "field_slot": "FIELD"},
    {"name": "mdl_volatility", "category": "model", "expression": "rank(-{FIELD})",
     "settings": {"neutralization": "MARKET", "decay": 3, "truncation": 0.1}, "field_slot": "FIELD"},
    {"name": "risk_ts_rank", "category": "model", "expression": "ts_rank({FIELD}, 63)",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 15, "truncation": 0.05}, "field_slot": "FIELD"},
    {"name": "risk_ts_rank_long", "category": "model", "expression": "ts_rank({FIELD}, 252)",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 5, "truncation": 0.05}, "field_slot": "FIELD"},

    # ── Generic field templates (fallback) ──
    {"name": "generic_raw", "category": "generic", "expression": "{FIELD}",
     "settings": {"neutralization": "SECTOR", "decay": 5, "truncation": 0.05}, "field_slot": "FIELD"},
    {"name": "generic_negated", "category": "generic", "expression": "-{FIELD}",
     "settings": {"neutralization": "SECTOR", "decay": 5, "truncation": 0.05}, "field_slot": "FIELD"},
    {"name": "generic_ts_rank_252", "category": "generic", "expression": "ts_rank({FIELD}, 252)",
     "settings": {"neutralization": "SECTOR", "decay": 5, "truncation": 0.05}, "field_slot": "FIELD"},
    {"name": "generic_ts_rank_63", "category": "generic", "expression": "ts_rank({FIELD}, 63)",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 5, "truncation": 0.05}, "field_slot": "FIELD"},
    {"name": "generic_ts_av_diff", "category": "generic", "expression": "ts_av_diff({FIELD}, 63)",
     "settings": {"neutralization": "SUBINDUSTRY", "decay": 5, "truncation": 0.05}, "field_slot": "FIELD"},
    {"name": "generic_deviation", "category": "generic", "expression": "{FIELD} - ts_mean({FIELD}, 252)",
     "settings": {"neutralization": "SECTOR", "decay": 5, "truncation": 0.05}, "field_slot": "FIELD"},
    {"name": "generic_zscore", "category": "generic", "expression": "ts_zscore({FIELD}, 63)",
     "settings": {"neutralization": "SECTOR", "decay": 5, "truncation": 0.05}, "field_slot": "FIELD"},
    {"name": "generic_ts_quantile", "category": "generic", "expression": "ts_quantile({FIELD}, 252)",
     "settings": {"neutralization": "SECTOR", "decay": 5, "truncation": 0.05}, "field_slot": "FIELD"},
]

# Regex to extract alpha expressions from markdown backtick blocks
EXPR_PATTERN = re.compile(
    r'`((?:ts_|rank|zscore|group_|trade_when|vec_|decay_days|signal|buzz|avg_|when|lookback|window|above|a\s*=)[^`]+)`',
    re.IGNORECASE
)


def fetch_url(url, timeout=30):
    """Fetch content from a URL with retry."""
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=timeout, headers={
                'User-Agent': 'GenAlpha-ResearchBot/1.0'
            })
            if resp.status_code == 200:
                return resp.text
            print(f"  HTTP {resp.status_code} for {url}")
        except requests.RequestException as e:
            print(f"  Attempt {attempt+1} failed: {e}")
        time.sleep(2)
    return None


def extract_expressions_from_markdown(text):
    """Extract alpha expressions from markdown seminar notes."""
    expressions = []
    for match in EXPR_PATTERN.finditer(text):
        expr = match.group(1).strip()
        if len(expr) > 10 and not expr.startswith('ts_rank(mdf_oey') and 'e.g.' not in expr:
            expressions.append(expr)
    return expressions


def categorize_field(field_id, field_meta=None):
    """Infer field category from field ID prefix and metadata."""
    fid = field_id.lower()
    if field_meta:
        cat = field_meta.get('category', {}).get('name', '').lower()
        if cat:
            return cat

    prefix_map = {
        'anl': 'analyst', 'anl4': 'analyst', 'fnd': 'fundamental', 'fnd6': 'fundamental',
        'nws': 'news', 'snt': 'news', 'scl': 'news', 'mdf': 'model', 'mdl': 'model',
        'opt': 'option', 'iv_': 'option', 'implied_': 'option', 'pcr_': 'option',
        'call_': 'option', 'put_': 'option',
    }
    for prefix, category in prefix_map.items():
        if fid.startswith(prefix):
            return category

    if any(k in fid for k in ['risk', 'volatil', 'beta', 'correl']):
        return 'model'
    if any(k in fid for k in ['sentiment', 'buzz', 'news']):
        return 'news'
    return 'generic'


def scrape_all():
    """Scrape all research sources and build template library."""
    print("=" * 60)
    print("SCRAPING ALPHA RESEARCH FROM WEB")
    print("=" * 60)

    scraped_expressions = []
    external_templates = []

    for source in RESEARCH_SOURCES:
        print(f"\nFetching: {source['name']} ({source['url']})")
        content = fetch_url(source['url'])
        if not content:
            print(f"  FAILED to fetch {source['name']}")
            continue

        if source['type'] == 'markdown':
            exprs = extract_expressions_from_markdown(content)
            scraped_expressions.extend(exprs)
            print(f"  Extracted {len(exprs)} expressions from markdown")
        elif source['type'] == 'json':
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    external_templates.extend(data)
                    print(f"  Loaded {len(data)} external templates")
            except json.JSONDecodeError:
                print(f"  Failed to parse JSON from {source['name']}")

    # Build final template library
    all_templates = list(CURATED_TEMPLATES)

    # Add scraped expressions as standalone PV templates (no field slot)
    seen_exprs = {t['expression'] for t in all_templates}
    for expr in scraped_expressions:
        if expr not in seen_exprs and len(expr) < 500:
            all_templates.append({
                "name": f"scraped_{len(all_templates)}",
                "category": "pv",
                "expression": expr,
                "settings": {"neutralization": "SUBINDUSTRY", "decay": 5, "truncation": 0.01},
                "field_slot": None,
                "source": "scraped",
            })
            seen_exprs.add(expr)

    # Merge external templates if fetched
    for ext in external_templates:
        if isinstance(ext, dict) and 'expression' in ext:
            all_templates.append({
                "name": ext.get("name", f"ext_{len(all_templates)}"),
                "category": ext.get("category", "generic"),
                "expression": ext["expression"],
                "settings": ext.get("settings", {"neutralization": "SECTOR", "decay": 5, "truncation": 0.05}),
                "field_slot": "FIELD" if "{FIELD}" in ext.get("expression", "") else None,
                "source": "external",
            })

    # Save
    output = {
        "total_templates": len(all_templates),
        "scraped_expressions": len(scraped_expressions),
        "templates": all_templates,
    }

    from genalpha.config import RESEARCH_TEMPLATES
    with open(RESEARCH_TEMPLATES, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n{'='*60}")
    print(f"RESEARCH SCRAPE COMPLETE")
    print(f"  Curated templates: {len(CURATED_TEMPLATES)}")
    print(f"  Scraped expressions: {len(scraped_expressions)}")
    print(f"  Total templates: {len(all_templates)}")
    print(f"  Saved to research_templates.json")
    print(f"{'='*60}")

    return output


if __name__ == '__main__':
    scrape_all()
