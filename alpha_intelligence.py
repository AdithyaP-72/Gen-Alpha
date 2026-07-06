"""
Alpha Intelligence Engine — Smart template/field recommendation using
trained models, scraped research, and genetic mutation of successful alphas.

Research-validated design principles (from SKILL.md / wq-alpha-research):
  • Golden combo:   group_rank(ts_rank(signal, N), subindustry)
  • Best templates: operating_income/equity, est_eps/close, FCF/equity
  • Top neutralization: SUBINDUSTRY (pass rate ~75%)
  • Pass rates by category: fundamental 40% > analyst 75% (flag fields) > technical 5%
  • Decay levers: fundamental=0, analyst=0-4, technical=10-30
  • Submission targets: Sharpe ≥ 1.3, Fitness ≥ 1.1, Turnover 1-20%
"""

import json
import re
import os
import random
import pickle
from collections import defaultdict

from scrape_research import categorize_field, CURATED_TEMPLATES


# ── High-value golden-combo templates derived from research ───────
GOLDEN_TEMPLATES = [
    # Fundamental quality — highest pass-rate family
    {
        "name": "gold_roe_trend",
        "category": "fundamental",
        "expression": "group_rank(ts_rank({FIELD} / equity, 126), subindustry)",
        "settings": {"neutralization": "SUBINDUSTRY", "decay": 0, "truncation": 0.08},
        "field_slot": "FIELD",
        "priority_boost": 2.0,
    },
    {
        "name": "gold_fcf_yield",
        "category": "fundamental",
        "expression": "group_rank(ts_rank({FIELD} / equity, 126), industry)",
        "settings": {"neutralization": "INDUSTRY", "decay": 0, "truncation": 0.08},
        "field_slot": "FIELD",
        "priority_boost": 1.8,
    },
    {
        "name": "gold_ratio_vs_cap",
        "category": "fundamental",
        "expression": "group_rank(ts_rank({FIELD} / cap, 252), subindustry)",
        "settings": {"neutralization": "SUBINDUSTRY", "decay": 0, "truncation": 0.08},
        "field_slot": "FIELD",
        "priority_boost": 1.7,
    },
    {
        "name": "gold_delta_trend",
        "category": "fundamental",
        "expression": "group_rank(ts_rank(ts_delta({FIELD}, 63), 252), subindustry)",
        "settings": {"neutralization": "SUBINDUSTRY", "decay": 4, "truncation": 0.08},
        "field_slot": "FIELD",
        "priority_boost": 1.5,
    },
    # Analyst revision signals — very high pass rate on flag fields
    {
        "name": "gold_anl_raw_subind",
        "category": "analyst",
        "expression": "group_rank(ts_rank({FIELD}, 63), subindustry)",
        "settings": {"neutralization": "SUBINDUSTRY", "decay": 0, "truncation": 0.08},
        "field_slot": "FIELD",
        "priority_boost": 2.5,
    },
    {
        "name": "gold_anl_flag",
        "category": "analyst",
        "expression": "{FIELD}",
        "settings": {"neutralization": "SECTOR", "decay": 5, "truncation": 0.05},
        "field_slot": "FIELD",
        "priority_boost": 2.0,
    },
    {
        "name": "gold_anl_ts_zscore",
        "category": "analyst",
        "expression": "group_rank(ts_zscore({FIELD}, 63), industry)",
        "settings": {"neutralization": "INDUSTRY", "decay": 0, "truncation": 0.08},
        "field_slot": "FIELD",
        "priority_boost": 1.8,
    },
    # Model / risk fields — proven subindustry + ts_rank_63
    {
        "name": "gold_mdl_subind_63",
        "category": "model",
        "expression": "group_rank(ts_rank({FIELD}, 63), subindustry)",
        "settings": {"neutralization": "SUBINDUSTRY", "decay": 0, "truncation": 0.08},
        "field_slot": "FIELD",
        "priority_boost": 1.6,
    },
    {
        "name": "gold_mdl_negated",
        "category": "model",
        "expression": "-group_rank(ts_rank({FIELD}, 63), subindustry)",
        "settings": {"neutralization": "SUBINDUSTRY", "decay": 0, "truncation": 0.08},
        "field_slot": "FIELD",
        "priority_boost": 1.5,
    },
    # News / sentiment with vec_avg — proven
    {
        "name": "gold_news_vec_backfill",
        "category": "news",
        "expression": "ts_backfill(-vec_avg({FIELD}), 20)",
        "settings": {"neutralization": "INDUSTRY", "decay": 10, "truncation": 0.01},
        "field_slot": "FIELD",
        "priority_boost": 1.6,
    },
    {
        "name": "gold_news_buzz_av_diff",
        "category": "news",
        "expression": "buzz = ts_backfill(-vec_sum({FIELD}), 20); ts_av_diff(buzz, 60)",
        "settings": {"neutralization": "INDUSTRY", "decay": 15, "truncation": 0.08},
        "field_slot": "FIELD",
        "priority_boost": 1.5,
    },
    # Options
    {
        "name": "gold_opt_ts_rank_63",
        "category": "option",
        "expression": "group_rank(ts_rank({FIELD}, 63), industry)",
        "settings": {"neutralization": "INDUSTRY", "decay": 0, "truncation": 0.08},
        "field_slot": "FIELD",
        "priority_boost": 1.4,
    },
    # Multi-factor composite stubs (PV; no field slot)
    {
        "name": "gold_roe_eps_combo",
        "category": "pv",
        "expression": (
            "0.5 * group_rank(ts_rank(operating_income / equity, 126), subindustry)"
            " + 0.5 * group_rank(ts_rank(est_eps / close, 126), industry)"
        ),
        "settings": {"neutralization": "SUBINDUSTRY", "decay": 4, "truncation": 0.08},
        "field_slot": None,
        "priority_boost": 1.8,
    },
    {
        "name": "gold_tech_fund_mixed",
        "category": "pv",
        "expression": (
            "0.5 * rank(-(close / open - 1))"
            " + 0.5 * rank(ts_rank(operating_income / equity, 126))"
        ),
        "settings": {"neutralization": "INDUSTRY", "decay": 8, "truncation": 0.08},
        "field_slot": None,
        "priority_boost": 1.5,
    },
    {
        "name": "gold_roe_raw",
        "category": "pv",
        "expression": "group_rank(ts_rank(operating_income / equity, 126), subindustry)",
        "settings": {"neutralization": "SUBINDUSTRY", "decay": 0, "truncation": 0.08},
        "field_slot": None,
        "priority_boost": 2.0,
    },
    {
        "name": "gold_eps_yield",
        "category": "pv",
        "expression": "group_rank(ts_rank(est_eps / close, 252), subindustry)",
        "settings": {"neutralization": "SUBINDUSTRY", "decay": 0, "truncation": 0.08},
        "field_slot": None,
        "priority_boost": 1.9,
    },
]

