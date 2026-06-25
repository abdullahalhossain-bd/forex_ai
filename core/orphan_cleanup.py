"""
core/orphan_cleanup.py — Auto-reconcile DB trades with MT5 live positions.

At startup (and on each cycle, optionally), this module:
  1. Reads live open positions from MT5 (via OrderManager.get_open_positions)
  2. Reads DB trades with status='OPEN'
  3. For each DB-OPEN trade:
     - If MT5 has a matching ticket → leave alone (real open position)
     - If MT5 does NOT have it → mark as CLOSED with reason='auto_orphan_cleanup'
       (position was closed externally: SL/TP hit, manual close, restart)
  4. Also clears stale 'open_pairs' list in daily_risk.json

This eliminates the 'Correlation conflict with {AUDUSD}' blocks that
happen when an old position was closed externally but the DB still
thinks it's open.

Usage (called from core/runtime.py at EXECUTION phase):
    from core.orphan_cleanup import reconcile_open_positions
    reconciled = reconcile_open_positions(db, mt5_conn)
    # reconciled = {'closed': 2, 'kept': 1, 'errors': 0}
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

log = get_logger("orphan_cleanup")


def reconcile_open_positions(
    db,
    mt5_conn=None,
    paper_trader=None,
) -> Dict[str, int]:
    """Reconcile DB trades with MT5 live positions.

    Args:
        db: TraderDB instance (or None to use default)
        mt5_conn: MT5Connection instance (or None to skip MT5 check)
        paper_trader: PaperTrader instance (or None to skip paper check)

    Returns:
        {'closed': N, 'kept': M, 'errors': E, 'mt5_tickets': [...]}
    """
    result = {"closed": 0, "kept": 0, "errors": 0, "mt5_tickets": []}
    log.info("[OrphanCleanup] Starting reconciliation...")

    # ── Step 1: get live MT5 open positions (tickets) ──
    mt5_tickets: set[int] = set()
    if mt5_conn is not None:
        try:
            import MetaTrader5 as mt5
            positions = mt5.positions_get()
            if positions:
                for p in positions:
                    mt5_tickets.add(int(p.ticket))
                    result["mt5_tickets"].append(int(p.ticket))
            log.info(f"[OrphanCleanup] MT5 live positions: {len(mt5_tickets)}")
        except Exception as e:
            log.warning(f"[OrphanCleanup] MT5 positions_get failed: {e}")
    else:
        log.info("[OrphanCleanup] No MT5 connection — will reconcile against paper trader only")

    # ── Step 2: get DB open trades ──
    db_path = Path("database/trader.db")
    if not db_path.exists():
        log.info("[OrphanCleanup] No DB file — nothing to reconcile")
        return result

    try:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Find all OPEN trades
        cur.execute("SELECT id, pair, type, lot, entry, open_time FROM trades WHERE status = 'OPEN'")
        open_rows = cur.fetchall()
        log.info(f"[OrphanCleanup] DB open trades: {len(open_rows)}")

        if not open_rows:
            conn.close()
            _clear_stale_open_pairs()
            return result

        # ── Step 3: for each DB-OPEN trade, check if it's really open ──
        for row in open_rows:
            trade_id = row["id"]
            pair = row["pair"]
            trade_type = row["type"]

            # Heuristic: if MT5 is available and has positions, check if
            # any of them matches this pair+type.  If MT5 has NO positions
            # at all but DB has OPEN trades, they're all orphans.
            is_orphan = False
            if mt5_conn is not None:
                if not mt5_tickets:
                    # MT5 has zero open positions → all DB-OPEN trades are orphans
                    is_orphan = True
                else:
                    # MT5 has some positions — check if any matches this pair
                    # (we don't have the ticket in DB trades table, so match by pair)
                    try:
                        import MetaTrader5 as mt5
                        matching = mt5.positions_get(symbol=pair)
                        if not matching:
                            is_orphan = True
                            log.info(
                                f"[OrphanCleanup] Trade #{trade_id} {pair} {trade_type}: "
                                f"no matching MT5 position → orphan"
                            )
                    except Exception as e:
                        log.warning(f"[OrphanCleanup] positions_get({pair}) failed: {e}")
                        # Don't mark as orphan if we can't verify
            else:
                # No MT5 — if paper trader has no open position for this pair,
                # treat as orphan.  Paper trader is the in-memory state.
                if paper_trader is not None:
                    try:
                        has_open = paper_trader.has_open_position(pair, trade_type)
                        if not has_open:
                            is_orphan = True
                            log.info(
                                f"[OrphanCleanup] Trade #{trade_id} {pair} {trade_type}: "
                                f"paper trader has no open position → orphan"
                            )
                    except Exception as e:
                        log.warning(f"[OrphanCleanup] paper_trader check failed: {e}")

            if is_orphan:
                try:
                    # Day 81+ hotfix: trades table has no close_reason column
                    # (schema: id, pair, timeframe, type, entry, sl, tp, lot,
                    #  confidence, open_time, close_time, exit_price, result,
                    #  pnl, pnl_pips, spread_cost, commission, slippage, pattern,
                    #  regime, trend, rsi, session, status, context_json)
                    # Use 'context_json' to record the cleanup reason, and set
                    # status='CLOSED', close_time=now, result='AUTO_CLOSED'.
                    context = {"close_reason": "auto_orphan_cleanup"}
                    cur.execute(
                        "UPDATE trades SET status = 'CLOSED', "
                        "close_time = ?, result = 'AUTO_CLOSED', "
                        "context_json = ? "
                        "WHERE id = ?",
                        (datetime.now(timezone.utc).isoformat(),
                         json.dumps(context), trade_id),
                    )
                    result["closed"] += 1
                    log.info(
                        f"[OrphanCleanup] ✅ Closed orphan trade #{trade_id} "
                        f"{pair} {trade_type} lot={row['lot']}"
                    )
                except Exception as e:
                    result["errors"] += 1
                    log.error(f"[OrphanCleanup] Failed to close trade #{trade_id}: {e}")
            else:
                result["kept"] += 1
                log.info(f"[OrphanCleanup] ✓ Kept trade #{trade_id} {pair} (still open)")

        conn.commit()
        conn.close()
    except Exception as e:
        result["errors"] += 1
        log.error(f"[OrphanCleanup] DB error: {e}", exc_info=True)

    # ── Step 4: clear stale open_pairs in daily_risk.json ──
    _clear_stale_open_pairs(mt5_tickets if mt5_tickets else None)

    log.info(
        f"[OrphanCleanup] Done — closed={result['closed']}, "
        f"kept={result['kept']}, errors={result['errors']}"
    )
    return result


def _clear_stale_open_pairs(live_tickets=None) -> None:
    """Clear the open_pairs list in daily_risk.json so the RiskEngine's
    correlation check doesn't block trades on pairs that are no longer open.
    """
    dr_path = Path("memory/daily_risk.json")
    if not dr_path.exists():
        return
    try:
        data = json.loads(dr_path.read_text())
        old_open_pairs = data.get("open_pairs", [])
        old_open_trades = data.get("open_trades", 0)
        if old_open_pairs or old_open_trades > 0:
            # If we have MT5 live positions, derive the real open_pairs from them
            # Otherwise just clear the list — PaperTrader is the source of truth
            data["open_pairs"] = []  # will be repopulated by sync_open_positions
            data["open_trades"] = 0
            dr_path.write_text(json.dumps(data, indent=2))
            log.info(
                f"[OrphanCleanup] Cleared stale daily_risk.json "
                f"(was: open_pairs={old_open_pairs}, open_trades={old_open_trades})"
            )
    except Exception as e:
        log.warning(f"[OrphanCleanup] daily_risk.json clear failed: {e}")


def quick_close_all_db_open() -> int:
    """One-shot utility: mark ALL DB-OPEN trades as CLOSED.

    Use this when you know MT5 has no positions and want to clear
    the slate without reconciliation.  Returns count of closed rows.
    """
    db_path = Path("database/trader.db")
    if not db_path.exists():
        return 0
    try:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        cur = conn.cursor()
        # Day 81+ hotfix: trades table has no close_reason column —
        # use context_json + result='AUTO_CLOSED' instead.
        context = json.dumps({"close_reason": "manual_cleanup"})
        cur.execute(
            "UPDATE trades SET status = 'CLOSED', "
            "close_time = ?, result = 'AUTO_CLOSED', "
            "context_json = ? "
            "WHERE status = 'OPEN'",
            (datetime.now(timezone.utc).isoformat(), context),
        )
        closed = cur.rowcount
        conn.commit()
        conn.close()
        log.info(f"[OrphanCleanup] quick_close_all_db_open: {closed} trades closed")
        # Also clear daily_risk.json
        _clear_stale_open_pairs()
        return closed
    except Exception as e:
        log.error(f"[OrphanCleanup] quick_close_all_db_open failed: {e}")
        return 0
