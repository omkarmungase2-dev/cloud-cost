# Cloud Cost Firewall for AI Apps: Product Requirements Document (PRD) v2.0, Final Build

**Author:** Sujal Mungase | **Team:** Voicelink | **Version:** 2.0 (supersedes v1.0) | **Status:** Final build for the Grand Finale | **Date:** October 2026

> **How to use this file (Hinglish, sirf aapke liye):**
> 1. Naya khali folder `cost-firewall` banao, is file ko `PRD.md` naam se uske andar rakho, aur Antigravity (ya koi bhi AI coding editor) mein wahi folder kholo.
> 2. Pehla prompt: *"Read PRD.md fully. This is the single source of truth. Part A is what and why, Part B is exactly how (follow its milestones in Section 16), Part C is real AI integration. First write an implementation plan and wait for my OK. Then build milestone by milestone, run the tests after each one and show me the real output. Do not skip ahead."*
> 3. Plan padho, OK bolo, har milestone ke baad tests khud chalao.
> 4. **Code banne ke baad har member apna hissa padhe.** AI se code banwana allowed hai, par samajhna aapki zimmedari hai (Q&A mein kisi se bhi poochha ja sakta hai).
> 5. Provider ke model IDs, prices, free-tier limits aur competitors ke features badalte rehte hain. Pitch se pehle unhe khud verify karo.

---

# PART A: PRODUCT REQUIREMENTS

## A1. Overview

### A1.1 Problem
AI apps built on LLMs have unpredictable, chain-based costs. One user request can trigger many model calls, tool calls, retries and sub-agent calls. An agent can silently multiply cost through loops, retries or unbounded chains, and every call is costlier than the last because the history is resent. Teams usually discover the damage only when the provider bill arrives, grouped by API key, with no way to tell which feature or user caused it.

### A1.2 Product
**Cloud Cost Firewall** is a drop-in proxy between an AI app and its LLM provider. The app changes only its `base_url`. The firewall measures cost per request in real time, estimates cost **before** each call, enforces budget policies (**ALLOW, WARN, DOWNGRADE, PAUSE for human approval, BLOCK**), records the actual cost, and shows everything in a **Playground**: a web page where a user types a prompt, sees the firewall's verdict live, and receives the real AI response.

**One-line pitch:** *"A credit-card limit and speed limiter for AI apps: it stops a runaway agent while the run is still cheap, not after the bill arrives."*

### A1.3 What changed since v1.0
| Area | v1.0 (draft) | v2.0 (final) |
|---|---|---|
| UI | Streamlit/React dashboard of past events | **Playground**: one HTML page served by the firewall. User types a prompt, sees the verdict, gets the AI reply, edits rules live, approves pauses in-page |
| AI | Not specified beyond "multiple providers" | **Real AI** through any OpenAI-compatible endpoint (Gemini, Groq, OpenAI, Ollama) plus a mock AI for practice and backup |
| Budgeting | Running total vs cap | **Reserve-then-decide**: estimate is reserved atomically before the call, so parallel calls cannot overshoot the cap |
| Actions | DOWNGRADE listed, not specified | All five actions fully specified and implemented |
| Resilience | Open question | Redis or Postgres failure degrades gracefully; proxy keeps working |
| Evidence | Metrics listed | `benchmark.py` measures real savings, latency overhead, time-to-block and estimate error |

## A2. Goals and non-goals

**Goals**
- G1. Track cost per request, run, user, feature and model in real time.
- G2. Estimate cost before each call; show estimate vs actual.
- G3. Detect runaway patterns (identical repeated calls, call-count explosions, cap crossing) and intervene before they get expensive.
- G4. Provide a live-editable policy engine (per-run cap, per-user daily cap, max calls, model allow-list, warn, pause, downgrade thresholds).
- G5. Provide human-in-the-loop approval (page buttons and optional Telegram).
- G6. Give an interactive Playground that makes all of the above visible to a judge in under 3 minutes.
- G7. Work with real LLMs through a one-line config change, with an offline fallback.

**Non-goals (v2.0)**
- Not a full FinOps platform (no invoice reconciliation, multi-cloud GPU billing, procurement).
- Not a replacement for provider-side rate limits or authentication.
- No guarantee of 100% overrun prevention. The firewall reduces exposure.
- No streaming responses, no native non-OpenAI request formats, no multi-tenant workspaces, no login/SSO (all listed as future work).
- No on-prem or local-GPU cost accounting (a local Ollama model is supported only as a provider, with notional prices).

## A3. Target users
| User | Need |
|---|---|
| Solo developer / student building an agent | Avoid an accidental bill spike while testing |
| Small team shipping an AI feature | Know which feature/user drives cost |
| Team lead / budget owner | A hard cap so a bug cannot exceed budget; approve legitimate expensive runs |
| On-call engineer | Be told, and asked for approval, when a run looks abnormal |
| **Hackathon judge (demo persona)** | Type a prompt and immediately understand what the firewall decided and why |

## A4. User stories
1. As a developer, I point my app at the firewall URL instead of the provider URL, with no change to application logic.
2. As a developer, I tag requests with user, feature and run id so cost is attributed correctly.
3. As a budget owner, I set a per-run cap and a per-user daily cap.
4. As a budget owner, I get a warning before the block, so I can intervene early.
5. As a budget owner, I would rather **pause and approve** an expensive-but-legitimate run than have it killed.
6. As a developer, I want a loop (same call repeated) stopped automatically.
7. As a developer, I see estimated vs actual cost for each request, so I can trust the estimates.
8. As a team lead, I see cost by feature, user and model.
9. As a judge, I type a prompt in the Playground and see the verdict, the reason, and the AI's reply.
10. As a presenter, I change a rule live and show the next prompt getting a different verdict.
11. As a presenter, I switch from a cloud AI to a local one if the WiFi fails.
12. As an on-call engineer, I approve or deny a paused run from my phone (Telegram, optional).

## A5. Functional requirements
Priority: **M** = must, **S** = should, **C** = could. "Part B" references give the exact behavior.

### Proxy
| ID | Requirement | Pri | Part B |
|---|---|---|---|
| FR1 | OpenAI-compatible `POST /v1/chat/completions` that forwards to the configured provider | M | §5 |
| FR2 | Accept `X-User-Id`, `X-Feature`, `X-Run-Id` headers for attribution (safe defaults) | M | §5 |
| FR3 | Return a clear 400 for `stream: true` (streaming deferred) | M | §5 |
| FR4 | Provider is selected only by `UPSTREAM_URL` / `UPSTREAM_KEY` in `.env`; provider key never reaches the client | M | §4, Part C |
| FR5 | Provider errors (status >= 400) pass through with `X-Firewall-Action: UPSTREAM_ERROR` and **no cost recorded** | M | §5 |
| FR6 | Every response carries verdict headers (`X-Firewall-*`) | M | §5 |

