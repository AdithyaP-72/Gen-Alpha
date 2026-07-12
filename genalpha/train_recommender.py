#!/usr/bin/env python3
"""
Train a search-policy artifact from simulation history and the SQLite experiment store.
"""

import json
import os
import pickle
import re
from collections import defaultdict

import numpy as np

from genalpha.alpha_store import AlphaStore

try:
    from sklearn.ensemble import GradientBoostingRegressor, GradientBoostingClassifier
    from sklearn.model_selection import cross_val_score
    from sklearn.preprocessing import LabelEncoder
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


TEMPLATE_PATTERNS = {
    "raw": r"^[a-zA-Z_][a-zA-Z0-9_]*$",
    "negated_raw": r"^-[a-zA-Z_][a-zA-Z0-9_]*$",
    "ts_rank_252": r"ts_rank\([^,]+,\s*252\)",
    "ts_rank_63": r"ts_rank\([^,]+,\s*63\)",
    "ts_zscore": r"ts_zscore\(",
    "ts_av_diff": r"ts_av_diff\(",
    "ts_regression": r"ts_regression\(",
    "trade_when": r"trade_when\(",
    "group_ops": r"group_[a-z_]+\(",
    "vec_ops": r"vec_[a-z_]+\(",
    "complex": r";",
}


def classify_template(expr):
    for name, pattern in TEMPLATE_PATTERNS.items():
        if re.search(pattern, expr):
            return name
    return "other"


def load_simulation_history(path=None):
    from genalpha.config import SIM_HISTORY
    path = str(path or SIM_HISTORY)
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path) as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def merge_history():
    store = AlphaStore()
    store_entries = store.get_history_entries()
    if store_entries:
        return store_entries
    return load_simulation_history()


def featurize(entry):
    expression = str(entry.get("expression", ""))
    settings = entry.get("settings", {})
    metadata = entry.get("metadata", {})
    return {
        "expression": expression,
        "fitness": entry.get("fitness", 0) or 0,
        "sharpe": entry.get("sharpe", 0) or 0,
        "turnover": entry.get("turnover", 0) or 0,
        "template_pattern": classify_template(expression),
        "hypothesis_family": entry.get("hypothesis_family") or metadata.get("hypothesis_family", "generic_signal"),
        "field_category": metadata.get("field_category", "generic"),
        "source": entry.get("source", "unknown"),
        "mutation_type": entry.get("mutation_type") or "none",
        "neutralization": settings.get("neutralization", "SECTOR"),
        "decay": settings.get("decay", 5),
        "truncation": settings.get("truncation", 0.05),
        "operator_count": len(re.findall(r"ts_\w+|rank|zscore|group_\w+|vec_\w+|trade_when", expression)),
        "has_trade_when": int("trade_when" in expression),
        "has_group": int("group_" in expression),
        "has_vec": int("vec_" in expression),
        "expr_length": len(expression),
    }


def summarize_arm(features, key):
    stats = defaultdict(lambda: {"count": 0, "total_fitness": 0.0, "good_count": 0, "max_fitness": -999.0})
    for feat in features:
        value = feat[key]
        stats[value]["count"] += 1
        stats[value]["total_fitness"] += feat["fitness"]
        stats[value]["max_fitness"] = max(stats[value]["max_fitness"], feat["fitness"])
        if feat["fitness"] >= 0.8:
            stats[value]["good_count"] += 1
    result = {}
    for arm, values in stats.items():
        count = max(values["count"], 1)
        result[arm] = {
            "count": values["count"],
            "avg_fitness": values["total_fitness"] / count,
            "success_rate": values["good_count"] / count,
            "max_fitness": values["max_fitness"],
            "ucb_bonus": (2.0 / (count ** 0.5)),
        }
    return result


def best_settings_by_family(features):
    grouped = defaultdict(list)
    for feat in features:
        grouped[feat["hypothesis_family"]].append(feat)
    best = {}
    for family, rows in grouped.items():
        row = max(rows, key=lambda item: item["fitness"])
        best[family] = {
            "neutralization": row["neutralization"],
            "decay": row["decay"],
            "truncation": row["truncation"],
            "best_fitness": row["fitness"],
        }
    return best


def best_settings_by_category(features):
    grouped = defaultdict(list)
    for feat in features:
        grouped[feat["field_category"]].append(feat)
    best = {}
    for category, rows in grouped.items():
        if not rows:
            continue
        row = max(rows, key=lambda item: item["fitness"])
        best[category] = {
            "neutralization": row["neutralization"],
            "decay": row["decay"],
            "truncation": row["truncation"],
            "best_fitness": row["fitness"],
        }
    return best


