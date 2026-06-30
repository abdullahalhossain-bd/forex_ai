# database/db.py
# ============================================================
# AI Trader — SQLite Database
# CSV এর চেয়ে fast, structured, queryable
# পরে PostgreSQL-এ migrate করা সহজ হবে
#
# Day 43 addition: `economic_history` table — news event + actual
# market reaction memory, যাতে FundamentalSentimentScore module
# পরে এই history থেকে currency bias বের করতে পারে।
# ============================================================

import sqlite3
import pandas as pd
import json
import os
import numpy as np
from datetime import datetime
from utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = "database/trader.db"
os.makedirs("database", exist_ok=True)


# ── JSON encoder that handles numpy types ───────────────────────────
# pandas/numpy produce np.int64, np.float64, np.bool_ etc. which the
# standard json.dumps() can't serialize.  This encoder converts them
# to native Python types so save_analysis() / save_trade_open() never
# crash with "Object of type bool is not JSON serializable".
class _NumpySafeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (pd.Timestamp, datetime)):
            return str(obj)
        # pd.isna() crashes on dicts/lists — only call on scalars.
        if isinstance(obj, (int, float, str)) or obj is None:
            try:
                if pd.isna(obj):
                    return None
            except Exception:
                pass
        return super().default(obj)


def _safe_json_dumps(obj):
    """json.dumps that never crashes — converts numpy types + falls back to str."""
    try:
        return json.dumps(obj, cls=_NumpySafeEncoder, default=str)
    except Exception:
        # Last resort: stringify everything we can't serialize
        try:
            return json.dumps(str(obj))
        except Exception:
            return "{}"


