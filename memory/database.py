# memory/database.py  —  Day 15 | Week 3 Memory Foundation

import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = "memory/trader.db"


class Database:
    """
    AI Trader-এর central memory system।

    4 টি table:
        1. trades        — প্রতিটি trade record
        2. analysis_log  — AI কী দেখে decision নিয়েছিল
        3. performance   — daily performance summary
        4. mistakes      — ভুল থেকে শেখা
    """

    def __init__(self, db_path: str = DB_PATH):
        Path("memory").mkdir(exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row  # dict-like access
        self.create_tables()
        print(f"✅ Database ready: {db_path}")

    # ── Table Creation ─────────────────────────────────────────

    def create_tables(self):
        cursor = self.conn.cursor()

        # 1. trades
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            pair         TEXT    NOT NULL,
            signal       TEXT    NOT NULL,
            entry        REAL,
            sl           REAL,
            tp           REAL,
            lot          REAL,
            result       TEXT,
            pnl          REAL    DEFAULT 0,
            rr_ratio     REAL,
            confidence   INTEGER,
            chart_snapshot TEXT,
            date         TEXT    DEFAULT (datetime('now'))
        )
        """)

        # 2. analysis_log
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS analysis_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            pair         TEXT,
            timeframe    TEXT,
            rsi          REAL,
            macd         REAL,
            trend        TEXT,
            regime       TEXT,
            pattern      TEXT,
            sr_location  TEXT,
            mtf_bias     TEXT,
            decision     TEXT,
            confidence   INTEGER,
            indicators   TEXT,
            date         TEXT    DEFAULT (datetime('now'))
        )
        """)

        # 3. performance
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS performance (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            date         TEXT    UNIQUE,
            total_trades INTEGER DEFAULT 0,
            wins         INTEGER DEFAULT 0,
            losses       INTEGER DEFAULT 0,
            win_rate     REAL    DEFAULT 0,
            pnl          REAL    DEFAULT 0,
            best_trade   REAL    DEFAULT 0,
            worst_trade  REAL    DEFAULT 0
        )
        """)

        # 4. mistakes
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS mistakes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id     INTEGER,
            pair         TEXT,
            error_type   TEXT,
            what_happened TEXT,
            lesson       TEXT,
            date         TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY (trade_id) REFERENCES trades(id)
        )
        """)

        self.conn.commit()

    # ── Trade CRUD ─────────────────────────────────────────────

    def save_trade(self, trade: dict) -> int:
        """
        Trade save করো।

        trade = {
            "pair": "EURUSD",
            "signal": "BUY",
            "entry": 1.0850,
            "sl": 1.0825,
            "tp": 1.0900,
            "lot": 0.01,
            "result": "WIN",   # পরে update করা হবে
            "pnl": 50,
            "rr_ratio": 2.0,
            "confidence": 75,
            "chart_snapshot": {...}  # optional
        }

        Returns: trade id
        """
        cursor = self.conn.cursor()

        snapshot = trade.get("chart_snapshot")
        if isinstance(snapshot, dict):
            snapshot = json.dumps(snapshot)

        cursor.execute("""
        INSERT INTO trades
            (pair, signal, entry, sl, tp, lot, result, pnl, rr_ratio, confidence, chart_snapshot)
        VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade.get("pair"),
            trade.get("signal"),
            trade.get("entry"),
            trade.get("sl"),
            trade.get("tp"),
            trade.get("lot", 0),
            trade.get("result", "OPEN"),
            trade.get("pnl", 0),
            trade.get("rr_ratio", 0),
            trade.get("confidence", 0),
            snapshot,
        ))

        self.conn.commit()
        trade_id = cursor.lastrowid
        print(f"💾 Trade saved: #{trade_id} | {trade.get('pair')} {trade.get('signal')}")
        return trade_id

    def update_trade_result(self, trade_id: int, result: str, pnl: float):
        """Trade শেষ হলে result update করো।"""
        cursor = self.conn.cursor()
        cursor.execute("""
        UPDATE trades
        SET result = ?, pnl = ?
        WHERE id = ?
        """, (result, pnl, trade_id))
        self.conn.commit()
        print(f"✅ Trade #{trade_id} updated: {result} | PnL: {pnl}")

    def get_recent_trades(self, limit: int = 10) -> list:
        """সর্বশেষ trades দেখো।"""
        cursor = self.conn.cursor()
        cursor.execute("""
        SELECT * FROM trades
        ORDER BY date DESC
        LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

    def get_trade_by_id(self, trade_id: int) -> dict:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
        row = cursor.fetchone()
        return dict(row) if row else {}

    # ── Analysis Log ───────────────────────────────────────────

    def save_analysis(self, analysis: dict) -> int:
        """
        AI কী দেখে decision নিয়েছিল সেটা save করো।

        analysis = {
            "pair": "EURUSD",
            "timeframe": "15m",
            "rsi": 63.7,
            "macd": 0.00034,
            "trend": "sideways",
            "regime": "TRENDING",
            "pattern": "hammer",
            "sr_location": "near_support",
            "mtf_bias": "BEARISH",
            "decision": "BUY",
            "confidence": 75,
            "indicators": {...}   # full indicator dict
        }
        """
        cursor = self.conn.cursor()

        indicators = analysis.get("indicators")
        if isinstance(indicators, dict):
            indicators = json.dumps(indicators)

        cursor.execute("""
        INSERT INTO analysis_log
            (pair, timeframe, rsi, macd, trend, regime, pattern,
             sr_location, mtf_bias, decision, confidence, indicators)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            analysis.get("pair"),
            analysis.get("timeframe"),
            analysis.get("rsi"),
            analysis.get("macd"),
            analysis.get("trend"),
            analysis.get("regime"),
            analysis.get("pattern"),
            analysis.get("sr_location"),
            analysis.get("mtf_bias"),
            analysis.get("decision"),
            analysis.get("confidence"),
            indicators,
        ))

        self.conn.commit()
        return cursor.lastrowid

    def get_similar_setups(self, pattern: str, regime: str, limit: int = 5) -> list:
        """
        একই ধরনের setup আগে কেমন perform করেছে।

        AI এটা দিয়ে শিখবে:
        "এই pattern + এই regime = আগে 70% win"
        """
        cursor = self.conn.cursor()
        cursor.execute("""
        SELECT a.*, t.result, t.pnl
        FROM analysis_log a
        LEFT JOIN trades t ON a.date = t.date
        WHERE a.pattern = ? AND a.regime = ?
        ORDER BY a.date DESC
        LIMIT ?
        """, (pattern, regime, limit))
        return [dict(row) for row in cursor.fetchall()]

    # ── Performance ────────────────────────────────────────────

    def update_daily_performance(self):
        """
        আজকের সব trade থেকে performance calculate করো।
        প্রতিদিন একবার call করো।
        """
        cursor = self.conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")

        cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN result = 'WIN' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN result = 'LOSS' THEN 1 ELSE 0 END) as losses,
            SUM(pnl) as total_pnl,
            MAX(pnl) as best,
            MIN(pnl) as worst
        FROM trades
        WHERE date LIKE ? AND result != 'OPEN'
        """, (f"{today}%",))

        row = cursor.fetchone()
        if not row or row["total"] == 0:
            return

        total  = row["total"]
        wins   = row["wins"] or 0
        losses = row["losses"] or 0
        pnl    = row["total_pnl"] or 0
        wr     = round((wins / total) * 100, 1) if total > 0 else 0

        cursor.execute("""
        INSERT INTO performance (date, total_trades, wins, losses, win_rate, pnl, best_trade, worst_trade)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            total_trades = excluded.total_trades,
            wins         = excluded.wins,
            losses       = excluded.losses,
            win_rate     = excluded.win_rate,
            pnl          = excluded.pnl,
            best_trade   = excluded.best_trade,
            worst_trade  = excluded.worst_trade
        """, (today, total, wins, losses, wr, pnl, row["best"], row["worst"]))

        self.conn.commit()
        print(f"📊 Performance updated: {today} | Trades: {total} | WR: {wr}% | PnL: {pnl}")

    def get_performance_summary(self, days: int = 7) -> dict:
        """শেষ N দিনের performance summary।"""
        cursor = self.conn.cursor()
        cursor.execute("""
        SELECT * FROM performance
        ORDER BY date DESC
        LIMIT ?
        """, (days,))
        rows = [dict(r) for r in cursor.fetchall()]

        if not rows:
            return {"status": "No data yet"}

        total_pnl  = sum(r["pnl"] for r in rows)
        avg_wr     = round(sum(r["win_rate"] for r in rows) / len(rows), 1)
        total_trades = sum(r["total_trades"] for r in rows)

        return {
            "days":          len(rows),
            "total_trades":  total_trades,
            "avg_win_rate":  avg_wr,
            "total_pnl":     round(total_pnl, 2),
            "daily":         rows,
        }

    # ── Mistakes / Learning ────────────────────────────────────

    def save_mistake(self, mistake: dict) -> int:
        """
        ভুল trade থেকে lesson save করো।

        mistake = {
            "trade_id": 25,
            "pair": "EURUSD",
            "error_type": "Early Entry",
            "what_happened": "Entered before confirmation",
            "lesson": "Wait for candle close above resistance"
        }
        """
        cursor = self.conn.cursor()
        cursor.execute("""
        INSERT INTO mistakes (trade_id, pair, error_type, what_happened, lesson)
        VALUES (?, ?, ?, ?, ?)
        """, (
            mistake.get("trade_id"),
            mistake.get("pair"),
            mistake.get("error_type"),
            mistake.get("what_happened"),
            mistake.get("lesson"),
        ))
        self.conn.commit()
        lid = cursor.lastrowid
        print(f"📝 Mistake logged: #{lid} | {mistake.get('error_type')}")
        return lid

    def get_lessons(self, pair: str = None, limit: int = 10) -> list:
        """AI-এর শেখা lessons দেখো।"""
        cursor = self.conn.cursor()
        if pair:
            cursor.execute("""
            SELECT * FROM mistakes WHERE pair = ?
            ORDER BY date DESC LIMIT ?
            """, (pair, limit))
        else:
            cursor.execute("""
            SELECT * FROM mistakes
            ORDER BY date DESC LIMIT ?
            """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

    def auto_log_mistake(self, trade_id: int):
        """
        LOSS trade হলে automatically mistake analyze করো।
        AI নিজেই বুঝবে কোথায় ভুল হলো।
        """
        trade = self.get_trade_by_id(trade_id)
        if not trade or trade.get("result") != "LOSS":
            return

        # Pattern-based mistake detection
        error_type    = "Unknown"
        what_happened = ""
        lesson        = ""

        rr = trade.get("rr_ratio", 0)
        conf = trade.get("confidence", 0)

        if conf < 60:
            error_type    = "Low Confidence Trade"
            what_happened = f"Entered with only {conf}% confidence"
            lesson        = "Minimum confidence should be 65% before entry"
        elif rr < 1.5:
            error_type    = "Poor Risk Reward"
            what_happened = f"R:R was only 1:{rr}"
            lesson        = "Never enter trade with R:R below 1:2"
        else:
            error_type    = "Market Condition"
            what_happened = "Setup looked good but market moved against"
            lesson        = "Accept losses — focus on process not outcome"

        self.save_mistake({
            "trade_id":     trade_id,
            "pair":         trade.get("pair"),
            "error_type":   error_type,
            "what_happened": what_happened,
            "lesson":       lesson,
        })

    # ── Stats ──────────────────────────────────────────────────

    def get_overall_stats(self) -> dict:
        """AI-এর সব সময়ের statistics।"""
        cursor = self.conn.cursor()
        cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN result='WIN'  THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses,
            SUM(CASE WHEN result='OPEN' THEN 1 ELSE 0 END) as open_trades,
            SUM(pnl) as total_pnl,
            AVG(pnl) as avg_pnl,
            MAX(pnl) as best_trade,
            MIN(pnl) as worst_trade,
            AVG(confidence) as avg_confidence
        FROM trades
        """)
        row = cursor.fetchone()
        data = dict(row)

        total = data.get("total", 0) or 0
        wins  = data.get("wins",  0) or 0
        data["win_rate"] = round((wins / total * 100), 1) if total > 0 else 0
        data["total_mistakes"] = len(self.get_lessons())

        return data

    def print_stats(self):
        """Console-এ সুন্দর করে stats দেখাও।"""
        s = self.get_overall_stats()
        bar = "═" * 48
        print(f"\n{bar}")
        print(f"  📊  AI TRADER — MEMORY STATS")
        print(bar)
        print(f"  Total Trades   : {s.get('total', 0)}")
        print(f"  Wins           : {s.get('wins', 0)}")
        print(f"  Losses         : {s.get('losses', 0)}")
        print(f"  Open           : {s.get('open_trades', 0)}")
        print(f"  Win Rate       : {s.get('win_rate', 0)}%")
        print(f"  Total PnL      : ${round(s.get('total_pnl') or 0, 2)}")
        print(f"  Avg PnL/Trade  : ${round(s.get('avg_pnl') or 0, 2)}")
        print(f"  Best Trade     : ${s.get('best_trade') or 0}")
        print(f"  Worst Trade    : ${s.get('worst_trade') or 0}")
        print(f"  Avg Confidence : {round(s.get('avg_confidence') or 0, 1)}%")
        print(f"  Lessons Learned: {s.get('total_mistakes', 0)}")
        print(bar)

    # ── Cleanup ────────────────────────────────────────────────

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
