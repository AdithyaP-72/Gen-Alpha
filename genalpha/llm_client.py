"""
LLM Client — Groq API integration with round-robin key rotation.

Uses Llama 3.3 70B to:
  1. Extract tradeable anomalies from academic paper abstracts
  2. Generate WorldQuant BRAIN expressions grounded against real operators
"""

import os
import json
import time
import itertools
import requests
from pathlib import Path
from genalpha import config

# ─── Configuration ────────────────────────────────────────────────
GROQ_MODEL = "llama-3.3-70b-versatile"        # generation (Agent A)
GROQ_MODEL_CRITIC = "llama-3.1-8b-instant"    # review (Agent B) — cheaper/faster
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_RETRIES = 5
BASE_BACKOFF = 2  # seconds

# Load operator reference for grounding
def _load_operators():
    path = config.BRAIN_OPERATORS
    if path.exists():
        with open(path) as f:
            ops = json.load(f)
        return ops
    return []

OPERATORS = _load_operators()
OPERATOR_NAMES = {op["name"] for op in OPERATORS}
if not OPERATOR_NAMES:
    print("  [LLM] WARNING: brain_operators.json missing/empty — operator validation "
          "will reject everything. Run `python3 scrape_brain.py` first.")
# Name + call signature only — descriptions tripled the prompt size on every call.
OPERATOR_REFERENCE = "\n".join(
    f"  {op['name']}: {op.get('definition', '')}"
    for op in OPERATORS
)


