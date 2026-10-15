"""
Approval module (PRD §8):
Handles the PAUSE flow, polling Redis/MemoryStore for admin decisions,
sending notifications via Telegram, and persisting approvals to Postgres.
"""

import time
import asyncio
from typing import Dict, Any, Optional
import httpx

from app import telegram


async def request_approval(
    store,
    db,
    client: Optional[httpx.AsyncClient],
    rules: Dict[str, Any],
    info: Dict[str, Any],
) -> Dict[str, Any]:
    """
    1. store.create_approval(run_id, info)
    2. telegram.notify(...) (no-op if not configured)
    3. Poll store.get_approval every 0.5 s until status != pending or timeout
    4. Save approval row in DB with wait_seconds
    5. Return the approval dict
    """
    run_id = info["run_id"]
    await store.create_approval(run_id, info)
    await telegram.notify(client, info)

    timeout_seconds = float(rules.get("pause_timeout_seconds") or 120)
    poll_interval = 0.5
    start_time = time.perf_counter()

    while True:
        elapsed = time.perf_counter() - start_time
        approval = await store.get_approval(run_id)
        if not approval or approval.get("status") != "pending":
            break

        if elapsed >= timeout_seconds:
            await store.decide_approval(run_id, None, by="timeout")
            approval = await store.get_approval(run_id)
            break

        await asyncio.sleep(poll_interval)

    wait_seconds = round(time.perf_counter() - start_time, 2)

    if db and hasattr(db, "save_approval"):
        await db.save_approval({
            "run_id": run_id,
            "user_id": info.get("user", "unknown"),
            "feature": info.get("feature", "unknown"),
            "projected_cost": info.get("projected", 0.0),
            "decision": approval.get("status", "timeout") if approval else "timeout",
            "decided_by": approval.get("decided_by", "system") if approval else "timeout",
            "new_cap": approval.get("new_cap") if approval else None,
            "wait_seconds": wait_seconds,
        })

    return approval or {"status": "timeout"}