class TraderDB:
    """
    AI Trader-এর central database।

    Tables:
        candles            — OHLCV data
        indicators         — calculated indicator values
        patterns           — detected patterns
        analysis           — full AI context per run
        trades             — paper/demo trade journal
        economic_history   — (Day 43) news event + market reaction memory
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_tables()
        log.info(f"Database ready: {db_path}")

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_tables(self):
        """Tables তৈরি করো (already exists হলে skip)"""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS candles (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol    TEXT    NOT NULL,
                    timeframe TEXT    NOT NULL,
                    time      TEXT    NOT NULL,
                    open      REAL,
                    high      REAL,
                    low       REAL,
                    close     REAL,
                    volume    REAL,
                    UNIQUE(symbol, timeframe, time)
                );

                CREATE TABLE IF NOT EXISTS indicators (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol    TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    time      TEXT NOT NULL,
                    rsi       REAL,
                    macd      REAL,
                    macd_sig  REAL,
                    sma_20    REAL,
                    sma_50    REAL,
                    sma_200   REAL,
                    atr       REAL,
                    bb_upper  REAL,
                    bb_lower  REAL,
                    trend     TEXT,
                    UNIQUE(symbol, timeframe, time)
                );

                CREATE TABLE IF NOT EXISTS patterns (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol    TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    time      TEXT NOT NULL,
                    pattern   TEXT,
                    engulfing TEXT,
                    star      TEXT,
                    signal    TEXT
                );

                CREATE TABLE IF NOT EXISTS analysis (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_time    TEXT NOT NULL,
                    symbol      TEXT NOT NULL,
                    timeframe   TEXT NOT NULL,
                    bias_score  INTEGER,
                    bias_label  TEXT,
                    context_json TEXT
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    pair            TEXT NOT NULL,
                    timeframe       TEXT,
                    type            TEXT NOT NULL,
                    entry           REAL,
                    sl              REAL,
                    tp              REAL,
                    lot             REAL,
                    confidence      INTEGER,
                    open_time       TEXT NOT NULL,
                    close_time      TEXT,
                    exit_price      REAL,
                    result          TEXT,
                    pnl             REAL,
                    pnl_pips        REAL,
                    spread_cost     REAL,
                    commission      REAL,
                    slippage        REAL,
                    pattern         TEXT,
                    regime          TEXT,
                    trend           TEXT,
                    rsi             REAL,
                    session         TEXT,
                    status          TEXT DEFAULT 'OPEN',
                    context_json    TEXT
                );

                CREATE TABLE IF NOT EXISTS economic_history (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    event           TEXT NOT NULL,
                    currency        TEXT NOT NULL,
                    impact          TEXT,
                    event_time      TEXT NOT NULL,
                    expected        TEXT,
                    actual          TEXT,
                    market_reaction TEXT,
                    pips_moved      REAL,
                    lesson          TEXT,
                    created_at      TEXT NOT NULL
                );
            """)

    # ─────────────────────────────────────────────
    # SAVE METHODS
    # ─────────────────────────────────────────────

    def save_candles(self, df: pd.DataFrame, symbol: str, timeframe: str):
        """OHLCV data save করো — duplicate হলে skip"""
        rows = []
        for ts, row in df.iterrows():
            rows.append((
                symbol, timeframe, str(ts),
                row.get('open'), row.get('high'),
                row.get('low'),  row.get('close'), row.get('volume'),
            ))
        with self._connect() as conn:
            conn.executemany("""
                INSERT OR IGNORE INTO candles
                (symbol, timeframe, time, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
        log.info(f"Candles saved: {symbol} {timeframe} | {len(rows)} rows")

    def save_indicators(self, df: pd.DataFrame, symbol: str, timeframe: str):
        """Indicator values save করো"""
        rows = []
        for ts, row in df.iterrows():
            rows.append((
                symbol, timeframe, str(ts),
                _safe(row, 'rsi'),       _safe(row, 'macd'),
                _safe(row, 'macd_signal'), _safe(row, 'sma_20'),
                _safe(row, 'sma_50'),    _safe(row, 'sma_200'),
                _safe(row, 'atr'),       _safe(row, 'bb_upper'),
                _safe(row, 'bb_lower'),  row.get('trend', ''),
            ))
        with self._connect() as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO indicators
                (symbol, timeframe, time, rsi, macd, macd_sig,
                 sma_20, sma_50, sma_200, atr, bb_upper, bb_lower, trend)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
        log.info(f"Indicators saved: {symbol} {timeframe}")

    def save_patterns(self, df: pd.DataFrame, symbol: str, timeframe: str):
        """Detected patterns save করো"""
        rows = []
        for ts, row in df.iterrows():
            pat = row.get('pattern', 'none')
            eng = row.get('engulfing', 'none')
            star = row.get('star_pattern', 'none')
            if pat == 'none' and eng == 'none' and star == 'none':
                continue
            rows.append((symbol, timeframe, str(ts), pat, eng, star, ''))
        if rows:
            with self._connect() as conn:
                conn.executemany("""
                    INSERT INTO patterns
                    (symbol, timeframe, time, pattern, engulfing, star, signal)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, rows)
            log.info(f"Patterns saved: {len(rows)} patterns")

    def save_analysis(self, symbol: str, timeframe: str,
                      bias_score: int, bias_label: str, context: dict):
        """Full analysis result save করো"""
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO analysis
                (run_time, symbol, timeframe, bias_score, bias_label, context_json)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                symbol, timeframe,
                bias_score, bias_label,
                _safe_json_dumps(context),
            ))
        log.info(f"Analysis saved: {symbol} bias={bias_score} ({bias_label})")

    # ─────────────────────────────────────────────
    # TRADES  (Day 17 — Paper Trading)
    # ─────────────────────────────────────────────

    def save_trade_open(self, trade: dict) -> int:
        """
        নতুন trade open হলে save করো। Returns the new trade's row id.
        `trade` dict-টা PaperTrader._build_trade_record() থেকে আসে।
        """
        with self._connect() as conn:
            cur = conn.execute("""
                INSERT INTO trades
                (pair, timeframe, type, entry, sl, tp, lot, confidence,
                 open_time, pattern, regime, trend, rsi, session,
                 status, context_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
            """, (
                trade["pair"], trade.get("timeframe"), trade["type"],
                trade["entry"], trade["sl"], trade["tp"], trade["lot"],
                trade.get("confidence"), trade["open_time"],
                trade.get("pattern"), trade.get("regime"),
                trade.get("trend"), trade.get("rsi"), trade.get("session"),
                _safe_json_dumps(trade.get("context", {})),
            ))
            trade_id = cur.lastrowid
        log.info(f"Trade OPEN saved: #{trade_id} {trade['pair']} {trade['type']} @ {trade['entry']}")
        return trade_id

    def save_trade_close(self, trade_id: int, close_data: dict) -> None:
        """
        Trade close হলে update করো (WIN/LOSS/BREAKEVEN + pnl + costs)।
        close_data keys: close_time, exit_price, result, pnl, pnl_pips,
                          spread_cost, commission, slippage
        """
        with self._connect() as conn:
            conn.execute("""
                UPDATE trades
                SET close_time = ?, exit_price = ?, result = ?,
                    pnl = ?, pnl_pips = ?, spread_cost = ?,
                    commission = ?, slippage = ?, status = 'CLOSED'
                WHERE id = ?
            """, (
                close_data["close_time"], close_data["exit_price"],
                close_data["result"], close_data["pnl"], close_data.get("pnl_pips"),
                close_data.get("spread_cost", 0), close_data.get("commission", 0),
                close_data.get("slippage", 0), trade_id,
            ))
        log.info(f"Trade CLOSE saved: #{trade_id} {close_data['result']} | PnL: ${close_data['pnl']}")

    def get_open_trades(self, pair: str = None) -> pd.DataFrame:
        """বর্তমান open trades দেখো (price update loop-এর জন্য)"""
        query  = "SELECT * FROM trades WHERE status = 'OPEN'"
        params = ()
        if pair:
            query += " AND pair = ?"
            params = (pair,)
        with self._connect() as conn:
            return pd.read_sql(query, conn, params=params)

    def has_open_trade(self, pair: str, trade_type: str | None = None) -> bool:
        """Duplicate trade protection-এর জন্য open position আছে কিনা দেখো।"""
        query = "SELECT COUNT(*) FROM trades WHERE status = 'OPEN' AND pair = ?"
        params: list = [pair]
        if trade_type:
            query += " AND type = ?"
            params.append(trade_type)
        with self._connect() as conn:
            count = conn.execute(query, tuple(params)).fetchone()[0]
        return count > 0

    def get_trade_history(self, pair: str = None, limit: int = 50) -> pd.DataFrame:
        """Closed trades history দেখো"""
        query  = "SELECT * FROM trades WHERE status = 'CLOSED'"
        params = []
        if pair:
            query += " AND pair = ?"
            params.append(pair)
        query += " ORDER BY close_time DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return pd.read_sql(query, conn, params=params)

    def get_account_stats(self, starting_balance: float = 10000.0) -> dict:
        """Dashboard summary — Day 17 doc-এর 'AI PAPER ACCOUNT' output"""
        with self._connect() as conn:
            row = conn.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses,
                       SUM(pnl) as total_pnl
                FROM trades WHERE status = 'CLOSED'
            """).fetchone()
        total, wins, losses, total_pnl = row
        total      = total or 0
        wins       = wins or 0
        total_pnl  = total_pnl or 0.0
        win_rate   = round(wins / total * 100, 1) if total else 0.0
        return {
            "balance":      round(starting_balance + total_pnl, 2),
            "total_trades": total,
            "wins":         wins,
            "losses":       losses,
            "win_rate":     win_rate,
            "total_pnl":    round(total_pnl, 2),
        }

    def get_overall_stats(self, starting_balance: float = 10000.0) -> dict:
        """Telegram status/reporting-এর জন্য all-time paper account stats।"""
        base_stats = self.get_account_stats(starting_balance=starting_balance)
        with self._connect() as conn:
            open_trades = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE status = 'OPEN'"
            ).fetchone()[0]
        return {
            "total": base_stats["total_trades"],
            "wins": base_stats["wins"],
            "losses": base_stats["losses"],
            "win_rate": base_stats["win_rate"],
            "total_pnl": base_stats["total_pnl"],
            "balance": base_stats["balance"],
            "open_trades": open_trades or 0,
        }

    # ─────────────────────────────────────────────
    # ECONOMIC HISTORY  (Day 43 — News Memory System)
    # ─────────────────────────────────────────────

    def save_economic_event(self, event: dict) -> int:
        """
        একটা economic event + (জানা থাকলে) তার actual market reaction
        save করো। `event` dict-এর সম্ভাব্য keys:
            event, currency, impact, event_time, expected, actual,
            market_reaction ("BULLISH"/"BEARISH"/"NEUTRAL"), pips_moved, lesson
        """
        with self._connect() as conn:
            cur = conn.execute("""
                INSERT INTO economic_history
                (event, currency, impact, event_time, expected, actual,
                 market_reaction, pips_moved, lesson, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.get("event", ""),
                event.get("currency", "").upper(),
                event.get("impact", "HIGH"),
                event.get("event_time", datetime.utcnow().isoformat()),
                event.get("expected"),
                event.get("actual"),
                event.get("market_reaction"),
                event.get("pips_moved"),
                event.get("lesson"),
                datetime.utcnow().isoformat(),
            ))
            event_id = cur.lastrowid
        log.info(
            f"Economic event saved: #{event_id} {event.get('currency')} "
            f"{event.get('event')} → {event.get('market_reaction', 'unknown')}"
        )
        return event_id

    def get_economic_history(self, currency: str = None, limit: int = 50) -> pd.DataFrame:
        """Recent economic events (lesson/reaction সহ) দেখো — currency filter optional।"""
        query  = "SELECT * FROM economic_history"
        params = []
        if currency:
            query += " WHERE currency = ?"
            params.append(currency.upper())
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return pd.read_sql(query, conn, params=params)

    def get_currency_fundamental_bias(self, currency: str, lookback: int = 10) -> dict:
        """
        একটা currency-র সাম্প্রতিক economic_history entries দেখে
        bullish/bearish reaction count থেকে একটা সরল fundamental bias বের করে।
        FundamentalSentimentScore module এটাকেই raw input হিসেবে ব্যবহার করবে।
        """
        history = self.get_economic_history(currency=currency, limit=lookback)
        if history.empty:
            return {
                "currency": currency.upper(), "sample_size": 0,
                "bullish_count": 0, "bearish_count": 0, "neutral_count": 0,
                "raw_score": 0,
            }

        reactions = history["market_reaction"].fillna("NEUTRAL").str.upper()
        bullish   = int((reactions == "BULLISH").sum())
        bearish   = int((reactions == "BEARISH").sum())
        neutral   = int((reactions == "NEUTRAL").sum())
        raw_score = bullish - bearish   # সরল net score

        return {
            "currency":      currency.upper(),
            "sample_size":   len(history),
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": neutral,
            "raw_score":     raw_score,
        }

    # ─────────────────────────────────────────────
    # QUERY METHODS
    # ─────────────────────────────────────────────

    def get_latest_analysis(self, symbol: str, limit: int = 5) -> pd.DataFrame:
        """সর্বশেষ N analysis result দেখো"""
        with self._connect() as conn:
            return pd.read_sql("""
                SELECT run_time, timeframe, bias_score, bias_label
                FROM analysis
                WHERE symbol = ?
                ORDER BY run_time DESC
                LIMIT ?
            """, conn, params=(symbol, limit))

    def get_pattern_history(self, symbol: str, limit: int = 20) -> pd.DataFrame:
        """Recent patterns দেখো"""
        with self._connect() as conn:
            return pd.read_sql("""
                SELECT time, pattern, engulfing, star
                FROM patterns
                WHERE symbol = ?
                  AND (pattern != 'none' OR engulfing != 'none')
                ORDER BY time DESC
                LIMIT ?
            """, conn, params=(symbol, limit))

    def stats(self):
        """Database stats দেখো"""
        with self._connect() as conn:
            for table in ['candles', 'indicators', 'patterns', 'analysis', 'trades', 'economic_history']:
                count = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                log.info(f"  {table:<18}: {count} rows")


def _safe(row, col):
    """NaN → None (SQLite-এর জন্য)"""
    import math
    val = row.get(col)
    if val is None:
        return None
    try:
        return None if math.isnan(float(val)) else float(val)
    except Exception:
        return None