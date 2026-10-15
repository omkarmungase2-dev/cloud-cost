"""
FastAPI application — the Cloud Cost Firewall proxy.
M6: Full pipeline with verdict.py headers, upstream-error handling,
models API, rule validation, playground route, and approvals.
"""

import os
import time
import httpx
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Request, Query, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse, RedirectResponse

from app.config import UPSTREAM_URL, UPSTREAM_KEY, DATABASE_URL, MAX_TOKENS_FIELD
from app.pricing import cost_of, estimate_cost, load_prices
from app.store import create_store
from app.policy import load_rules, save_rules, signature, decide
from app.db import create_db, Database, NoopDatabase
from app.approvals import request_approval
from app.verdict import build_verdict_headers


# ---------------------------------------------------------------------------
# App state (set during lifespan)
# ---------------------------------------------------------------------------
store = None
db = None
_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global store, db, _client
    _client = httpx.AsyncClient(timeout=200.0)
    store = await create_store()
    db = await create_db(DATABASE_URL)
    print(f"[firewall] Proxy ready. Upstream: {UPSTREAM_URL}")
    print(f"[firewall] Key set: {'yes' if UPSTREAM_KEY else 'no'}")
    print(f"[firewall] Store: {store.name}")
    print(f"[firewall] DB: {db.name}")
    yield
    if _client:
        await _client.aclose()
    if db:
        await db.close()


app = FastAPI(title="Cloud Cost Firewall", version="0.6.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Routes: Root & Playground (PRD §10)
# ---------------------------------------------------------------------------
@app.get("/")
async def root():
    return RedirectResponse(url="/playground")


@app.get("/playground")
async def playground():
    for rel_path in ["app/playground.html", "static/playground.html"]:
        p = os.path.join(os.path.dirname(os.path.dirname(__file__)), rel_path)
        if os.path.exists(p):
            return FileResponse(p)
    return HTMLResponse("<h1>Playground</h1><p>playground.html not found</p>")


@app.get("/approvals")
async def approvals_page():
    html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "approvals.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return HTMLResponse("<h1>Approvals page</h1><p>static/approvals.html not found</p>")


# ---------------------------------------------------------------------------
# Health check (PRD §10)
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "store": store.name if store else "not-configured",
        "db": db.name if db else "off",
        "telegram": False,
    }


# ---------------------------------------------------------------------------
# API: Models (PRD §10)
# ---------------------------------------------------------------------------
@app.get("/api/models")
async def api_models():
    prices = load_prices()
    models = []
    for model_id, rates in prices.items():
        if not model_id.startswith("_") and isinstance(rates, dict):
            models.append({
                "id": model_id,
                "in": rates.get("in", 0.0),
                "out": rates.get("out", 0.0),
            })
    return models


# ---------------------------------------------------------------------------
# API: Approvals (PRD §8, §10)
# ---------------------------------------------------------------------------
@app.get("/api/approvals")
async def api_get_approvals():
    return await store.list_pending()


@app.post("/api/approvals/{run_id}/approve")
async def api_approve(run_id: str, new_cap: Optional[float] = None):
    rules = load_rules()
    if new_cap is None:
        base_cap = rules.get("run_cap") or 3.0
        new_cap = float(base_cap) * 2.0
    applied = await store.decide_approval(run_id, ok=True, new_cap=new_cap, by="dashboard")
    return {"status": "approved" if applied else "not_pending", "new_cap": new_cap, "run_id": run_id}


@app.post("/api/approvals/{run_id}/deny")
async def api_deny(run_id: str):
    applied = await store.decide_approval(run_id, ok=False, by="dashboard")
    return {"status": "denied" if applied else "not_pending", "run_id": run_id}


