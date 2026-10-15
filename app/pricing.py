"""
Pricing and cost estimation.
Loads prices.json (Rs per 1000 tokens), computes actual cost from provider
usage, and estimates cost before a call using the chars/4 heuristic.
"""

import json
import os
from pathlib import Path

# Path to the prices file (project root)
_PRICES_PATH = Path(__file__).resolve().parent.parent / "prices.json"
_prices_cache: dict | None = None
_prices_mtime: float = 0.0


def load_prices() -> dict:
    """Load prices.json, re-reading only when the file has changed (hot-reload)."""
    global _prices_cache, _prices_mtime
    try:
        mtime = os.path.getmtime(_PRICES_PATH)
        if _prices_cache is None or mtime != _prices_mtime:
            with open(_PRICES_PATH, "r", encoding="utf-8") as f:
                _prices_cache = json.load(f)
            _prices_mtime = mtime
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[pricing] WARNING: cannot load prices.json: {e}")
        if _prices_cache is None:
            # Absolute fallback so the proxy never crashes
            _prices_cache = {"default": {"in": 0.05, "out": 0.15}}
    return _prices_cache


def _get_rate(model: str) -> dict:
    """Get the {in, out} rate for a model, falling back to 'default' then 'mock-large'."""
    prices = load_prices()
    if model in prices:
        return prices[model]
    if "default" in prices:
        return prices["default"]
    # Last resort (should never happen if prices.json is valid)
    return {"in": 0.50, "out": 1.50}


def cost_of(model: str, in_tokens: int, out_tokens: int) -> float:
    """
    Actual cost in Rs.
    Formula: in_tokens/1000 * price_in + out_tokens/1000 * price_out
    """
    rate = _get_rate(model)
    return round(in_tokens / 1000 * rate["in"] + out_tokens / 1000 * rate["out"], 5)


def estimate_cost(model: str, messages: list, expected_output_tokens: int) -> tuple[float, int, int]:
    """
    Estimate cost before the call.
    Input tokens = len(json.dumps(messages)) // 4   (1 token ≈ 4 chars).
    Returns (estimated_cost_rs, est_input_tokens, expected_output_tokens).
    """
    input_tokens = len(json.dumps(messages)) // 4
    est = cost_of(model, input_tokens, expected_output_tokens)
    return est, input_tokens, expected_output_tokens
