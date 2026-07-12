import pickle
import numpy as np
import warnings
from genalpha.train_recommender import featurize

# Suppress sklearn warnings about feature names
warnings.filterwarnings("ignore", category=UserWarning)

try:
    from genalpha.config import FITNESS_MODEL
    with open(FITNESS_MODEL, "rb") as f:
        model_payload = pickle.load(f)
    regressor = model_payload["regressor"]
    classifier = model_payload["classifier"]
    encoders = model_payload["encoders"]
except Exception as e:
    print(f"Failed to load fitness_model.pkl: {e}")
    regressor, classifier, encoders = None, None, None

def encode_features(feat, encoders):
    def safe_transform(enc, val, fallback=0):
        try:
            return enc.transform([val])[0]
        except Exception:
            return fallback

    return [
        safe_transform(encoders["category"], feat["field_category"]),
        safe_transform(encoders["family"], feat["hypothesis_family"]),
        safe_transform(encoders["source"], feat["source"]),
        safe_transform(encoders["neutralization"], feat["neutralization"]),
        safe_transform(encoders["mutation"], feat["mutation_type"]),
        feat["decay"],
        feat["truncation"],
        feat["operator_count"],
        feat["has_trade_when"],
        feat["has_group"],
        feat["has_vec"],
        feat["expr_length"],
    ]

def optimize_settings(expression, base_settings=None, metadata=None):
    if regressor is None:
        return base_settings or {}, 0.5, 0.5
        
    base_settings = base_settings or {}
    metadata = metadata or {}
    
    decays = [0, 5, 10, 20]
    truncations = [0.01, 0.05, 0.08, 0.1]
    neutralizations = ["SUBINDUSTRY", "INDUSTRY", "SECTOR", "MARKET"]
    
    best_settings = base_settings.copy()
    max_fitness = -999
    max_prob = 0
    
    for d in decays:
        for t in truncations:
            for n in neutralizations:
                trial = {
                    "expression": expression,
                    "settings": {"decay": d, "truncation": t, "neutralization": n},
                    "metadata": metadata,
                    "source": "llm-arxiv",
                    "mutation_type": "none"
                }
                
                feat_dict = featurize(trial)
                x = np.array([encode_features(feat_dict, encoders)])
                
                pred_fit = regressor.predict(x)[0]
                pred_prob = classifier.predict_proba(x)[0][1] # Probability of success (class 1)
                
                if pred_fit > max_fitness:
                    max_fitness = pred_fit
                    max_prob = pred_prob
                    best_settings["decay"] = d
                    best_settings["truncation"] = t
                    best_settings["neutralization"] = n
                    
    return best_settings, max_fitness, max_prob

if __name__ == "__main__":
    test_expr = "group_rank(ts_rank(close - ts_mean(close, 63), 63), industry)"
    best_set, fit, prob = optimize_settings(test_expr)
    print("Test Expression:", test_expr)
    print("Optimal Settings:", best_set)
    print(f"Predicted Fitness: {fit:.3f}")
    print(f"Success Probability: {prob:.1%}")