### Cost estimation and tracking
| ID | Requirement | Pri | Part B |
|---|---|---|---|
| FR7 | Estimate cost before the call: input = chars/4 tokens, output = previous output or `max_tokens` or 200 | M | §4b |
| FR8 | Record actual cost from provider `usage`; store estimate vs actual per call | M | §5, §7 |
| FR9 | Editable price table (`prices.json`, Rs per 1000 tokens) with a `default` fallback | M | §4, §4b |
| FR10 | Track running total, call count, per-call latency per run (Redis) | M | §7 |
| FR11 | Track per-user daily spend | M | §7 |
| FR12 | Atomic reservation of the estimate before the decision | M | §5 |
| FR13 | Run-level prediction of final cost | C | §17 |

### Policy engine
| ID | Requirement | Pri | Part B |
|---|---|---|---|
| FR14 | Rules: per-run cap, per-user daily cap, max calls per run, model allow-list per feature, warn threshold, pause threshold, downgrade threshold, loop limit | M | §6 |
| FR15 | Every rule resolves to one action: ALLOW, WARN, DOWNGRADE, PAUSE, BLOCK, with a human-readable reason including numbers | M | §6 |
| FR16 | Loop detection: fingerprint of the last message; BLOCK when it repeats beyond the limit | M | §5, §6 |
| FR17 | Rules live in `policies.json`, hot-reloaded, and editable at runtime via API and Playground | M | §4, §10 |
| FR18 | Anomaly rule vs historical median per feature | C | §17 |

### Approval workflow
| ID | Requirement | Pri | Part B |
|---|---|---|---|
| FR19 | PAUSE holds the in-flight request and creates an approval record | M | §8 |
| FR20 | Approve (optionally with a new cap) or Deny from the Playground or the fallback approvals page | M | §8, §10 |
| FR21 | Approve resumes the call under the new cap; Deny returns 403; timeout returns 408 | M | §5, §8 |
| FR22 | Telegram message with Approve/Deny buttons, accepted only from the configured chat | S | §8 |

### Playground (the dashboard)
| ID | Requirement | Pri | Part B |
|---|---|---|---|
| FR23 | Prompt textarea, Send, chat bubbles for user, AI and system messages | M | §11 |
| FR24 | Verdict card: action badge, reason, estimate, projected cost, cap, actual cost, tokens, latency, model used | M | §11 |
| FR25 | Run budget bar (run total vs cap) | M | §11 |
| FR26 | Inline PAUSE box with Approve/Deny and a new-cap field | M | §11 |
| FR27 | Rules panel: edit rules live; "Auto-set from last call" button | M | §11 |
| FR28 | Session counters and a live event log | M | §11 |
| FR29 | Demo buttons: resend last prompt, "stuck agent" loop (8x), big prompt, new run | M | §11 |
| FR30 | Settings: user id, feature, model (with suggestions), max tokens, remember-conversation, system prompt, typing effect | M | §11, Part C |

### Data and operations
| ID | Requirement | Pri | Part B |
|---|---|---|---|
| FR31 | Live counters in Redis with TTLs; automatic in-memory fallback | M | §7 |
| FR32 | Permanent history in PostgreSQL (requests, runs, approvals), written in the background after the response; automatic disable on failure | M | §9 |
| FR33 | History APIs: runs, requests, approvals, summary by feature/user/model, estimate accuracy | M | §10 |
| FR34 | One-click start on Windows (`start_all.bat`) and Docker Compose for Redis and Postgres | M | §15 |
| FR35 | `benchmark.py` measures savings, latency overhead, time-to-block, estimate error | M | §12 |
| FR36 | `check_provider.py` verifies a provider and shows tokens and Rs cost; `price_helper.py` converts USD/1M to Rs/1K | M | Part C |
| FR37 | Mock AI server and demo agent (chaos, research) for practice and backup | M | §12 |

## A6. Non-functional requirements
| Category | Requirement |
|---|---|
| Latency | Firewall overhead target under 50 ms median for non-streaming calls (measured with `benchmark.py`, not assumed) |
| Reliability | Redis down: in-memory fallback with warning. Postgres down: history off with warning. Proxy keeps serving. Policy-evaluation exceptions fail **closed** (HTTP 500), never silently allowing spend |
| Security | Provider key only in `.env`, never logged or sent to the browser; Telegram accepts only the configured chat; Playground/rules endpoints are unauthenticated (demo only, stated openly) |
| Portability | Windows 11 first; `docker compose up -d` for infra; no Node/build step |
| Extensibility | Prices and rules editable without code changes |
| Understandability | Small, commented functions so every team member can explain every file |
| Safety of UI | All user/AI text rendered with `textContent`, never raw HTML |

## A7. Architecture
```
Browser (Playground)  --prompt-->  FIREWALL (FastAPI :8000)  --forward-->  AI PROVIDER
  textarea, verdict card            1 identify (headers)                    Gemini / Groq / OpenAI
  rules panel, approve box          2 estimate cost                         / Ollama (local) / Mock AI
  AI reply bubble  <--reply-------  3 reserve + loop count
                   <--X-Firewall-*  4 decide: ALLOW WARN DOWNGRADE PAUSE BLOCK
                                    5 forward or stop  6 record actual cost
                                          |            |
                                       Redis        PostgreSQL (background write)
                              (live totals, reserve,   (requests, runs, approvals)
                               events, approvals)       Telegram (optional) for Approve/Deny
```
Components: FastAPI proxy, Policy Engine (pure function), Store (Redis with memory fallback), Database (Postgres with graceful disable), Approval Service (+ Telegram), Playground (single HTML), tools (mock AI, demo agent, benchmark, provider checker).

## A8. Data model (summary)
Redis (live): run hash, call list, signature counts, reserved amount, cap override, per-user daily spend, events list, approval hashes. PostgreSQL (permanent): `requests`, `runs`, `approvals`. Full field lists are in Part B §7 and §9. The `policies` and `prices` of v1.0 are now JSON files (editable, hot-reloaded) instead of tables.

## A9. Key user flows
1. **Normal prompt:** type, Send, verdict ALLOW, reply shown, card shows estimate vs actual.
2. **Cost creeping up (WARN, then PAUSE):** with "remember conversation" on, each prompt costs more; budget bar rises; WARN appears; then PAUSE shows the in-page box; Approve resumes under a larger cap.
3. **Runaway loop (BLOCK):** "Stuck agent" resends the same prompt; call 4 is blocked with the loop reason; the call never reaches the provider; "saved" counter updates.
4. **Live rule change:** lower the cap in the Rules panel; next prompt gets BLOCK or PAUSE immediately.
5. **Provider failure:** wrong key or rate limit shows a purple UPSTREAM_ERROR and costs nothing.

