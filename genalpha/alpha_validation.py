"""
Validation, normalization, and metadata extraction for candidate alpha expressions.
"""

import json
import re

from genalpha.scrape_research import categorize_field


FIELD_TOKEN_RE = re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b")
WINDOW_RE = re.compile(r",\s*(\d+)\)")
OPERATOR_RE = re.compile(r"\b(ts_[a-z_]+|group_[a-z_]+|vec_[a-z_]+|rank|zscore|quantile|trade_when)\b")

# Load valid operator names from brain_operators.json
def _load_operator_names():
    import os
    from genalpha.config import BRAIN_OPERATORS as path
    if os.path.exists(path):
        with open(path) as f:
            return {op["name"] for op in json.load(f)}
    return set()

VALID_OPERATOR_NAMES = _load_operator_names()


def validate_operators(expression):
    """Check that all operators in an expression exist in brain_operators.json.

    Returns (is_valid, list_of_invalid_operators).
    """
    found_ops = set(OPERATOR_RE.findall(expression))
    # These are always valid (built-in or aliases)
    always_valid = {"rank", "zscore", "quantile", "trade_when"}
    invalid = []
    for op in found_ops:
        if op in always_valid:
            continue
        if op in VALID_OPERATOR_NAMES:
            continue
        invalid.append(op)
    return (len(invalid) == 0), invalid

KEYWORDS = {
    "if", "else", "true", "false", "rank", "zscore", "quantile", "trade_when",
    "returns", "close", "open", "high", "low", "volume", "vwap",
    "sector", "industry", "subindustry", "market", "cap", "sharesout",
}


def canonicalize_expression(expression):
    text = " ".join(expression.strip().split())
    text = re.sub(r"\s*([(),/*+\-?:=<>])\s*", r"\1", text)
    text = re.sub(r",", ", ", text)
    return text.strip()


def extract_primary_field(expression, field_index):
    tokens = FIELD_TOKEN_RE.findall(expression)
    for token in tokens:
        if token in field_index:
            return token
    for token in tokens:
        if token.lower() not in KEYWORDS and not token.isupper():
            return token
    return None


def infer_hypothesis_family(expression, field_id=None, category=None):
    text = expression.lower()
    if "trade_when" in text and "news" in text:
        return "news_conditioned_reversion"
    if "trade_when" in text or "std_dev" in text:
        return "volatility_gated_reversion"
    if category == "analyst":
        return "analyst_revision"
    if category == "fundamental":
        return "valuation_reversion"
    if category == "news":
        return "news_sentiment"
    if category == "option":
        return "options_positioning"
    if category == "model":
        return "model_risk_signal"
    if any(token in text for token in ["vwap", "returns", "volume", "high", "low", "close"]):
        return "price_volume_reversion"
    return "generic_signal"


def analyze_expression(expression, field_index):
    canonical = canonicalize_expression(expression)
    field_id = extract_primary_field(canonical, field_index)
    category = categorize_field(field_id, field_index.get(field_id, {})) if field_id else "generic"
    metadata = {
        "operators": sorted(set(OPERATOR_RE.findall(canonical))),
        "windows": [int(value) for value in WINDOW_RE.findall(canonical)],
        "field_id": field_id,
        "field_category": category,
        "field_type": field_index.get(field_id, {}).get("type") if field_id else None,
        "hypothesis_family": infer_hypothesis_family(canonical, field_id, category),
        "expression_length": len(canonical),
    }
    return canonical, metadata


def validate_candidate(expression, settings, field_index):
    expression = expression.strip()
    if not expression:
        return False, "empty_expression", {}

    canonical, metadata = analyze_expression(expression, field_index)
    notes = []

    if canonical.count("(") != canonical.count(")"):
        return False, "unbalanced_parentheses", metadata
    if "{" in canonical or "}" in canonical:
        return False, "unresolved_placeholder", metadata
    if canonical.endswith("=") or canonical.endswith(";"):
        return False, "incomplete_assignment", metadata
    if metadata["expression_length"] < 4:
        return False, "expression_too_short", metadata
    if canonical.count("?") != canonical.count(":"):
        return False, "invalid_ternary", metadata

    field_id = metadata["field_id"]
    field_type = metadata["field_type"]
    has_vec_wrapper = "vec_" in canonical
    if field_type == "VECTOR" and not has_vec_wrapper:
        return False, "vector_field_missing_vec_wrapper", metadata
    if field_type == "MATRIX" and has_vec_wrapper and field_id and f"vec_avg({field_id})" not in canonical and f"vec_sum({field_id})" not in canonical:
        notes.append("matrix_field_with_vec_wrapper")

    if "trade_when(" in canonical and canonical.count(",") < 2:
        return False, "invalid_trade_when", metadata

    metadata["settings_key"] = json.dumps(settings, sort_keys=True)
    metadata["notes"] = notes
    return True, None, metadata
