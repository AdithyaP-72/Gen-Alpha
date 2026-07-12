#!/usr/bin/env python3
"""
ArXiv Research Pipeline — Fetch quantitative finance papers, extract anomalies
via LLM, generate grounded BRAIN expressions, validate, and save.

Usage:
    python arxiv_pipeline.py                    # Default: 10 papers
    python arxiv_pipeline.py --max-papers 20    # Custom count
    python arxiv_pipeline.py --query "momentum" # Custom search term
"""

import argparse
import json
import time
import re
from pathlib import Path
from collections import Counter

import arxiv

from genalpha.llm_client import GroqClient, OPERATOR_NAMES, GROQ_MODEL_CRITIC
from genalpha.alpha_validation import validate_candidate
from genalpha.pipeline_logging import log
from genalpha import config

# ─── Configuration ────────────────────────────────────────────────
OUTPUT_FILE = config.LLM_ALPHAS

# ArXiv search queries targeting different anomaly families
SEARCH_QUERIES = [
    "cat:q-fin.ST AND (cross-sectional equity anomaly OR factor investing)",
    "cat:q-fin.PM AND (portfolio optimization OR asset pricing anomaly)",
    "cat:q-fin.TR AND (momentum OR mean reversion OR market microstructure)",
    "cat:q-fin.CP AND (alpha signal OR quantitative trading strategy)",
    "all:(post-earnings announcement drift OR earnings surprise equity)",
    "all:(implied volatility skew OR options-implied information equity)",
    "all:(news sentiment stock returns OR social media equity prediction)",
    "all:(short interest anomaly OR insider trading signal)",
    "all:(cross-sectional momentum OR industry momentum equity)",
    "all:(value factor OR book-to-market ratio anomaly)",
]


def load_existing_templates():
    """Load existing templates for few-shot similarity matching."""
    path = config.RESEARCH_TEMPLATES
    if path.exists():
        with open(path) as f:
            data = json.load(f)
            return [t["expression"] for t in data.get("templates", []) if t.get("expression")]
    return []


def load_field_index():
    """Load field index for validation."""
    path = config.BRAIN_FIELDS
    if path.exists():
        with open(path) as f:
            fields = json.load(f)
            return {f["id"]: f for f in fields}
    return {}


def get_relevant_field_ids(anomaly, field_index):
    """Pick relevant field IDs based on the anomaly's data needs."""
    data_needed = anomaly.get("data_needed", [])
    signal_type = anomaly.get("signal_type", "other")

    # Map data needs to field ID prefixes
    prefix_map = {
        "earnings": ["anl4_", "est_eps", "operating_income", "net_income", "ebit"],
        "sentiment": ["nws12_", "news_", "rp_css_", "rp_ess_", "rp_nip_"],
        "price": [],  # Built-in: close, open, high, low, vwap
        "volume": [],  # Built-in: volume
        "fundamentals": ["revenue", "assets", "liabilities", "equity", "debt", "cash_flow"],
        "volatility": ["implied_volatility", "unsystematic_risk", "beta_"],
        "insider": ["insider_", "rp_ess_insider", "rp_nip_insider"],
        "options": ["implied_volatility", "pcr_", "call_", "put_"],
    }

    relevant_prefixes = []
    for need in data_needed:
        need_lower = need.lower()
        for key, prefixes in prefix_map.items():
            if key in need_lower:
                relevant_prefixes.extend(prefixes)

    # Fallback based on signal type
    type_prefixes = {
        "momentum": ["returns", "close"],
        "mean_reversion": ["close", "vwap"],
        "value": ["revenue", "ebit", "operating_income", "equity", "est_eps"],
        "quality": ["operating_income", "net_income", "cash_flow"],
        "sentiment": ["nws12_", "news_", "rp_css_", "rp_ess_"],
        "volatility": ["implied_volatility", "unsystematic_risk", "beta_"],
        "event_driven": ["anl4_", "est_", "nws12_"],
    }
    if signal_type in type_prefixes:
        relevant_prefixes.extend(type_prefixes[signal_type])

    if not relevant_prefixes:
        relevant_prefixes = ["operating_income", "revenue", "est_eps", "news_"]

    # Find matching fields
    matching = []
    for fid, meta in field_index.items():
        if meta.get("type") != "MATRIX" or meta.get("coverage", 0) < 0.20:
            continue
        for prefix in relevant_prefixes:
            if fid.startswith(prefix) or fid == prefix:
                matching.append(fid)
                break

    return matching[:30]


