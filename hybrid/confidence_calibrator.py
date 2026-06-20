# hybrid/confidence_calibrator.py  —  Day 49 Bonus #2 | Confidence Calibration ⭐
# ============================================================
# Doc Bonus #2:
#     "85% confidence setup — বাস্তবে win rate কত? তারপর confidence
#      adjust করবে।"
#
# এটা একটা classic ML concept-এর lightweight version — "calibration".
# একটা ভালো-calibrated model-এর 80% confidence trade-গুলো বাস্তবেই
# প্রায় ৮০% সময় win করা উচিত। বাস্তবে practice-এ models সাধারণত
# overconfident হয় — তাই calibration historical win-rate দিয়ে
# confidence-কে "সত্যি" সংখ্যার কাছে টেনে আনে।
#
# Method: bucket-based calibration (Platt scaling-এর simpler বিকল্প,
# কোনো extra ML library লাগে না)।
#   1. প্রতিটা closed trade-কে confidence bucket-এ ভাগ করো (0-50,
#      50-60, 60-70, 70-80, 80-90, 90-100)
#   2. প্রতি bucket-এর actual win rate বের করো
#   3. নতুন prediction আসলে তার bucket-এর historical win rate দিয়ে
#      blend করো (raw confidence-কে পুরোপুরি override না করে — sample
#      size কম থাকলে raw confidence-কেই বেশি weight দেওয়া হয়)
#
# Data source: learning_agent.py-এর memory/trade_memory.json
# (LearningAgent ইতিমধ্যে confidence + result/outcome save করে —
# এই module শুধু read করে analyze করে, নতুন storage বানায়নি)।
# ============================================================

import json
import os

from utils.logger import get_logger

log = get_logger("confidence_calibrator")

TRADE_MEMORY_PATH = "memory/trade_memory.json"

BUCKETS = [(0, 50), (50, 60), (60, 70), (70, 80), (80, 90), (90, 101)]
MIN_SAMPLES_FOR_TRUST = 10   # bucket-এ এর কম sample থাকলে raw confidence-কেই বেশি বিশ্বাস করো


