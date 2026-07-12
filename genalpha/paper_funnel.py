"""
Data funnel: score arXiv abstracts locally and forward only the most relevant
ones to the (expensive) 70B anomaly extractor.

Two scorers, best available wins:
  1. sentence-transformers embeddings (optional dependency, ~100 MB model)
  2. keyword-overlap fallback — zero dependencies, always available

Each domain provides the query/target_fields/key_operators that form its
"hypothesis prototype" text.
"""

import math
import re

_ST_MODEL = None
_ST_FAILED = False


def _get_embedder():
    """Lazy-load sentence-transformers; never a hard requirement."""
    global _ST_MODEL, _ST_FAILED
    if _ST_MODEL is not None or _ST_FAILED:
        return _ST_MODEL
    try:
        from sentence_transformers import SentenceTransformer
        _ST_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        _ST_FAILED = True
    return _ST_MODEL


_STOP_WORDS = {
    "the", "a", "an", "and", "or", "of", "in", "to", "is", "are", "that",
    "with", "for", "on", "by", "from", "at", "as", "it", "we", "this",
    "paper", "study", "using", "based", "results", "show", "propose",
    "cat", "all",
}

# Terms that signal a tradeable cross-sectional equity result vs. pure theory
_TRADEABLE_HINTS = {
    "cross-sectional": 2.0, "anomaly": 1.5, "abnormal returns": 2.0,
    "predict": 1.0, "alpha": 1.5, "long-short": 2.0, "portfolio": 0.5,
    "equity": 0.5, "stock returns": 1.5, "signal": 1.0, "factor": 1.0,
    "sharpe": 1.5, "backtest": 1.5, "out-of-sample": 1.5,
}


def _tokens(text):
    return {w for w in re.findall(r"[a-z][a-z\-]+", text.lower())} - _STOP_WORDS


def _domain_prototype(domain):
    return " ".join(
        [domain.get("label", ""), domain.get("query", "")]
        + domain.get("target_fields", [])
        + domain.get("key_operators", [])
    )


def _keyword_score(abstract, domain):
    """Fallback scorer: domain-keyword overlap + tradeability hints."""
    abs_lower = abstract.lower()
    abs_tokens = _tokens(abstract)
    proto_tokens = _tokens(_domain_prototype(domain))
    if not abs_tokens:
        return 0.0
    overlap = len(abs_tokens & proto_tokens) / math.sqrt(len(proto_tokens) or 1)
    hints = sum(w for phrase, w in _TRADEABLE_HINTS.items() if phrase in abs_lower)
    return overlap + hints * 0.2


def _embedding_score(abstracts, domain, model):
    from sentence_transformers import util
    proto = _domain_prototype(domain) + " tradeable cross-sectional equity anomaly signal"
    embeddings = model.encode(abstracts + [proto], convert_to_tensor=True, show_progress_bar=False)
    sims = util.cos_sim(embeddings[:-1], embeddings[-1:])
    return [float(s[0]) for s in sims]


def select_top_papers(papers, domain, k):
    """Rank candidate arXiv papers by local relevance and return the top k."""
    if len(papers) <= k:
        return list(papers)

    abstracts = [(p.title.strip() + ". " + p.summary.strip())[:2000] for p in papers]
    model = _get_embedder()
    if model is not None:
        try:
            scores = _embedding_score(abstracts, domain, model)
        except Exception:
            scores = [_keyword_score(a, domain) for a in abstracts]
    else:
        scores = [_keyword_score(a, domain) for a in abstracts]

    ranked = sorted(zip(scores, range(len(papers))), key=lambda x: -x[0])
    return [papers[i] for _score, i in ranked[:k]]