def find_similar_templates(anomaly, all_templates, top_k=8):
    """Simple keyword-based similarity to find relevant few-shot examples."""
    hypothesis = anomaly.get("hypothesis", "").lower()
    signal_type = anomaly.get("signal_type", "").lower()
    keywords = set(hypothesis.split() + signal_type.split())

    # Remove stop words
    stop_words = {"the", "a", "an", "and", "or", "of", "in", "to", "is", "are",
                  "that", "with", "for", "on", "by", "from", "at", "as", "it"}
    keywords -= stop_words

    scored = []
    for tmpl in all_templates:
        tmpl_lower = tmpl.lower()
        score = sum(1 for kw in keywords if kw in tmpl_lower)
        # Boost templates with similar operators
        if signal_type == "momentum" and "ts_delta" in tmpl_lower:
            score += 2
        if signal_type == "mean_reversion" and ("ts_zscore" in tmpl_lower or "ts_rank" in tmpl_lower):
            score += 2
        if signal_type == "sentiment" and "vec_avg" in tmpl_lower:
            score += 3
        if signal_type == "value" and ("equity" in tmpl_lower or "close" in tmpl_lower):
            score += 2
        if "group_rank" in tmpl_lower:
            score += 1  # Always slightly prefer golden combo patterns
        scored.append((tmpl, score))

    scored.sort(key=lambda x: -x[1])
    return [t for t, s in scored[:top_k]]


def validate_expression(expression, field_index):
    """Validate a generated expression against real operators and fields."""
    # Check for hallucinated operators
    found_ops = re.findall(r"\b(ts_\w+|group_\w+|vec_\w+)\b", expression)
    invalid_ops = [op for op in found_ops if op not in OPERATOR_NAMES]

    if invalid_ops:
        return False, f"Invalid operators: {invalid_ops}"

    # Run through the existing validator
    settings = {"neutralization": "SUBINDUSTRY", "decay": 0, "truncation": 0.08}
    is_valid, reason, metadata = validate_candidate(expression, settings, field_index)

    if not is_valid:
        return False, reason

    return True, None


