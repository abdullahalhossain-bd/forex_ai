"""Tests for Book Pages 136-151 — Final Risk Management Guardrails."""
import sys
sys.path.insert(0, "/home/z/my-project/forex_ai")

import warnings
warnings.filterwarnings("ignore")

from risk.book_guardrails import (
    check_correlation_exposure,
    check_anti_revenge_trading,
    check_cost_aware_ev,
    run_all_guardrails,
    DEFAULT_CORRELATION_THRESHOLD,
    DEFAULT_LOSS_STREAK_THRESHOLD,
)


# ─── TESTS ────────────────────────────────────────────────────

def test_correlation_no_open_positions():
    """No open positions → pass."""
    print("\n========== TEST 1: No open positions ==========")
    r = check_correlation_exposure(
        proposed_pair="EURUSD",
        proposed_direction="BUY",
        open_positions=[],
    )
    assert r.passed == True
    print(f"  Passed: {r.passed}, reason: {r.reason}")
    print("TEST 1 passed")


def test_correlation_same_direction_violation():
    """EURUSD long + GBPUSD long → block (correlation 0.85)."""
    print("\n========== TEST 2: Same-direction correlated pairs ==========")
    r = check_correlation_exposure(
        proposed_pair="EURUSD",
        proposed_direction="BUY",
        open_positions=[{"pair": "GBPUSD", "direction": "BUY"}],
    )
    assert r.passed == False
    assert "Overconcentrated" in r.reason
    print(f"  Passed: {r.passed}, reason: {r.reason[:100]}")
    print("TEST 2 passed")


def test_correlation_opposite_direction_partial_hedge():
    """EURUSD long + GBPUSD short → partial hedge (less risky, still flagged but allowed)."""
    print("\n========== TEST 3: Opposite-direction correlated (partial hedge) ==========")
    r = check_correlation_exposure(
        proposed_pair="EURUSD",
        proposed_direction="BUY",
        open_positions=[{"pair": "GBPUSD", "direction": "SELL"}],
    )
    # Opposite direction on correlated pair = partial hedge — should pass
    print(f"  Passed: {r.passed}, reason: {r.reason[:100]}")
    # The current implementation flags correlated opposite direction but as "partial hedge"
    # and doesn't block (only same_direction violations block)
    assert r.passed == True
    print("TEST 3 passed")


def test_correlation_uncorrelated_pairs_pass():
    """EURUSD long + USDJPY short → low correlation, passes."""
    print("\n========== TEST 4: Uncorrelated pairs ==========")
    r = check_correlation_exposure(
        proposed_pair="EURUSD",
        proposed_direction="BUY",
        open_positions=[{"pair": "USDJPY", "direction": "SELL"}],
    )
    # EURUSD-USDJPY correlation = -0.40 (below 0.70 threshold)
    assert r.passed == True
    print(f"  Passed: {r.passed}, reason: {r.reason[:100]}")
    print("TEST 4 passed")


def test_anti_revenge_no_loss_streak():
    """No loss streak → pass even if oversized."""
    print("\n========== TEST 5: No loss streak ==========")
    r = check_anti_revenge_trading(
        proposed_lot_size=0.50,
        normal_lot_size=0.20,
        consecutive_losses=1,
    )
    assert r.passed == True
    print(f"  Passed: {r.passed}, reason: {r.reason[:100]}")
    print("TEST 5 passed")


def test_anti_revenge_loss_streak_normal_size():
    """Loss streak + normal size → pass (disciplined)."""
    print("\n========== TEST 6: Loss streak + normal size ==========")
    r = check_anti_revenge_trading(
        proposed_lot_size=0.20,
        normal_lot_size=0.20,
        consecutive_losses=3,
    )
    assert r.passed == True
    print(f"  Passed: {r.passed}, reason: {r.reason[:100]}")
    print("TEST 6 passed")


def test_anti_revenge_loss_streak_oversized():
    """Loss streak + oversized → BLOCK."""
    print("\n========== TEST 7: Revenge trading detected ==========")
    r = check_anti_revenge_trading(
        proposed_lot_size=0.50,
        normal_lot_size=0.20,
        consecutive_losses=3,
    )
    assert r.passed == False
    assert "REVENGE TRADING" in r.reason
    print(f"  Passed: {r.passed}, reason: {r.reason[:100]}")
    print("TEST 7 passed")


