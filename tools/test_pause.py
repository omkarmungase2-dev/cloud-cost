"""
Integration test for Milestone 5: PAUSE flow.
Per PRD §13 & §14:
- Big prompt ("word " * 3200) costs est ~Rs 2.3, above pause_at (2.0) and below run_cap (3.0)
- Triggers PAUSE
- On approve (new cap 6.0): request completes with HTTP 200
- On deny: request completes with HTTP 403
Needs: mock_llm on port 9000, firewall on port 8000.
"""

import sys
import time
import threading
import httpx

FIREWALL_URL = "http://localhost:8000"


def test_approve():
    run_id = f"pause-appr-{int(time.time())}"
    prompt = "word " * 3200  # ~4000 tokens, estimates ~Rs 2.3 with mock-large

    # Background thread to wait for pending approval, then approve it
    def approver():
        time.sleep(0.5)
        with httpx.Client(timeout=10.0) as client:
            for _ in range(20):
                resp = client.get(f"{FIREWALL_URL}/api/approvals")
                if resp.status_code == 200 and resp.json():
                    items = resp.json()
                    match = [x for x in items if x.get("run_id") == run_id]
                    if match:
                        appr_resp = client.post(f"{FIREWALL_URL}/api/approvals/{run_id}/approve?new_cap=6.0")
                        assert appr_resp.status_code == 200
                        print(f"  [approver] Approved run {run_id} with new_cap=6.0")
                        return
                time.sleep(0.3)
            print(f"  [approver] WARNING: Did not find pending approval for {run_id}")

    t = threading.Thread(target=approver)
    t.start()

    print(f"\n1. Testing PAUSE -> APPROVE on run {run_id}...")
    headers = {
        "Content-Type": "application/json",
        "X-Run-Id": run_id,
        "X-User-Id": "alice",
        "X-Feature": "big-doc",
    }
    body = {
        "model": "mock-large",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 100,
    }

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{FIREWALL_URL}/v1/chat/completions", headers=headers, json=body)
        t.join()

        print(f"  Response HTTP: {resp.status_code}")
        print(f"  Action header: {resp.headers.get('X-Firewall-Action')}")
        print(f"  Cap header: {resp.headers.get('X-Firewall-Cap')}")

        assert resp.status_code == 200, f"Expected HTTP 200 on approve, got {resp.status_code}"
        assert resp.headers.get("X-Firewall-Action") in ("ALLOW", "WARN"), f"Unexpected action: {resp.headers.get('X-Firewall-Action')}"
        assert resp.headers.get("X-Firewall-Cap") == "6.0", f"Expected Cap 6.0, got {resp.headers.get('X-Firewall-Cap')}"
        print("  PASS: PAUSE -> APPROVE returned HTTP 200 with new cap!")


def test_deny():
    run_id = f"pause-deny-{int(time.time())}"
    prompt = "word " * 3200

    def denier():
        time.sleep(0.5)
        with httpx.Client(timeout=10.0) as client:
            for _ in range(20):
                resp = client.get(f"{FIREWALL_URL}/api/approvals")
                if resp.status_code == 200 and resp.json():
                    items = resp.json()
                    match = [x for x in items if x.get("run_id") == run_id]
                    if match:
                        deny_resp = client.post(f"{FIREWALL_URL}/api/approvals/{run_id}/deny")
                        assert deny_resp.status_code == 200
                        print(f"  [denier] Denied run {run_id}")
                        return
                time.sleep(0.3)
            print(f"  [denier] WARNING: Did not find pending approval for {run_id}")

    t = threading.Thread(target=denier)
    t.start()

    print(f"\n2. Testing PAUSE -> DENY on run {run_id}...")
    headers = {
        "Content-Type": "application/json",
        "X-Run-Id": run_id,
        "X-User-Id": "bob",
        "X-Feature": "big-doc",
    }
    body = {
        "model": "mock-large",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 100,
    }

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{FIREWALL_URL}/v1/chat/completions", headers=headers, json=body)
        t.join()

        print(f"  Response HTTP: {resp.status_code}")
        print(f"  Action header: {resp.headers.get('X-Firewall-Action')}")
        assert resp.status_code == 403, f"Expected HTTP 403 on deny, got {resp.status_code}"
        assert resp.headers.get("X-Firewall-Action") == "DENIED"
        print("  PASS: PAUSE -> DENY returned HTTP 403 with DENIED action!")


def main():
    print("Testing Milestone 5: PAUSE Integration Flow...")
    # Reset firewall first
    with httpx.Client(timeout=5.0) as client:
        client.post(f"{FIREWALL_URL}/api/reset")

    test_approve()
    test_deny()
    print("\n=== TEST_PAUSE PASSED (Approve=200, Deny=403) ===")


if __name__ == "__main__":
    main()
