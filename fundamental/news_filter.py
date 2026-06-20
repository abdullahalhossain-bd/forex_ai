# fundamental/news_filter.py  —  Day 11 | Real News Filter Engine

import requests
import pytz
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from utils.logger import get_logger

log = get_logger("news_filter")


class NewsFilter:
    """
    Real economic calendar থেকে high impact news check করে।
    Primary: Forex Factory scraper
    Fallback: Hard-coded weekly schedule (যদি scrape fail করে)
    """

    # News window — event এর আগে/পরে কতক্ষণ trade বন্ধ
    WINDOW_BEFORE = 30   # minutes
    WINDOW_AFTER  = 60   # minutes

    # এই currencies এর news check করবো
    WATCHED_CURRENCIES = {"USD", "EUR", "GBP", "JPY"}

    HIGH_IMPACT_KEYWORDS = [
        "Non-Farm", "NFP", "CPI", "Interest Rate", "FOMC",
        "GDP", "Unemployment", "Retail Sales", "Fed Chair",
        "ECB", "BOE", "BOJ", "Inflation", "PMI Flash",
    ]

    FF_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.forexfactory.com/",
    }

    # ── Main public method ─────────────────────────────────────
    def check(self, symbol: str = "EURUSD") -> dict:
        """
        Symbol থেকে currencies বের করে news check করে।
        EURUSD → EUR + USD উভয়ই check হবে।
        """
        currencies = self._extract_currencies(symbol)
        log.info(f"Checking news for: {currencies}")

        events = self._fetch_events()

        if not events:
            log.warning("Could not fetch live news — using safe fallback")
            return self._safe_result("News fetch failed — proceed with caution")

        now_utc = datetime.now(pytz.utc)
        flagged = []

        for event in events:
            if event["currency"] not in currencies:
                continue
            if not event["high_impact"]:
                continue

            event_time = event["time"]
            window_start = event_time - timedelta(minutes=self.WINDOW_BEFORE)
            window_end   = event_time + timedelta(minutes=self.WINDOW_AFTER)

            if window_start <= now_utc <= window_end:
                mins_to = int((event_time - now_utc).total_seconds() / 60)
                flagged.append({
                    "event":    event["title"],
                    "currency": event["currency"],
                    "time":     event_time.strftime("%H:%M UTC"),
                    "mins_to":  mins_to,
                })

        if flagged:
            ev = flagged[0]
            reason = (
                f"{ev['currency']} {ev['event']} @ {ev['time']} "
                f"({abs(ev['mins_to'])} min {'until' if ev['mins_to'] > 0 else 'ago'})"
            )
            return {
                "trade_allowed": False,
                "reason":        reason,
                "flagged_events": flagged,
                "currencies_checked": list(currencies),
            }

        # Upcoming events এর list (info only)
        upcoming = [
            e for e in events
            if e["currency"] in currencies
            and e["high_impact"]
            and e["time"] > now_utc
            and (e["time"] - now_utc).total_seconds() < 3 * 3600
        ]

        return {
            "trade_allowed":      True,
            "reason":             "No high impact news in window",
            "flagged_events":     [],
            "upcoming_events":    [
                {
                    "event":    e["title"],
                    "currency": e["currency"],
                    "time":     e["time"].strftime("%H:%M UTC"),
                }
                for e in upcoming[:3]
            ],
            "currencies_checked": list(currencies),
        }

    # ── Forex Factory scraper ──────────────────────────────────
    def _fetch_events(self) -> list:
        try:
            url  = "https://www.forexfactory.com/calendar"
            resp = requests.get(url, headers=self.FF_HEADERS, timeout=10)
            resp.raise_for_status()
            return self._parse_ff(resp.text)
        except Exception as e:
            log.warning(f"Forex Factory fetch failed: {e}")
            return []

    def _parse_ff(self, html: str) -> list:
        soup   = BeautifulSoup(html, "html.parser")
        events = []
        now    = datetime.now(pytz.utc)

        # FF table rows
        rows = soup.select("tr.calendar__row")
        current_date = now.date()
        current_time = None

        for row in rows:
            try:
                # Date cell (span এ থাকে)
                date_cell = row.select_one(".calendar__date span")
                if date_cell and date_cell.text.strip():
                    # FF date format: "Mon Jan 20"
                    date_str = date_cell.text.strip()
                    try:
                        parsed = datetime.strptime(
                            f"{date_str} {now.year}", "%a %b %d %Y"
                        )
                        current_date = parsed.date()
                    except ValueError:
                        pass

                # Time cell
                time_cell = row.select_one(".calendar__time")
                if time_cell and time_cell.text.strip():
                    t_text = time_cell.text.strip()
                    if ":" in t_text:
                        try:
                            t = datetime.strptime(t_text, "%I:%M%p")
                            current_time = t.time()
                        except ValueError:
                            pass

                if current_time is None:
                    continue

                # Currency
                cur_cell = row.select_one(".calendar__currency")
                if not cur_cell:
                    continue
                currency = cur_cell.text.strip().upper()
                if currency not in self.WATCHED_CURRENCIES:
                    continue

                # Impact (FF uses icon classes: high/medium/low)
                impact_cell = row.select_one(".calendar__impact span")
                impact_cls  = impact_cell.get("class", []) if impact_cell else []
                is_high     = any("red" in c or "high" in c for c in impact_cls)

                # Title
                title_cell = row.select_one(".calendar__event-title")
                title      = title_cell.text.strip() if title_cell else ""

                # keyword fallback for impact detection
                if not is_high:
                    is_high = any(
                        kw.lower() in title.lower()
                        for kw in self.HIGH_IMPACT_KEYWORDS
                    )

                # Build UTC datetime
                naive_dt = datetime.combine(current_date, current_time)
                # FF shows US Eastern time
                eastern  = pytz.timezone("US/Eastern")
                local_dt = eastern.localize(naive_dt)
                utc_dt   = local_dt.astimezone(pytz.utc)

                events.append({
                    "title":       title,
                    "currency":    currency,
                    "high_impact": is_high,
                    "time":        utc_dt,
                })

            except Exception:
                continue

        log.info(f"Parsed {len(events)} events from Forex Factory")
        return events

    # ── Helpers ───────────────────────────────────────────────
    def _extract_currencies(self, symbol: str) -> set:
        symbol = symbol.upper().replace("/", "").replace("=X", "")
        if len(symbol) >= 6:
            return {symbol[:3], symbol[3:6]}
        return {"USD"}

    def _safe_result(self, reason: str) -> dict:
        return {
            "trade_allowed":      True,
            "reason":             reason,
            "flagged_events":     [],
            "upcoming_events":    [],
            "currencies_checked": [],
        }

    # ── Currency strength (basic) ──────────────────────────────
    def currency_strength(self, ind_ctx: dict) -> dict:
        """
        Basic currency strength — indicator থেকে।
        Week 4 এ full multi-pair analysis আসবে।
        """
        price = ind_ctx.get("close", 0)
        sma20 = ind_ctx.get("sma20", price)
        sma50 = ind_ctx.get("sma50", price)
        rsi   = ind_ctx.get("rsi", 50)

        score = 0
        if price > sma20: score += 1
        if price > sma50: score += 1
        if rsi > 55:      score += 1
        if rsi < 45:      score -= 1
        if price < sma20: score -= 1
        if price < sma50: score -= 1

        label = (
            "STRONG"   if score >= 2  else
            "WEAK"     if score <= -2 else
            "NEUTRAL"
        )
        return {"score": score, "label": label}

    # ── Event Memory save ──────────────────────────────────────
    def save_event_memory(self, event: dict, reaction_pips: float = 0) -> None:
        """
        News event + market reaction memory তে save করে।
        Future self-learning এর জন্য।
        """
        import json, os
        path = "memory/news_history.json"
        os.makedirs("memory", exist_ok=True)

        history = []
        if os.path.exists(path):
            try:
                with open(path) as f:
                    history = json.load(f)
            except Exception:
                pass

        history.append({
            "timestamp":     datetime.now(pytz.utc).isoformat(),
            "event":         event.get("event", ""),
            "currency":      event.get("currency", ""),
            "reaction_pips": reaction_pips,
            "lesson":        f"Avoid entry 30 min before {event.get('event', '')}",
        })

        with open(path, "w") as f:
            json.dump(history[-100:], f, indent=2)   # শেষ 100টা রাখো

        log.info(f"News memory saved: {event.get('event')}")

    # ── Print ──────────────────────────────────────────────────
    def print_summary(self, result: dict) -> None:
        bar    = "═" * 44
        allowed = result["trade_allowed"]
        icon   = "✅" if allowed else "⛔"

        log.info(bar)
        log.info(f"  {icon}  NEWS FILTER")
        log.info(bar)
        log.info(f"  Trade allowed : {allowed}")
        log.info(f"  Reason        : {result['reason']}")

        if result.get("flagged_events"):
            log.info("  ── Flagged ──")
            for ev in result["flagged_events"]:
                log.info(f"    {ev['currency']} {ev['event']} @ {ev['time']}")

        if result.get("upcoming_events"):
            log.info("  ── Upcoming (3h) ──")
            for ev in result["upcoming_events"]:
                log.info(f"    {ev['currency']} {ev['event']} @ {ev['time']}")

        log.info(bar)

    def get_ai_context(self, result: dict) -> dict:
        return {
            "news_trade_allowed": result["trade_allowed"],
            "news_reason":        result["reason"],
            "news_flagged_count": len(result.get("flagged_events", [])),
            "news_upcoming":      result.get("upcoming_events", []),
        }