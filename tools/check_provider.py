"""
Provider connectivity checker (tools/check_provider.py).
Per PRD §C3:
- Standard library only (no external dependencies)
- Reads .env (and environment) for UPSTREAM_URL, UPSTREAM_KEY, MAX_TOKENS_FIELD
- Sends one tiny prompt ("Say hello in one short sentence.") with 60 max tokens directly to the provider
- Prints URL, model, whether key is set (NEVER prints the key)
- Prints latency, reply, usage, and computed cost from prices.json (flagging default rate fallback)
- Provides diagnostic hints on HTTP and connection errors
"""

import sys
import os
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

# Safe terminal encoding on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_env_vars():
    """Simple parser for .env without third-party dependencies."""
    env_vars = {}
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env_vars[k.strip()] = v.strip().strip("'\"")
    # OS environment overrides .env
    for k, v in os.environ.items():
        env_vars[k] = v
    return env_vars


def load_prices_json():
    prices_path = Path(__file__).resolve().parent.parent / "prices.json"
    if prices_path.exists():
        try:
            with open(prices_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"default": {"in": 0.05, "out": 0.15}}


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/check_provider.py <model-id>")
        print("Example: python tools/check_provider.py mock-large")
        sys.exit(1)

    model_id = sys.argv[1]
    env = load_env_vars()

    upstream_url = env.get("UPSTREAM_URL", "http://localhost:9000/v1/chat/completions")
    upstream_key = env.get("UPSTREAM_KEY", "").strip()
    max_tokens_field = env.get("MAX_TOKENS_FIELD", "max_tokens").strip()

    print("=" * 65)
    print("🔍 CHECKING AI PROVIDER DIRECT CONNECTIVITY")
    print("=" * 65)
    print(f"Target URL:    {upstream_url}")
    print(f"Model ID:      {model_id}")
    print(f"API Key set:   {'YES (configured)' if upstream_key else 'NO (empty/none)'}")
    print(f"Tokens field:  {max_tokens_field}")
    print("-" * 65)

    prompt = "Say hello in one short sentence."
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
    }
    payload[max_tokens_field] = 60

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "CostFirewall/2.0",
    }
    if upstream_key:
        headers["Authorization"] = f"Bearer {upstream_key}"

    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(upstream_url, data=data_bytes, headers=headers, method="POST")

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            resp_body = resp.read().decode("utf-8")
            resp_json = json.loads(resp_body)

            reply = (
                resp_json.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            usage = resp_json.get("usage")

            print(f"Status:        HTTP {resp.status} OK")
            print(f"Latency:       {latency_ms} ms")
            print(f"Reply:         \"{reply}\"")
            print(f"Usage:         {json.dumps(usage)}")

            # Price computation
            prices = load_prices_json()
            is_default = False
            if model_id in prices:
                rates = prices[model_id]
            else:
                rates = prices.get("default", {"in": 0.05, "out": 0.15})
                is_default = True

            if usage:
                in_tok = usage.get("prompt_tokens", 0)
                out_tok = usage.get("completion_tokens", 0)
                cost = (in_tok / 1000 * rates["in"]) + (out_tok / 1000 * rates["out"])
                rate_note = " (using 'default' fallback rate)" if is_default else ""
                print(f"Firewall Cost: Rs {cost:.5f}{rate_note}")
            else:
                print("Firewall Cost: Rs 0.00000 (Provider returned no usage object!)")

            print("\n✅ PROVIDER TEST PASSED! The provider is reachable and responsive.")

    except urllib.error.HTTPError as e:
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"Status:        HTTP {e.code} Error ({latency_ms} ms)")
        print(f"Response:      {err_body}")

        hint = ""
        if e.code == 400:
            hint = "Request field error: Try setting MAX_TOKENS_FIELD=max_completion_tokens in .env"
        elif e.code == 401:
            hint = "Authentication error: Check that UPSTREAM_KEY in .env is valid and active"
        elif e.code == 403:
            hint = "Permission error: The API key lacks permission or quota for this model"
        elif e.code == 404:
            hint = "Not found: Verify UPSTREAM_URL and that the model-id exists for this provider"
        elif e.code == 429:
            hint = "Rate limit: The provider has throttled requests or quota has been exhausted"

        if hint:
            print(f"\n💡 Hint: {hint}")
        sys.exit(1)

    except urllib.error.URLError as e:
        print(f"Connection Error: {e.reason}")
        print("\n💡 Hint: Check your internet connection, or if testing locally, verify Ollama/Mock is running.")
        sys.exit(1)


if __name__ == "__main__":
    main()
