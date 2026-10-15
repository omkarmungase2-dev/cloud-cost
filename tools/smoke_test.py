"""
Smoke test: sends one request through the firewall and verifies it works.
Needs: mock_llm.py running on port 9000, firewall on port 8000.
"""

import json
import sys
import urllib.request

FIREWALL_URL = "http://localhost:8000/v1/chat/completions"


def main():
    payload = json.dumps({
        "model": "mock-large",
        "messages": [{"role": "user", "content": "Hello, how are you?"}],
        "max_tokens": 300,
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "X-Run-Id": "smoke-001",
        "X-User-Id": "tester",
        "X-Feature": "smoke-test",
    }

    req = urllib.request.Request(FIREWALL_URL, data=payload, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"FAIL: HTTP {e.code}")
        print(e.read().decode("utf-8"))
        sys.exit(1)
    except Exception as e:
        print(f"FAIL: {e}")
        print("Make sure mock_llm.py (port 9000) and the firewall (port 8000) are running.")
        sys.exit(1)

    # Assertions
    assert status == 200, f"Expected 200, got {status}"
    assert "usage" in body, "Response missing 'usage' field"
    assert "choices" in body, "Response missing 'choices' field"

    usage = body["usage"]
    reply = body["choices"][0]["message"]["content"]

    print(f"Status: {status}")
    print(f"Model:  {body.get('model', '?')}")
    print(f"Usage:  prompt_tokens={usage['prompt_tokens']}, completion_tokens={usage['completion_tokens']}")
    print(f"Reply:  {reply[:80]}...")
    print("\n=== SMOKE TEST PASSED ===")


if __name__ == "__main__":
    main()
