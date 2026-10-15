# Cloud Cost Firewall — Benchmark Results

**Generated:** 2026-10-15 06:51:07 UTC  
> **Note:** The mock AI upstream includes a fixed simulated delay (~400ms). The latency overhead measured below isolates the pure proxy evaluation overhead.

---

## 1. Latency Overhead

| Metric | Direct Upstream | Via Firewall Proxy | Proxy Overhead |
|---|---|---|---|
| **Median Latency** | 420.24 ms | 440.46 ms | **+20.21 ms** |
| **p95 Latency** | 425.82 ms | 457.82 ms | **+32.0 ms** |

*Measured across 30 sequential requests per target with 3 warm-up calls.*

---

## 2. Chaos Agent Protection (Runaway Loop Prevention)

| State | Calls Allowed | Total Cost | Duration | Outcome |
|---|---|---|---|---|
| **Direct (Unprotected)** | 15 calls | Rs 15.15650 | 6.22s | Runaway loop waste |
| **Via Firewall** | 4 calls | Rs 1.19750 | 1.37s | **Blocked at call 4 (Loop limit 3)** |

- **Money Saved:** **Rs 13.95900**
- **Cost Reduction:** **92.1%**

---

## 3. Cost Estimation Accuracy

- **Calls analyzed:** 3
- **Mean estimation error:** **12.04%**
- **Estimation heuristic:** `len(json.dumps(messages)) // 4` input tokens + expected output tokens.
