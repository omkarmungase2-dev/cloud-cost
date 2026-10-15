"""
Price helper utility (tools/price_helper.py).
Per PRD §C3:
Converts USD per 1M tokens to Rs per 1,000 tokens and optionally merges into prices.json.

Usage:
  python tools/price_helper.py --model <id> --in <USD per 1M> --out <USD per 1M> --rate <USD to INR> [--write]

Example:
  python tools/price_helper.py --model gpt-4o-mini --in 0.15 --out 0.60 --rate 86.5 --write
"""

import sys
import json
import argparse
from pathlib import Path

# Safe terminal encoding on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser(description="Convert provider USD/1M token pricing to Rs/1K tokens.")
    parser.add_argument("--model", required=True, help="Model identifier string")
    parser.add_argument("--in", dest="usd_in", type=float, required=True, help="Input price in USD per 1M tokens")
    parser.add_argument("--out", dest="usd_out", type=float, required=True, help="Output price in USD per 1M tokens")
    parser.add_argument("--rate", type=float, default=86.5, help="USD to INR exchange rate (default: 86.5)")
    parser.add_argument("--write", action="store_true", help="Merge rates directly into prices.json")

    args = parser.parse_args()

    # Formula: Rs per 1000 tokens = (USD per 1M tokens) * rate / 1000
    rs_in = round(args.usd_in * args.rate / 1000.0, 5)
    rs_out = round(args.usd_out * args.rate / 1000.0, 5)

    entry = {
        args.model: {
            "in": rs_in,
            "out": rs_out,
        }
    }

    print(json.dumps(entry, indent=2))
    print(f"\nCalculated for '{args.model}' at USD/INR {args.rate}:")
    print(f"  Input:  ${args.usd_in}/1M  ->  Rs {rs_in:.5f} / 1k tokens")
    print(f"  Output: ${args.usd_out}/1M ->  Rs {rs_out:.5f} / 1k tokens")

    if args.write:
        prices_path = Path(__file__).resolve().parent.parent / "prices.json"
        prices = {}
        if prices_path.exists():
            try:
                with open(prices_path, "r", encoding="utf-8") as f:
                    prices = json.load(f)
            except Exception as e:
                print(f"Warning: Failed to read existing prices.json: {e}")

        prices[args.model] = {"in": rs_in, "out": rs_out}
        with open(prices_path, "w", encoding="utf-8") as f:
            json.dump(prices, f, indent=2)

        print(f"\n✅ Merged '{args.model}' into {prices_path.name}")


if __name__ == "__main__":
    main()
