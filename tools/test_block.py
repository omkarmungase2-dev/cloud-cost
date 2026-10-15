"""
Integration test: send the same prompt 6 times.
Expected: first 3 succeed (200), calls 4-6 are blocked (429) by loop rule.
Also verifies a BLOCK event exists.
Needs: mock_llm.py on port 9000, firewall on port 8000.
"""

import json
import sys
import urllib.request
import urllib.error

FIREWALL_URL = "http://localhost:8000/v1/chat/completions"
EVENTS_URL = "http://localhost:8000/api/events?limit=50"
RUN_ID = "block-test-001"


def send_prompt(prompt: str, run_id: str) -> int:
    """Send one request and return the HTTP status code."""
    payload = json.dumps({
        "model": "mock-large",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 300,
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "X-Run-Id": run_id,
        "X-User-Id": "tester",
        "X-Feature": "test",
    }

    req = urllib.request.Request(FIREWALL_URL, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def main():
    # Reset state first
    try:
        req = urllib.request.Request("http://localhost:8000/api/reset", method="POST",
                                      data=b"", headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

    prompt = "Tell me a joke about cats"
    n = 6
    statuses = []

    print(f"Sending the same prompt {n} times on run {RUN_ID}...")
    for i in range(n):
        status = send_prompt(prompt, RUN_ID)
        statuses.append(status)
        print(f"  Call {i+1}: HTTP {status}")

    expected = [200, 200, 200, 429, 429, 429]
    print(f"\nStatuses:  {statuses}")
    print(f"Expected:  {expected}")
    assert statuses == expected, f"Statuses don't match: {statuses} != {expected}"

    # Check that a BLOCK event exists
    req = urllib.request.Request(EVENTS_URL)
    with urllib.request.urlopen(req, timeout=10) as resp:
        events = json.loads(resp.read().decode("utf-8"))

    block_events = [e for e in events if e.get("action") == "BLOCK"]
    assert len(block_events) > 0, "No BLOCK events found"
    print(f"\nBLOCK events found: {len(block_events)}")
    print(f"First BLOCK reason: {block_events[0].get('reason', '?')}")

    print(f"\n=== TEST_BLOCK PASSED ===")


if __name__ == "__main__":
    main()
