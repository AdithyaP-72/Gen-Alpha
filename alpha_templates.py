"""
Alpha templates derived from WorldQuant researcher seminars and verified expressions.
These templates are designed to be filled with specific data fields from various categories.
"""

TEMPLATES = [
    {
        "name": "mean_reversion_vol_regime",
        "category": "Price/Volume",
        "description": "Trades reversion only during high volatility regimes.",
        "expression": "trade_when(ts_rank(ts_std_dev(returns, 22), 252) > 0.55, -ts_corr(returns, ts_delay({FIELD}, 1), 252), -1)",
        "settings": {
            "universe": "TOP3000",
            "neutralization": "subindustry",
            "truncation": 0.01,
            "decay": 3,
            "delay": 1
        },
        "compatible_fields": ["pv", "model"]
    },
    {
        "name": "options_positioning",
        "category": "Option",
        "description": "Compares historical option metric to current close.",
        "expression": "ts_delay({FIELD}, 7) / close",
        "settings": {
            "universe": "TOP3000",
            "neutralization": "sector",
            "truncation": 0.05,
            "decay": 4,
            "delay": 1
        },
        "compatible_fields": ["option"]
    },
    {
        "name": "analyst_revision_momentum",
        "category": "Analyst",
        "description": "Percentile ranking of analyst revision fields.",
        "expression": "ts_rank({FIELD}, 252)",
        "settings": {
            "universe": "TOP3000",
            "neutralization": "subindustry",
            "truncation": 0.01,
            "decay": 0,
            "delay": 1
        },
        "compatible_fields": ["analyst"]
    },
    {
        "name": "fundamental_valuation",
        "category": "Fundamental",
        "description": "Mean reversion of fundamental valuation metric.",
        "expression": "-ts_rank({FIELD}, 63)",
        "settings": {
            "universe": "TOP3000",
            "neutralization": "industry",
            "truncation": 0.01,
            "decay": 5,
            "delay": 1
        },
        "compatible_fields": ["fundamental"]
    },
    {
        "name": "news_sentiment_reversion",
        "category": "News",
        "description": "Correlation of returns against sentiment.",
        "expression": "-ts_corr(returns, ts_delay({FIELD}, 1), 120)",
        "settings": {
            "universe": "TOP3000",
            "neutralization": "subindustry",
            "truncation": 0.01,
            "decay": 15,
            "delay": 1
        },
        "compatible_fields": ["news"]
    },
    {
        "name": "volatility_spread",
        "category": "Option",
        "description": "Spread between implied volatility metrics.",
        "expression": "ts_rank({FIELD} - implied_volatility_put_720, 252)",
        "settings": {
            "universe": "TOP3000",
            "neutralization": "market",
            "truncation": 0.01,
            "decay": 3,
            "delay": 1
        },
        "compatible_fields": ["option"]
    },
    {
        "name": "github_simple_reversion",
        "category": "Price/Volume",
        "description": "Simple price reversion: (high+low)/2 - close",
        "expression": "(high + low)/2 - close",
        "settings": {
            "universe": "TOP3000",
            "neutralization": "market",
            "truncation": 0.05,
            "decay": 5,
            "delay": 1
        },
        "compatible_fields": ["pv"]
    },
    {
        "name": "github_valuation_short",
        "category": "Fundamental",
        "description": "Short overpriced companies based on EV/EBITDA",
        "expression": "-ts_rank({FIELD}, 63)",
        "settings": {
            "universe": "TOP3000",
            "neutralization": "industry",
            "truncation": 0.05,
            "decay": 5,
            "delay": 1
        },
        "compatible_fields": ["fundamental"]
    },
    {
        "name": "github_news_reversion",
        "category": "News",
        "description": "Hot news mixed with reversion",
        "expression": "trade_when(rank(ts_sum({FIELD}, 60)) > 0.5, 1, rank(-ts_delta(close, 2)))",
        "settings": {
            "universe": "TOP3000",
            "neutralization": "subindustry",
            "truncation": 0.05,
            "decay": 5,
            "delay": 1
        },
        "compatible_fields": ["news"]
    }
]

def get_templates_for_category(category_name):
    """Return all templates that are compatible with the given category."""
    return [t for t in TEMPLATES if category_name.lower() in t["compatible_fields"]]

def generate_expression(template, field_name):
    """Generates an alpha expression string by filling in the data field."""
    return template["expression"].format(FIELD=field_name)