## A10. AI integration (product view; details in Part C)
- Any provider that speaks the OpenAI chat-completions format works by changing `UPSTREAM_URL`, `UPSTREAM_KEY` and the model id. Verified on 15 Oct 2026 from official docs: Gemini, Groq and Ollama endpoints (see Part C). OpenAI's endpoint is standard but was not re-verified.
- **Three-tier fallback for the finale:** (1) cloud AI (Gemini or Groq), (2) local Ollama (works offline), (3) mock AI. Switching is one `.env` copy and a firewall restart.
- **Free tiers:** actual bill is Rs 0, so the firewall shows **notional** costs using the model's paid rates. The team must say so openly.
- **Honesty rules for the UI and pitch:** typing effect is cosmetic, not streaming; estimates are approximations; rules endpoints have no auth.

## A11. Success metrics and targets
| Metric | How measured | Target |
|---|---|---|
| Money saved on the stuck-agent demo | `benchmark.py` (direct vs protected) | At least 80% less spend (expected about 92% with the mock) |
| Time-to-block | `benchmark.py` | Under 2 seconds on the mock |
| Latency overhead | `benchmark.py`, median over 30 calls | Under 50 ms (report the measured number, whatever it is) |
| Estimate accuracy | Mean absolute % error, estimate vs actual | Report the measured value; investigate anything above 20% on the mock |
| Reliability | Proxy still answers with Redis stopped and with Postgres stopped | Yes (tested) |
| Test suite | All tests in Part B §14 | 100% pass |
| Demo robustness | Full demo flow (Part B §18) run end to end | 3 clean runs in a row before presenting |

## A12. Differentiation
Existing tools (LiteLLM, Helicone, Portkey) already offer proxying, per-key/per-user budgets and observability. This product differentiates through:
1. **Run-level control**: decisions use the projected total of an in-progress run, not just a running total.
2. **Loop detection**: repeated identical calls are stopped, not only money thresholds.
3. **Pause-for-approval**: an intermediate action between allow and block.
4. **Model downgrade**: switch to a cheaper model instead of stopping.
5. **Interactive Playground** that shows the reasoning behind every decision.

*Competitor feature sets change quickly. Re-verify them before the final pitch.*

## A13. Risks and mitigations
| Risk | Mitigation |
|---|---|
| Estimates are wrong | Show estimate vs actual; reserve is conservative; accuracy metric |
| Stale or missing prices | `prices.json` + `default` rate; `check_provider.py` warns when a model has no rate |
| Provider returns no `usage` | `check_provider.py` detects it; cost would read 0, so choose another provider/model |
| Streaming unsupported | Clear 400; typing effect is cosmetic; streaming listed as stretch |
| False positives block legitimate work | PAUSE path with human override; rules editable live |
| WiFi or provider outage at the venue | Three-tier fallback (cloud, Ollama, mock) |
| Provider rate limits during the demo | Keep prompts short; have a second provider ready |
| Windows or Docker problems | Retry logic on startup; in-memory fallback; `start_all.bat` |
| Scope creep in 24 hours | Build strictly in Part B §16 order; stretch only after M8 and M10 pass |
| Team cannot explain AI-generated code | Read every file; use the tests as a guided tour; rehearse Q&A |

## A14. Scope and 24-hour plan
- **Must (core MVP):** M1 to M8 and M10 (Part B §16).
- **Should:** M9 Telegram.
- **Could:** stretch goals in Part B §17.

| Hours | Work |
|---|---|
| 0 to 6 | M1 proxy, M2 store, M3 policy engine and tests |
| 6 to 12 | M4 Postgres, M5 approvals |
| 12 to 18 | M6 verdict headers and live rules, M7 Playground |
| 18 to 22 | M8 tools and benchmark, M10 real AI integration |
| 22 to 24 | Rehearse the demo 3 times, record a backup video, fix only blockers |

## A15. Acceptance criteria
| ID | Criterion |
|---|---|
| AC1 | `start_all.bat` brings up Redis, Postgres, firewall and opens the Playground; chips show store and db status |
| AC2 | A prompt typed in the Playground returns a **real** AI answer (chosen provider) with a filled verdict card |
| AC3 | The stuck-agent button produces BLOCK on call 4 with a loop reason, and the blocked call never reaches the provider |
| AC4 | A PAUSE appears in the page; Approve resumes the call; Deny returns 403 |
| AC5 | Lowering the cap in the Rules panel changes the next verdict without a restart |
| AC6 | Stopping Redis does not stop the proxy (memory mode warning appears) |
| AC7 | History survives `docker compose down` then `up -d` (Postgres volume) |
| AC8 | `benchmark.py` writes real numbers for savings, latency overhead and estimate error |
| AC9 | `check_provider.py` passes for the chosen provider and shows Rs cost |
| AC10 | All tests in Part B §14 pass |

## A16. Decisions on the open questions of v1.0
| v1.0 question | Decision |
|---|---|
| Fail-open vs fail-closed | Storage failures (Redis, Postgres) **degrade** and never block traffic. Policy-evaluation exceptions **fail closed** (HTTP 500). A configurable mode is future work |
| Price table maintenance | `prices.json` with `default` fallback and the provider checker; verify rates from the provider's pricing page |
| Streaming cost estimation | Streaming is out of scope for v2.0 |
| False positives | PAUSE with human override and live-editable rules |
| MVP vs full product | This document: Part A scope, Part B build order |

---

# PART B: TECHNICAL BUILD SPECIFICATION
*(Follow this exactly. Section numbers are referenced from Part A.)*

### 0. Instructions to the coding agent

You are building a hackathon project that must be **demo-ready in 24 hours**. Follow these rules:

- Build **exactly** what this spec says. Where the spec is silent, choose the **simplest** option.
- Code must be **beginner-readable**: small functions, clear names, short comments explaining *why*. The team has to explain every file to judges.
- Prefer few dependencies. No frontend build tools (no Node, no React build). The UI is **one static HTML file** served by FastAPI.
- Target OS is **Windows 11** (also fine on macOS/Linux). Never use Unix-only commands in scripts. Provide a `start_all.bat`.
- Work in **milestones** (Section 16). After each milestone, run its tests and report the real output. Do not claim a test passed unless you ran it.
- Never hardcode secrets. Read config from `.env`.
- If something in this spec seems wrong or impossible, say so and propose the smallest fix. Do not silently change behavior.

### 1. Product in one paragraph

**Cloud Cost Firewall** is a drop-in **proxy** between an AI app/agent and an LLM provider. The app only changes its `base_url`. For every request the firewall (1) identifies user/feature/run from headers, (2) **estimates cost before** calling the provider, (3) applies budget **policies** and decides **ALLOW / WARN / DOWNGRADE / PAUSE / BLOCK**, (4) forwards or stops the call, (5) records the **actual** cost, (6) streams all of this to a **Playground UI** where a user types a prompt and sees the firewall's verdict live plus the AI's response. It stops runaway agents (loops, retries, ever-growing chains) **while still cheap**, not after the bill arrives.

One-line pitch: *"A credit-card limit and speed limiter for AI apps."*

Currency is **Indian Rupees (Rs)**. Prices are Rs per **1000 tokens**.

