# analysis/support_resistance.py
# ============================================================
# Day 5 — Support & Resistance Engine
# AI Trader-এর Market Structure Foundation
# ============================================================

import pandas as pd
import numpy as np


class SupportResistance:
    """
    AI Trader-এর S/R detection engine।

    সে যা করতে পারে:
    - Swing High / Swing Low detect করে
    - Price zones cluster করে
    - Pivot levels calculate করে
    - Current price থেকে nearest S/R বলে
    - AI Brain-এর জন্য context তৈরি করে
    """

    def __init__(self, window=5, tolerance=0.0015):
        """
        window     : Swing detect করতে কতটা candle দেখবে (দুই পাশে)
        tolerance  : কত কাছাকাছি হলে একই zone ধরবে (price difference)
        """
        self.window    = window
        self.tolerance = tolerance

    # ─────────────────────────────────────────────
    # STEP 1: Swing High & Low
    # ─────────────────────────────────────────────

    def find_swing_highs(self, df):
        """
        Swing High — আশেপাশের candle-এর চেয়ে high বেশি।
        এগুলোই Resistance zone-এর উৎস।
        """
        swing_highs = []
        w = self.window

        for i in range(w, len(df) - w):
            current = df['high'].iloc[i]
            left    = df['high'].iloc[i - w : i]
            right   = df['high'].iloc[i + 1 : i + w + 1]

            if current > left.max() and current > right.max():
                swing_highs.append({
                    'index': i,
                    'time':  df.index[i],
                    'price': round(current, 5),
                })

        return swing_highs

    def find_swing_lows(self, df):
        """
        Swing Low — আশেপাশের candle-এর চেয়ে low কম।
        এগুলোই Support zone-এর উৎস।
        """
        swing_lows = []
        w = self.window

        for i in range(w, len(df) - w):
            current = df['low'].iloc[i]
            left    = df['low'].iloc[i - w : i]
            right   = df['low'].iloc[i + 1 : i + w + 1]

            if current < left.min() and current < right.min():
                swing_lows.append({
                    'index': i,
                    'time':  df.index[i],
                    'price': round(current, 5),
                })

        return swing_lows

    # ─────────────────────────────────────────────
    # STEP 2: Price Zone Clustering
    # ─────────────────────────────────────────────

    def create_price_zones(self, levels):
        """
        কাছাকাছি levels গুলো একটা zone-এ merge করো।
        একই area-তে বারবার react করলে সেটা strong zone।

        tolerance: এই পরিমাণ price difference হলে same zone ধরবে
        """
        zones = []

        for level in levels:
            price = level['price']
            merged = False

            for zone in zones:
                if abs(price - zone['center']) <= self.tolerance:
                    zone['prices'].append(price)
                    zone['center'] = round(float(np.mean(zone['prices'])), 5)
                    zone['touches'] += 1
                    merged = True
                    break

            if not merged:
                zones.append({
                    'center':  price,
                    'prices':  [price],
                    'touches': 1,
                })

        # বেশি touches = stronger zone — sort করো
        zones.sort(key=lambda z: z['touches'], reverse=True)
        return zones

    # ─────────────────────────────────────────────
    # STEP 3: Pivot Point Calculation
    # ─────────────────────────────────────────────

    def calculate_pivot(self, df):
        """
        Classic Pivot Point — আগের candle-এর H/L/C দিয়ে।
        Formula:
          Pivot = (High + Low + Close) / 3
          R1 = 2×Pivot - Low
          R2 = Pivot + (High - Low)
          S1 = 2×Pivot - High
          S2 = Pivot - (High - Low)
        """
        # আগের candle (most recent complete candle)
        prev = df.iloc[-2]
        H = prev['high']
        L = prev['low']
        C = prev['close']

        pivot = (H + L + C) / 3

        return {
            'pivot': round(pivot, 5),
            'R1':    round(2 * pivot - L, 5),
            'R2':    round(pivot + (H - L), 5),
            'S1':    round(2 * pivot - H, 5),
            'S2':    round(pivot - (H - L), 5),
        }

    # ─────────────────────────────────────────────
    # STEP 4: Nearest S/R from Current Price
    # ─────────────────────────────────────────────

    def find_nearest_levels(self, current_price, support_zones, resistance_zones):
        """
        Current price থেকে nearest support ও resistance খোঁজো।
        AI এটা দেখে বলবে: কতটা দূরে আছি, কোন দিকে move করতে পারে।
        """
        # Nearest Support — price-এর নিচে
        supports_below = [
            z for z in support_zones
            if z['center'] < current_price
        ]
        nearest_support = max(
            supports_below, key=lambda z: z['center']
        ) if supports_below else None

        # Nearest Resistance — price-এর উপরে
        resistances_above = [
            z for z in resistance_zones
            if z['center'] > current_price
        ]
        nearest_resistance = min(
            resistances_above, key=lambda z: z['center']
        ) if resistances_above else None

        return nearest_support, nearest_resistance

    # ─────────────────────────────────────────────
    # STEP 5: FULL PIPELINE
    # ─────────────────────────────────────────────

    def analyze(self, df):
        """
        সব S/R analysis একসাথে করো।
        Return করে: support_zones, resistance_zones, pivot, nearest levels
        """
        swing_highs = self.find_swing_highs(df)
        swing_lows  = self.find_swing_lows(df)

        resistance_zones = self.create_price_zones(swing_highs)
        support_zones    = self.create_price_zones(swing_lows)
        pivot            = self.calculate_pivot(df)

        current_price = float(df['close'].iloc[-1])
        nearest_sup, nearest_res = self.find_nearest_levels(
            current_price, support_zones, resistance_zones
        )

        return {
            'support_zones':    support_zones,
            'resistance_zones': resistance_zones,
            'pivot':            pivot,
            'nearest_support':  nearest_sup,
            'nearest_res':      nearest_res,
            'current_price':    current_price,
        }

    # ─────────────────────────────────────────────
    # SUMMARY — Human Readable
    # ─────────────────────────────────────────────

    def get_summary(self, result):
        """Market structure summary print করো"""
        cp  = result['current_price']
        sup = result['nearest_support']
        res = result['nearest_res']
        piv = result['pivot']

        print("\n" + "═" * 46)
        print("  📐  SUPPORT & RESISTANCE  (Day 5)")
        print("═" * 46)
        print(f"  Current Price  :  {cp:.5f}")
        print()

        if res:
            dist_r = round((res['center'] - cp) * 10000, 1)
            print(f"  Resistance     :  {res['center']:.5f}  "
                  f"(+{dist_r} pips)  strength: {'★' * min(res['touches'], 5)}")
        else:
            print("  Resistance     :  Not found")

        if sup:
            dist_s = round((cp - sup['center']) * 10000, 1)
            print(f"  Support        :  {sup['center']:.5f}  "
                  f"(-{dist_s} pips)  strength: {'★' * min(sup['touches'], 5)}")
        else:
            print("  Support        :  Not found")

        print()
        print(f"  ── Pivot Levels ──")
        print(f"  R2 : {piv['R2']:.5f}")
        print(f"  R1 : {piv['R1']:.5f}")
        print(f"  PP : {piv['pivot']:.5f}")
        print(f"  S1 : {piv['S1']:.5f}")
        print(f"  S2 : {piv['S2']:.5f}")

        # Location analysis
        print()
        if sup and res:
            total_range = res['center'] - sup['center']
            position    = (cp - sup['center']) / total_range
            if position > 0.7:
                location = "🔴 Near Resistance — Sell pressure zone"
            elif position < 0.3:
                location = "🟢 Near Support — Buy pressure zone"
            else:
                location = "🟡 Mid Range — Wait for direction"
            print(f"  Location       :  {location}")

        print("═" * 46 + "\n")

    # ─────────────────────────────────────────────
    # AI CONTEXT — Day 6 handoff
    # ─────────────────────────────────────────────

    def get_ai_context(self, result):
        """
        AI Brain-এর জন্য S/R context dict।
        Day 6-এ Trend Engine এর সাথে combine হবে।
        """
        cp  = result['current_price']
        sup = result['nearest_support']
        res = result['nearest_res']

        nearest_sup_price = sup['center'] if sup else None
        nearest_res_price = res['center'] if res else None
        sup_strength      = sup['touches'] if sup else 0
        res_strength      = res['touches'] if res else 0

        dist_to_sup = round((cp - nearest_sup_price) * 10000, 1) if nearest_sup_price else None
        dist_to_res = round((nearest_res_price - cp) * 10000, 1) if nearest_res_price else None

        # Location
        location = 'mid_range'
        if nearest_sup_price and nearest_res_price:
            total = nearest_res_price - nearest_sup_price
            pos   = (cp - nearest_sup_price) / total if total else 0.5
            if pos > 0.7:   location = 'near_resistance'
            elif pos < 0.3: location = 'near_support'

        return {
            'nearest_support':    nearest_sup_price,
            'nearest_resistance': nearest_res_price,
            'support_strength':   sup_strength,
            'resistance_strength': res_strength,
            'dist_to_support_pips':    dist_to_sup,
            'dist_to_resistance_pips': dist_to_res,
            'price_location':     location,
            'pivot':              result['pivot']['pivot'],
            'R1':                 result['pivot']['R1'],
            'S1':                 result['pivot']['S1'],
        }