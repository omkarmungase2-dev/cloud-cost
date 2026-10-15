"""
State store: Redis (primary) with in-memory fallback.
Both classes expose identical async interfaces so the rest of the app
does not care which one is active.

Redis keys use 24h TTL (48h for user daily spend).
"""

import json
import time
import asyncio
from datetime import datetime, timezone
from collections import defaultdict

# ---------------------------------------------------------------------------
# MemoryStore — fallback when Redis is down
# ---------------------------------------------------------------------------

class MemoryStore:
    """In-memory store. Same interface as RedisStore but no persistence."""

    name = "memory"

    def __init__(self):
        self._runs = {}          # run_id -> {run_id, user, feature, started_at, total_cost, est_total, call_count}
        self._calls = defaultdict(list)   # run_id -> [call records]
        self._sigs = defaultdict(lambda: defaultdict(int))  # run_id -> {sig: count}
        self._reserved = defaultdict(float)  # run_id -> reserved amount
        self._caps = {}          # run_id -> cap override
        self._user_daily = defaultdict(float)  # "user:date" -> spend
        self._events = []        # newest first
        self._approvals = {}     # run_id -> approval hash
        self._lock = asyncio.Lock()

    async def get_run(self, run_id: str) -> dict | None:
        return self._runs.get(run_id)

    async def last_output_tokens(self, run_id: str) -> int | None:
        """Return the output tokens of the last call in this run, or None."""
        calls = self._calls.get(run_id, [])
        if calls:
            return calls[-1].get("out_tokens")
        return None

    async def add_call(self, run_id, user, feature, model, tin, tout, est, actual, latency_ms):
        """Record a completed call. Updates all run counters atomically."""
        async with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            if run_id not in self._runs:
                self._runs[run_id] = {
                    "run_id": run_id, "user": user, "feature": feature,
                    "started_at": now, "total_cost": 0.0, "est_total": 0.0, "call_count": 0,
                }
            run = self._runs[run_id]
            run["total_cost"] = round(run["total_cost"] + actual, 5)
            run["est_total"] = round(run["est_total"] + est, 5)
            run["call_count"] += 1

            call_rec = {
                "run_id": run_id, "user": user, "feature": feature, "model": model,
                "in_tokens": tin, "out_tokens": tout,
                "est": round(est, 5), "actual": round(actual, 5),
                "latency_ms": round(latency_ms, 1), "ts": now,
            }
            self._calls[run_id].append(call_rec)

            # Update per-user daily spend
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            key = f"{user}:{day}"
            self._user_daily[key] = round(self._user_daily[key] + actual, 5)

    async def all_runs(self) -> list[dict]:
        return list(self._runs.values())

    async def user_spend_today(self, user: str) -> float:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._user_daily.get(f"{user}:{day}", 0.0)

    async def get_totals(self, run_id: str) -> tuple[float, int]:
        """Return (total_cost, call_count) for a run."""
        run = self._runs.get(run_id)
        if run:
            return run["total_cost"], run["call_count"]
        return 0.0, 0

    async def reserve(self, run_id: str, est: float) -> float:
        """Add est to the reserved pool and return the new total reserved."""
        async with self._lock:
            self._reserved[run_id] = round(self._reserved[run_id] + est, 5)
            return self._reserved[run_id]

    async def release(self, run_id: str, est: float):
        """Remove est from the reserved pool."""
        async with self._lock:
            self._reserved[run_id] = round(max(0, self._reserved[run_id] - est), 5)

    async def bump_signature(self, run_id: str, sig: str) -> int:
        """Increment and return the count for this signature in this run."""
        async with self._lock:
            self._sigs[run_id][sig] += 1
            return self._sigs[run_id][sig]

    async def log_event(self, ev: dict):
        """Prepend an event (newest first), trim to 500."""
        ev = {k: round(v, 5) if isinstance(v, float) else v for k, v in ev.items()}
        self._events.insert(0, ev)
        self._events = self._events[:500]

    async def get_events(self, limit: int = 50) -> list[dict]:
        return self._events[:limit]

    async def create_approval(self, run_id: str, info: dict):
        """Create a pending approval record."""
        self._approvals[run_id] = {
            "status": "pending",
            "new_cap": None,
            "decided_by": None,
            "requested_at": datetime.now(timezone.utc).isoformat(),
            **info,
        }

    async def get_approval(self, run_id: str) -> dict | None:
        return self._approvals.get(run_id)

    async def list_pending(self) -> list[dict]:
        return [a for a in self._approvals.values() if a.get("status") == "pending"]

    async def decide_approval(self, run_id: str, ok: bool | None, new_cap: float | None = None, by: str = "dashboard") -> bool:
        """
        Decide a pending approval.
        ok=True -> approved, ok=False -> denied, ok=None -> timeout.
        Returns True if applied (was pending), False otherwise.
        """
        a = self._approvals.get(run_id)
        if not a or a["status"] != "pending":
            return False
        if ok is True:
            a["status"] = "approved"
            a["decided_by"] = by
            if new_cap is not None:
                a["new_cap"] = new_cap
                self._caps[run_id] = new_cap
        elif ok is False:
            a["status"] = "denied"
            a["decided_by"] = by
        else:
            a["status"] = "timeout"
            a["decided_by"] = "timeout"
        return True

    async def get_cap_override(self, run_id: str) -> float | None:
        cap = self._caps.get(run_id)
        return float(cap) if cap is not None else None

    async def get_run_calls(self, run_id: str) -> list[dict]:
        """Return all call records for a run."""
        return self._calls.get(run_id, [])

    async def reset(self):
        """Clear all live data."""
        self._runs.clear()
        self._calls.clear()
        self._sigs.clear()
        self._reserved.clear()
        self._caps.clear()
        self._user_daily.clear()
        self._events.clear()
        self._approvals.clear()


