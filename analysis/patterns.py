# analysis/patterns.py
# ============================================================
# Day 4 — Candlestick Pattern Detection Engine
# TA-Lib ছাড়া — Pure Python Logic
# AI Trader-এর Price Action Brain
# ============================================================

import pandas as pd


class PatternDetector:
    """
    Candlestick pattern detector — TA-Lib ছাড়া।

    প্রতিটা pattern-এর নিজস্ব mathematical rule আছে।
    AI এই patterns দেখে price behavior বুঝবে।
    """

    # ─────────────────────────────────────────────
    # MAIN METHOD — সব pattern একসাথে
    # ─────────────────────────────────────────────

    def detect_all(self, df):
        """
        DataFrame-এ প্রতিটা candle-এর জন্য pattern detect করো।
        নতুন column যোগ হবে: 'pattern'
        """
        df = df.copy()
        df['pattern'] = df.apply(self._detect_row, axis=1)
        detected = df[df['pattern'] != 'none']['pattern'].value_counts()
        print(f"✅ Pattern detection done | Unique patterns: {len(detected)}")
        return df

    def _detect_row(self, row):
        """একটা candle দেখে pattern বলো"""
        checks = [
            self.is_doji(row),
            self.is_hammer(row),
            self.is_shooting_star(row),
            self.is_bullish_engulfing_row(row),
            self.is_bearish_engulfing_row(row),
            self.is_pin_bar(row),
        ]
        # প্রথম যেটা match করে সেটাই return
        for result in checks:
            if result and result != 'none':
                return result
        return 'none'

    # ─────────────────────────────────────────────
    # INDIVIDUAL PATTERNS
    # ─────────────────────────────────────────────

    def is_doji(self, row):
        """
        Doji — open ও close প্রায় সমান।
        অনিশ্চয়তা দেখায় — reversal সম্ভব।
        """
        body       = abs(row['close'] - row['open'])
        full_range = row['high'] - row['low']

        if full_range == 0:
            return 'none'

        # Body, full candle range-এর ১০% এর কম হলে Doji
        if body / full_range < 0.1:
            return 'doji'
        return 'none'

    def is_hammer(self, row):
        """
        Hammer — ছোট body, লম্বা lower wick।
        Downtrend-এ দেখা দিলে bullish reversal signal।

        Rule:
          lower_wick > body * 2
          upper_wick < body * 0.5
        """
        body        = abs(row['close'] - row['open'])
        upper_wick  = row['high'] - max(row['open'], row['close'])
        lower_wick  = min(row['open'], row['close']) - row['low']

        if body == 0:
            return 'none'

        if lower_wick > body * 2 and upper_wick <= body * 0.5:
            return 'hammer'
        return 'none'

    def is_shooting_star(self, row):
        """
        Shooting Star — ছোট body, লম্বা upper wick।
        Uptrend-এ দেখা দিলে bearish reversal signal।

        Rule:
          upper_wick > body * 2
          lower_wick < body * 0.5
        """
        body        = abs(row['close'] - row['open'])
        upper_wick  = row['high'] - max(row['open'], row['close'])
        lower_wick  = min(row['open'], row['close']) - row['low']

        if body == 0:
            return 'none'

        if upper_wick > body * 2 and lower_wick < body * 0.5:
            return 'shooting_star'
        return 'none'

    def is_pin_bar(self, row):
        """
        Pin Bar — strong rejection candle।
        Hammer/Shooting Star-এর চেয়ে আরো extreme।

        Rule:
          wick, body-এর ৩ গুণের বেশি
        """
        body        = abs(row['close'] - row['open'])
        upper_wick  = row['high'] - max(row['open'], row['close'])
        lower_wick  = min(row['open'], row['close']) - row['low']

        if body == 0:
            return 'none'

        if lower_wick > body * 3:
            return 'bullish_pin_bar'
        if upper_wick > body * 3:
            return 'bearish_pin_bar'
        return 'none'

    def is_bullish_engulfing_row(self, row):
        """Single row দিয়ে detect হয় না — দুটো candle লাগে।
        detect_engulfing() ব্যবহার করো DataFrame-এ।"""
        return 'none'

    def is_bearish_engulfing_row(self, row):
        return 'none'

    # ─────────────────────────────────────────────
    # MULTI-CANDLE PATTERNS (DataFrame দরকার)
    # ─────────────────────────────────────────────

    def detect_engulfing(self, df):
        """
        Bullish/Bearish Engulfing — দুটো consecutive candle দেখে।

        Bullish Engulfing:
          আগের candle bearish (red)
          পরের candle bullish (green) এবং আগেরটাকে পুরো ঢেকে দেয়

        Bearish Engulfing:
          আগের candle bullish (green)
          পরের candle bearish (red) এবং আগেরটাকে পুরো ঢেকে দেয়
        """
        df = df.copy()
        df['engulfing'] = 'none'

        for i in range(1, len(df)):
            prev = df.iloc[i - 1]
            curr = df.iloc[i]

            prev_bearish = prev['close'] < prev['open']
            curr_bullish = curr['close'] > curr['open']
            bullish_engulf = (
                prev_bearish and curr_bullish
                and curr['open']  < prev['close']
                and curr['close'] > prev['open']
            )

            prev_bullish = prev['close'] > prev['open']
            curr_bearish = curr['close'] < curr['open']
            bearish_engulf = (
                prev_bullish and curr_bearish
                and curr['open']  > prev['close']
                and curr['close'] < prev['open']
            )

            if bullish_engulf:
                df.iloc[i, df.columns.get_loc('engulfing')] = 'bullish_engulfing'
            elif bearish_engulf:
                df.iloc[i, df.columns.get_loc('engulfing')] = 'bearish_engulfing'

        return df

    def detect_morning_evening_star(self, df):
        """
        Morning Star (bullish reversal) — ৩টা candle:
          1. বড় bearish candle
          2. ছোট body candle (star)
          3. বড় bullish candle

        Evening Star (bearish reversal) — ৩টা candle:
          1. বড় bullish candle
          2. ছোট body candle (star)
          3. বড় bearish candle
        """
        df = df.copy()
        df['star_pattern'] = 'none'

        for i in range(2, len(df)):
            c1 = df.iloc[i - 2]
            c2 = df.iloc[i - 1]
            c3 = df.iloc[i]

            c2_body = abs(c2['close'] - c2['open'])
            c1_body = abs(c1['close'] - c1['open'])
            c3_body = abs(c3['close'] - c3['open'])

            # Morning Star
            if (
                c1['close'] < c1['open']            # c1 bearish
                and c2_body < c1_body * 0.3          # c2 small body
                and c3['close'] > c3['open']          # c3 bullish
                and c3_body > c1_body * 0.5           # c3 significant
            ):
                df.iloc[i, df.columns.get_loc('star_pattern')] = 'morning_star'

            # Evening Star
            elif (
                c1['close'] > c1['open']             # c1 bullish
                and c2_body < c1_body * 0.3           # c2 small body
                and c3['close'] < c3['open']           # c3 bearish
                and c3_body > c1_body * 0.5            # c3 significant
            ):
                df.iloc[i, df.columns.get_loc('star_pattern')] = 'evening_star'

        return df

    # ─────────────────────────────────────────────
    # FULL PIPELINE — সব একসাথে
    # ─────────────────────────────────────────────

    def run_full_detection(self, df):
        """সব pattern একসাথে detect করো এবং final df return করো"""
        df = self.detect_all(df)
        df = self.detect_engulfing(df)
        df = self.detect_morning_evening_star(df)
        return df

    # ─────────────────────────────────────────────
    # SUMMARY — AI Brain-এর জন্য
    # ─────────────────────────────────────────────

    def get_latest_patterns(self, df, lookback=5):
        """
        সর্বশেষ N candle-এ কী কী pattern ছিল।
        AI Brain এই list দেখে context বুঝবে।
        """
        recent = df.tail(lookback)
        found  = []

        for _, row in recent.iterrows():
            for col in ['pattern', 'engulfing', 'star_pattern']:
                if col in row and row[col] != 'none':
                    found.append({
                        'time':    str(row.name),
                        'pattern': row[col],
                    })

        print("\n" + "═" * 46)
        print(f"  🕯️  CANDLESTICK PATTERNS  (Last {lookback} candles)")
        print("═" * 46)
        if found:
            for item in found:
                signal = self._pattern_signal(item['pattern'])
                print(f"  {item['time'][-8:]}  |  {item['pattern']:<22}  {signal}")
        else:
            print("  No significant patterns in recent candles.")
        print("═" * 46 + "\n")

        return found

    def get_ai_pattern_context(self, df, lookback=5):
        """Day 4 → Day 5 handoff: AI Brain-এর জন্য pattern context dict"""
        patterns = self.get_latest_patterns(df, lookback)
        latest   = df.iloc[-1]

        # সবচেয়ে recent pattern টা নাও
        last_pattern = 'none'
        if patterns:
            last_pattern = patterns[-1]['pattern']

        return {
            "latest_pattern":  last_pattern,
            "pattern_signal":  self._pattern_signal(last_pattern),
            "recent_patterns": [p['pattern'] for p in patterns],
            "candle_type":     'bullish' if latest['close'] > latest['open'] else 'bearish',
            "body_size":       round(abs(latest['close'] - latest['open']), 5),
        }

    @staticmethod
    def _pattern_signal(pattern):
        """Pattern দেখে signal বলো"""
        bullish = ['hammer', 'bullish_engulfing', 'morning_star', 'bullish_pin_bar']
        bearish = ['shooting_star', 'bearish_engulfing', 'evening_star', 'bearish_pin_bar']
        neutral = ['doji']

        if pattern in bullish: return '🟢 Bullish Signal'
        if pattern in bearish: return '🔴 Bearish Signal'
        if pattern in neutral: return '🟡 Neutral / Wait'
        return '⬜ No Signal'