# ---------------------------------------------------------------------------
# Core pipeline: POST /v1/chat/completions (PRD §5)
# ---------------------------------------------------------------------------
@app.post("/v1/chat/completions")
async def chat_completions(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()

    # Step 1: reject streaming
    if body.get("stream"):
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Streaming is not supported yet. Set stream: false.", "type": "cost_firewall"}},
        )

    # Read attribution headers
    run_id = request.headers.get("X-Run-Id", "no-run")
    user_id = request.headers.get("X-User-Id", "unknown")
    feature = request.headers.get("X-Feature", "unknown")
    model = body.get("model", "unknown")
    max_tokens = body.get("max_tokens", 200)
    messages = body.get("messages", [])

    # Step 2: load rules
    rules = load_rules()

    # Step 3: estimate cost
    last_out = await store.last_output_tokens(run_id)
    expected_out = last_out if last_out else max_tokens
    est, est_in, est_out = estimate_cost(model, messages, expected_out)

    # Step 4: get current totals
    run_total, run_calls = await store.get_totals(run_id)

    # Step 5: reserve estimate
    reserved_after = await store.reserve(run_id, est)

    # Step 6: bump loop signature
    sig = signature(messages)
    loop_count = await store.bump_signature(run_id, sig)

    # Step 7: user spend and cap override
    user_spent = await store.user_spend_today(user_id)
    cap_override = await store.get_cap_override(run_id)

    # Step 8: decide
    d = decide(
        rules,
        model=model, feature=feature, est=est,
        run_total=run_total, run_calls=run_calls,
        reserved_after=reserved_after, loop_count=loop_count,
        user_spent=user_spent, cap_override=cap_override,
    )

    action = d["action"]
    reason = d["reason"]
    projected = d["projected"]
    effective_model = d["model"]
    cap_val = cap_override or rules.get("run_cap")

    now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")

    # Step 9: PAUSE flow (PRD §5 step 9 & §8)
    if action == "PAUSE":
        await store.release(run_id, est)
        await store.log_event({
            "ts": time.time(), "time": now_str,
            "run_id": run_id, "user": user_id, "feature": feature,
            "call": run_calls + 1, "action": "PAUSE", "reason": reason,
            "model": model, "est": est, "total": run_total,
        })
        print(f"[firewall] PAUSE run={run_id} call={run_calls + 1} reason={reason}")

        info = {
            "run_id": run_id, "user": user_id, "feature": feature,
            "spent": run_total, "est": est, "projected": projected,
            "cap": rules.get("run_cap", 0.0), "reason": reason,
        }
        approval_res = await request_approval(store, db, _client, rules, info)
        status = approval_res.get("status")

        if status == "denied":
            await store.log_event({
                "ts": time.time(), "time": now_str,
                "run_id": run_id, "user": user_id, "feature": feature,
                "call": run_calls + 1, "action": "DENIED", "reason": "Admin denied approval request",
                "model": model, "est": est, "total": run_total,
            })
            background_tasks.add_task(
                db.save,
                {
                    "run_id": run_id, "user_id": user_id, "feature": feature,
                    "model": model, "input_tokens": est_in, "output_tokens": 0,
                    "estimated_cost": est, "actual_cost": 0.0, "latency_ms": 0.0,
                    "action": "DENIED", "reason": "Admin denied approval request",
                }
            )
            v_headers = build_verdict_headers(
                action="DENIED",
                reason="Admin denied approval request",
                est=est, projected=projected, run_total=run_total,
                cap=cap_val, model=model, call=run_calls + 1,
            )
            return JSONResponse(
                status_code=403,
                content={"error": {"message": "DENIED by Cost Firewall: Admin rejected approval", "type": "cost_firewall"}},
                headers=v_headers,
            )

        if status == "timeout":
            await store.log_event({
                "ts": time.time(), "time": now_str,
                "run_id": run_id, "user": user_id, "feature": feature,
                "call": run_calls + 1, "action": "TIMEOUT", "reason": "Approval request timed out",
                "model": model, "est": est, "total": run_total,
            })
            background_tasks.add_task(
                db.save,
                {
                    "run_id": run_id, "user_id": user_id, "feature": feature,
                    "model": model, "input_tokens": est_in, "output_tokens": 0,
                    "estimated_cost": est, "actual_cost": 0.0, "latency_ms": 0.0,
                    "action": "TIMEOUT", "reason": "Approval request timed out",
                }
            )
            v_headers = build_verdict_headers(
                action="TIMEOUT",
                reason="Approval request timed out",
                est=est, projected=projected, run_total=run_total,
                cap=cap_val, model=model, call=run_calls + 1,
            )
            return JSONResponse(
                status_code=408,
                content={"error": {"message": "TIMEOUT by Cost Firewall: Approval request timed out", "type": "cost_firewall"}},
                headers=v_headers,
            )

        # status == "approved"
        await store.log_event({
            "ts": time.time(), "time": now_str,
            "run_id": run_id, "user": user_id, "feature": feature,
            "call": run_calls + 1, "action": "APPROVED",
            "reason": f"Approved by {approval_res.get('decided_by', 'admin')}",
            "model": model, "est": est, "total": run_total,
        })
        cap_override = await store.get_cap_override(run_id)
        cap_val = cap_override or rules.get("run_cap")
        reserved_after = await store.reserve(run_id, est)

        # Re-decide with new cap_override (do not re-bump loop signature)
        d = decide(
            rules,
            model=model, feature=feature, est=est,
            run_total=run_total, run_calls=run_calls,
            reserved_after=reserved_after, loop_count=loop_count,
            user_spent=user_spent, cap_override=cap_override,
        )
        action = d["action"]
        reason = d["reason"]
        projected = d["projected"]
        effective_model = d["model"]

        if action == "BLOCK":
            await store.release(run_id, est)
            await store.log_event({
                "ts": time.time(), "time": now_str,
                "run_id": run_id, "user": user_id, "feature": feature,
                "call": run_calls + 1, "action": "BLOCK", "reason": reason,
                "model": model, "est": est, "total": run_total,
            })
            background_tasks.add_task(
                db.save,
                {
                    "run_id": run_id, "user_id": user_id, "feature": feature,
                    "model": model, "input_tokens": est_in, "output_tokens": 0,
                    "estimated_cost": est, "actual_cost": 0.0, "latency_ms": 0.0,
                    "action": "BLOCK", "reason": reason,
                }
            )
            v_headers = build_verdict_headers(
                action="BLOCK",
                reason=reason,
                est=est, projected=projected, run_total=run_total,
                cap=cap_val, model=model, call=run_calls + 1,
            )
            return JSONResponse(
                status_code=429,
                content={"error": {"message": f"BLOCKED by Cost Firewall: {reason}", "type": "cost_firewall"}},
                headers=v_headers,
            )

    # Step 10: BLOCK
    if action == "BLOCK":
        await store.release(run_id, est)
        await store.log_event({
            "ts": time.time(), "time": now_str,
            "run_id": run_id, "user": user_id, "feature": feature,
            "call": run_calls + 1, "action": "BLOCK", "reason": reason,
            "model": model, "est": est, "total": run_total,
        })
        background_tasks.add_task(
            db.save,
            {
                "run_id": run_id, "user_id": user_id, "feature": feature,
                "model": model, "input_tokens": est_in, "output_tokens": 0,
                "estimated_cost": est, "actual_cost": 0.0, "latency_ms": 0.0,
                "action": "BLOCK", "reason": reason,
            }
        )
        print(f"[firewall] BLOCK run={run_id} call={run_calls + 1} reason={reason}")
        v_headers = build_verdict_headers(
            action="BLOCK",
            reason=reason,
            est=est, projected=projected, run_total=run_total,
            cap=cap_val, model=model, call=run_calls + 1,
        )
        return JSONResponse(
            status_code=429,
            content={"error": {"message": f"BLOCKED by Cost Firewall: {reason}", "type": "cost_firewall"}},
            headers=v_headers,
        )

    # Step 11: DOWNGRADE — replace model in body
    if action == "DOWNGRADE":
        body["model"] = effective_model
        reason += f" ({model} -> {effective_model})"

    # Step 12: Rename max_tokens if MAX_TOKENS_FIELD differs
    if MAX_TOKENS_FIELD and MAX_TOKENS_FIELD != "max_tokens" and "max_tokens" in body:
        body[MAX_TOKENS_FIELD] = body.pop("max_tokens")

    # Forward to upstream
    fwd_headers = {
        "Content-Type": "application/json",
        "User-Agent": "CostFirewall/2.0",
    }
    if UPSTREAM_KEY:
        fwd_headers["Authorization"] = f"Bearer {UPSTREAM_KEY}"

    t0 = time.perf_counter()
    try:
        upstream_resp = await _client.post(UPSTREAM_URL, json=body, headers=fwd_headers)
    except httpx.HTTPError as e:
        print(f"[firewall] Upstream network error: {e}")
        await store.release(run_id, est)
        return JSONResponse(
            status_code=502,
            content={"error": {"message": f"Upstream unreachable: {e}", "type": "cost_firewall"}},
        )
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    # Step 13: Upstream error — pass through, no cost
    if upstream_resp.status_code >= 400:
        await store.release(run_id, est)
        v_headers = build_verdict_headers(
            action="UPSTREAM_ERROR",
            reason=f"Upstream returned HTTP {upstream_resp.status_code}",
            model=effective_model,
            latency_ms=latency_ms,
        )
        return JSONResponse(
            status_code=upstream_resp.status_code,
            content=upstream_resp.json(),
            headers=v_headers,
        )

    # Step 14: Compute actual cost, record call, release reservation
    resp_json = upstream_resp.json()
    usage = resp_json.get("usage", {})
    in_tokens = usage.get("prompt_tokens", 0)
    out_tokens = usage.get("completion_tokens", 0)
    actual = cost_of(effective_model, in_tokens, out_tokens)

    await store.add_call(run_id, user_id, feature, effective_model, in_tokens, out_tokens, est, actual, latency_ms)
    await store.release(run_id, est)

    new_total, new_calls = await store.get_totals(run_id)

    # Log event
    await store.log_event({
        "ts": time.time(), "time": now_str,
        "run_id": run_id, "user": user_id, "feature": feature,
        "call": new_calls, "action": action, "reason": reason,
        "model": effective_model, "est": est, "actual": actual, "total": new_total,
    })

    # Persist call in background to DB (PRD §5 step 15)
    background_tasks.add_task(
        db.save,
        {
            "run_id": run_id, "user_id": user_id, "feature": feature,
            "model": effective_model, "input_tokens": in_tokens, "output_tokens": out_tokens,
            "estimated_cost": est, "actual_cost": actual, "latency_ms": latency_ms,
            "action": action, "reason": reason,
        }
    )

    print(
        f"[firewall] {action} run={run_id} call={new_calls} model={effective_model} "
        f"est=Rs{est:.5f} actual=Rs{actual:.5f} total=Rs{new_total:.5f} latency={latency_ms}ms"
    )

    # Step 15: Return with verdict headers
    v_headers = build_verdict_headers(
        action=action,
        reason=reason,
        est=est,
        projected=projected,
        run_total=new_total,
        cap=cap_val,
        actual=actual,
        latency_ms=latency_ms,
        model=effective_model,
        call=new_calls,
    )

    return JSONResponse(
        status_code=upstream_resp.status_code,
        content=resp_json,
        headers=v_headers,
    )