def process_paper(client, paper, all_templates, field_index):
    """Process a single paper: extract anomaly → generate expressions → validate."""
    title = paper.title.strip()
    abstract = paper.summary.strip()

    log(f"\n{'─'*60}")
    log(f"  Paper: {title[:70]}{'...' if len(title) > 70 else ''}")
    log(f"  URL:   {paper.entry_id}")

    # Step 1: Extract anomaly
    # Returns None on LLM failure (retryable) vs [] for definitively
    # non-tradeable papers — callers must not blacklist papers on None.
    anomaly = client.extract_anomaly(title, abstract)
    if not anomaly:
        log(f"  ✗ Failed to extract anomaly")
        return None

    try:
        confidence = float(anomaly.get("confidence", 0.0))
    except (ValueError, TypeError):
        confidence = 0.0

    log(f"  Anomaly: {anomaly.get('hypothesis', '?')[:60]}...")
    log(f"  Type: {anomaly.get('signal_type', '?')}, Confidence: {confidence:.2f}")

    if confidence < 0.3:
        log(f"  ✗ Low confidence ({confidence:.2f}) — skipping")
        return []

    # Step 2: Find similar templates and relevant fields
    similar = find_similar_templates(anomaly, all_templates)
    relevant_fields = get_relevant_field_ids(anomaly, field_index)
    log(f"  Similar templates: {len(similar)}, Relevant fields: {len(relevant_fields)}")

    # Step 3: Generate expressions (Agent A)
    result = client.generate_expressions(anomaly, similar, relevant_fields)
    if not result or "expressions" not in result:
        log(f"  ✗ Failed to generate expressions")
        return None

    generated = result["expressions"]
    log(f"  Generated: {len(generated)} expressions")

    def _make_entry(expr, gen, is_valid, reason):
        return {
            "expression": expr,
            "settings": {
                "universe": "TOP3000",
                "neutralization": str(gen.get("settings", {}).get("neutralization", "SUBINDUSTRY")).upper(),
                "decay": min(gen.get("settings", {}).get("decay", 0) or 0, 20),
                "truncation": gen.get("settings", {}).get("truncation", 0.08),
                "delay": 1,
                "nan_handling": "ON",
            },
            "source": "llm-arxiv",
            "paper_title": title,
            "paper_url": paper.entry_id,
            "anomaly": anomaly.get("hypothesis", ""),
            "signal_type": anomaly.get("signal_type", "other"),
            "rationale": gen.get("rationale", ""),
            "llm_confidence": gen.get("confidence", 0),
            "anomaly_confidence": confidence,
            "valid": is_valid,
            "validation_reason": reason,
        }

    # Step 4: Local validation first (free) — with one Chain-of-Alpha rewrite
    # round on validator failures before giving up on an expression.
    valid_alphas = []
    survivors = []  # (entry, gen) pairs that passed local validation
    for gen in generated:
        expr = gen.get("expression", "")
        if not expr:
            continue

        is_valid, reason = validate_expression(expr, field_index)
        if not is_valid:
            log(f"    ✗ ({reason}) {expr[:60]} → asking Agent A for a rewrite...")
            rewrite = client.rewrite_expression(expr, str(reason), gen.get("rationale"))
            _record_llm(paper.entry_id, "refiner", rewrite)
            if rewrite:
                expr2 = rewrite["expression"]
                is_valid, reason = validate_expression(expr2, field_index)
                if is_valid:
                    log(f"    ✓ (rewritten) {expr2[:60]}")
                    expr = expr2
        else:
            log(f"    ✓ {expr[:65]}{'...' if len(expr) > 65 else ''}")

        entry = _make_entry(expr, gen, is_valid, reason)
        valid_alphas.append(entry)
        if is_valid:
            survivors.append((entry, gen))

    # Step 5: Agent B — one batched critic call over the survivors
    if survivors:
        reviews = client.critique_expressions([
            {"expression": e["expression"], "rationale": e["rationale"], "settings": e["settings"]}
            for e, _ in survivors
        ])
        _record_llm(paper.entry_id, "critic", reviews)
        if reviews:
            by_idx = {r.get("idx"): r for r in reviews if isinstance(r, dict)}
            for i, (entry, gen) in enumerate(survivors):
                review = by_idx.get(i)
                if not review:
                    continue
                verdict = review.get("verdict", "approve")
                entry["critic_verdict"] = verdict
                entry["critic_issues"] = review.get("issues", [])
                if verdict == "reject":
                    entry["valid"] = False
                    entry["validation_reason"] = f"critic_reject: {', '.join(review.get('issues', []))}"
                    log(f"    ✗ critic rejected: {entry['expression'][:50]} ({entry['validation_reason'][:60]})")
                elif verdict == "revise":
                    # ≤1 revision round, only for flagged expressions
                    hint = review.get("fix_hint", "")
                    rewrite = client.rewrite_expression(
                        entry["expression"],
                        f"Critic issues: {', '.join(review.get('issues', []))}. Hint: {hint}",
                        entry["rationale"],
                    )
                    _record_llm(paper.entry_id, "refiner", rewrite, round_idx=1)
                    if rewrite:
                        is_valid, reason = validate_expression(rewrite["expression"], field_index)
                        if is_valid:
                            log(f"    ✓ critic-revised: {rewrite['expression'][:55]}")
                            entry["expression"] = rewrite["expression"]

    valid_count = sum(1 for a in valid_alphas if a["valid"])
    log(f"  Result: {valid_count}/{len(valid_alphas)} passed validation + review")

    return valid_alphas


def _record_llm(paper_id, role, response, round_idx=0):
    """Best-effort audit trail of actor/critic exchanges."""
    try:
        from genalpha.alpha_store import AlphaStore
        AlphaStore().record_llm_interaction(
            role, response, paper_id=paper_id, round_idx=round_idx,
            model=GROQ_MODEL_CRITIC if role == "critic" else None,
        )
    except Exception:
        pass


