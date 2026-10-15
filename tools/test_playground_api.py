"""
Integration test for Milestone 6: Playground API.
Per PRD §14:
- Asserts /playground returns 200
- Asserts /api/models returns valid models with in/out rates (excluding keys starting with _)
- Asserts POST /api/policies valid updates succeed, invalid returns 400
- Asserts POST /v1/chat/completions includes all verdict headers:
  X-Firewall-Action, X-Firewall-Reason, X-Firewall-Estimate, X-Firewall-Projected,
  X-Firewall-Run-Total, X-Firewall-Cap, X-Firewall-Cost, X-Firewall-Latency-Ms,
  X-Firewall-Model, X-Firewall-Call
"""

import sys
import httpx

FIREWALL_URL = "http://localhost:8000"


def test_playground_route(client: httpx.Client):
    resp = client.get(f"{FIREWALL_URL}/playground")
    assert resp.status_code == 200, f"Expected 200 for /playground, got {resp.status_code}"
    print("PASS: /playground returned 200")


def test_models_endpoint(client: httpx.Client):
    resp = client.get(f"{FIREWALL_URL}/api/models")
    assert resp.status_code == 200, f"Expected 200 for /api/models, got {resp.status_code}"
    models = resp.json()
    assert isinstance(models, list), "Expected list of models"
    assert len(models) >= 2, f"Expected at least 2 models, got {len(models)}"
    for m in models:
        assert not m["id"].startswith("_"), f"Found comment key in models: {m['id']}"
        assert "in" in m and "out" in m, f"Missing in/out rate in model {m}"
    model_ids = [m["id"] for m in models]
    assert "mock-large" in model_ids, "mock-large not found in models"
    print(f"PASS: /api/models returned {len(models)} models: {model_ids}")


def test_policies_validation(client: httpx.Client):
    # 1. Invalid: negative value
    bad_resp1 = client.post(f"{FIREWALL_URL}/api/policies", json={"run_cap": -1.0})
    assert bad_resp1.status_code == 400, f"Expected 400 for negative cap, got {bad_resp1.status_code}"

    # 2. Invalid: unknown key
    bad_resp2 = client.post(f"{FIREWALL_URL}/api/policies", json={"unknown_rule": 5.0})
    assert bad_resp2.status_code == 400, f"Expected 400 for unknown rule, got {bad_resp2.status_code}"

    # 3. Valid update
    good_resp = client.post(f"{FIREWALL_URL}/api/policies", json={"warn_at": 1.25})
    assert good_resp.status_code == 200, f"Expected 200 for valid update, got {good_resp.status_code}"
    updated = good_resp.json()
    assert updated.get("warn_at") == 1.25, f"Expected warn_at=1.25, got {updated.get('warn_at')}"

    # Reset warn_at back to 1.0
    client.post(f"{FIREWALL_URL}/api/policies", json={"warn_at": 1.0})
    print("PASS: POST /api/policies properly accepted valid and rejected invalid (400) updates")


def test_verdict_headers(client: httpx.Client):
    client.post(f"{FIREWALL_URL}/api/reset")
    run_id = "test-verdict-run-001"
    headers = {
        "Content-Type": "application/json",
        "X-Run-Id": run_id,
        "X-User-Id": "tester",
        "X-Feature": "verdict-test",
    }
    body = {
        "model": "mock-large",
        "messages": [{"role": "user", "content": "Hello world"}],
        "max_tokens": 50,
    }

    resp = client.post(f"{FIREWALL_URL}/v1/chat/completions", headers=headers, json=body)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    required_headers = [
        "X-Firewall-Action",
        "X-Firewall-Reason",
        "X-Firewall-Estimate",
        "X-Firewall-Projected",
        "X-Firewall-Run-Total",
        "X-Firewall-Cap",
        "X-Firewall-Cost",
        "X-Firewall-Latency-Ms",
        "X-Firewall-Model",
        "X-Firewall-Call",
    ]

    for h in required_headers:
        assert h in resp.headers, f"Missing required verdict header: {h}"
        val = resp.headers[h]
        assert val is not None and val != "", f"Verdict header {h} is empty"

    print("PASS: All required X-Firewall-* verdict headers verified:")
    for h in required_headers:
        print(f"  {h}: {resp.headers[h]}")


def main():
    print("Testing Milestone 6: Playground API & Verdict Headers...")
    with httpx.Client(timeout=10.0) as client:
        test_playground_route(client)
        test_models_endpoint(client)
        test_policies_validation(client)
        test_verdict_headers(client)

    print("\n=== TEST_PLAYGROUND_API PASSED ===")


if __name__ == "__main__":
    main()