def build_ml_arrays(features):
    cat_encoder = LabelEncoder()
    family_encoder = LabelEncoder()
    source_encoder = LabelEncoder()
    neut_encoder = LabelEncoder()
    mutation_encoder = LabelEncoder()

    cat_encoder.fit([f["field_category"] for f in features])
    family_encoder.fit([f["hypothesis_family"] for f in features])
    source_encoder.fit([f["source"] for f in features])
    neut_encoder.fit([f["neutralization"] for f in features])
    mutation_encoder.fit([f["mutation_type"] for f in features])

    X = []
    y = []
    y_class = []
    for feat in features:
        X.append(
            [
                cat_encoder.transform([feat["field_category"]])[0],
                family_encoder.transform([feat["hypothesis_family"]])[0],
                source_encoder.transform([feat["source"]])[0],
                neut_encoder.transform([feat["neutralization"]])[0],
                mutation_encoder.transform([feat["mutation_type"]])[0],
                feat["decay"],
                feat["truncation"],
                feat["operator_count"],
                feat["has_trade_when"],
                feat["has_group"],
                feat["has_vec"],
                feat["expr_length"],
            ]
        )
        y.append(feat["fitness"])
        y_class.append(1 if feat["fitness"] >= 0.8 else 0)
    encoders = {
        "category": cat_encoder,
        "family": family_encoder,
        "source": source_encoder,
        "neutralization": neut_encoder,
        "mutation": mutation_encoder,
    }
    return np.array(X), np.array(y), np.array(y_class), encoders


def train_models():
    print("=" * 60)
    print("TRAINING SEARCH POLICY")
    print("=" * 60)

    entries = merge_history()
    features = [featurize(entry) for entry in entries]
    print(f"Training on {len(features)} simulations")

    policy = {
        "version": 3,
        "training_samples": len(features),
        "learned_stats": {
            "category": summarize_arm(features, "field_category"),
            "template": summarize_arm(features, "template_pattern"),
            "family": summarize_arm(features, "hypothesis_family"),
            "source": summarize_arm(features, "source"),
            "mutation": summarize_arm(features, "mutation_type"),
            "neutralization": summarize_arm(features, "neutralization"),
            "decay": summarize_arm(features, "decay"),
        },
        "best_settings_per_family": best_settings_by_family(features),
        "best_settings_per_category": best_settings_by_category(features),
    }

    model_payload = None
    if SKLEARN_AVAILABLE and len(features) >= 20:
        X, y, y_class, encoders = build_ml_arrays(features)
        regressor = GradientBoostingRegressor(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            min_samples_leaf=3,
            random_state=42,
        )
        classifier = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            min_samples_leaf=3,
            random_state=42,
        )
        regressor.fit(X, y)
        # Balance the sparse positive class (~10%) so the screening gate doesn't
        # collapse into rejecting everything (docs.md "ML Pessimism / Mode Collapse").
        n_pos = int(y_class.sum())
        n_neg = len(y_class) - n_pos
        if n_pos > 0 and n_neg > 0:
            w_pos = len(y_class) / (2.0 * n_pos)
            w_neg = len(y_class) / (2.0 * n_neg)
            sample_weight = np.where(y_class == 1, w_pos, w_neg)
        else:
            sample_weight = None
        classifier.fit(X, y_class, sample_weight=sample_weight)
        try:
            cv = max(2, min(5, len(X) // 5))
            reg_cv = cross_val_score(regressor, X, y, cv=cv, scoring="r2")
            cls_cv = cross_val_score(classifier, X, y_class, cv=cv, scoring="accuracy")
            print(f"  Fitness predictor R^2: {reg_cv.mean():.3f}")
            print(f"  Success classifier accuracy: {cls_cv.mean():.3f}")
        except ValueError as e:
            print(f"  Cross-validation skipped: {e}")
        model_payload = {
            "regressor": regressor,
            "classifier": classifier,
            "encoders": encoders,
        }

    from genalpha.config import ALPHA_INTELLIGENCE, FITNESS_MODEL
    with open(ALPHA_INTELLIGENCE, "w") as handle:
        json.dump(policy, handle, indent=2)
    if model_payload:
        with open(FITNESS_MODEL, "wb") as handle:
            pickle.dump(model_payload, handle)

    for family, stats in sorted(policy["learned_stats"]["family"].items(), key=lambda item: -item[1]["avg_fitness"])[:8]:
        print(
            f"  {family:28s} avg={stats['avg_fitness']:.3f} "
            f"success={stats['success_rate']:.0%} n={stats['count']}"
        )
    return policy


if __name__ == "__main__":
    train_models()