def test_cost_aware_ev_positive():
    """High expected PnL → pass after costs."""
    print("\n========== TEST 8: Positive net EV ==========")
    r = check_cost_aware_ev(
        expected_pnl_pips=20.0,
        pair="EURUSD",
    )
    assert r.passed == True
    print(f"  Passed: {r.passed}, net_ev: {r.details['net_ev_pips']} pips")
    print("TEST 8 passed")


def test_cost_aware_ev_negative():
    """Low expected PnL → reject (net EV ≤ 0)."""
    print("\n========== TEST 9: Negative net EV ==========")
    r = check_cost_aware_ev(
        expected_pnl_pips=2.0,
        pair="EURUSD",
    )
    assert r.passed == False
    assert "Net EV after costs is" in r.reason
    print(f"  Passed: {r.passed}, net_ev: {r.details['net_ev_pips']} pips")
    print("TEST 9 passed")


def test_cost_aware_ev_below_minimum():
    """Positive but below minimum EV → reject."""
    print("\n========== TEST 10: Below minimum EV ==========")
    r = check_cost_aware_ev(
        expected_pnl_pips=3.5,  # 3.5 - 2.2 costs = 1.3 pips (positive but low)
        pair="EURUSD",
        min_net_ev_pips=2.0,
    )
    assert r.passed == False
    print(f"  Passed: {r.passed}, net_ev: {r.details['net_ev_pips']} pips")
    print("TEST 10 passed")


def test_cost_aware_ev_xauusd():
    """XAUUSD has higher spread — verify lookup works."""
    print("\n========== TEST 11: XAUUSD spread lookup ==========")
    r = check_cost_aware_ev(
        expected_pnl_pips=50.0,
        pair="XAUUSD",
    )
    assert r.details["spread_pips"] == 25.0  # XAUUSD default spread
    print(f"  XAUUSD spread: {r.details['spread_pips']} pips")
    print(f"  Net EV: {r.details['net_ev_pips']} pips")
    assert r.passed == True
    print("TEST 11 passed")


def test_aggregate_all_pass():
    """All 3 guardrails pass."""
    print("\n========== TEST 12: All guardrails pass ==========")
    agg = run_all_guardrails(
        proposed_pair="EURUSD",
        proposed_direction="BUY",
        proposed_lot_size=0.20,
        normal_lot_size=0.20,
        consecutive_losses=0,
        open_positions=[],
        expected_pnl_pips=20.0,
    )
    print(f"  Passed: {agg['passed_count']}/{agg['total_count']}")
    assert agg["all_passed"] == True
    assert agg["passed_count"] == 3
    print("TEST 12 passed")


def test_aggregate_some_fail():
    """Multiple guardrails fail → aggregate reports block_reason."""
    print("\n========== TEST 13: Aggregate with failures ==========")
    agg = run_all_guardrails(
        proposed_pair="EURUSD",
        proposed_direction="BUY",
        proposed_lot_size=0.50,
        normal_lot_size=0.20,
        consecutive_losses=3,
        open_positions=[{"pair": "GBPUSD", "direction": "BUY"}],
        expected_pnl_pips=2.0,
    )
    print(f"  Passed: {agg['passed_count']}/{agg['total_count']}")
    print(f"  Block reason: {agg['block_reason'][:80]}")
    assert agg["all_passed"] == False
    assert agg["passed_count"] < 3
    assert agg["block_reason"] is not None
    print("TEST 13 passed")


def test_schema_conformance():
    """Verify GuardrailResult schema."""
    print("\n========== TEST 14: Schema conformance ==========")
    r = check_anti_revenge_trading(
        proposed_lot_size=0.10,
        normal_lot_size=0.10,
        consecutive_losses=0,
    )
    d = r.to_dict()
    for field in ["rule_name", "passed", "reason", "details"]:
        assert field in d
    assert isinstance(d["passed"], bool)
    assert isinstance(d["details"], dict)
    print(f"  Schema OK: {d['rule_name']}, passed={d['passed']}")
    print("TEST 14 passed")


if __name__ == "__main__":
    test_correlation_no_open_positions()
    test_correlation_same_direction_violation()
    test_correlation_opposite_direction_partial_hedge()
    test_correlation_uncorrelated_pairs_pass()
    test_anti_revenge_no_loss_streak()
    test_anti_revenge_loss_streak_normal_size()
    test_anti_revenge_loss_streak_oversized()
    test_cost_aware_ev_positive()
    test_cost_aware_ev_negative()
    test_cost_aware_ev_below_minimum()
    test_cost_aware_ev_xauusd()
    test_aggregate_all_pass()
    test_aggregate_some_fail()
    test_schema_conformance()
    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
    print("=" * 50)