# ---------------------------------------------------------------------------
# RedisStore — primary store when Redis is available
# ---------------------------------------------------------------------------

class RedisStore:
    """Redis-backed store. All counters use atomic operations."""

    name = "redis"

    def __init__(self, client):
        self._r = client  # redis.asyncio.Redis instance

    async def get_run(self, run_id: str) -> dict | None:
        data = await self._r.hgetall(f"run:{run_id}")
        if not data:
            return None
        return {
            "run_id": data.get("run_id", run_id),
            "user": data.get("user", "unknown"),
            "feature": data.get("feature", "unknown"),
            "started_at": data.get("started_at", ""),
            "total_cost": float(data.get("total_cost", 0)),
            "est_total": float(data.get("est_total", 0)),
            "call_count": int(data.get("call_count", 0)),
        }

    async def last_output_tokens(self, run_id: str) -> int | None:
        """Return the output tokens of the last call in this run."""
        raw = await self._r.lindex(f"run:{run_id}:calls", -1)
        if raw:
            rec = json.loads(raw)
            return rec.get("out_tokens")
        return None

    async def add_call(self, run_id, user, feature, model, tin, tout, est, actual, latency_ms):
        """Record a call using a transactional pipeline (MULTI/EXEC)."""
        now = datetime.now(timezone.utc).isoformat()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        call_rec = json.dumps({
            "run_id": run_id, "user": user, "feature": feature, "model": model,
            "in_tokens": tin, "out_tokens": tout,
            "est": round(est, 5), "actual": round(actual, 5),
            "latency_ms": round(latency_ms, 1), "ts": now,
        })

        pipe = self._r.pipeline(transaction=True)
        key = f"run:{run_id}"
        # Create/update run hash
        pipe.hsetnx(key, "run_id", run_id)
        pipe.hsetnx(key, "user", user)
        pipe.hsetnx(key, "feature", feature)
        pipe.hsetnx(key, "started_at", now)
        pipe.hincrbyfloat(key, "total_cost", round(actual, 5))
        pipe.hincrbyfloat(key, "est_total", round(est, 5))
        pipe.hincrby(key, "call_count", 1)
        pipe.expire(key, 86400)
        # Append call record
        pipe.rpush(f"run:{run_id}:calls", call_rec)
        pipe.expire(f"run:{run_id}:calls", 86400)
        # Per-user daily spend
        user_key = f"user:{user}:{day}"
        pipe.incrbyfloat(user_key, round(actual, 5))
        pipe.expire(user_key, 172800)  # 48h
        await pipe.execute()

    async def all_runs(self) -> list[dict]:
        """Scan for run:* keys, skipping sub-keys (those with more than one colon)."""
        runs = []
        async for key_bytes in self._r.scan_iter("run:*", count=200):
            key = key_bytes if isinstance(key_bytes, str) else key_bytes.decode()
            # Skip sub-keys like run:xxx:calls, run:xxx:sig, etc.
            after_prefix = key[4:]  # remove "run:"
            if ":" in after_prefix:
                continue
            run_id = after_prefix
            run = await self.get_run(run_id)
            if run:
                runs.append(run)
        return runs

    async def user_spend_today(self, user: str) -> float:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        val = await self._r.get(f"user:{user}:{day}")
        return float(val) if val else 0.0

    async def get_totals(self, run_id: str) -> tuple[float, int]:
        data = await self._r.hmget(f"run:{run_id}", "total_cost", "call_count")
        cost = float(data[0]) if data[0] else 0.0
        count = int(data[1]) if data[1] else 0
        return cost, count

    async def reserve(self, run_id: str, est: float) -> float:
        """Atomically add est to reserved and return new total."""
        val = await self._r.incrbyfloat(f"run:{run_id}:reserved", round(est, 5))
        await self._r.expire(f"run:{run_id}:reserved", 86400)
        return float(val)

    async def release(self, run_id: str, est: float):
        val = await self._r.incrbyfloat(f"run:{run_id}:reserved", -round(est, 5))
        # Clamp to 0
        if float(val) < 0:
            await self._r.set(f"run:{run_id}:reserved", "0")
            await self._r.expire(f"run:{run_id}:reserved", 86400)

    async def bump_signature(self, run_id: str, sig: str) -> int:
        val = await self._r.hincrby(f"run:{run_id}:sig", sig, 1)
        await self._r.expire(f"run:{run_id}:sig", 86400)
        return int(val)

    async def log_event(self, ev: dict):
        ev = {k: round(v, 5) if isinstance(v, float) else v for k, v in ev.items()}
        await self._r.lpush("events", json.dumps(ev))
        await self._r.ltrim("events", 0, 499)

    async def get_events(self, limit: int = 50) -> list[dict]:
        raw = await self._r.lrange("events", 0, limit - 1)
        return [json.loads(r) for r in raw]

    async def create_approval(self, run_id: str, info: dict):
        data = {
            "status": "pending",
            "new_cap": "",
            "decided_by": "",
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }
        data.update({k: str(v) if v is not None else "" for k, v in info.items()})
        await self._r.hset(f"approval:{run_id}", mapping=data)
        await self._r.expire(f"approval:{run_id}", 3600)

    async def get_approval(self, run_id: str) -> dict | None:
        data = await self._r.hgetall(f"approval:{run_id}")
        if not data:
            return None
        result = {}
        for k, v in data.items():
            key = k if isinstance(k, str) else k.decode()
            val = v if isinstance(v, str) else v.decode()
            result[key] = val
        # Convert numeric fields
        if result.get("new_cap") and result["new_cap"] != "":
            try:
                result["new_cap"] = float(result["new_cap"])
            except ValueError:
                result["new_cap"] = None
        else:
            result["new_cap"] = None
        return result

    async def list_pending(self) -> list[dict]:
        pending = []
        async for key_bytes in self._r.scan_iter("approval:*", count=200):
            key = key_bytes if isinstance(key_bytes, str) else key_bytes.decode()
            run_id = key.split(":", 1)[1]
            a = await self.get_approval(run_id)
            if a and a.get("status") == "pending":
                pending.append(a)
        return pending

    async def decide_approval(self, run_id: str, ok: bool | None, new_cap: float | None = None, by: str = "dashboard") -> bool:
        a = await self.get_approval(run_id)
        if not a or a.get("status") != "pending":
            return False
        updates = {"decided_by": by}
        if ok is True:
            updates["status"] = "approved"
            if new_cap is not None:
                updates["new_cap"] = str(new_cap)
                await self._r.set(f"run:{run_id}:cap", str(new_cap))
                await self._r.expire(f"run:{run_id}:cap", 86400)
        elif ok is False:
            updates["status"] = "denied"
        else:
            updates["status"] = "timeout"
            updates["decided_by"] = "timeout"
        await self._r.hset(f"approval:{run_id}", mapping=updates)
        return True

    async def get_cap_override(self, run_id: str) -> float | None:
        val = await self._r.get(f"run:{run_id}:cap")
        if val:
            return float(val)
        return None

    async def get_run_calls(self, run_id: str) -> list[dict]:
        raw = await self._r.lrange(f"run:{run_id}:calls", 0, -1)
        return [json.loads(r) for r in raw]

    async def reset(self):
        """Flush all keys (careful: this wipes everything in the Redis DB)."""
        await self._r.flushdb()


# ---------------------------------------------------------------------------
# Factory: try Redis, fall back to memory
# ---------------------------------------------------------------------------

async def create_store() -> MemoryStore | RedisStore:
    """
    Try to connect to Redis (3 attempts, 1.5s apart).
    Fall back to MemoryStore with a loud warning.
    """
    import redis.asyncio as aioredis
    from app.config import REDIS_URL

    for attempt in range(1, 4):
        try:
            client = aioredis.from_url(REDIS_URL, decode_responses=True)
            await client.ping()
            print(f"[store] Connected to Redis ({REDIS_URL})")
            return RedisStore(client)
        except Exception as e:
            print(f"[store] Redis attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                await asyncio.sleep(1.5)

    print("[store] WARNING: Redis unavailable — using in-memory store. Data will be lost on restart!")
    return MemoryStore()
