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
from dotenv import load_dotenv

load_dotenv()

# ─── Configuration ────────────────────────────────────────────────
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_RETRIES = 5
BASE_BACKOFF = 2  # seconds

# Load operator reference for grounding
def _load_operators():
    path = Path(__file__).parent / "brain_operators.json"
    if path.exists():
        with open(path) as f:
            ops = json.load(f)
        return ops
    return []

OPERATORS = _load_operators()
OPERATOR_NAMES = {op["name"] for op in OPERATORS}
OPERATOR_REFERENCE = "\n".join(
    f"  {op['name']}: {op.get('definition', '')} — {op.get('description', '')[:120]}"
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

    def _call(self, messages, temperature=0.7, max_tokens=2048):
        """Make a single API call with retry and key rotation."""
        for attempt in range(MAX_RETRIES):
            key = self._next_key()
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": GROQ_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            try:
                resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=60)

                if resp.status_code == 200:
                    self._call_count += 1
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    return self._parse_json_response(content)

                if resp.status_code == 400:
                    # JSON mode failed — try a different key (different randomness)
                    print(f"    [LLM] JSON generation failed (attempt {attempt+1}), rotating key...")
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