### 2. Hard constraints and tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Web/proxy | FastAPI + uvicorn, `httpx.AsyncClient` for upstream calls |
| Live state | Redis 7 (via `redis` package, `redis.asyncio`) |
| Permanent data | PostgreSQL 16 via SQLAlchemy 2.0 **async** + `asyncpg` (tables via `create_all`, no Alembic) |
| UI | Single file `app/playground.html` (vanilla JS + CSS, no CDN, no frameworks) |
| Notifications | Telegram Bot API via plain `httpx` long-polling (optional) |
| Local infra | `docker-compose.yml` with `redis` and `postgres` (named volume `pgdata`) |
| Config | `.env` + `policies.json` + `prices.json` (hot-reloaded where stated) |
| Run | `uvicorn app.main:app --env-file .env --port 8000` (needs `python-dotenv`) |

`requirements.txt`: `fastapi`, `uvicorn[standard]`, `httpx`, `python-dotenv`, `redis`, `sqlalchemy`, `asyncpg`.

**Resilience rule (important for live demos):** if Redis is unreachable after retries, fall back to an in-memory store with a loud warning. If Postgres is unreachable after retries, disable history with a warning. The proxy itself must keep working in both cases.

### 3. Repository layout

```
cost-firewall/
  PRD.md                   (this file)
  README.md                (setup + demo steps, written by you)
  requirements.txt
  .env.example  .gitignore
  .env.mock/.gemini/.groq/.openai/.ollama .example   (provider templates, Part C)
  docker-compose.yml
  policies.json            (editable rules, hot-reloaded by mtime)
  prices.json              (editable price table)
  start_all.bat            (Windows one-click start)
  app/
    __init__.py
    config.py             (UPSTREAM_URL, UPSTREAM_KEY from env)
    pricing.py            (price table, cost_of, estimate_cost)
    policy.py             (load_rules, save_rules, signature, decide)
    store.py              (MemoryStore, RedisStore, create_store)
    db.py                 (SQLAlchemy models, Database class, create_db)
    approvals.py          (request_approval: pause logic)
    telegram.py           (notify + poll_loop)
    verdict.py            (verdict_headers)
    main.py               (FastAPI app and all routes)
    playground.html       (the UI)
    approvals.html        (tiny standalone approve page, fallback)
  tools/
    mock_llm.py           (fake OpenAI-compatible AI server, stdlib only, port 9000)
    agent.py              (demo agent: chaos / research / --direct)
    benchmark.py          (measures savings, latency overhead, accuracy)
    check_provider.py     (verifies a real AI provider, Part C)
    price_helper.py       (USD per 1M tokens to Rs per 1K, Part C)
    test_policy.py  test_approval_logic.py  test_block.py  test_pause.py
    test_concurrent.py  test_history.py  test_playground_api.py  smoke_test.py
```

### 4. Configuration files

#### `.env.example`
```
UPSTREAM_URL=http://localhost:9000/v1/chat/completions
UPSTREAM_KEY=
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=postgresql+asyncpg://firewall:firewall@localhost:5432/firewall
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
MAX_TOKENS_FIELD=max_tokens
```
Add commented presets for real providers (OpenAI-compatible endpoints). Tell the user to **verify model names, prices and free-tier limits in provider docs**:
- Gemini: `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`
- Groq: `https://api.groq.com/openai/v1/chat/completions`
- OpenAI: `https://api.openai.com/v1/chat/completions`
- Ollama (local, offline, no key): `http://localhost:11434/v1/chat/completions`

#### `prices.json` (Rs per 1000 tokens)
```json
{
  "_comment": "Rs per 1000 tokens. Add your model + rate. 'default' is used for unknown models. Rates are estimates, verify with provider.",
  "mock-large": {"in": 0.50, "out": 1.50},
  "mock-small": {"in": 0.10, "out": 0.30},
  "default":    {"in": 0.05, "out": 0.15}
}
```

#### `policies.json` (`null` = rule disabled)
```json
{
  "_comment": "Rules in Rs. null = off.",
  "run_cap": 3.0,
  "warn_at": 1.0,
  "pause_at": 2.0,
  "pause_timeout_seconds": 120,
  "loop_limit": 3,
  "max_calls_per_run": 30,
  "user_daily_cap": 50.0,
  "downgrade": {"at": null, "map": {"mock-large": "mock-small"}},
  "allowed_models": {}
}
```
`load_rules()` re-reads the file only when its mtime changes (no restart needed).
`save_rules(updates)` accepts only: `run_cap, warn_at, pause_at, user_daily_cap, pause_timeout_seconds, loop_limit, max_calls_per_run, downgrade_at`. Empty string or null means disabled. Negative values and unknown keys raise `ValueError`. After writing, update the in-memory cache.

#### `docker-compose.yml`
Services `redis` (image `redis:7`, port 6379) and `postgres` (image `postgres:16`, user/password/db all `firewall`, port 5432, volume `pgdata:/var/lib/postgresql/data`). Declare the `pgdata` volume.

#### `.gitignore`: `.env`, `.venv/`, `__pycache__/`

### 4b. Pricing and estimation (`app/pricing.py`)

- `cost_of(model, in_tokens, out_tokens) = in_tokens/1000 * price_in + out_tokens/1000 * price_out`. Unknown model falls back to `prices.json["default"]`, then to `mock-large`.
- `estimate_cost(model, messages, expected_output_tokens)`: input tokens = `len(json.dumps(messages)) // 4` (1 token is about 4 chars), plus `expected_output_tokens`, priced with `cost_of`.
- Expected output tokens = the previous call's output tokens in the same run if any, else request `max_tokens`, else `200`.

### 5. Core pipeline: `POST /v1/chat/completions`

OpenAI-compatible request and response. Headers: `X-Run-Id` (default `no-run`), `X-User-Id` (default `unknown`), `X-Feature` (default `unknown`). The body is forwarded unchanged except for a possible model downgrade.

**Algorithm (implement exactly in this order):**

