"""
Test: 20 parallel calls on one run.
Asserts call_count == 20 and total matches the sum of individual calls.
Needs: mock_llm.py on port 9000, firewall on port 8000.
"""

import json
import sys
import asyncio
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

FIREWALL_URL = "http://localhost:8000/v1/chat/completions"
RUN_ID = "concurrent-test-001"


def send_one(call_num: int) -> dict:
    """Send one request through the firewall. Returns the usage dict."""
    payload = json.dumps({
        "model": "mock-large",
        "messages": [{"role": "user", "content": f"Concurrent call number {call_num}"}],
        "max_tokens": 300,
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "X-Run-Id": RUN_ID,
        "X-User-Id": "concurrent-tester",
        "X-Feature": "concurrent-test",
    }

    req = urllib.request.Request(FIREWALL_URL, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body.get("usage", {})


def main():
    n = 20
    print(f"Sending {n} parallel requests on run {RUN_ID}...")

    # Reset state first
    try:
        req = urllib.request.Request("http://localhost:8000/api/reset", method="POST",
                                      data=b"", headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

    # Ensure caps allow 20 concurrent calls without triggering PAUSE
    try:
        req = urllib.request.Request(
            "http://localhost:8000/api/policies",
            method="POST",
            data=json.dumps({"run_cap": 25.0, "pause_at": 25.0}).encode(),
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

    # Send n calls in parallel using threads
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(send_one, i) for i in range(n)]
        results = []
        errors = []
        for i, f in enumerate(futures):
            try:
                results.append(f.result())
            except Exception as e:
                errors.append(f"Call {i}: {e}")

    if errors:
        print(f"ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  {e}")
        # Some errors are OK if they're due to policy blocks, but for M2 there's no policy yet
        if len(results) == 0:
            print("FAIL: no successful calls")
            sys.exit(1)

    print(f"Successful calls: {len(results)}")

    # Check the run summary
    req = urllib.request.Request(f"http://localhost:8000/api/runs/{RUN_ID}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        run = json.loads(resp.read().decode("utf-8"))

    call_count = run["call_count"]
    total_cost = run["total_cost"]

    print(f"Run call_count: {call_count}")
    print(f"Run total_cost: Rs{total_cost:.5f}")

    # Assertions
    assert call_count == n, f"Expected call_count={n}, got {call_count}"

    # Check total matches sum of individual call costs
    calls = run.get("calls", [])
    if calls:
        sum_actual = round(sum(c["actual"] for c in calls), 5)
        print(f"Sum of call actuals: Rs{sum_actual:.5f}")
        assert abs(total_cost - sum_actual) < 0.001, \
            f"Total {total_cost} != sum of calls {sum_actual}"

    # Restore default policies
    try:
        req = urllib.request.Request(
            "http://localhost:8000/api/policies",
            method="POST",
            data=json.dumps({"run_cap": 3.0, "pause_at": 2.0}).encode(),
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

    print(f"\n=== CONCURRENT TEST PASSED (call_count={call_count}, total=Rs{total_cost:.5f}) ===")


if __name__ == "__main__":
    main()
