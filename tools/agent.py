"""
Agent simulator (tools/agent.py).
Simulates an AI agent workflow:
  python tools/agent.py chaos [--direct]
  python tools/agent.py research [--direct]

Uses urllib (standard library).
Default target: http://localhost:8000/v1/chat/completions (via firewall)
With --direct:  http://localhost:9000/v1/chat/completions (bypassing firewall)
"""

import sys
import json
import time
import uuid
import urllib.request
import urllib.error

# Ensure Windows terminal encoding doesn't crash on special characters
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FIREWALL_URL = "http://localhost:8000/v1/chat/completions"
DIRECT_URL = "http://localhost:9000/v1/chat/completions"

RESEARCH_TASKS = [
    "Find the top 3 noise-canceling headphones under $300.",
    "Compare battery life and comfort between Sony WH-1000XM5 and Bose QC Ultra.",
    "Check customer reviews regarding microphone quality on zoom calls.",
    "Identify discount codes or seasonal promotions available on major retailers.",
    "Summarize warranty policy and return window for each option.",
    "Recommend the best overall choice for a frequent remote traveler.",
]


def run_agent(mode: str, direct: bool = False):
    target_url = DIRECT_URL if direct else FIREWALL_URL
    run_id = f"agent-{mode}-{uuid.uuid4().hex[:6]}"
    user_id = "sujal"
    feature = "shopping-agent"

    print("=" * 65)
    print(f"🤖 STARTING AGENT: mode='{mode}', target='{'DIRECT' if direct else 'FIREWALL'}'")
    print(f"   Run ID:  {run_id}")
    print(f"   Target:  {target_url}")
    print("=" * 65)

    history = []
    total_cost = 0.0
    calls_made = 0

    max_calls = 15 if mode == "chaos" else len(RESEARCH_TASKS)
    prompt_source = (
        ["Repeated looping sub-query: Search inventory for item SKU 98234-A"] * 15
        if mode == "chaos"
        else RESEARCH_TASKS
    )

    t_start = time.perf_counter()

    for i in range(max_calls):
        calls_made += 1
        prompt = prompt_source[i]

        # Accumulate history so each call grows larger
        history.append({"role": "user", "content": prompt})

        payload = json.dumps({
            "model": "mock-large",
            "messages": history,
            "max_tokens": 250,
        }).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "X-Run-Id": run_id,
            "X-User-Id": user_id,
            "X-Feature": feature,
        }

        req = urllib.request.Request(target_url, data=payload, headers=headers, method="POST")

        call_t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=200) as resp:
                call_latency = round((time.perf_counter() - call_t0) * 1000, 1)
                data = json.loads(resp.read().decode("utf-8"))

                usage = data.get("usage", {})
                in_tok = usage.get("prompt_tokens", 0)
                out_tok = usage.get("completion_tokens", 0)

                # Read cost from response headers (if via firewall) or compute notional
                hdr_cost = resp.headers.get("X-Firewall-Cost")
                hdr_act = resp.headers.get("X-Firewall-Action", "ALLOW")
                if hdr_cost:
                    call_cost = float(hdr_cost)
                else:
                    # Direct notional cost with mock-large (in: 0.50, out: 1.50 per 1k)
                    call_cost = (in_tok / 1000 * 0.50) + (out_tok / 1000 * 1.50)

                total_cost += call_cost

                # Accumulate reply into history
                reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                history.append({"role": "assistant", "content": reply})

                color = "\033[92m" if total_cost < 2.0 else ("\033[93m" if total_cost < 3.0 else "\033[91m")
                reset = "\033[0m"
                print(
                    f"  Call {calls_made:2d}: {color}{hdr_act:7s}{reset} | "
                    f"Tokens: {in_tok:4d} in, {out_tok:3d} out | "
                    f"Cost: Rs{call_cost:.5f} | "
                    f"Running: {color}Rs{total_cost:.5f}{reset} | "
                    f"Latency: {call_latency}ms"
                )

        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="ignore")
            hdr_act = err.headers.get("X-Firewall-Action", f"HTTP {err.code}")
            hdr_reason = err.headers.get("X-Firewall-Reason", "")

            print("\n" + "-" * 65)
            print(f"🛑 HALTED at call {calls_made} — {hdr_act}")
            if hdr_reason:
                print(f"   Reason: {hdr_reason}")
            try:
                parsed_err = json.loads(err_body)
                msg = parsed_err.get("error", {}).get("message", err_body)
                print(f"   Message: {msg}")
            except Exception:
                print(f"   Raw: {err_body}")

            print(f"   Final total cost before stop: Rs{total_cost:.5f}")
            print(f"   Total duration: {round(time.perf_counter() - t_start, 2)}s")
            print("-" * 65)
            return {
                "calls": calls_made,
                "stopped": True,
                "action": hdr_act,
                "total_cost": total_cost,
                "run_id": run_id,
            }

    print("\n" + "-" * 65)
    print(f"✅ AGENT FINISHED ALL {calls_made} CALLS.")
    print(f"   Final total cost: Rs{total_cost:.5f}")
    print(f"   Total duration: {round(time.perf_counter() - t_start, 2)}s")
    print("-" * 65)
    return {
        "calls": calls_made,
        "stopped": False,
        "total_cost": total_cost,
        "run_id": run_id,
    }


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("chaos", "research"):
        print("Usage: python tools/agent.py chaos|research [--direct]")
        sys.exit(1)

    mode = sys.argv[1]
    direct = "--direct" in sys.argv
    run_agent(mode, direct)


if __name__ == "__main__":
    main()