def run_pipeline(max_papers=10, custom_query=None):
    """Main pipeline: fetch papers → extract → generate → validate → save."""
    log("=" * 60)
    log("  ARXIV RESEARCH PIPELINE")
    log("=" * 60)

    # Initialize
    client = GroqClient()
    all_templates = load_existing_templates()
    field_index = load_field_index()
    log(f"  Templates for grounding: {len(all_templates)}")
    log(f"  Field index size: {len(field_index)}")

    # Fetch papers
    queries = [custom_query] if custom_query else SEARCH_QUERIES
    papers_per_query = max(1, max_papers // len(queries))

    # Load previously seen papers from JSON to avoid duplicates
    seen_ids = set()
    existing_alphas = []
    if Path(OUTPUT_FILE).exists():
        try:
            with open(OUTPUT_FILE, "r") as f:
                data = json.load(f)
                existing_alphas = data.get("alphas", [])
                for a in existing_alphas:
                    if "paper_url" in a:
                        seen_ids.add(a["paper_url"])
        except Exception:
            pass
            
    all_papers = []
    arxiv_client = arxiv.Client(delay_seconds=1.0)

    for query in queries:
        log(f"\n  Searching: {query[:60]}...")
        search = arxiv.Search(
            query=query,
            max_results=papers_per_query * 3, # fetch more since we might skip seen ones
            sort_by=arxiv.SortCriterion.Relevance,
        )
        count = 0
        try:
            for paper in arxiv_client.results(search):
                if paper.entry_id not in seen_ids:
                    seen_ids.add(paper.entry_id)
                    all_papers.append(paper)
                    count += 1
                if count >= papers_per_query:
                    break
        except Exception as e:
            log(f"    ArXiv error: {e}")
            continue
        log(f"    Found {count} papers")

        if len(all_papers) >= max_papers:
            break

    all_papers = all_papers[:max_papers]
    log(f"\n  Total papers to process: {len(all_papers)}")

    # Process each paper
    all_alphas = []
    for paper in all_papers:
        try:
            alphas = process_paper(client, paper, all_templates, field_index)
            all_alphas.extend(alphas or [])
        except Exception as e:
            log(f"  ✗ Error processing paper: {e}")
        time.sleep(0.5)  # Be polite to Groq

    # Save accumulated results
    accumulated_alphas = existing_alphas + all_alphas
    valid_alphas = [a for a in accumulated_alphas if a.get("valid")]
    output = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "papers_processed": len(all_papers),
        "total_expressions": len(accumulated_alphas),
        "valid_expressions": len(valid_alphas),
        "alphas": accumulated_alphas,
    }
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    # Save only the latest run summary
    latest_run_output = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "papers_processed": len(all_papers),
        "total_expressions": len(all_alphas),
        "valid_expressions": len([a for a in all_alphas if a.get("valid")]),
        "alphas": all_alphas,
    }
    with open(config.LATEST_RUN, "w") as f:
        json.dump(latest_run_output, f, indent=2)

    # Summary
    log(f"\n{'='*60}")
    log(f"  PIPELINE COMPLETE")
    log(f"{'='*60}")
    log(f"  Papers processed:    {len(all_papers)}")
    log(f"  Expressions generated: {len(all_alphas)}")
    log(f"  Valid expressions:   {len(valid_alphas)}")
    log(f"  LLM calls made:     {client._call_count}")
    log(f"  Saved to:            {OUTPUT_FILE}")

    # Signal type breakdown
    if all_alphas:
        types = Counter(a.get("signal_type", "unknown") for a in all_alphas)
        log(f"\n  Signal type breakdown:")
        for stype, count in types.most_common():
            log(f"    {stype:20s}: {count}")

    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ArXiv Research Pipeline")
    parser.add_argument("--max-papers", type=int, default=10, help="Max papers to process")
    parser.add_argument("--query", type=str, default=None, help="Custom ArXiv search query")
    args = parser.parse_args()

    run_pipeline(max_papers=args.max_papers, custom_query=args.query)