1. If `body.stream` is true, return **400** with a clear error ("streaming not supported yet").
2. Load rules (`load_rules()`).
3. `est = estimate_cost(...)`.
4. `run_total, run_calls = store.get_totals(run_id)`.
5. `reserved_after = store.reserve(run_id, est)` (atomic; includes this call's estimate. This prevents parallel calls from jointly exceeding the cap).
6. `loop_count = store.bump_signature(run_id, signature(messages))` (atomic).
7. `user_spent = store.user_spend_today(user)`; `override = store.get_cap_override(run_id)`.
8. `d = decide(rules, ...)` (Section 6).
9. **If `d.action == PAUSE`:** `store.release(run_id, est)`; log event `PAUSE`; call `request_approval(...)` (Section 8).
   - status `denied` leads to **403** and event `DENIED`. Status `timeout` leads to **408** and event `TIMEOUT`. Both also write a DB row (counted as blocked).
   - status `approved`: log event `APPROVED`, re-fetch override, **re-reserve**, and call `decide` again with `cap_override` (without re-bumping the loop counter). Continue with the new decision.
10. **If action is BLOCK:** `release`, log event, return **429** with body `{"error":{"message":"BLOCKED by Cost Firewall: <reason>","type":"cost_firewall"}}`. The request is **never sent upstream**.
11. If action is DOWNGRADE: replace `body["model"]` with `d.model`, and append `(old -> new)` to the reason.
12. If env `MAX_TOKENS_FIELD` (default `max_tokens`) differs, rename the body's `max_tokens` key to it (the estimate in step 3 still uses the original). Then forward with `httpx` (add `Authorization: Bearer <UPSTREAM_KEY>` only if the key is set). On network error: `release`, return **502**.
13. If upstream status >= 400: `release`, pass the upstream error body and status through with header `X-Firewall-Action: UPSTREAM_ERROR`. **Do not record any cost.**
14. Compute `actual = cost_of(model, usage.prompt_tokens, usage.completion_tokens)`. Call `store.add_call(...)` then `store.release(run_id, est)`. Log event with `actual`.
15. Return the upstream JSON with status code and **verdict headers**. Persist to Postgres in a **FastAPI/Starlette `BackgroundTask`** attached to the response, so DB latency is not added to the request.

**Loop signature:** `sha1(json.dumps(messages[-1], sort_keys=True)).hexdigest()[:12]`. **Use `hashlib`, never Python's built-in `hash()`** (it differs per process and breaks multi-worker setups).

**Verdict headers** (every response from this endpoint: allowed, blocked, denied, upstream error): `X-Firewall-Action`, `X-Firewall-Reason` (ASCII only, max 200 chars; strip non-ASCII), and when known `X-Firewall-Estimate`, `-Projected`, `-Run-Total` (total **after** the call for successes, before for blocks), `-Cap` (override or `run_cap`), `-Cost` (actual), `-Latency-Ms`, `-Model`, `-Call`. Implement in `app/verdict.py`.

### 6. Policy engine (`app/policy.py`)

`decide(rules, *, model, feature, est, run_total, run_calls, reserved_after, loop_count, user_spent, cap_override=None)` is a **pure function** (no I/O). It returns `{"action", "reason", "model", "projected"}` where `projected = run_total + reserved_after` (rounded to 5 decimals). **First matching rule wins, in this order:**

| # | Condition | Action |
|---|---|---|
| 1 | `allowed_models[feature]` exists and model not in it | BLOCK |
| 2 | `loop_limit` set and `loop_count > loop_limit` | BLOCK (loop) |
| 3 | `max_calls_per_run` set and `run_calls + 1 > max_calls_per_run` | BLOCK |
| 4 | `user_daily_cap` set and `user_spent + est > user_daily_cap` | BLOCK |
| 5 | `cap = cap_override or run_cap`; `projected > cap` | BLOCK |
| 6 | `pause_at` set and `projected > pause_at` and **no** cap_override | PAUSE |
| 7 | `downgrade.at` set and `projected > downgrade.at` and model in `downgrade.map` | DOWNGRADE (new model from map) |
| 8 | `warn_at` set and `projected > warn_at` | WARN |
| 9 | otherwise | ALLOW |

Each reason is a short human-readable sentence including the numbers (e.g. "run cap Rs3.0 will be crossed (estimate Rs3.40)").

### 7. State: Redis (`app/store.py`)

Two classes with **identical async interfaces**: `MemoryStore` (fallback) and `RedisStore`. `create_store()` tries Redis (3 attempts, 1.5 s apart) then falls back. Each class has a `name` attribute (`"memory"` or `"redis"`).

Methods: `get_run(run_id)`, `last_output_tokens(run_id)`, `add_call(run_id,user,feature,model,tin,tout,est,actual,latency_ms)`, `all_runs()`, `user_spend_today(user)`, `get_totals(run_id)`, `reserve(run_id,est)`, `release(run_id,est)`, `bump_signature(run_id,sig)`, `log_event(ev)`, `get_events(limit)`, `create_approval`, `get_approval`, `list_pending`, `decide_approval(run_id, ok, new_cap=None, by="dashboard")`, `get_cap_override(run_id)`, `reset()`.

**Redis keys (TTL 24 h unless noted):**
- `run:{id}` hash: `run_id,user,feature,started_at,total_cost,est_total,call_count`. Totals use `HINCRBYFLOAT` / `HINCRBY`.
- `run:{id}:calls` list of JSON call records.
- `run:{id}:sig` hash `{signature: count}` using `HINCRBY`.
- `run:{id}:reserved` float using `INCRBYFLOAT`.
- `run:{id}:cap` string (approved cap override).
- `user:{user}:{YYYY-MM-DD}` float using `INCRBYFLOAT` (TTL 48 h).
- `events` list (`LPUSH` + `LTRIM 0 499`).
- `approval:{run_id}` hash `status,new_cap,decided_by,requested_at,run_id,user,feature,spent,est,projected,reason,cap` (TTL 1 h).

`add_call` uses a **transactional pipeline** (`MULTI/EXEC`) so all counters update atomically. `all_runs()` scans `run:*` and **skips keys containing more than one colon** (`:calls`, `:sig`, `:reserved`, `:cap`).

`decide_approval(ok)`: only applies if status is currently `pending`. Maps `True/False/None` to `approved/denied/timeout`. On approve with `new_cap`, store `run:{id}:cap`. Returns whether it was applied.

**Event record:** `{ts, time "HH:MM:SS", run_id, user, feature, call, action, reason, model, est, actual?, total}`. Actions: `ALLOW, WARN, DOWNGRADE, PAUSE, APPROVED, DENIED, TIMEOUT, BLOCK`. Round costs to **5 decimals** (real models cost fractions of a paisa).

### 8. Approvals (PAUSE) (`app/approvals.py`, `app/telegram.py`)

`request_approval(store, db, client, rules, info)`:
1. `store.create_approval(run_id, info)`.
2. `telegram.notify(...)` (no-op if Telegram is not configured; never raises).
3. Poll `store.get_approval` every **0.5 s** until status is not `pending` or `pause_timeout_seconds` (default 120) passes. On timeout call `decide_approval(run_id, None, by="timeout")`.
4. Save an `approvals` row (`db.save_approval`) with `wait_seconds`.
5. Return the approval dict. (Polling Redis makes it work across multiple workers.)

Endpoints decide it: `POST /api/approvals/{run_id}/approve?new_cap=` (default new cap = `run_cap * 2`) and `/deny`.

**Telegram (optional):** enabled only if both env vars are set. `notify` sends a message with an inline keyboard (Approve/Deny; `callback_data` = `a:{run_id}` / `d:{run_id}`, max 64 bytes). `poll_loop` uses `getUpdates` long-polling (`timeout=25`, `allowed_updates=["callback_query"]`) started as an asyncio task in the app lifespan and cancelled on shutdown. **Only accept callbacks whose chat id equals `TELEGRAM_CHAT_ID`.** Answer each callback query. Document that Telegram polling must run with a single worker.

### 9. PostgreSQL (`app/db.py`)

Models (SQLAlchemy 2.0 `Mapped` style):
- `requests`: `id` pk, `run_id`(idx), `user_id`(idx), `feature`(idx), `model`, `input_tokens`, `output_tokens`, `estimated_cost`, `actual_cost`, `latency_ms`, `action`, `reason`, `created_at` (server default now).
- `runs`: `run_id` pk, `user_id`, `feature`, `total_cost`, `call_count`, `blocked_count`, `status` (`running`/`blocked`), `started_at`, `last_at`.
- `approvals`: `id`, `run_id`(idx), `user_id`, `feature`, `projected_cost`, `decision`, `decided_by`, `new_cap` (nullable), `wait_seconds`, `created_at`.

`Database.save(rec)`: in **one transaction** insert a `requests` row and **upsert** `runs` (`INSERT ... ON CONFLICT (run_id) DO UPDATE` adding cost and counts; status becomes `blocked` if any blocked). Actions `BLOCK`, `DENIED`, `TIMEOUT` count as blocked (call_count +0, blocked_count +1). It must **catch and print** exceptions, because logging failures must never break the proxy. `create_db()` retries 5 times (2 s apart) because Postgres starts slowly in Docker. `Database.reset()` truncates all three tables. `Database.fetch(sql, **params)` returns list of dicts using `text()` queries.

### 10. API reference (`app/main.py`)

| Method + Path | Purpose |
|---|---|
| `GET /` | redirect to `/playground` |
| `GET /playground` | serves `playground.html` |
| `GET /approvals` | serves `approvals.html` (simple fallback page) |
| `GET /health` | `{status, store, db: "postgres"/"off", telegram: bool}` |
| `POST /v1/chat/completions` | the firewall pipeline (Section 5) |
| `GET /api/policies`, `POST /api/policies` | read / update rules (via `save_rules`; 400 on invalid) |
| `GET /api/models` | models from `prices.json` (excluding keys starting with `_`) with in/out rates |
| `GET /api/runs`, `GET /api/runs/{run_id}` | live runs from the store (detail includes per-call `est`/`actual`/`latency_ms`) |
| `GET /api/users/{user}/today` | user's spend today |
| `GET /api/events?limit=` | recent events (newest first) |
| `GET /api/stats` | `{spent, calls_allowed, blocked, saved_estimate}` from last 500 events (`saved_estimate` = sum of `est` of BLOCK events) |
| `GET /api/approvals` | pending approvals |
| `POST /api/approvals/{run_id}/approve?new_cap=` / `/deny` | decide |
| `GET /api/history/runs?limit=` | runs table |
| `GET /api/history/requests?run_id=&limit=` | requests table (build the WHERE clause in Python; do not pass NULL params to asyncpg) |
| `GET /api/history/summary` | `by_feature`, `by_user`, `by_model` (calls + cost, excluding BLOCK), `blocked {count, saved_estimate}`, `estimate_accuracy {avg_error_percent, avg_latency_ms}` |
| `GET /api/history/approvals` | approvals table |
| `POST /api/reset?history=false` | clear live data; `history=true` also truncates Postgres |

All `/api/history/*` return **503** with a clear message if Postgres is off. In SQL, round money with `ROUND(x::numeric, 5)::float`.

### 11. Playground UI (`app/playground.html`): the main demo surface

A single dark-themed, responsive HTML file (two columns on desktop, stacked on mobile). **No external requests.** Render all user/AI text with `textContent` (never `innerHTML` with untrusted text).

**Header:** title "Cloud Cost Firewall", chips for `store`, `db`, `telegram` (from `/health`), and a one-line flow: *Prompt → Cost estimate → Policy rules → Verdict → AI → Response → Real cost recorded*.

**Left column (Chat card):**
- Scrollable message list: user bubble (right, blue), AI bubble (left), system bubble (centered, colored border) for BLOCK/DENIED/errors. AI bubbles show a small meta line: `ACTION | cost | latency` plus reason when not ALLOW.
- Textarea + **Send** (also **Ctrl+Enter**).
- Buttons: **Send**, **Same prompt dobara** (resend last), **Atka agent (8x same)** (send the same prompt up to 8 times sequentially with history off, 250 ms apart, stop on BLOCK/DENIED/TIMEOUT/error), **Bada prompt** (fills textarea with about 16,000 characters of filler), **New run** (new random `run-xxxxxx` id, clears history and budget bar).
- Inputs: User ID (default `sujal`), Feature (default `playground`), Model (text input with `<datalist>` from `/api/models`, default `mock-large`), Max output tokens (default 300), checkbox **"remember conversation"** (when on, send full history each time so cost visibly grows). Also an optional **System prompt** input (if non-empty, prepend `{role:'system',content}` to messages) and a checkbox **Typing effect** (default on) that reveals the AI reply progressively as a *cosmetic* animation (about 20 ms ticks). It is NOT streaming and the UI must not claim it is.
- Shows current Run ID.

**Each send:** `fetch('/v1/chat/completions', ...)` with headers `X-Run-Id`, `X-User-Id`, `X-Feature` and body `{model, messages, max_tokens}`. While waiting, poll `/api/approvals` every 700 ms; if an approval for the **current run id** is pending, show the PAUSE box. Read the verdict from the **response headers**. On success append the AI reply; if "remember conversation" is on, push user+assistant messages to local history. On non-OK show the error message in a system bubble.

**Right column:**
1. **PAUSE box** (hidden by default, orange): reason, spent so far, projected cost, "New cap Rs" input, **Approve** and **Deny** buttons (call the approve/deny endpoints for the current run).
2. **Firewall verdict card:** big colored badge (ALLOW green, WARN yellow, DOWNGRADE blue, PAUSE orange, BLOCK/DENIED/TIMEOUT red, UPSTREAM_ERROR purple), the reason, and a table: Estimate, Projected (run total + this call), Run cap, Actual cost, Tokens (in/out from `usage`), Latency, Model used. Plus a **run budget bar** (`run_total / cap`, green under 60%, yellow 60 to 90%, red above) with text.
3. **Session card:** four counters (spent, allowed, blocked, saved estimate from `/api/stats`) and the last 8 events from `/api/events` (time, colored action, last 6 chars of run id, call number, cost, reason). Refresh after every call.
4. **Rules card:** inputs for run cap, warn at, pause at, downgrade at, loop limit, user daily cap; **Rules save** (POST `/api/policies`; empty = null) and **Auto-set from last call**, which sets `warn_at = 2.5x`, `pause_at = 4x`, `run_cap = 6x`, `user_daily_cap = 200x` of the last successful call's actual cost (so the demo works with any provider's real, tiny prices). Show cost with 4 to 5 decimals when below Rs 0.01.

