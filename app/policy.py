"""
Policy engine: loads rules from policies.json, computes loop signatures,
and makes pure-function decisions (no I/O in decide()).

Rules are hot-reloaded by checking the file's mtime.
"""

import json
import os
import hashlib
from pathlib import Path

_POLICIES_PATH = Path(__file__).resolve().parent.parent / "policies.json"
_rules_cache: dict | None = None
_rules_mtime: float = 0.0

# ---------------------------------------------------------------------------
# Load / save rules
# ---------------------------------------------------------------------------

def load_rules() -> dict:
    """Load policies.json, re-reading only when the file has changed."""
    global _rules_cache, _rules_mtime
    try:
        mtime = os.path.getmtime(_POLICIES_PATH)
        if _rules_cache is None or mtime != _rules_mtime:
            with open(_POLICIES_PATH, "r", encoding="utf-8") as f:
                _rules_cache = json.load(f)
            _rules_mtime = mtime
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[policy] WARNING: cannot load policies.json: {e}")
        if _rules_cache is None:
            _rules_cache = {
                "run_cap": 3.0, "warn_at": 1.0, "pause_at": 2.0,
                "pause_timeout_seconds": 120, "loop_limit": 3,
                "max_calls_per_run": 30, "user_daily_cap": 50.0,
                "downgrade": {"at": None, "map": {}}, "allowed_models": {},
            }
    return _rules_cache


# Keys that can be updated via the API
_EDITABLE_KEYS = {
    "run_cap", "warn_at", "pause_at", "user_daily_cap",
    "pause_timeout_seconds", "loop_limit", "max_calls_per_run", "downgrade_at",
}


def save_rules(updates: dict):
    """
    Merge updates into policies.json.
    Only the keys in _EDITABLE_KEYS are accepted.
    Empty string or None means disabled (set to null).
    Negative values and unknown keys raise ValueError.
    """
    global _rules_cache, _rules_mtime

    for key in updates:
        if key not in _EDITABLE_KEYS:
            raise ValueError(f"Unknown rule key: {key}")

    current = load_rules().copy()

    for key, val in updates.items():
        # Empty string or None → disabled
        if val is None or val == "" or val == "null":
            if key == "downgrade_at":
                dg = current.get("downgrade", {"at": None, "map": {}})
                dg["at"] = None
                current["downgrade"] = dg
            else:
                current[key] = None
            continue

        # Convert to number
        try:
            num = float(val)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid value for {key}: {val}")

        if num < 0:
            raise ValueError(f"Negative value for {key}: {num}")

        # Integer fields
        if key in ("loop_limit", "max_calls_per_run", "pause_timeout_seconds"):
            num = int(num)

        if key == "downgrade_at":
            dg = current.get("downgrade", {"at": None, "map": {}})
            dg["at"] = num
            current["downgrade"] = dg
        else:
            current[key] = num

    # Write back
    with open(_POLICIES_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)

    _rules_cache = current
    _rules_mtime = os.path.getmtime(_POLICIES_PATH)


# ---------------------------------------------------------------------------
# Loop signature
# ---------------------------------------------------------------------------

def signature(messages: list) -> str:
    """
    SHA1 hash of the last message (deterministic across processes).
    Returns the first 12 hex chars.
    PRD: never use Python's built-in hash().
    """
    if not messages:
        return "empty"
    last = messages[-1]
    raw = json.dumps(last, sort_keys=True).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Decision engine (pure function — no I/O)
# ---------------------------------------------------------------------------

def decide(
    rules: dict,
    *,
    model: str,
    feature: str,
    est: float,
    run_total: float,
    run_calls: int,
    reserved_after: float,
    loop_count: int,
    user_spent: float,
    cap_override: float | None = None,
) -> dict:
    """
    Evaluate rules in priority order (PRD §6). Returns:
      {action, reason, model, projected}
    First matching rule wins.
    """
    projected = round(run_total + reserved_after, 5)

    # Rule 1: model allow-list per feature
    allowed = rules.get("allowed_models", {})
    if feature in allowed and model not in allowed[feature]:
        return {
            "action": "BLOCK",
            "reason": f"Model {model} not allowed for feature {feature}",
            "model": model,
            "projected": projected,
        }

    # Rule 2: loop detection
    loop_limit = rules.get("loop_limit")
    if loop_limit is not None and loop_count > loop_limit:
        return {
            "action": "BLOCK",
            "reason": f"Loop detected: same message repeated {loop_count} times (limit {loop_limit})",
            "model": model,
            "projected": projected,
        }

    # Rule 3: max calls per run
    max_calls = rules.get("max_calls_per_run")
    if max_calls is not None and run_calls + 1 > max_calls:
        return {
            "action": "BLOCK",
            "reason": f"Max calls per run exceeded ({run_calls + 1} > {max_calls})",
            "model": model,
            "projected": projected,
        }

    # Rule 4: user daily cap
    user_cap = rules.get("user_daily_cap")
    if user_cap is not None and user_spent + est > user_cap:
        return {
            "action": "BLOCK",
            "reason": f"User daily cap Rs{user_cap} will be crossed (spent Rs{user_spent:.5f} + est Rs{est:.5f})",
            "model": model,
            "projected": projected,
        }

    # Rule 5: run cap (with override)
    cap = cap_override if cap_override is not None else rules.get("run_cap")
    if cap is not None and projected > cap:
        return {
            "action": "BLOCK",
            "reason": f"Run cap Rs{cap} will be crossed (projected Rs{projected:.5f})",
            "model": model,
            "projected": projected,
        }

    # Rule 6: pause threshold (only if no cap override — approved runs skip pause)
    pause_at = rules.get("pause_at")
    if pause_at is not None and projected > pause_at and cap_override is None:
        return {
            "action": "PAUSE",
            "reason": f"Projected Rs{projected:.5f} exceeds pause threshold Rs{pause_at}",
            "model": model,
            "projected": projected,
        }

    # Rule 7: downgrade
    dg = rules.get("downgrade", {})
    dg_at = dg.get("at") if dg else None
    dg_map = dg.get("map", {}) if dg else {}
    if dg_at is not None and projected > dg_at and model in dg_map:
        new_model = dg_map[model]
        return {
            "action": "DOWNGRADE",
            "reason": f"Projected Rs{projected:.5f} exceeds downgrade threshold Rs{dg_at} ({model} -> {new_model})",
            "model": new_model,
            "projected": projected,
        }

    # Rule 8: warn
    warn_at = rules.get("warn_at")
    if warn_at is not None and projected > warn_at:
        return {
            "action": "WARN",
            "reason": f"Projected Rs{projected:.5f} exceeds warn threshold Rs{warn_at}",
            "model": model,
            "projected": projected,
        }

    # Rule 9: allow
    return {
        "action": "ALLOW",
        "reason": "Within budget",
        "model": model,
        "projected": projected,
    }