# ---------------------------------------------------------------------------
# API: Runs
# ---------------------------------------------------------------------------
@app.get("/api/runs")
async def api_runs():
    return await store.all_runs()


@app.get("/api/runs/{run_id}")
async def api_run_detail(run_id: str):
    run = await store.get_run(run_id)
    if not run:
        return JSONResponse(status_code=404, content={"error": "run not found"})
    calls = await store.get_run_calls(run_id)
    return {**run, "calls": calls}


# ---------------------------------------------------------------------------
# API: User daily spend
# ---------------------------------------------------------------------------
@app.get("/api/users/{user}/today")
async def api_user_today(user: str):
    spent = await store.user_spend_today(user)
    return {"user": user, "spent_today": round(spent, 5)}


# ---------------------------------------------------------------------------
# API: Events
# ---------------------------------------------------------------------------
@app.get("/api/events")
async def api_events(limit: int = Query(50, ge=1, le=500)):
    return await store.get_events(limit)


# ---------------------------------------------------------------------------
# API: Stats
# ---------------------------------------------------------------------------
@app.get("/api/stats")
async def api_stats():
    events = await store.get_events(500)
    spent = 0.0
    allowed = 0
    blocked = 0
    saved = 0.0
    for ev in events:
        act = ev.get("action", "")
        if act in ("ALLOW", "WARN", "DOWNGRADE"):
            spent += ev.get("actual", 0)
            allowed += 1
        elif act in ("BLOCK", "DENIED", "TIMEOUT"):
            blocked += 1
            saved += ev.get("est", 0)
    return {
        "spent": round(spent, 5),
        "calls_allowed": allowed,
        "blocked": blocked,
        "saved_estimate": round(saved, 5),
    }


