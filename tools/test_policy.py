"""
Unit tests for the policy engine (app/policy.py).
No server needed — tests the pure decide() function directly.
"""

import sys
import os

# Add project root to path so we can import app modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.policy import decide, signature


def default_rules():
    """Return a fresh copy of default rules for each test."""
    return {
        "run_cap": 3.0,
        "warn_at": 1.0,
        "pause_at": 2.0,
        "pause_timeout_seconds": 120,
        "loop_limit": 3,
        "max_calls_per_run": 30,
        "user_daily_cap": 50.0,
        "downgrade": {"at": None, "map": {"mock-large": "mock-small"}},
        "allowed_models": {},
    }


def test_allow():
    """Normal call within budget -> ALLOW."""
    d = decide(default_rules(), model="mock-large", feature="test", est=0.3,
               run_total=0.0, run_calls=0, reserved_after=0.3,
               loop_count=1, user_spent=0.0)
    assert d["action"] == "ALLOW", f"Expected ALLOW, got {d}"
    print("  PASS: test_allow")


def test_warn():
    """Projected above warn_at but below pause_at -> WARN."""
    d = decide(default_rules(), model="mock-large", feature="test", est=0.3,
               run_total=0.5, run_calls=2, reserved_after=0.8,
               loop_count=1, user_spent=0.0)
    assert d["action"] == "WARN", f"Expected WARN, got {d}"
    assert "warn" in d["reason"].lower()
    print("  PASS: test_warn")


def test_downgrade():
    """Projected above downgrade.at with model in map -> DOWNGRADE."""
    rules = default_rules()
    rules["downgrade"]["at"] = 1.5
    d = decide(rules, model="mock-large", feature="test", est=0.3,
               run_total=1.0, run_calls=3, reserved_after=0.8,
               loop_count=1, user_spent=0.0)
    assert d["action"] == "DOWNGRADE", f"Expected DOWNGRADE, got {d}"
    assert d["model"] == "mock-small", f"Expected mock-small, got {d['model']}"
    print("  PASS: test_downgrade")


def test_pause():
    """Projected above pause_at but below run_cap, no cap_override -> PAUSE."""
    d = decide(default_rules(), model="mock-large", feature="test", est=0.5,
               run_total=1.2, run_calls=4, reserved_after=1.0,
               loop_count=1, user_spent=0.0)
    # projected = 1.2 + 1.0 = 2.2, pause_at = 2.0, run_cap = 3.0
    assert d["action"] == "PAUSE", f"Expected PAUSE, got {d}"
    print("  PASS: test_pause")


def test_cap_block():
    """Projected above run_cap -> BLOCK."""
    d = decide(default_rules(), model="mock-large", feature="test", est=1.0,
               run_total=2.0, run_calls=5, reserved_after=1.5,
               loop_count=1, user_spent=0.0)
    # projected = 2.0 + 1.5 = 3.5, run_cap = 3.0
    assert d["action"] == "BLOCK", f"Expected BLOCK, got {d}"
    assert "cap" in d["reason"].lower()
    print("  PASS: test_cap_block")


def test_loop_block():
    """Loop count 4 with limit 3 -> BLOCK."""
    d = decide(default_rules(), model="mock-large", feature="test", est=0.1,
               run_total=0.2, run_calls=3, reserved_after=0.1,
               loop_count=4, user_spent=0.0)
    assert d["action"] == "BLOCK", f"Expected BLOCK, got {d}"
    assert "loop" in d["reason"].lower()
    print("  PASS: test_loop_block")


def test_loop_at_limit_allows():
    """Loop count exactly at the limit (3) -> NOT blocked (only > limit blocks)."""
    d = decide(default_rules(), model="mock-large", feature="test", est=0.1,
               run_total=0.0, run_calls=0, reserved_after=0.1,
               loop_count=3, user_spent=0.0)
    assert d["action"] != "BLOCK", f"Expected not BLOCK at loop_count=limit, got {d}"
    print("  PASS: test_loop_at_limit_allows")