Disable Send while a request is in flight. Handle "firewall not reachable" gracefully.

### 12. Tools

**`tools/mock_llm.py`** (stdlib only, `ThreadingHTTPServer`, port 9000): `POST /v1/chat/completions` returns an OpenAI-shaped response. Reply text = `"Step done. " + "Here is a detailed answer with many words. " * 18`. `prompt_tokens = len(" ".join(message contents)) // 4`, `completion_tokens = len(reply) // 4`. Sleep 0.4 s to imitate latency. Echo the requested `model`.

**`tools/agent.py`** (`python tools/agent.py chaos|research [--direct]`): uses `urllib`; default URL is the firewall (8000), `--direct` uses the mock (9000). Sends `X-Run-Id` (random), `X-User-Id: sujal`, `X-Feature: shopping-agent`. Keeps and resends history (so each call is costlier). `chaos` repeats the same user message up to 15 times; `research` sends 6 different task messages. Prints per-call tokens, cost and running total (green/yellow/red). On HTTP error prints the firewall message and exits with the total so far. Timeout 200 s (PAUSE waits).

**`tools/benchmark.py`:** measures (1) latency overhead (30 calls direct vs via firewall, 3 warm-ups, median and p95, **use a fresh user id and unique run ids** so caps do not interfere), (2) the chaos agent direct vs protected (cost, calls, seconds-to-block, savings %), (3) mean estimate error from `/api/runs/{run}`. Writes `benchmark_results.json` and `benchmark_results.md` with a note that the mock has fixed latency.