# ---------------------------------------------------------------------------
# API: Policies
# ---------------------------------------------------------------------------
@app.get("/api/policies")
async def api_get_policies():
    return load_rules()


@app.post("/api/policies")
async def api_set_policies(request: Request):
    body = await request.json()
    try:
        save_rules(body)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    return load_rules()


# ---------------------------------------------------------------------------
# API: History (PostgreSQL — PRD §10)
# ---------------------------------------------------------------------------
@app.get("/api/history/runs")
async def api_history_runs(limit: int = Query(50, ge=1, le=500)):
    if db.name == "off":
        return []
    sql = "SELECT run_id, user_id, feature, total_cost, call_count, blocked_count, status, started_at, last_at FROM runs ORDER BY started_at DESC LIMIT :limit"
    rows = await db.fetch(sql, limit=limit)
    for r in rows:
        if isinstance(r.get("started_at"), datetime):
            r["started_at"] = r["started_at"].isoformat()
        if isinstance(r.get("last_at"), datetime):
            r["last_at"] = r["last_at"].isoformat()
    return rows


@app.get("/api/history/requests")
async def api_history_requests(run_id: Optional[str] = None, limit: int = Query(50, ge=1, le=500)):
    if db.name == "off":
        return []
    # PRD §10: build WHERE clause in Python; do not pass NULL params to asyncpg
    if run_id:
        sql = "SELECT id, run_id, user_id, feature, model, input_tokens, output_tokens, estimated_cost, actual_cost, latency_ms, action, reason, created_at FROM requests WHERE run_id = :run_id ORDER BY created_at DESC LIMIT :limit"
        rows = await db.fetch(sql, run_id=run_id, limit=limit)
    else:
        sql = "SELECT id, run_id, user_id, feature, model, input_tokens, output_tokens, estimated_cost, actual_cost, latency_ms, action, reason, created_at FROM requests ORDER BY created_at DESC LIMIT :limit"
        rows = await db.fetch(sql, limit=limit)

    for r in rows:
        if isinstance(r.get("created_at"), datetime):
            r["created_at"] = r["created_at"].isoformat()
    return rows


