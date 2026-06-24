"""
computer_use/ — DEPRECATED (Day 81+)
=====================================

This package contains the TradingView browser-automation agent
(Playwright-based screen control, chart drawing, vision AI).  It is
intentionally NOT wired into the main runtime anymore.

Reason for deprecation:
    The system architecture moved to MT5-as-single-source-of-truth.
    TradingView data != MT5 broker data (different spreads, tick timing,
    liquidity conditions).  Mixing analysis from TradingView with
    execution on MT5 causes consistency issues.

Status:
    - Files are kept for reference and emergency fallback only
    - Main runtime (core/runtime.py) does NOT boot any computer_use modules
    - The Day 46 demo script (run_day46_demo.py) is preserved as documentation

If you need TradingView automation in the future:
    - Re-enable by adding a phase in core/runtime.py that boots these modules
    - Make sure the analysis-vs-execution consistency issue is addressed
      (e.g. by paper trading on TradingView data instead of MT5 execution)

DO NOT IMPORT from this package in new code.
"""

# Empty __init__ — no exports, so `from computer_use import X` will fail
# loudly if any module still depends on it.