def test_max_calls():
    """Exceeding max_calls_per_run -> BLOCK."""
    d = decide(default_rules(), model="mock-large", feature="test", est=0.1,
               run_total=0.2, run_calls=30, reserved_after=0.1,
               loop_count=1, user_spent=0.0)
    # run_calls + 1 = 31 > 30
    assert d["action"] == "BLOCK", f"Expected BLOCK, got {d}"
    assert "max calls" in d["reason"].lower()
    print("  PASS: test_max_calls")


def test_user_cap():
    """User daily cap exceeded -> BLOCK."""
    d = decide(default_rules(), model="mock-large", feature="test", est=1.0,
               run_total=0.0, run_calls=0, reserved_after=1.0,
               loop_count=1, user_spent=50.0)
    # user_spent + est = 51.0 > 50.0
    assert d["action"] == "BLOCK", f"Expected BLOCK, got {d}"
    assert "user" in d["reason"].lower() or "daily" in d["reason"].lower()
    print("  PASS: test_user_cap")


def test_model_restriction():
    """Model not in allowed_models for this feature -> BLOCK."""
    rules = default_rules()
    rules["allowed_models"] = {"shopping-agent": ["mock-small"]}
    d = decide(rules, model="mock-large", feature="shopping-agent", est=0.1,
               run_total=0.0, run_calls=0, reserved_after=0.1,
               loop_count=1, user_spent=0.0)
    assert d["action"] == "BLOCK", f"Expected BLOCK, got {d}"
    assert "not allowed" in d["reason"].lower()
    print("  PASS: test_model_restriction")


def test_approved_cap_override_no_pause():
    """With cap_override, projected > pause_at but < cap_override -> no PAUSE."""
    d = decide(default_rules(), model="mock-large", feature="test", est=0.5,
               run_total=1.2, run_calls=4, reserved_after=1.0,
               loop_count=1, user_spent=0.0, cap_override=6.0)
    # projected = 2.2, pause_at = 2.0, cap_override = 6.0
    # With cap_override: skip PAUSE, check against cap_override (2.2 < 6.0) -> WARN
    assert d["action"] != "PAUSE", f"Expected no PAUSE with cap_override, got {d}"
    assert d["action"] == "WARN", f"Expected WARN (projected > warn_at), got {d}"
    print("  PASS: test_approved_cap_override_no_pause")


def test_approved_cap_override_still_block():
    """With cap_override, projected > cap_override -> BLOCK."""
    d = decide(default_rules(), model="mock-large", feature="test", est=5.0,
               run_total=2.0, run_calls=5, reserved_after=5.0,
               loop_count=1, user_spent=0.0, cap_override=6.0)
    # projected = 2.0 + 5.0 = 7.0 > 6.0
    assert d["action"] == "BLOCK", f"Expected BLOCK even with cap_override, got {d}"
    print("  PASS: test_approved_cap_override_still_block")


def test_signature_equal():
    """Same messages produce the same signature."""
    msgs1 = [{"role": "user", "content": "hello world"}]
    msgs2 = [{"role": "user", "content": "hello world"}]
    assert signature(msgs1) == signature(msgs2), "Same messages should give same signature"
    print("  PASS: test_signature_equal")


def test_signature_different():
    """Different messages produce different signatures."""
    msgs1 = [{"role": "user", "content": "hello"}]
    msgs2 = [{"role": "user", "content": "world"}]
    assert signature(msgs1) != signature(msgs2), "Different messages should give different signatures"
    print("  PASS: test_signature_different")


def main():
    tests = [
        test_allow, test_warn, test_downgrade, test_pause,
        test_cap_block, test_loop_block, test_loop_at_limit_allows,
        test_max_calls, test_user_cap, test_model_restriction,
        test_approved_cap_override_no_pause, test_approved_cap_override_still_block,
        test_signature_equal, test_signature_different,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {t.__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"test_policy: {passed} passed, {failed} failed out of {len(tests)}")
    if failed:
        print("=== TEST_POLICY FAILED ===")
        sys.exit(1)
    else:
        print("=== TEST_POLICY PASSED ===")


if __name__ == "__main__":
    main()