class GroqClient:
    """Round-robin Groq API client with automatic key rotation and retry."""

    def __init__(self):
        self.keys = self._load_keys()
        self._key_cycle = itertools.cycle(self.keys)
        self._call_count = 0
        print(f"  GroqClient initialized with {len(self.keys)} API keys")

    def _load_keys(self):
        keys = []
        for i in range(1, 10):
            key = os.getenv(f"GROQ_API_KEY_{i}")
            if key:
                keys.append(key)
        if not keys:
            raise ValueError("No GROQ_API_KEY_* found in .env")
        return keys

    def _next_key(self):
        return next(self._key_cycle)

    def _parse_json_response(self, content):
        """Robustly extract JSON from LLM response text."""
        import re

        # Clean common LLM artifacts
        content = content.strip()
        # Remove BOM and zero-width chars
        content = content.lstrip('\ufeff\u200b')

        # 1. Direct parse
        try:
            return json.loads(content)
        except (json.JSONDecodeError, ValueError):
            pass

        # 2. Extract from markdown code block
        match = re.search(r'```(?:json)?\s*(\{.+\})\s*```', content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except (json.JSONDecodeError, ValueError):
                pass

        # 3. Find the largest { ... } block using brace counting
        start = content.find('{')
        if start != -1:
            depth = 0
            best_end = start
            for i in range(start, len(content)):
                if content[i] == '{':
                    depth += 1
                elif content[i] == '}':
                    depth -= 1
                    if depth == 0:
                        best_end = i + 1
                        break
            candidate = content[start:best_end]
            # Try fixing common JSON issues: trailing commas, single quotes
            candidate = re.sub(r',\s*}', '}', candidate)
            candidate = re.sub(r',\s*]', ']', candidate)
            try:
                return json.loads(candidate)
            except (json.JSONDecodeError, ValueError):
                pass

        print(f"    [LLM] Could not parse JSON from response ({len(content)} chars)")
        print(f"    [LLM] First 200 chars: {content[:200]}")
        return None

    def _call(self, messages, temperature=0.7, max_tokens=2048, model=None):
        """Make a single API call with retry and key rotation."""
        use_json_mode = True
        for attempt in range(MAX_RETRIES):
            key = self._next_key()
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": model or GROQ_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if use_json_mode:
                payload["response_format"] = {"type": "json_object"}

            try:
                resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=60)

                if resp.status_code == 200:
                    self._call_count += 1
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    return self._parse_json_response(content)

                if resp.status_code == 400:
                    # Could be strict JSON mode misbehaving — drop it and rotate key
                    print(f"    [LLM] HTTP 400 (attempt {attempt+1}), "
                          f"{'disabling JSON mode and ' if use_json_mode else ''}rotating key...")
                    use_json_mode = False
                    time.sleep(1)
                    continue

                if resp.status_code == 429:
                    wait = BASE_BACKOFF * (2 ** attempt) + (time.time() % 3)
                    print(f"    [LLM] Rate limited (key ...{key[-6:]}). Retrying in {wait:.1f}s...")
                    time.sleep(wait)
                    continue

                print(f"    [LLM] HTTP {resp.status_code}: {resp.text[:200]}")
                if resp.status_code in (401, 403):
                    # Bad key — try next one
                    continue
                return None

            except requests.RequestException as e:
                print(f"    [LLM] Request error: {e}")
                time.sleep(BASE_BACKOFF)
                continue

        print(f"    [LLM] All {MAX_RETRIES} retries exhausted")
        return None

    def test_connection(self):
        """Quick test that the API keys work."""
        result = self._call([
            {"role": "user", "content": "Respond with JSON: {\"status\": \"ok\", \"model\": \"your model name\"}"}
        ], max_tokens=50)
        return result

    def extract_anomaly(self, title, abstract):
        """Extract a tradeable anomaly from a paper abstract.

        Returns dict with: hypothesis, direction, holding_period, data_needed, confidence
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a senior quantitative researcher at a systematic hedge fund. "
                    "Your job is to read academic finance paper abstracts and identify "
                    "tradeable market anomalies that can be expressed as cross-sectional "
                    "equity signals.\n\n"
                    "Respond with a JSON object containing:\n"
                    "- \"hypothesis\": one-sentence description of the anomaly\n"
                    "- \"direction\": \"long\" or \"short\" or \"long-short\"\n"
                    "- \"holding_period\": estimated in trading days (e.g. 5, 21, 63, 252)\n"
                    "- \"data_needed\": list of data types needed (e.g. [\"price\", \"volume\", \"earnings\", \"sentiment\"])\n"
                    "- \"signal_type\": one of [\"momentum\", \"mean_reversion\", \"value\", \"quality\", \"sentiment\", \"volatility\", \"event_driven\", \"other\"]\n"
                    "- \"confidence\": 0.0-1.0 how likely this is implementable as a daily cross-sectional signal\n"
                    "- \"reasoning\": brief explanation of why this anomaly might persist\n\n"
                    "CRITICAL: You must output STRICT, VALID JSON only. Ensure all string values are wrapped in double quotes. Do not include markdown code block formatting or any text outside the JSON object.\n\n"
                    "If the paper is not about a tradeable equity anomaly, set confidence to 0.0."
                ),
            },
            {
                "role": "user",
                "content": f"Paper Title: {title}\n\nAbstract: {abstract}",
            },
        ]
        return self._call(messages, temperature=0.3, max_tokens=500)

    def generate_expressions(self, anomaly, similar_templates, field_ids=None):
        """Generate BRAIN-valid expressions from an anomaly description.

        Args:
            anomaly: dict from extract_anomaly()
            similar_templates: list of existing template expression strings (few-shot examples)
            field_ids: optional list of real field IDs to use

        Returns list of dicts with: expression, settings, rationale
        """
        examples_block = "\n".join(
            f"  Example {i+1}: {t}" for i, t in enumerate(similar_templates[:8])
        )

        field_block = ""
        if field_ids:
            field_block = (
                "\n\nAvailable data fields you can use (real field IDs from the platform):\n"
                + "\n".join(f"  - {fid}" for fid in field_ids[:30])
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert at writing WorldQuant BRAIN alpha expressions. "
                    "You MUST only use operators from this exact reference list:\n\n"
                    f"{OPERATOR_REFERENCE}\n\n"
                    "Key built-in price/volume fields: close, open, high, low, volume, vwap, returns, cap, sharesout\n"
                    "Grouping fields: sector, industry, subindustry, market\n\n"
                    "Rules:\n"
                    "1. Expressions must be valid FASTEXPR syntax\n"
                    "2. Use ONLY operators listed above — do NOT invent operators\n"
                    "3. For VECTOR fields (like nws12_*), wrap with vec_avg() or vec_sum() first\n"
                    "4. Prefer the 'golden combo' pattern: group_rank(ts_rank(signal, N), subindustry)\n"
                    "5. Use ternary conditionals sparingly: condition ? value_if_true : value_if_false\n"
                    "6. Variable assignments use: var_name = expr; next_expr\n"
                    "7. Keep expressions under 200 characters when possible\n\n"
                    "Here are existing successful expressions for reference:\n"
                    f"{examples_block}\n"
                    f"{field_block}\n\n"
                    "Respond with a STRICT, VALID JSON object containing:\n"
                    "- \"expressions\": list of objects, each with:\n"
                    "  - \"expression\": the BRAIN expression string\n"
                    "  - \"settings\": {\"neutralization\": str, \"decay\": int, \"truncation\": float}\n"
                    "  - \"rationale\": one sentence explaining the signal logic\n"
                    "  - \"confidence\": 0.0-1.0 estimated probability of passing validation\n"
                    "Generate 3-5 diverse expressions that capture different aspects of the anomaly.\n"
                    "CRITICAL: Ensure all string values are wrapped in double quotes. Do not include markdown formatting or text outside the JSON object."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Anomaly: {anomaly.get('hypothesis', 'Unknown')}\n"
                    f"Direction: {anomaly.get('direction', 'long-short')}\n"
                    f"Signal type: {anomaly.get('signal_type', 'other')}\n"
                    f"Holding period: {anomaly.get('holding_period', 63)} days\n"
                    f"Data needed: {anomaly.get('data_needed', ['price'])}\n"
                    f"Reasoning: {anomaly.get('reasoning', 'N/A')}\n\n"
                    "Generate BRAIN expressions to exploit this anomaly."
                ),
            },
        ]
        return self._call(messages, temperature=0.6, max_tokens=1500)

    # ── Agent B: batched critic (actor-critic review) ─────────────
    CRITIC_RUBRIC = (
        "You are a risk manager at a systematic hedge fund reviewing alpha "
        "expressions for the WorldQuant BRAIN platform BEFORE they are simulated. "
        "All simulations run with delay=1 (yesterday's data trades today).\n\n"
        "Review each expression for these failure modes:\n"
        "- look_ahead_bias: uses information not available at the delay-1 close\n"
        "- neutralization_mismatch: e.g. a market-wide signal under SECTOR/MARKET "
        "neutralization nets to ~zero positions\n"
        "- vector_unwrapped: VECTOR fields (nws12_*, rp_*) used without vec_avg()/vec_sum()\n"
        "- degenerate_signal: constant, near-constant, or division that explodes on "
        "zero/negative denominators (e.g. dividing by a field that crosses zero)\n"
        "- overfit_complexity: many arbitrary constants or deeply nested logic with "
        "no economic rationale\n"
        "- rationale_mismatch: the math does not implement the stated rationale\n\n"
        "Respond with STRICT JSON: {\"reviews\": [{\"idx\": int, "
        "\"verdict\": \"approve\"|\"revise\"|\"reject\", \"issues\": [str], "
        "\"fix_hint\": str}]}. Be pragmatic: approve reasonable expressions; "
        "reserve reject for clear defects."
    )

    def critique_expressions(self, candidates):
        """Agent B: review a batch of expressions in ONE call on the cheap model.

        candidates: list of {"expression", "rationale", "settings"}.
        Returns list of review dicts aligned by idx, or None on failure
        (callers must treat None as approve-all — the critic is advisory).
        """
        if not candidates:
            return []
        listing = "\n".join(
            f"{i}. expression: {c.get('expression', '')}\n"
            f"   rationale: {c.get('rationale', 'n/a')}\n"
            f"   settings: neutralization={c.get('settings', {}).get('neutralization')}, "
            f"decay={c.get('settings', {}).get('decay')}"
            for i, c in enumerate(candidates)
        )
        result = self._call(
            [
                {"role": "system", "content": self.CRITIC_RUBRIC},
                {"role": "user", "content": f"Review these candidate alphas:\n\n{listing}"},
            ],
            temperature=0.2, max_tokens=1200, model=GROQ_MODEL_CRITIC,
        )
        if not result or "reviews" not in result:
            return None
        return result["reviews"]

    # ── Chain-of-Alpha: generation chain (fix compile/validation errors) ──
    def rewrite_expression(self, expression, error, rationale=None):
        """Feed the exact FASTEXPR/validator error back for a targeted rewrite.

        Returns {"expression": str} or None.
        """
        result = self._call(
            [
                {
                    "role": "system",
                    "content": (
                        "You fix WorldQuant BRAIN FASTEXPR expressions that failed to "
                        "compile or validate. You MUST only use operators from this list:\n\n"
                        f"{OPERATOR_REFERENCE}\n\n"
                        "Keep the economic intent identical; change only what the error "
                        "requires. Respond with STRICT JSON: "
                        "{\"expression\": \"<fixed expression>\"}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Expression: {expression}\n"
                        f"Intent: {rationale or 'unknown'}\n"
                        f"Exact error from the platform/validator:\n{error}"
                    ),
                },
            ],
            temperature=0.3, max_tokens=400,
        )
        if result and isinstance(result.get("expression"), str) and result["expression"].strip():
            return {"expression": result["expression"].strip()}
        return None

    # ── Chain-of-Alpha: optimization chain (improve near-misses) ──
    def refine_expression(self, expression, metrics, failed_checks=None, rationale=None):
        """Ask for a targeted improvement of a near-miss using its measured metrics.

        Returns {"expression": str, "change": str} or None.
        """
        checks_str = ", ".join(failed_checks or []) or "none"
        result = self._call(
            [
                {
                    "role": "system",
                    "content": (
                        "You improve WorldQuant BRAIN alpha expressions that are close to "
                        "the submittable thresholds (Fitness ≥ 1.1, Sharpe ≥ 1.3, Turnover "
                        "1–35%). You MUST only use operators from this list:\n\n"
                        f"{OPERATOR_REFERENCE}\n\n"
                        "Make ONE targeted change addressing the weakest metric (e.g. high "
                        "turnover → smooth with ts_decay_linear or longer windows; low "
                        "sharpe → better conditioning or grouping). Respond with STRICT "
                        "JSON: {\"expression\": \"<improved>\", \"change\": \"<what you changed and why>\"}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Expression: {expression}\n"
                        f"Intent: {rationale or 'unknown'}\n"
                        f"Measured: sharpe={metrics.get('sharpe')}, fitness={metrics.get('fitness')}, "
                        f"turnover={metrics.get('turnover')}, drawdown={metrics.get('drawdown')}\n"
                        f"Failed platform checks: {checks_str}"
                    ),
                },
            ],
            temperature=0.4, max_tokens=500,
        )
        if result and isinstance(result.get("expression"), str) and result["expression"].strip():
            return {"expression": result["expression"].strip(),
                    "change": result.get("change", "")}
        return None


if __name__ == "__main__":
    print("Testing Groq connection...")
    client = GroqClient()
    result = client.test_connection()
    print(f"  Result: {result}")

    # Quick test of anomaly extraction
    print("\nTesting anomaly extraction...")
    test_anomaly = client.extract_anomaly(
        "Post-Earnings Announcement Drift",
        "We find that stocks with positive earnings surprises continue to outperform "
        "for 60 trading days after the announcement, while negative surprises continue "
        "to underperform. The drift is strongest in small-cap stocks and is not fully "
        "explained by risk factors."
    )
    print(f"  Anomaly: {json.dumps(test_anomaly, indent=2)}")

    # Quick test of expression generation
    if test_anomaly:
        print("\nTesting expression generation...")
        examples = [
            "group_rank(ts_rank(operating_income / equity, 126), subindustry)",
            "ts_rank(news_sentiment, 63) > 0.7 ? -returns : returns",
            "avg_news = vec_avg(nws12_afterhsz_sl); rank(ts_sum(avg_news, 60)) > 0.5 ? 1 : rank(-ts_delta(close, 2))",
        ]
        exprs = client.generate_expressions(test_anomaly, examples)
        print(f"  Generated: {json.dumps(exprs, indent=2)}")
