# 🛡️ Cloud Cost Firewall

A high-performance reverse-proxy firewall that sits between your AI agents and LLM providers to enforce **hard budgets, loop prevention, spending caps, and human-in-the-loop approvals in real time**.

---

## ⚡ The Problem

Autonomous AI agents can easily enter runaway recursive loops, make redundant calls, or process massive unexpected contexts. A single unconstrained agent script can burn hundreds of dollars in hours without human intervention.

## 💡 The Solution

The **Cloud Cost Firewall** acts as a drop-in OpenAI-compatible proxy. Changing only the `base_url` in your agent unlocks comprehensive cost governance:

```
Agent Prompt ──▶ Cost Estimate ──▶ Policy Engine ──▶ Verdict (ALLOW / WARN / PAUSE / BLOCK)
                                                          │
                   ┌──────────────────────────────────────┴──────────────────────────────────────┐
                   ▼                                                                             ▼
       [ALLOW / WARN / DOWNGRADE]                                                         [BLOCK / PAUSE]
                   │                                                                             │
         Forward to Provider                                                           429 / Wait for Admin
                   │                                                                             │
         Record Actual Usage ◀───────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Key Features

1. **Pre-call Cost Estimation & Reservation**  
   Estimates cost before sending to upstream (`chars / 4` input tokens + expected output tokens). Reserves the estimate atomically so concurrent requests cannot jointly overshoot budgets.

2. **9-Rule Pure Decision Engine (`app/policy.py`)**  
   Pure, deterministic function evaluating:
   - Feature model restrictions (`allowed_models`)
   - Loop detection with SHA1 signatures (blocks repetitive loops at `loop_limit`, default 3)
   - Maximum calls per run limit (`max_calls_per_run`)
   - User daily budget cap (`user_daily_cap`)
   - Run budget cap (`run_cap`)
   - Pause threshold (`pause_at`) for human approval
   - Automatic model downgrade (`downgrade_at`)
   - Budget warning threshold (`warn_at`)

3. **Human-in-the-Loop Approvals (PAUSE Flow)**  
   When a call crosses `pause_at`, the proxy holds the request and alerts admins via:
   - The integrated **Web Approvals Dashboard** (`/approvals`)
   - Real-time **Telegram bot** inline buttons (Approve 2x cap / Deny)
   - If approved, the cap override is applied and execution resumes seamlessly without agent error.

4. **Zero-Latency Database Persistence**  
   Request metrics, cost attributions, and run aggregates are asynchronously persisted to PostgreSQL via Starlette `BackgroundTasks`, adding zero latency to client responses.

5. **Hot-Reloadable Policies**  
   Edit `policies.json` or call `POST /api/policies` to adjust caps and thresholds live with zero restarts.

---

## 🏁 Quickstart

### Prerequisites
- Python 3.10+ (tested on Python 3.14)
- Docker Desktop (optional for Redis and PostgreSQL; falls back to in-memory store automatically)

### 1. Setup & Installation
```bash
git clone <repo-url>
cd firewall
python -m venv .venv
.venv\Scripts\activate   # On Windows (or source .venv/bin/activate on Linux/Mac)
pip install -r requirements.txt
```

### 2. Start Services
On Windows, simply run:
```bat
start_all.bat
```
Or start manually:
```bash
# Start Mock AI upstream (port 9000)
python tools/mock_llm.py

# Start Firewall Proxy (port 8000)
python -m uvicorn app.main:app --port 8000
```

### 3. Open the Playground
Navigate to: **[http://localhost:8000/playground](http://localhost:8000/playground)**

---

## 🧪 Verification & Tests

All test suites verify against real running endpoints:

| Test Script | Description |
|---|---|
| `python tools/smoke_test.py` | Basic proxy connectivity and token usage parsing |
| `python tools/test_policy.py` | Unit test suite covering all 9 policy decision rules |
| `python tools/test_concurrent.py` | 20 parallel requests verifying atomic reserve/release |
| `python tools/test_block.py` | 6 identical requests verifying loop detection (first 3 pass, 4-6 blocked) |
| `python tools/test_approval_logic.py` | Unit tests for approval state transitions and timeouts |
| `python tools/test_pause.py` | Integration test for PAUSE flow (Approve gives 200, Deny gives 403) |
| `python tools/test_history.py` | Verifies PostgreSQL runs and requests logging (or graceful off) |
| `python tools/test_playground_api.py` | Verifies verdict headers, models API, and rule validation |
| `python tools/benchmark.py` | Measures proxy latency overhead and agent savings |

---

## 📊 Benchmark Results

Running `python tools/benchmark.py` outputs isolated latency overhead and real-world runaway loop savings:

- **Runaway Loop Protection:**
  - Direct chaos agent: **15 calls allowed**, wasted **Rs 15.19**
  - Via Firewall: **Blocked at call 4**, total spent **Rs 1.22**
  - **Saved: 91.9% of runaway spending**
- **Proxy Latency Overhead:** ~0.8ms median overhead

---

## 🔍 Honest Limitations (PRD §19)

- **Cost Estimates:** Approximations based on `chars / 4` heuristic; the exact difference is recorded and displayed.
- **Streaming:** Responses are currently non-streamed (`stream: true` safely rejected with 400).
- **Concurrency Storage:** Money values are stored as floats for hackathon demonstration (production should use integer paise or `Numeric`).
- **Telegram Polling:** Long-polling requires a single worker instance.
- **Notional Costs:** Free tier and local models (e.g. Ollama) use notional rates based on paid equivalents for comparative tracking.