class ConfidenceCalibrator:
    """
    Usage:
        cal = ConfidenceCalibrator()
        report = cal.build_calibration_report()
        adjusted = cal.calibrate(raw_confidence=85)
        # adjusted ~ 85-এর bucket-এ historical win rate যদি ৭০% হয়,
        # তাহলে blend করে কিছুটা কমানো confidence ফেরত দেবে
    """

    def __init__(self, memory_path: str = TRADE_MEMORY_PATH):
        self.memory_path = memory_path

    # ═══════════════════════════════════════════════════════
    # 1. BUCKET ANALYSIS
    # ═══════════════════════════════════════════════════════

    def build_calibration_report(self) -> dict:
        """প্রতিটা confidence bucket-এর জন্য predicted vs actual win rate বের করো।"""
        history = self._load_closed_trades()
        report = {}

        for lo, hi in BUCKETS:
            bucket_trades = [
                t for t in history
                if t.get("confidence") is not None and lo <= t["confidence"] < hi
            ]
            n = len(bucket_trades)
            if n == 0:
                report[f"{lo}-{hi}"] = {
                    "samples": 0, "predicted_avg": None,
                    "actual_win_rate": None, "trustworthy": False,
                }
                continue

            wins = sum(1 for t in bucket_trades if t.get("result") == "WIN")
            predicted_avg = round(sum(t["confidence"] for t in bucket_trades) / n, 1)
            actual_win_rate = round(wins / n * 100, 1)

            report[f"{lo}-{hi}"] = {
                "samples": n,
                "predicted_avg": predicted_avg,
                "actual_win_rate": actual_win_rate,
                "trustworthy": n >= MIN_SAMPLES_FOR_TRUST,
                "gap": round(predicted_avg - actual_win_rate, 1),
            }

        return report

    # ═══════════════════════════════════════════════════════
    # 2. CALIBRATE A NEW PREDICTION  ⭐⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════

    def calibrate(self, raw_confidence: int) -> dict:
        """
        নতুন trade-এর raw confidence নিয়ে historical bucket win-rate দিয়ে
        adjust করো।

        Blend logic:
            sample কম (< MIN_SAMPLES_FOR_TRUST)  → raw confidence-কেই বেশি weight (90%)
            sample যথেষ্ট (>= MIN_SAMPLES_FOR_TRUST) → historical win rate-কে বেশি weight (70%)

        এভাবে শুরুতে (যখন data কম) AI-এর raw judgment respect করা হয়,
        পরে যত বেশি trade হবে তত বেশি reality-grounded calibration হবে।
        """
        report = self.build_calibration_report()
        bucket_key = self._find_bucket(raw_confidence)
        bucket = report.get(bucket_key, {})

        if not bucket or bucket.get("samples", 0) == 0:
            return {
                "raw_confidence": raw_confidence,
                "calibrated_confidence": raw_confidence,
                "bucket": bucket_key,
                "adjustment": 0,
                "note": "No historical data for this bucket — using raw confidence",
            }

        actual_win_rate = bucket["actual_win_rate"]
        n = bucket["samples"]

        if n >= MIN_SAMPLES_FOR_TRUST:
            weight_actual = 0.70
        else:
            # sample size বাড়ার সাথে সাথে gradually actual win-rate-কে বেশি বিশ্বাস করো
            weight_actual = 0.30 * (n / MIN_SAMPLES_FOR_TRUST)

        weight_raw = 1 - weight_actual
        calibrated = round(raw_confidence * weight_raw + actual_win_rate * weight_actual)
        calibrated = max(0, min(99, calibrated))

        result = {
            "raw_confidence": raw_confidence,
            "calibrated_confidence": calibrated,
            "bucket": bucket_key,
            "bucket_samples": n,
            "bucket_actual_win_rate": actual_win_rate,
            "adjustment": calibrated - raw_confidence,
            "note": (
                f"Bucket {bucket_key}% historically wins {actual_win_rate}% of the time "
                f"(n={n}) — {'trusted' if n >= MIN_SAMPLES_FOR_TRUST else 'low-sample, partial trust'}"
            ),
        }

        if abs(result["adjustment"]) >= 10:
            log.info(
                f"[ConfidenceCalibrator] ⚠️ Large adjustment: {raw_confidence}% → "
                f"{calibrated}% (bucket {bucket_key} actual win-rate {actual_win_rate}%)"
            )
        return result

    def _find_bucket(self, confidence: int) -> str:
        for lo, hi in BUCKETS:
            if lo <= confidence < hi:
                return f"{lo}-{hi}"
        return f"{BUCKETS[-1][0]}-{BUCKETS[-1][1]}"

    # ═══════════════════════════════════════════════════════
    # 3. OVERALL CALIBRATION HEALTH  (is the AI over/under-confident?)
    # ═══════════════════════════════════════════════════════

    def get_calibration_health(self) -> dict:
        """
        Overall — AI কি systematically overconfident না underconfident?
        Trustworthy bucket-গুলোর gap (predicted_avg - actual_win_rate)
        average করে বোঝা যায়।
        """
        report = self.build_calibration_report()
        trustworthy = [b for b in report.values() if b.get("trustworthy")]

        if not trustworthy:
            return {"status": "INSUFFICIENT_DATA", "avg_gap": None}

        avg_gap = round(sum(b["gap"] for b in trustworthy) / len(trustworthy), 1)

        if avg_gap > 10:
            status = "OVERCONFIDENT"
        elif avg_gap < -10:
            status = "UNDERCONFIDENT"
        else:
            status = "WELL_CALIBRATED"

        return {"status": status, "avg_gap": avg_gap, "trustworthy_buckets": len(trustworthy)}

    # ═══════════════════════════════════════════════════════
    # INTERNAL
    # ═══════════════════════════════════════════════════════

    def _load_closed_trades(self) -> list:
        if not os.path.exists(self.memory_path):
            return []
        try:
            with open(self.memory_path, encoding="utf-8") as f:
                history = json.load(f)
        except Exception as e:
            log.warning(f"[ConfidenceCalibrator] Could not load trade memory: {e}")
            return []
        return [t for t in history if t.get("result") in ("WIN", "LOSS")]

    # ═══════════════════════════════════════════════════════
    # PRINT SUMMARY
    # ═══════════════════════════════════════════════════════

    def print_report(self) -> None:
        report = self.build_calibration_report()
        health = self.get_calibration_health()
        bar = "═" * 54
        print(f"\n{bar}")
        print("  🎯  CONFIDENCE CALIBRATION  (Day 49)")
        print(bar)
        print(f"  Overall status : {health['status']}  (avg gap: {health.get('avg_gap')})")
        print()
        for bucket, stats in report.items():
            if stats["samples"] == 0:
                print(f"  {bucket:<8}%  — no data")
                continue
            trust = "✅" if stats["trustworthy"] else "🔸"
            print(
                f"  {bucket:<8}%  {trust}  n={stats['samples']:<4} "
                f"predicted_avg={stats['predicted_avg']:<6} "
                f"actual_win={stats['actual_win_rate']:<6} "
                f"gap={stats['gap']:+}"
            )
        print(bar + "\n")