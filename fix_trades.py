#!/usr/bin/env python3
# fix_bug3_trader.py — Day 37 Hotfix: Bug 3 Only (trader.py)
# ============================================================
# Bug 3: trader.py-এ Day 76 Sizer threshold fix।
# প্রথম 100 decisions-এ minimum confidence 55% → 38% করা হবে।
# এতে নতুন bot early-phase-এ trade করতে পারবে এবং শিখতে পারবে।
#
# Usage:
#   python fix_bug3_trader.py           # fix apply করো
#   python fix_bug3_trader.py --check   # dry run
#   python fix_bug3_trader.py --verify  # verify only
# ============================================================

import argparse
import os
import re
import shutil
from datetime import datetime

PROJECT_ROOT = os.getcwd()
TRADER_PATH  = os.path.join(PROJECT_ROOT, "trader.py")
BACKUP_DIR   = os.path.join(PROJECT_ROOT, "backups", f"hotfix_bug3_{datetime.now().strftime('%Y%m%d_%H%M%S')}")


def _backup(filepath: str) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_path = os.path.join(BACKUP_DIR, os.path.basename(filepath))
    shutil.copy2(filepath, backup_path)
    return backup_path


def _read(filepath: str) -> str | None:
    if not os.path.exists(filepath):
        print(f"  ❌ File not found: {filepath}")
        return None
    with open(filepath, encoding="utf-8") as f:
        return f.read()


def _write(filepath: str, content: str) -> None:
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def fix_bug3(check_only: bool = False) -> bool:
    print(f"\n── Bug 3: Day 76 Sizer Threshold ({TRADER_PATH}) ──")

    content = _read(TRADER_PATH)
    if content is None:
        return False

    # Already patched?
    if "HOTFIX_BUG3" in content:
        print("  ✅ Already patched")
        return True

    # ── Step 1: "Day 76 Sizer" block খুঁজো ─────────────────────
    # লগে দেখা গেছে:
    #   [Day 76 Sizer] REJECTED EURUSD BUY — Confidence 34% < 55% minimum → reject
    # তাই এই pattern খুঁজছি:
    #   if confidence < 55  অথবা  if conf < 55  অথবা  < 55% minimum
    #
    # Pattern 1: if confidence/conf < NUMBER (55 বা অন্য value)
    pattern1 = re.compile(
        r'([ \t]*)(if (?:confidence|conf)\b[^\n]*< (\d+)[^\n]*\n'
        r'([ \t]*log\.[^\n]*[Rr]eject[^\n]*\n)?'
        r'[ \t]*return False)',
        re.MULTILINE
    )

    # Pattern 2: Day 76 Sizer block comment-এর পরে threshold
    pattern2 = re.compile(
        r'(Day 76 Sizer[^\n]*\n(?:[^\n]*\n){0,5}?)'
        r'([ \t]*)(if (?:confidence|conf)\b[^\n]*< (\d+))',
        re.MULTILINE
    )

    # Pattern 3: সরাসরি "< 55" খোঁজো Day 76 Sizer-এর কাছাকাছি
    day76_idx = content.find("Day 76 Sizer")
    if day76_idx == -1:
        day76_idx = content.find("Day76 Sizer")

    if day76_idx == -1:
        print("  ❌ 'Day 76 Sizer' string পাওয়া যায়নি trader.py-এ।")
        _print_manual()
        return False

    # Day 76 Sizer block-এর আশেপাশে (±500 chars) threshold খুঁজো
    search_start = max(0, day76_idx - 200)
    search_end   = min(len(content), day76_idx + 1000)
    block        = content[search_start:search_end]

    # এই block-এ "< NUMBER" pattern খুঁজো
    threshold_pattern = re.compile(r'< (\d+)', re.MULTILINE)
    threshold_matches = list(threshold_pattern.finditer(block))

    if not threshold_matches:
        print("  ❌ Threshold value পাওয়া যায়নি। Manual patch করুন।")
        _print_manual()
        return False

    # সব match দেখাও (debug)
    print(f"  ℹ️  Day 76 Sizer block-এ threshold candidates:")
    for m in threshold_matches[:5]:
        ctx_start = max(0, m.start() - 40)
        ctx_end   = min(len(block), m.end() + 40)
        print(f"      ...{block[ctx_start:ctx_end].strip()}...")

    # ── Step 2: Best match বেছে নাও ─────────────────────────────
    # "55" বা "60" বা লগে দেখা মানটা খুঁজো
    best_match = None
    for m in threshold_matches:
        val = int(m.group(1))
        if 40 <= val <= 70:  # reasonable threshold range
            best_match = m
            break

    if not best_match:
        best_match = threshold_matches[0]

    threshold_val = int(best_match.group(1))
    print(f"  ℹ️  Found threshold: {threshold_val}")

    if check_only:
        print(f"  🔍 Would change threshold logic: {threshold_val} → dynamic (38 early, {threshold_val} normal)")
        return True

    # ── Step 3: Patch apply করো ──────────────────────────────────
    # Block-এ threshold-এর আগে dynamic logic inject করবো।
    # Block absolute position calculate করো
    abs_threshold_pos = search_start + best_match.start()

    # থ্রেশহোল্ড-এর আগের line খুঁজো (indentation পেতে)
    line_start = content.rfind("\n", 0, abs_threshold_pos) + 1
    indent     = re.match(r"([ \t]*)", content[line_start:]).group(1)

    # Injection: dynamic threshold variable
    injection = (
        f"# ── HOTFIX_BUG3 Day37: early-phase dynamic threshold ───────────\n"
        f"{indent}# নতুন bot-এ sample কম থাকলে confidence naturally কম আসে।\n"
        f"{indent}# প্রথম 100 decisions-এ threshold কম রাখি, পরে normal হবে।\n"
        f"{indent}_day76_min_conf = {threshold_val}\n"
        f"{indent}try:\n"
        f"{indent}    _total_dec = getattr(self, '_total_decisions', None)\n"
        f"{indent}    if _total_dec is None:\n"
        f"{indent}        from database.db import get_db as _gdb\n"
        f"{indent}        _total_dec = _gdb().count_rows('decisions') if hasattr(_gdb(), 'count_rows') else 999\n"
        f"{indent}    if int(_total_dec) < 100:\n"
        f"{indent}        _day76_min_conf = 38\n"
        f"{indent}except Exception:\n"
        f"{indent}    pass\n"
        f"{indent}# ──────────────────────────────────────────────────────────────\n"
        f"{indent}"
    )

    # "< threshold_val" → "< _day76_min_conf" (শুধু Day 76 block-এ)
    # আগে injection insert করবো, তারপর replace করবো
    new_content = (
        content[:line_start]
        + injection
        + content[line_start:]
    )

    # এখন threshold replace করো (injection-এর পরে position shift হয়েছে)
    new_content = new_content.replace(
        f"< {threshold_val}",
        f"< _day76_min_conf",
        1  # শুধু প্রথম occurrence (Day 76 block-এর কাছেরটা)
    )

    # Log message-এও threshold update করো (optional, improves readability)
    new_content = new_content.replace(
        f"< {threshold_val}% minimum",
        f"< {{_day76_min_conf}}% minimum",
        1
    )
    new_content = new_content.replace(
        f"{threshold_val}% minimum",
        f"{{_day76_min_conf}}% minimum",
        1
    )

    backup = _backup(TRADER_PATH)
    print(f"  📦 Backup: {backup}")
    _write(TRADER_PATH, new_content)
    print(f"  ✅ Patched: dynamic threshold injected (early={38}, normal={threshold_val})")
    return True