**`tools/check_provider.py`** and **`tools/price_helper.py`**: see Part C, Section C3.

### 13. Expected behavior with default config (use for verification)

- Mock chaos agent **direct**: 15 calls cost about **Rs 15.19**.
- Mock chaos agent **via firewall**: calls 1 to 3 allowed (about Rs 0.30, 0.40, 0.50; total about **Rs 1.20**), call **4 blocked by loop rule**.
- A single request with a message of `"word " * 3200` (about 4000 input tokens) estimates about Rs 2.3, which is above `pause_at` (2.0) and below `run_cap` (3.0), so it must **PAUSE**. After Approve (new cap Rs 6.0) it is allowed. After Deny it returns **403**.

### 14. Tests (all must exist and pass)

| File | Needs server? | Asserts |
|---|---|---|
| `test_policy.py` | no | ALLOW, WARN, DOWNGRADE, PAUSE, cap BLOCK, loop BLOCK (loop_count 4) vs ALLOW at limit (3), max calls, user cap, model restriction, approved cap override (no PAUSE; BLOCK if still over), signature equal/different |
| `test_approval_logic.py` | no | with `MemoryStore` and a fake DB: approve sets cap override 6.0, deny leaves none, timeout works |
| `check_runs`/`smoke_test.py` | yes | one call returns 200 with `usage` |
| `test_block.py` | yes | same prompt 6x gives `[200,200,200,429,429,429]` and a BLOCK event exists |
| `test_pause.py` | yes | big prompt pauses, approve gives 200, deny gives 403 |
| `test_concurrent.py` | yes | 20 parallel calls on one run give `call_count == 20` and total matches the sum of calls |
| `test_history.py` | yes + Postgres | 4 rows (3 allowed + 1 BLOCK) for a loop run; run summary correct |
| `test_playground_api.py` | yes | verdict headers present, `/api/models`, `POST /api/policies` valid/invalid (400), `/playground` is 200 |

### 15. Windows helpers

`start_all.bat`: `cd /d %~dp0`; `docker compose up -d`; wait about 6 s; start Mock AI and Firewall in separate `cmd /k` windows with the venv activated (`.venv\Scripts\activate`); wait about 5 s; `start http://localhost:8000/playground`. Add a comment: for a real provider, set `.env` and remove the Mock AI line.

### 16. Milestones (build in this order; stop and test after each)

| # | Build | Done when |
|---|---|---|
| M1 | Project skeleton, `config`, `pricing`, passthrough proxy, `mock_llm.py`, `smoke_test.py` | smoke test prints 200 + usage; console shows cost and latency |
| M2 | `store.py` (Memory + Redis with retries), run tracking, reserve/release, `/api/runs`, `/api/users/.../today` | `test_concurrent.py` PASS with Redis **and** with Redis stopped (memory fallback) |
| M3 | `policy.py` + `policies.json`, loop signature, events, `/api/events`, `/api/stats`, `/api/policies` | `test_policy.py` PASS, `test_block.py` PASS |
| M4 | `db.py`, background writes, history endpoints | `test_history.py` PASS; data survives `docker compose down` then `up -d` |
| M5 | Approvals (store, `approvals.py`, endpoints, `approvals.html`), PAUSE flow in the pipeline | `test_approval_logic.py` and `test_pause.py` PASS |
| M6 | `verdict.py` headers, upstream-error handling, `/api/models`, `save_rules` + `POST /api/policies` | `test_playground_api.py` PASS |
| M7 | `playground.html` | Manual: send a prompt, see verdict and response; trigger WARN, PAUSE (approve in page), BLOCK (loop button); edit rules live |
| M8 | `agent.py`, `benchmark.py`, `start_all.bat`, README | `agent.py chaos` blocks at call 4; `benchmark.py` writes results |
| M9 (should) | Telegram notify and polling | PAUSE sends a message with buttons; Approve works from the phone |
| M10 | Real AI integration (Part C): env templates, `check_provider.py`, `price_helper.py`, system prompt and typing effect in the Playground, `MAX_TOKENS_FIELD` | `check_provider.py` passes for the chosen provider; a real prompt in the Playground returns a real answer with a verdict |

**24-hour budget guide:** M1 to M3 by hour 6, M4 and M5 by hour 12, M6 and M7 by hour 18, M8 and M10 by hour 22, rehearse the demo in the last 2 hours.

### 17. Stretch goals (only after M8 passes)

1. **Anomaly rule (PRD FR13):** flag a run whose projected cost is above 3x the historical median run cost for that feature (query `runs`); action WARN or PAUSE.
2. **Run-level prediction (FR10):** predicted final cost = `current + avg_cost_per_call * expected_remaining_calls`, using the feature's historical average call count; show it in the verdict card.
3. **Streaming support** (`stream: true`): pass through chunks and count tokens from the final usage chunk (or estimate if absent).
4. **Anthropic native adapter** behind the same interface (OpenAI-compatible endpoints already cover most providers).
5. **Per-feature monthly budget** rule using Postgres sums.

### 18. Final demo flow (acceptance checklist)

1. `start_all.bat`; Playground opens; chips show `store: redis`, `db: postgres`.
2. Send a normal prompt: **ALLOW**, response appears, verdict card filled.
3. Click **Auto-set from last call**. Send 3 to 4 prompts (with "remember conversation" on): budget bar rises, **WARN**, then **PAUSE** appears in the page, **Approve**, then the call continues.
4. Click **Atka agent (8x same)**: **BLOCK** on call 4 with the loop reason; session "saved" counter updates.
5. Change a rule live (for example lower the cap) and show the next prompt gets a different verdict.
6. Show history in Postgres (`/api/history/summary`) and the benchmark numbers.
7. Show the one-line integration: only `base_url` changes in `tools/agent.py`.

