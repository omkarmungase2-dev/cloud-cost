"""
Unit tests for approval logic (app/approvals.py and app/store.py).
Per PRD §14:
- Uses MemoryStore and a fake DB (no server needed).
- Asserts:
  1. approve sets cap override 6.0 and status 'approved'
  2. deny leaves no cap override and status 'denied'
  3. timeout works when elapsed >= pause_timeout_seconds
"""

import sys
import os
import asyncio

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.store import MemoryStore
from app.approvals import request_approval


class FakeDB:
    def __init__(self):
        self.saved_approvals = []

    async def save_approval(self, rec):
        self.saved_approvals.append(rec)


async def test_approve_flow():
    store = MemoryStore()
    db = FakeDB()
    run_id = "test-approve-run"
    rules = {"run_cap": 3.0, "pause_timeout_seconds": 5}
    info = {
        "run_id": run_id,
        "user": "alice",
        "feature": "chat",
        "spent": 1.5,
        "est": 1.0,
        "projected": 2.5,
        "cap": 3.0,
        "reason": "Test pause",
    }

    # Simulate admin approving after 0.2 seconds with new_cap=6.0
    async def admin_approve():
        await asyncio.sleep(0.2)
        applied = await store.decide_approval(run_id, ok=True, new_cap=6.0, by="tester")
        assert applied is True, "Expected decide_approval to succeed"

    admin_task = asyncio.create_task(admin_approve())
    res = await request_approval(store, db, None, rules, info)
    await admin_task

    assert res["status"] == "approved", f"Expected status 'approved', got {res.get('status')}"
    assert res.get("new_cap") == 6.0, f"Expected new_cap 6.0, got {res.get('new_cap')}"
    override = await store.get_cap_override(run_id)
    assert override == 6.0, f"Expected cap override 6.0 in store, got {override}"
    assert len(db.saved_approvals) == 1, "Expected 1 approval saved in DB"
    assert db.saved_approvals[0]["decision"] == "approved"
    assert db.saved_approvals[0]["new_cap"] == 6.0
    print("PASS: test_approve_flow (cap override 6.0 set, status approved)")


async def test_deny_flow():
    store = MemoryStore()
    db = FakeDB()
    run_id = "test-deny-run"
    rules = {"run_cap": 3.0, "pause_timeout_seconds": 5}
    info = {
        "run_id": run_id,
        "user": "bob",
        "feature": "search",
        "spent": 2.1,
        "est": 0.5,
        "projected": 2.6,
        "cap": 3.0,
        "reason": "Test pause",
    }

    async def admin_deny():
        await asyncio.sleep(0.2)
        applied = await store.decide_approval(run_id, ok=False, by="tester")
        assert applied is True

    admin_task = asyncio.create_task(admin_deny())
    res = await request_approval(store, db, None, rules, info)
    await admin_task

    assert res["status"] == "denied", f"Expected status 'denied', got {res.get('status')}"
    override = await store.get_cap_override(run_id)
    assert override is None, f"Expected no cap override, got {override}"
    assert len(db.saved_approvals) == 1
    assert db.saved_approvals[0]["decision"] == "denied"
    assert db.saved_approvals[0]["new_cap"] is None
    print("PASS: test_deny_flow (no cap override, status denied)")


async def test_timeout_flow():
    store = MemoryStore()
    db = FakeDB()
    run_id = "test-timeout-run"
    rules = {"run_cap": 3.0, "pause_timeout_seconds": 1}  # 1 second timeout
    info = {
        "run_id": run_id,
        "user": "charlie",
        "feature": "coder",
        "spent": 2.2,
        "est": 0.6,
        "projected": 2.8,
        "cap": 3.0,
        "reason": "Test pause timeout",
    }

    # No admin decision made; let it timeout
    res = await request_approval(store, db, None, rules, info)

    assert res["status"] == "timeout", f"Expected status 'timeout', got {res.get('status')}"
    override = await store.get_cap_override(run_id)
    assert override is None, f"Expected no cap override on timeout, got {override}"
    assert len(db.saved_approvals) == 1
    assert db.saved_approvals[0]["decision"] == "timeout"
    assert db.saved_approvals[0]["wait_seconds"] >= 0.9
    print("PASS: test_timeout_flow (timed out as expected, status timeout)")


async def main():
    print("Running approval logic unit tests (no server needed)...")
    await test_approve_flow()
    await test_deny_flow()
    await test_timeout_flow()
    print("\n=== ALL APPROVAL LOGIC TESTS PASSED ===")


if __name__ == "__main__":
    asyncio.run(main())
