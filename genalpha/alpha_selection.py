"""
Robustness and novelty checks for promoting candidate alphas.
"""

import re


def structural_signature(expression, metadata):
    ops = ",".join(metadata.get("operators", []))
    category = metadata.get("field_category", "generic")
    family = metadata.get("hypothesis_family", "generic_signal")
    windows = ",".join(str(w) for w in metadata.get("windows", []))
    expr = re.sub(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", "FIELD", expression)
    expr = re.sub(r"\d+", "N", expr)
    return f"{family}|{category}|{ops}|{windows}|{expr}"


def compute_novelty_score(expression, metadata, promoted_rows):
    signature = structural_signature(expression, metadata)
    if not promoted_rows:
        return 1.0, signature

    overlap = 0
    for row in promoted_rows:
        if row["canonical_expression"] == expression:
            return 0.0, signature
        rationale = row.get("rationale_json") or ""
        if signature in rationale:
            overlap += 1

    novelty = max(0.0, 1.0 - (overlap / max(5, len(promoted_rows))))
    return novelty, signature


def robustness_score(base_result, neighboring_results):
    if not neighboring_results:
        return 0.0
    valid = [res for res in neighboring_results if res]
    if not valid:
        return 0.0
    avg_fitness = sum(res.get("fitness", 0) for res in valid) / len(valid)
    pass_rate = sum(1 for res in valid if res.get("fitness", 0) >= 0.8) / len(valid)
    penalty = 0.25 if any((res.get("sharpe", 0) < 0) for res in valid) else 0.0
    return max(0.0, min(1.0, (avg_fitness / max(base_result.get("fitness", 1), 1)) * 0.6 + pass_rate * 0.5 - penalty))


def should_promote(expression, result, metadata, neighboring_results, promoted_rows, fitness_save=1.15):
    novelty, signature = compute_novelty_score(expression, metadata, promoted_rows)
    robustness = robustness_score(result, neighboring_results)

    reasons = {
        "novelty_score": novelty,
        "robustness_score": robustness,
        "signature": signature,
        "base_fitness": result.get("fitness", 0),
    }

    if result.get("fitness", 0) < fitness_save:
        reasons["decision"] = "reject_below_save_threshold"
        return False, reasons
    if novelty < 0.25:
        reasons["decision"] = "reject_low_novelty"
        return False, reasons
    if neighboring_results and robustness < 0.35:
        reasons["decision"] = "reject_low_robustness"
        return False, reasons

    reasons["decision"] = "promote"
    return True, reasons