def verify() -> bool:
    print("\n══════════════════════════════════════════")
    print("  🔍  VERIFICATION")
    print("══════════════════════════════════════════")
    content = _read(TRADER_PATH)
    if content is None:
        return False
    has = "HOTFIX_BUG3" in content and "_day76_min_conf" in content
    print(f"  {'✅' if has else '❌'} Bug 3 — dynamic threshold in trader.py")
    if has:
        print("  ✅  Patch সফলভাবে apply হয়েছে!")
    else:
        print("  ❌  Patch apply হয়নি।")
    print("══════════════════════════════════════════")
    return has


def _print_manual():
    print("""
  ── Manual Patch Instructions ──
  trader.py-এ "Day 76 Sizer" section খুঁজুন।
  এরকম কিছু দেখতে পাবেন:

      if confidence < 55:
          log.info(f"[Day 76 Sizer] REJECTED ... Confidence {confidence}% < 55% minimum → reject")
          return False

  এর ঠিক আগে এটা যোগ করুন:

      # HOTFIX_BUG3: early-phase dynamic threshold
      _day76_min_conf = 55
      try:
          if getattr(self, '_total_decisions', 999) < 100:
              _day76_min_conf = 38
      except Exception:
          pass

  এবং চেক পরিবর্তন করুন:

      if confidence < _day76_min_conf:
          log.info(f"[Day 76 Sizer] REJECTED ... Confidence {confidence}% < {_day76_min_conf}% minimum → reject")
          return False
""")


def main():
    parser = argparse.ArgumentParser(description="Bug 3 Fix: trader.py Day 76 Sizer")
    parser.add_argument("--check",  action="store_true", help="Dry run")
    parser.add_argument("--verify", action="store_true", help="Verify only")
    args = parser.parse_args()

    print("══════════════════════════════════════════")
    print("  🔧  Bug 3 Patcher — trader.py")
    print(f"  📁  {TRADER_PATH}")
    print("══════════════════════════════════════════")

    if args.verify:
        verify()
        return

    if args.check:
        print("  ℹ️  DRY RUN\n")

    ok = fix_bug3(check_only=args.check)

    if not args.check:
        verify()

    if ok:
        print("\n  পরবর্তী পদক্ষেপ: bot restart করুন।")
        print("  লগে দেখবেন confidence ≥ 38% হলে trade pass হবে।")


if __name__ == "__main__":
    main()