# ── Best settings per category derived from research ─────────────
RESEARCH_SETTINGS = {
    "analyst": {
        "neutralization": "SUBINDUSTRY",
        "decay": 0,
        "truncation": 0.08,
        "nan_handling": "ON",
    },
    "fundamental": {
        "neutralization": "SUBINDUSTRY",
        "decay": 0,
        "truncation": 0.08,
        "nan_handling": "ON",
    },
    "model": {
        "neutralization": "SUBINDUSTRY",
        "decay": 0,
        "truncation": 0.08,
        "nan_handling": "ON",
    },
    "news": {
        "neutralization": "INDUSTRY",
        "decay": 10,
        "truncation": 0.08,
        "nan_handling": "ON",
    },
    "option": {
        "neutralization": "INDUSTRY",
        "decay": 3,
        "truncation": 0.08,
        "nan_handling": "ON",
    },
    "pv": {
        "neutralization": "INDUSTRY",
        "decay": 10,
        "truncation": 0.08,
        "nan_handling": "OFF",
    },
    "generic": {
        "neutralization": "SUBINDUSTRY",
        "decay": 0,
        "truncation": 0.08,
        "nan_handling": "ON",
    },
}


class AlphaIntelligence:
    """Learns from simulation history and research to prioritize mining."""

    def __init__(self, intelligence_path="alpha_intelligence.json",
                 templates_path="research_templates.json"):
        self.intelligence = self._load_json(intelligence_path)
        self.templates = self._load_templates(templates_path)
        self.fitness_model = self._load_model("fitness_model.pkl")
        self.field_index = self._build_field_index()

    def _load_json(self, path):
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
        return {}

    def _load_templates(self, path):
        base = list(CURATED_TEMPLATES)
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
                base = data.get('templates', base)
        # Prepend golden templates so they headline the queue
        return GOLDEN_TEMPLATES + base

    def _load_model(self, path):
        if os.path.exists(path):
            with open(path, 'rb') as f:
                return pickle.load(f)
        return None

    def _build_field_index(self):
        """Build field metadata index from brain_fields.json."""
        index = {}
        if os.path.exists("brain_fields.json"):
            with open("brain_fields.json") as f:
                fields = json.load(f)
                for field in fields:
                    index[field['id']] = field
        return index

    def score_field(self, field_id):
        """Score a field's mining priority (higher = mine first)."""
        score = 0.0
        meta = self.field_index.get(field_id, {})
        cat = categorize_field(field_id, meta)

        # Historical performance for this category
        cat_stats = self.intelligence.get('learned_stats', {}).get('category', {})
        if cat in cat_stats:
            score += cat_stats[cat]['avg_fitness'] * 2
            score += cat_stats[cat]['success_rate'] * 3

        # Historical performance for this specific field
        field_stats = self.intelligence.get('learned_stats', {}).get('field', {})
        if field_id in field_stats:
            score += field_stats[field_id]['max_fitness'] * 1.5

        # Field metadata bonuses
        coverage = meta.get('coverage', 0)
        alpha_count = meta.get('alphaCount', 0)
        user_count = meta.get('userCount', 0)

        score += coverage * 2                     # prefer high coverage
        score += min(alpha_count / 100, 2)        # proven fields bonus (capped)
        score += min(user_count / 50, 1)          # popular fields bonus (capped)

        # Penalize already-tested fields that showed low fitness
        if field_id in field_stats:
            if field_stats[field_id]['count'] >= 6:
                score -= 2.0  # heavily tested with poor results
            elif field_stats[field_id]['count'] >= 3:
                score -= 0.8

        return score

    def rank_fields(self, field_ids):
        """Rank a list of field IDs by mining priority."""
        scored = [(fid, self.score_field(fid)) for fid in field_ids]
        scored.sort(key=lambda x: -x[1])
        return scored

    def get_templates_for_field(self, field_id):
        """Get ranked list of (expression, settings) for a field."""
        meta = self.field_index.get(field_id, {})
        cat = categorize_field(field_id, meta)
        field_type = meta.get('type', 'MATRIX')

        candidates = []

        for tmpl in self.templates:
            if tmpl.get('field_slot') == 'FIELD':
                if tmpl['category'] in (cat, 'generic'):
                    expr = tmpl['expression'].replace('{FIELD}', field_id)
                    settings = self._optimize_settings(tmpl.get('settings', {}), cat)
                    priority = self._score_template(tmpl['name'], cat)
                    # Apply boost if this is a golden template
                    priority += tmpl.get('priority_boost', 0)
                    candidates.append({
                        'expression': expr,
                        'settings': settings,
                        'template_name': tmpl['name'],
                        'priority': priority,
                    })
            elif tmpl.get('field_slot') is None and tmpl['category'] == 'pv':
                candidates.append({
                    'expression': tmpl['expression'],
                    'settings': tmpl.get('settings', {}),
                    'template_name': tmpl['name'],
                    'priority': self._score_template(tmpl['name'], 'pv') + tmpl.get('priority_boost', 0),
                })

        # Vector fields: keep only vec_avg-based expressions
        if field_type == 'VECTOR':
            vec_candidates = [c for c in candidates if 'vec_' in c['expression']]
            if not vec_candidates:
                vec_candidates.append({
                    'expression': f"ts_backfill(-vec_avg({field_id}), 20)",
                    'settings': self._optimize_settings({}, cat),
                    'template_name': 'vector_backfill',
                    'priority': 1.2,
                })
            candidates = vec_candidates

        candidates.sort(key=lambda x: -x['priority'])
        return candidates

    def _score_template(self, template_name, category):
        """Score a template based on historical performance."""
        tmpl_stats = self.intelligence.get('learned_stats', {}).get('template', {})
        pattern_map = {
            'anl_raw_flag': 'raw', 'generic_raw': 'raw',
            'anl_ts_rank': 'ts_rank_252', 'generic_ts_rank_252': 'ts_rank_252',
            'fnd_ts_rank_short': 'ts_rank_63', 'generic_ts_rank_63': 'ts_rank_63',
            'fnd_zscore_short': 'ts_zscore', 'generic_zscore': 'ts_zscore',
            'fnd_av_diff': 'ts_av_diff', 'generic_ts_av_diff': 'ts_av_diff',
            'pv_vol_regime_reversion': 'trade_when',
            'fnd_group_zscore': 'group_zscore',
            'news_sentiment_conditional': 'trade_when',
            # Golden combos — use known performance of constituent patterns
            'gold_anl_raw_subind': 'raw',
            'gold_anl_flag': 'raw',
            'gold_anl_ts_zscore': 'ts_zscore',
            'gold_mdl_subind_63': 'ts_rank_63',
            'gold_news_vec_backfill': 'vec_avg',
        }
        pattern = pattern_map.get(template_name, 'other')
        if pattern in tmpl_stats:
            return tmpl_stats[pattern]['avg_fitness'] + tmpl_stats[pattern]['success_rate']
        return 0.3  # default for untested templates

    def _optimize_settings(self, base_settings, category):
        """Merge template settings with research-derived best settings."""
        research = RESEARCH_SETTINGS.get(category, RESEARCH_SETTINGS['generic'])
        learned = self.intelligence.get('best_settings_per_category', {}).get(category, {})

        # Priority: explicit base > learned > research defaults
        settings = {
            "universe": "TOP3000",
            "delay": 1,
            "neutralization": (
                base_settings.get('neutralization')
                or learned.get('neutralization')
                or research['neutralization']
            ),
            "decay": (
                base_settings['decay'] if 'decay' in base_settings
                else learned.get('decay', research['decay'])
            ),
            "truncation": (
                base_settings.get('truncation')
                or learned.get('truncation')
                or research['truncation']
            ),
            "nan_handling": research.get('nan_handling', 'ON'),
        }
        return settings

    def mutate_successful_alpha(self, expression, settings, mutation_strength=0.3):
        """
        Generate mutations of a successful alpha expression.

        Mutation strategies:
          - Negation flip
          - Window changes (ts_rank/ts_zscore lookback)
          - Neutralization tier changes
          - Decay value changes (research-tuned ladder)
          - Truncation changes
          - Operator substitution (rank ↔ group_rank, ts_rank ↔ ts_zscore)
          - Golden-combo wrapping (inject group_rank outer layer)
          - Decay-mix: combine signal with slow-moving counterpart
        """
        mutations = []

        # ── 1. Negation flip ────────────────────────────────────
        if expression.startswith('-'):
            mutations.append({
                'expression': expression[1:],
                'settings': settings.copy(),
                'mutation': 'flip_negation',
            })
        else:
            mutations.append({
                'expression': f'-({expression})' if ' ' in expression else f'-{expression}',
                'settings': settings.copy(),
                'mutation': 'add_negation',
            })

        # ── 2. Window mutations ──────────────────────────────────
        window_swaps = [
            (252, 63), (252, 126), (252, 500),
            (63, 126), (63, 252),
            (126, 63), (126, 252),
            (20, 63), (20, 126),
        ]
        for old_w, new_w in window_swaps:
            pattern = f', {old_w})'
            if pattern in expression:
                mutated = expression.replace(pattern, f', {new_w})', 1)
                mutations.append({
                    'expression': mutated,
                    'settings': settings.copy(),
                    'mutation': f'window_{old_w}_to_{new_w}',
                })

        # ── 3. Neutralization mutations ──────────────────────────
        for neut in ['SUBINDUSTRY', 'INDUSTRY', 'MARKET', 'SECTOR']:
            if neut != settings.get('neutralization'):
                trial = settings.copy()
                trial['neutralization'] = neut
                mutations.append({
                    'expression': expression,
                    'settings': trial,
                    'mutation': f'neut_{neut}',
                })

        # ── 4. Decay mutations (research-backed ladder) ──────────
        for decay in [0, 3, 5, 8, 10, 15, 20]:
            if decay != settings.get('decay'):
                trial = settings.copy()
                trial['decay'] = decay
                mutations.append({
                    'expression': expression,
                    'settings': trial,
                    'mutation': f'decay_{decay}',
                })

        # ── 5. Truncation mutations ──────────────────────────────
        for trunc in [0.01, 0.05, 0.08, 0.1]:
            if trunc != settings.get('truncation'):
                trial = settings.copy()
                trial['truncation'] = trunc
                mutations.append({
                    'expression': expression,
                    'settings': trial,
                    'mutation': f'trunc_{trunc}',
                })

        # ── 6. Operator substitutions ────────────────────────────
        op_subs = [
            ('ts_rank', 'ts_quantile'),
            ('ts_rank', 'ts_zscore'),
            ('ts_zscore', 'ts_rank'),
            ('rank', 'zscore'),
            ('zscore', 'rank'),
        ]
        for old_op, new_op in op_subs:
            if old_op in expression:
                mutated = expression.replace(old_op, new_op, 1)
                if mutated != expression:
                    mutations.append({
                        'expression': mutated,
                        'settings': settings.copy(),
                        'mutation': f'op_{old_op}_to_{new_op}',
                    })

        # ── 7. Golden-combo wrapping ─────────────────────────────
        # If expression starts with ts_rank but lacks group_rank outer layer, add it
        stripped = expression.lstrip('-').strip()
        if stripped.startswith('ts_rank(') and 'group_rank' not in expression:
            golden = f"group_rank({expression}, subindustry)"
            trial = settings.copy()
            trial['neutralization'] = 'SUBINDUSTRY'
            trial['decay'] = 0
            mutations.append({
                'expression': golden,
                'settings': trial,
                'mutation': 'golden_combo_wrap',
            })

        # If expression has no group operator at all, try wrapping in group_rank
        if 'group_rank' not in expression and 'group_zscore' not in expression:
            for group in ['subindustry', 'industry']:
                wrapped = f"group_rank({expression}, {group})"
                trial = settings.copy()
                trial['neutralization'] = 'SUBINDUSTRY' if group == 'subindustry' else 'INDUSTRY'
                mutations.append({
                    'expression': wrapped,
                    'settings': trial,
                    'mutation': f'group_rank_{group}_wrap',
                })

        # ── 8. nanHandling toggle ────────────────────────────────
        for nh in ['ON', 'OFF']:
            if nh != settings.get('nan_handling'):
                trial = settings.copy()
                trial['nan_handling'] = nh
                mutations.append({
                    'expression': expression,
                    'settings': trial,
                    'mutation': f'nanhandling_{nh}',
                })

        random.shuffle(mutations)
        n = max(1, int(len(mutations) * mutation_strength))
        return mutations[:n]

    def get_pv_alphas(self):
        """Get standalone price/volume alphas that don't need a field."""
        pv = []
        for tmpl in self.templates:
            if tmpl.get('field_slot') is None and tmpl['category'] == 'pv':
                pv.append({
                    'expression': tmpl['expression'],
                    'settings': tmpl.get('settings', {
                        "universe": "TOP3000", "neutralization": "SUBINDUSTRY",
                        "decay": 0, "truncation": 0.08, "delay": 1,
                    }),
                    'template_name': tmpl['name'],
                    'priority': tmpl.get('priority_boost', 0.5),
                })
        return pv

    def get_mutation_targets(self, min_fitness=0.6):
        """Load successful alphas from history for mutation."""
        targets = []
        if not os.path.exists("simulation_history.json"):
            return targets
        with open("simulation_history.json") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)
                fitness = entry.get('fitness', 0) or 0
                if fitness >= min_fitness:
                    targets.append({
                        'expression': entry['expression'],
                        'settings': entry.get('settings', {}),
                        'fitness': fitness,
                    })
        # Deduplicate and sort by fitness descending
        seen = set()
        unique = []
        for t in sorted(targets, key=lambda x: -x['fitness']):
            if t['expression'] not in seen:
                seen.add(t['expression'])
                unique.append(t)
        return unique[:25]

    def build_mining_queue(self, field_ids, include_pv=True, include_mutations=True):
        """
        Build a prioritized mining queue of (expression, settings, metadata).
        Queue order: golden PV stubs → mutation targets → field-based templates.
        """
        queue = []
        seen_exprs = set()

        def _add(item):
            key = item['expression'][:80]
            if key not in seen_exprs:
                seen_exprs.add(key)
                queue.append(item)

        # 1. High-value standalone PV / golden templates
        if include_pv:
            for pv in self.get_pv_alphas():
                _add({**pv, 'source': 'pv_template'})

        # 2. Mutation targets from successful history
        if include_mutations:
            for target in self.get_mutation_targets(min_fitness=0.6):
                muts = self.mutate_successful_alpha(
                    target['expression'], target['settings']
                )
                for mut in muts:
                    _add({
                        'expression': mut['expression'],
                        'settings': mut['settings'],
                        'template_name': f"mut_{mut['mutation']}",
                        'source': 'mutation',
                        'priority': target['fitness'] * 0.6,
                        'parent_fitness': target['fitness'],
                    })

        # 3. Field-based templates (ranked by intelligence score)
        ranked_fields = self.rank_fields(field_ids)
        for field_id, field_score in ranked_fields:
            templates = self.get_templates_for_field(field_id)
            for i, tmpl in enumerate(templates):
                priority = field_score + tmpl['priority'] - (i * 0.05)
                _add({
                    'expression': tmpl['expression'],
                    'settings': tmpl['settings'],
                    'template_name': tmpl['template_name'],
                    'source': 'field_template',
                    'field': field_id,
                    'priority': priority,
                })

        queue.sort(key=lambda x: -x.get('priority', 0))
        return queue
