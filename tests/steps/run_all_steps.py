#!/usr/bin/env python3
"""
tests/steps/run_all_steps.py
==============================
MASTER TEST RUNNER — সব ১১টা step একসাথে চালায়

প্রতিটা step আলাদাভাবে execute করে এবং শেষে একটা summary দেখায়:
  - কোন step pass করেছে
  - কোন step fail করেছে
  - প্রতিটার duration

Usage:
    python tests/steps/run_all_steps.py                    # EURUSD, no test trade
    python tests/steps/run_all_steps.py GBPUSD XAUUSD      # multiple symbols
    python tests/steps/run_all_steps.py EURUSD --trade     # with test trade
"""
import os
import sys
import subprocess
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(str(PROJECT_ROOT / ".env"))


def _c(text, color):
    if not sys.stdout.isatty():
        return text
    codes = {"red": "31", "green": "32", "yellow": "33",
             "cyan": "36", "bold": "1", "gray": "90"}
    return f"\033[{codes.get(color, '0')}m{text}\033[0m"


def run_step(step_num, script_name, symbol, do_trade=False):
    """একটা step চালায় এবং (success, duration) return করে।"""
    script_path = PROJECT_ROOT / "tests" / "steps" / script_name
    if not script_path.exists():
        return False, 0, f"Script not found: {script_path}"

    # Build command
    cmd = [sys.executable, str(script_path)]
    if script_name in ("step_02_market_data.py", "step_03_indicators.py",
                       "step_04_smc_engine.py", "step_06_signal_engine.py",
                       "step_08_decision_agent.py", "step_09_risk_engine.py"):
        cmd.append(symbol)
    elif script_name == "step_11_execution.py" and do_trade:
        cmd.append("--trade")

    t0 = time.time()
    try:
        result = subprocess.run(
            cmd, cwd=str(PROJECT_ROOT),
            capture_output=True, text=True, timeout=120,
        )
        elapsed = time.time() - t0
        success = result.returncode == 0
        return success, elapsed, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, time.time() - t0, "TIMEOUT (120s)"
    except Exception as e:
        return False, time.time() - t0, str(e)


def main():
    # Parse args
    symbols = []
    do_trade = False
    for arg in sys.argv[1:]:
        if arg == "--trade":
            do_trade = True
        elif not arg.startswith("-"):
            symbols.append(arg.upper())
    if not symbols:
        symbols = ["EURUSD"]

    # Steps to run
    steps = [
        (1,  "step_01_mt5_connection.py",    "MT5 Connection"),
        (2,  "step_02_market_data.py",       "Market Data Fetch"),
        (3,  "step_03_indicators.py",        "Technical Indicators"),
        (4,  "step_04_smc_engine.py",        "SMC Engine"),
        (5,  "step_05_session.py",           "Session Analyzer"),
        (6,  "step_06_signal_engine.py",     "Signal Engine"),
        (7,  "step_07_llm_analyst.py",       "LLM Analyst"),
        (8,  "step_08_decision_agent.py",    "Decision Agent"),
        (9,  "step_09_risk_engine.py",       "Risk Engine"),
        (10, "step_10_trade_permission.py",  "Trade Permission"),
        (11, "step_11_execution.py",         "Execution Router"),
    ]

    print()
    print(_c("=" * 70, "bold"))
    print(_c("  FOREX AI — FULL PIPELINE TEST (11 Steps)", "bold"))
    print(_c("=" * 70, "bold"))
    print(f"  Symbols   : {', '.join(symbols)}")
    print(f"  Test trade: {'YES (--trade)' if do_trade else 'NO'}")
    print(f"  Time      : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Run each step for each symbol
    all_results = []
    for symbol in symbols:
        print(_c(f"\n{'─' * 70}", "cyan"))
        print(_c(f"  SYMBOL: {symbol}", "bold"))
        print(_c(f"{'─' * 70}", "cyan"))

        for step_num, script, name in steps:
            print(f"\n  [{step_num:2d}/11] {name}...")
            success, elapsed, output = run_step(step_num, script, symbol, do_trade)

            # Show last few lines of output
            lines = output.strip().splitlines() if output else []
            # Show the summary line (last few lines)
            for line in lines[-5:]:
                print(f"       {line}")

            status = _c("[PASS]", "green") if success else _c("[FAIL]", "red")
            print(f"  {status} {name} ({elapsed:.1f}s)")

            all_results.append({
                "symbol": symbol,
                "step": step_num,
                "name": name,
                "success": success,
                "elapsed": elapsed,
            })

            # If step 1 fails, no point continuing (MT5 not connected)
            if step_num == 1 and not success:
                print(_c("\n  ⛔ Step 1 failed — MT5 not connected. বাকি steps skip করা হলো।", "red"))
                for remaining_num, remaining_name, _ in steps[1:]:
                    all_results.append({
                        "symbol": symbol, "step": remaining_num,
                        "name": remaining_name, "success": False, "elapsed": 0,
                    })
                break

    # ── Final Summary ──
    print()
    print(_c("=" * 70, "bold"))
    print(_c("  FINAL SUMMARY", "bold"))
    print(_c("=" * 70, "bold"))

    for symbol in symbols:
        sym_results = [r for r in all_results if r["symbol"] == symbol]
        passed = sum(1 for r in sym_results if r["success"])
        total = len(sym_results)
        status = _c("✅", "green") if passed == total else _c("❌", "red")
        print(f"\n  {status} {symbol}: {passed}/{total} steps passed")
        for r in sym_results:
            mark = _c("✓", "green") if r["success"] else _c("✗", "red")
            print(f"     {mark} Step {r['step']:2d}: {r['name']}")

    # Overall
    total_passed = sum(1 for r in all_results if r["success"])
    total_all = len(all_results)
    print()
    print(f"  Total: {total_passed}/{total_all} steps passed")

    if total_passed == total_all:
        print(_c("\n  🎉 সব steps pass করেছে! Trading pipeline সম্পূর্ণ কাজ করছে।", "green"))
    else:
        failed = [r for r in all_results if not r["success"]]
        print(_c(f"\n  ⚠️  {len(failed)} step(s) failed:", "yellow"))
        print(_c("  ব্যর্থ steps আলাদাভাবে চালান:", "yellow"))
        for r in failed:
            print(_c(f"     python tests/steps/step_{r['step']:02d}_*.py {r['symbol']}", "yellow"))

    print()
    return 0 if total_passed == total_all else 1


if __name__ == "__main__":
    sys.exit(main())