@app.get("/api/history/summary")
async def api_history_summary():
    if db.name == "off":
        return {
            "by_feature": {},
            "by_user": {},
            "by_model": {},
            "blocked": {"count": 0, "saved_estimate": 0.0},
            "estimate_accuracy": {"avg_error_percent": 0.0, "avg_latency_ms": 0.0},
        }

    # Allowed requests aggregations (exclude BLOCK, DENIED, TIMEOUT)
    feat_rows = await db.fetch(
        "SELECT feature, COUNT(*) as calls, SUM(actual_cost) as total_cost "
        "FROM requests WHERE action NOT IN ('BLOCK', 'DENIED', 'TIMEOUT') "
        "GROUP BY feature"
    )
    by_feature = {
        r["feature"]: {"calls": r["calls"], "total_cost": round(float(r["total_cost"] or 0), 5)}
        for r in feat_rows
    }

    user_rows = await db.fetch(
        "SELECT user_id, COUNT(*) as calls, SUM(actual_cost) as total_cost "
        "FROM requests WHERE action NOT IN ('BLOCK', 'DENIED', 'TIMEOUT') "
        "GROUP BY user_id"
    )
    by_user = {
        r["user_id"]: {"calls": r["calls"], "total_cost": round(float(r["total_cost"] or 0), 5)}
        for r in user_rows
    }

    model_rows = await db.fetch(
        "SELECT model, COUNT(*) as calls, SUM(actual_cost) as total_cost "
        "FROM requests WHERE action NOT IN ('BLOCK', 'DENIED', 'TIMEOUT') "
        "GROUP BY model"
    )
    by_model = {
        r["model"]: {"calls": r["calls"], "total_cost": round(float(r["total_cost"] or 0), 5)}
        for r in model_rows
    }

    # Blocked requests
    block_rows = await db.fetch(
        "SELECT COUNT(*) as count, SUM(estimated_cost) as saved "
        "FROM requests WHERE action IN ('BLOCK', 'DENIED', 'TIMEOUT')"
    )
    b_cnt = block_rows[0]["count"] if block_rows else 0
    b_saved = block_rows[0]["saved"] if block_rows and block_rows[0]["saved"] else 0.0

    # Accuracy and latency for allowed requests with actual > 0
    acc_rows = await db.fetch(
        "SELECT estimated_cost, actual_cost, latency_ms "
        "FROM requests WHERE action NOT IN ('BLOCK', 'DENIED', 'TIMEOUT') AND actual_cost > 0"
    )
    if acc_rows:
        errors = [abs(r["estimated_cost"] - r["actual_cost"]) / r["actual_cost"] * 100 for r in acc_rows]
        latencies = [r["latency_ms"] for r in acc_rows]
        avg_err = round(sum(errors) / len(errors), 2)
        avg_lat = round(sum(latencies) / len(latencies), 1)
    else:
        avg_err = 0.0
        avg_lat = 0.0

    return {
        "by_feature": by_feature,
        "by_user": by_user,
        "by_model": by_model,
        "blocked": {"count": b_cnt, "saved_estimate": round(float(b_saved), 5)},
        "estimate_accuracy": {"avg_error_percent": avg_err, "avg_latency_ms": avg_lat},
    }


@app.get("/api/history/approvals")
async def api_history_approvals(limit: int = Query(50, ge=1, le=500)):
    if db.name == "off":
        return []
    sql = "SELECT id, run_id, user_id, feature, projected_cost, decision, decided_by, new_cap, wait_seconds, created_at FROM approvals ORDER BY created_at DESC LIMIT :limit"
    rows = await db.fetch(sql, limit=limit)
    for r in rows:
        if isinstance(r.get("created_at"), datetime):
            r["created_at"] = r["created_at"].isoformat()
    return rows


# ---------------------------------------------------------------------------
# API: Reset
# ---------------------------------------------------------------------------
@app.post("/api/reset")
async def api_reset(history: bool = False):
    await store.reset()
    if history and db:
        await db.reset()
    return {"status": "reset", "history": history}
