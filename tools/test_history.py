"""
Integration test for Milestone 4: PostgreSQL history logging.
Per PRD §14:
- Sends a loop run of 4 requests (3 allowed + 1 BLOCK)
- Verifies 4 rows in /api/history/requests for the run_id
- Verifies run summary in /api/history/runs: call_count=3, blocked_count=1, status='blocked'
- Verifies aggregate stats in /api/history/summary
"""

import sys
import time
import httpx

FIREWALL_URL = "http://localhost:8000"


def main():
    print("Testing Milestone 4: Database History Endpoints...")

    # 1. Check health
    with httpx.Client(timeout=10.0) as client:
        try:
            h_resp = client.get(f"{FIREWALL_URL}/health")
            health = h_resp.json()
            print(f"Firewall health: store={health.get('store')}, db={health.get('db')}")
        except Exception as e:
            print(f"Error: Firewall server not responding on {FIREWALL_URL}: {e}")
            sys.exit(1)

        if health.get("db") == "off":
            print("\n[NOTE] PostgreSQL is currently offline (health reports db: off).")
            print("To run with PostgreSQL:")
            print("  1. Start Docker Desktop")
            print("  2. Run: docker compose up -d")
            print("  3. Restart the firewall: uvicorn app.main:app --port 8000")
            print("\nChecking history endpoints with db off (should return graceful empty structures)...")
            runs_resp = client.get(f"{FIREWALL_URL}/api/history/runs")
            reqs_resp = client.get(f"{FIREWALL_URL}/api/history/requests")
            summ_resp = client.get(f"{FIREWALL_URL}/api/history/summary")
            assert runs_resp.status_code == 200, f"Expected 200, got {runs_resp.status_code}"
            assert reqs_resp.status_code == 200, f"Expected 200, got {reqs_resp.status_code}"
            assert summ_resp.status_code == 200, f"Expected 200, got {summ_resp.status_code}"
            print("Graceful off responses verified:")
            print("  /api/history/runs:", runs_resp.json())
            print("  /api/history/requests:", reqs_resp.json())
            print("  /api/history/summary:", summ_resp.json())
            print("\n=== HISTORY TEST GRACEFUL (DB OFF) VERIFIED ===")
            return

        # 2. Reset history
        reset_resp = client.post(f"{FIREWALL_URL}/api/reset?history=true")
        assert reset_resp.status_code == 200, f"Reset failed: {reset_resp.text}"

        # 3. Send 4 identical requests on run history-test-001
        run_id = f"hist-test-{int(time.time())}"
        headers = {
            "Content-Type": "application/json",
            "X-Run-Id": run_id,
            "X-User-Id": "alice",
            "X-Feature": "code-review",
        }
        body = {
            "model": "mock-large",
            "messages": [{"role": "user", "content": "Explain quicksort algorithm in detail."}],
            "max_tokens": 50,
        }

        print(f"\nSending 4 identical calls on run {run_id}...")
        statuses = []
        for i in range(1, 5):
            resp = client.post(f"{FIREWALL_URL}/v1/chat/completions", headers=headers, json=body)
            statuses.append(resp.status_code)
            action = resp.headers.get("X-Firewall-Action", "")
            print(f"  Call {i}: HTTP {resp.status_code} ({action})")

        assert statuses == [200, 200, 200, 429], f"Expected [200, 200, 200, 429], got {statuses}"

        # Wait for BackgroundTasks to persist to DB
        time.sleep(1.0)

        # 4. Verify /api/history/requests for this run_id
        reqs_resp = client.get(f"{FIREWALL_URL}/api/history/requests?run_id={run_id}")
        assert reqs_resp.status_code == 200
        reqs = reqs_resp.json()
        print(f"\nRequests in DB for run {run_id}: {len(reqs)}")
        assert len(reqs) == 4, f"Expected 4 requests in DB, got {len(reqs)}"

        actions = [r["action"] for r in reqs]
        assert "BLOCK" in actions, "Expected a BLOCK request in DB"
        block_rows = [r for r in reqs if r["action"] == "BLOCK"]
        allowed_rows = [r for r in reqs if r["action"] != "BLOCK"]
        assert len(block_rows) == 1, f"Expected 1 BLOCK, got {len(block_rows)}"
        assert len(allowed_rows) == 3, f"Expected 3 allowed, got {len(allowed_rows)}"
        print(f"  Actions verified: {actions}")

        # 5. Verify /api/history/runs
        runs_resp = client.get(f"{FIREWALL_URL}/api/history/runs")
        assert runs_resp.status_code == 200
        runs = runs_resp.json()
        matching_runs = [r for r in runs if r["run_id"] == run_id]
        assert len(matching_runs) == 1, f"Run {run_id} not found in runs table"
        run_row = matching_runs[0]
        print(f"\nRun row: {run_row}")
        assert run_row["call_count"] == 3, f"Expected call_count=3, got {run_row['call_count']}"
        assert run_row["blocked_count"] == 1, f"Expected blocked_count=1, got {run_row['blocked_count']}"
        assert run_row["status"] == "blocked", f"Expected status='blocked', got {run_row['status']}"
        assert run_row["user_id"] == "alice"
        assert run_row["feature"] == "code-review"

        # 6. Verify /api/history/summary
        sum_resp = client.get(f"{FIREWALL_URL}/api/history/summary")
        assert sum_resp.status_code == 200
        summary = sum_resp.json()
        print(f"\nSummary: {summary}")
        assert summary["blocked"]["count"] >= 1, "Expected blocked.count >= 1"
        assert summary["blocked"]["saved_estimate"] > 0, "Expected blocked.saved_estimate > 0"
        assert "code-review" in summary["by_feature"]
        assert "alice" in summary["by_user"]
        assert "mock-large" in summary["by_model"]

        print("\n=== TEST_HISTORY PASSED (4 rows, run summary correct, aggregates verified) ===")


if __name__ == "__main__":
    main()
