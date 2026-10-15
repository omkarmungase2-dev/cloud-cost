"""
Verdict headers builder (PRD §5).
Constructs ASCII-safe HTTP headers for every firewall response:
allowed, blocked, denied, timeout, and upstream error.
"""

from typing import Dict, Any, Optional


def build_verdict_headers(
    action: str,
    reason: str = "",
    *,
    est: Optional[float] = None,
    projected: Optional[float] = None,
    run_total: Optional[float] = None,
    cap: Optional[float] = None,
    actual: Optional[float] = None,
    latency_ms: Optional[float] = None,
    model: Optional[str] = None,
    call: Optional[int] = None,
) -> Dict[str, str]:
    """
    Build standardized X-Firewall-* response headers.
    Reason is sanitized to ASCII-only and truncated to 200 chars.
    """
    clean_reason = reason.encode("ascii", "ignore").decode("ascii")[:200]

    headers: Dict[str, str] = {
        "X-Firewall-Action": str(action),
        "X-Firewall-Reason": clean_reason,
    }

    if est is not None:
        headers["X-Firewall-Estimate"] = str(round(float(est), 5))
    if projected is not None:
        headers["X-Firewall-Projected"] = str(round(float(projected), 5))
    if run_total is not None:
        headers["X-Firewall-Run-Total"] = str(round(float(run_total), 5))
    if cap is not None and cap != "":
        headers["X-Firewall-Cap"] = str(cap)
    if actual is not None:
        headers["X-Firewall-Cost"] = str(round(float(actual), 5))
    if latency_ms is not None:
        headers["X-Firewall-Latency-Ms"] = str(round(float(latency_ms), 1))
    if model is not None:
        headers["X-Firewall-Model"] = str(model)
    if call is not None:
        headers["X-Firewall-Call"] = str(call)

    return headers