### 19. Honest limitations (put these in README and be ready to say them to judges)

- Cost estimates are approximations (characters/4); estimate vs actual gap is measured and shown.
- Responses are not streamed yet.
- The mock AI has fixed latency, so benchmark overhead is the meaningful number, not total latency.
- Rules/approve endpoints have no authentication (demo only). Production needs auth.
- Money is stored as floats for the demo; production should use integer paise or `Numeric`.
- Approve/Deny races use check-then-set, not a Lua script.
- Tables are created with `create_all`; production would use Alembic migrations.
- Telegram polling requires a single worker.
- On free tiers or local models, shown costs are notional (paid-plan rates); say so.
- The typing effect is cosmetic; responses are not streamed.

### 20. Do-nots

- Do not use Python's `hash()` for signatures. Do not add a frontend build step. Do not use `localStorage` for important state.
- Do not let DB or Telegram failures break proxy requests.
- Do not call the upstream provider for a call that was decided BLOCK/DENIED/TIMEOUT.
- Do not record cost for upstream error responses.
- Do not print or log API keys.

---

# PART C: REAL AI INTEGRATION

## C1. Providers (all use the OpenAI chat-completions format)
| Provider | `UPSTREAM_URL` | Key | Notes |
|---|---|---|---|
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` | Google AI Studio | Endpoint verified from official docs (15 Oct 2026). Copy the model id from AI Studio |
| Groq | `https://api.groq.com/openai/v1/chat/completions` | console.groq.com/keys | Endpoint verified (15 Oct 2026). Docs example model: `llama-3.3-70b-versatile` (verify it is current). Some fields (e.g. logprobs) are unsupported; the firewall does not send them |
| OpenAI | `https://api.openai.com/v1/chat/completions` | platform.openai.com | Standard endpoint, **not re-verified**. Some models need `max_completion_tokens` (see `MAX_TOKENS_FIELD`) |
| Ollama (local) | `http://localhost:11434/v1/chat/completions` | none (ignored) | Verified. Run `ollama pull llama3.2` first; model id `llama3.2`. Works with no internet |
| Mock | `http://localhost:9000/v1/chat/completions` | none | Practice and last-resort backup |

Model ids, free-tier limits and prices change often. Read the provider's model list and pricing page yourself.

## C2. Environment templates (create these files in the project root)
Create `.env.mock.example`, `.env.gemini.example`, `.env.groq.example`, `.env.openai.example`, `.env.ollama.example`. Each contains `UPSTREAM_URL` (from C1), `UPSTREAM_KEY` (`PASTE_YOUR_KEY`, or empty for Ollama and Mock), `REDIS_URL`, `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and a commented line `# MAX_TOKENS_FIELD=max_completion_tokens`. Example `.env.ollama.example`:
```
UPSTREAM_URL=http://localhost:11434/v1/chat/completions
UPSTREAM_KEY=
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=postgresql+asyncpg://firewall:firewall@localhost:5432/firewall
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
# MAX_TOKENS_FIELD=max_completion_tokens
```
Switching provider = `copy .env.<name>.example .env`, then restart the firewall.

## C3. Tools to implement
**`tools/check_provider.py <model-id>`** (stdlib only). Reads `.env` (and environment) for `UPSTREAM_URL`, `UPSTREAM_KEY`, optional `MAX_TOKENS_FIELD`. Sends one tiny prompt ("Say hello in one short sentence.") with a 60-token limit directly to the provider. Prints URL, model, whether a key is set (**never print the key**), latency, reply, `usage`, and the cost the firewall would compute from `prices.json` (flagging when the model has no entry and the `default` rate is used, and when the provider returns no `usage`). On HTTP errors print the provider's message plus a hint: 400 = request field (try `MAX_TOKENS_FIELD`), 401 = key, 403 = permission, 404 = URL or model, 429 = rate limit. Connection errors suggest checking internet or whether Ollama is running.

**`tools/price_helper.py --model <id> --in <USD per 1M input> --out <USD per 1M output> --rate <USD to INR> [--write]`**: prints `{model: {"in": X, "out": Y}}` where `X = usd_in * rate / 1000` (Rs per 1000 tokens), and with `--write` merges it into `prices.json`.

## C4. Pricing policy
- Paid plan: use the provider's real prices converted to Rs per 1000 tokens.
- Free tier or local model: use the paid-plan ("notional") rates and **state this to judges**.
- No entry: `default` rate applies and numbers are only indicative.

## C5. Calibrating rules to real prices
Real calls cost fractions of a rupee, so the default caps would never trigger. In the Playground, send one prompt, then press **Auto-set from last call**: `warn_at = 2.5x`, `pause_at = 4x`, `run_cap = 6x`, `user_daily_cap = 200x` of that call's actual cost. With "remember conversation" on, growing history walks the run through WARN, PAUSE and BLOCK naturally. Show costs with 4 to 5 decimals when below Rs 0.01.

## C6. Fallback procedure for the finale
1. Main: Gemini or Groq. 2. WiFi problem: `copy .env.ollama.example .env`, restart the firewall. 3. Last resort: `copy .env.mock.example .env`, run `python tools/mock_llm.py`. Before presenting: `python tools/check_provider.py <model>`, one full rehearsal, then `POST /api/reset?history=true` for a clean start.

## C7. Troubleshooting
| Symptom | Cause and fix |
|---|---|
| Playground says it cannot reach the firewall | `uvicorn` not running or port 8000 busy |
| Verdict `UPSTREAM_ERROR` | Provider rejected the call. Run `check_provider.py` (key, model, quota) |
| 400 mentioning `max_tokens` | Set `MAX_TOKENS_FIELD=max_completion_tokens` in `.env` |
| Cost always 0 | Provider returned no `usage` |
| Cost shows 0.0000 | Real prices are tiny; use Auto-set and show 5 decimals |
| WARN/PAUSE never appears | Caps too high; Auto-set or turn on "remember conversation" |
| Chip says `store: memory` | Redis not reachable; start Docker Desktop and `docker compose up -d` |
| Chip says `db: off` | Postgres not ready; restart the firewall after a few seconds |
| Slow replies | Provider latency; try Groq or Ollama |

## C8. Glossary (simple meanings)
- **Proxy**: a middleman between the app and the AI provider.
- **Token**: a small piece of text the AI charges for (about 4 characters).
- **Run**: one task made of many AI calls.
- **Estimate vs actual**: the cost guessed before the call vs the cost computed from the provider's reported tokens.
- **Reserve**: setting aside the estimate before the call so parallel calls cannot overshoot the cap.
- **Redis**: very fast temporary memory for live counters.
- **PostgreSQL**: permanent database for history and reports.
- **Notional cost**: the cost at paid rates when the real bill is zero (free tier or local model).
