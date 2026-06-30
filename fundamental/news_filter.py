# fundamental/news_filter.py  —  Day 11 (base) + Day 43 + Day 90 + Day 91 + Day 92
#
# Day 92 fix: নিজস্ব _FAIRECONOMY_CACHE সরিয়ে shared
# fundamental.faireconomy_cache.fetch_faireconomy() ব্যবহার করা হচ্ছে।
# এতে economic_calendar_api এবং news_filter দুটোই একই cache থেকে পাবে।

import time
from datetime import datetime, timedelta

import pytz
import requests
from bs4 import BeautifulSoup

from utils.logger import get_logger
from fundamental.faireconomy_cache import fetch_faireconomy

log = get_logger("news_filter")

try:
    import cloudscraper
    _CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    _CLOUDSCRAPER_AVAILABLE = False

VOLATILITY_MAP = {
    "non-farm":        {"level": "EXTREME", "pips": (80, 150)},
    "nfp":             {"level": "EXTREME", "pips": (80, 150)},
    "interest rate":   {"level": "EXTREME", "pips": (70, 130)},
    "fomc":            {"level": "EXTREME", "pips": (70, 130)},
    "fed chair":       {"level": "HIGH",    "pips": (40, 90)},
    "cpi":             {"level": "HIGH",    "pips": (50, 100)},
    "inflation":       {"level": "HIGH",    "pips": (40, 90)},
    "unemployment":    {"level": "HIGH",    "pips": (40, 80)},
    "ecb":             {"level": "HIGH",    "pips": (40, 90)},
    "boe":             {"level": "HIGH",    "pips": (35, 80)},
    "boj":             {"level": "HIGH",    "pips": (35, 80)},
    "gdp":             {"level": "MEDIUM",  "pips": (30, 60)},
    "retail sales":    {"level": "MEDIUM",  "pips": (25, 50)},
    "pmi":             {"level": "MEDIUM",  "pips": (20, 45)},
}
DEFAULT_VOLATILITY = {"level": "LOW", "pips": (5, 20)}

CURRENCY_PAIR_MAP = {
    "USD": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "XAUUSD"],
    "EUR": ["EURUSD", "EURGBP", "EURJPY", "EURAUD", "EURCAD", "EURCHF", "EURNZD"],
    "GBP": ["GBPUSD", "EURGBP", "GBPJPY", "GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "JPY": ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "CADJPY", "CHFJPY", "NZDJPY"],
}

AFTERMATH_WAIT_MINUTES = 15

HARDCODED_WEEKLY_EVENTS = [
    (2, 12, 30, "USD", "CPI (typical release day/time — verify live calendar)"),
    (4, 12, 30, "USD", "Non-Farm Payrolls (typical 1st-Friday release — verify live calendar)"),
    (2, 18, 0,  "USD", "FOMC Statement (typical — verify live calendar)"),
    (3, 11, 45, "EUR", "ECB Rate Decision (typical — verify live calendar)"),
    (3, 6, 0,   "GBP", "BOE Rate Decision (typical — verify live calendar)"),
]


class NewsFilter:
    WINDOW_BEFORE = 30
    WINDOW_AFTER  = 60
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
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.forexfactory.com/",
    }
    FETCH_MAX_RETRIES   = 1
    FETCH_RETRY_DELAY_S = 2.0

    def __init__(self):
        self._scraper = None

    def check(self, symbol: str = "EURUSD") -> dict:
        currencies = self._extract_currencies(symbol)
        log.info(f"Checking news for: {currencies}")

        events, source = self._fetch_events()

        if not events:
            log.warning("Could not fetch any news data — using safe fallback (trade allowed)")
            return self._safe_result("News fetch failed — proceed with caution")

        now_utc = datetime.now(pytz.utc)
        flagged = []

        for event in events:
            if event["currency"] not in currencies:
                continue
            if not event["high_impact"]:
                continue

            event_time   = event["time"]
            window_start = event_time - timedelta(minutes=self.WINDOW_BEFORE)
            window_end   = event_time + timedelta(minutes=self.WINDOW_AFTER)

            if window_start <= now_utc <= window_end:
                mins_to = int((event_time - now_utc).total_seconds() / 60)
                vol     = self.estimate_volatility(event["title"])
                flagged.append({
                    "event":      event["title"],
                    "currency":   event["currency"],
                    "time":       event_time.strftime("%H:%M UTC"),
                    "mins_to":    mins_to,
                    "volatility": vol,
                })

        if flagged:
            ev        = flagged[0]
            aftermath = self.post_news_status(self._event_time_from_label(ev, now_utc))
            reason = (
                f"{ev['currency']} {ev['event']} @ {ev['time']} "
                f"({abs(ev['mins_to'])} min {'until' if ev['mins_to'] > 0 else 'ago'}) "
                f"— expected volatility: {ev['volatility']['level']}"
            )
            return {
                "trade_allowed":      False,
                "reason":             reason,
                "flagged_events":     flagged,
                "currencies_checked": list(currencies),
                "risk_level":         self._max_risk_level(flagged),
                "aftermath":          aftermath,
                "source":             source,
            }

        upcoming_raw = [
            e for e in events
            if e["currency"] in currencies
            and e["high_impact"]
            and e["time"] > now_utc
            and (e["time"] - now_utc).total_seconds() < 3 * 3600
        ]
        upcoming = [
            {
                "event":      e["title"],
                "currency":   e["currency"],
                "time":       e["time"].strftime("%H:%M UTC"),
                "volatility": self.estimate_volatility(e["title"]),
            }
            for e in upcoming_raw[:3]
        ]

        return {
            "trade_allowed":      True,
            "reason":             "No high impact news in window",
            "flagged_events":     [],
            "upcoming_events":    upcoming,
            "currencies_checked": list(currencies),
            "risk_level":         self._max_risk_level(upcoming) if upcoming else "LOW",
            "aftermath":          {"in_confirmation_window": False, "advice": ""},
            "source":             source,
        }

    def estimate_volatility(self, title: str) -> dict:
        title_lower = (title or "").lower()
        for keyword, info in VOLATILITY_MAP.items():
            if keyword in title_lower:
                return dict(info)
        return dict(DEFAULT_VOLATILITY)

    def affected_pairs(self, currency: str) -> list:
        return CURRENCY_PAIR_MAP.get(currency.upper(), [])

    def post_news_status(self, event_time) -> dict:
        if event_time is None:
            return {"in_confirmation_window": False, "advice": ""}
        now_utc     = datetime.now(pytz.utc)
        elapsed_min = (now_utc - event_time).total_seconds() / 60
        if 0 <= elapsed_min < AFTERMATH_WAIT_MINUTES:
            remaining = round(AFTERMATH_WAIT_MINUTES - elapsed_min)
            return {
                "in_confirmation_window": True,
                "minutes_remaining":      remaining,
                "advice": (
                    f"News released {round(elapsed_min)} min ago — first move "
                    f"often fakes out (liquidity grab). Wait {remaining} more "
                    f"min and confirm direction before entering."
                ),
            }
        return {"in_confirmation_window": False, "advice": ""}

    def _event_time_from_label(self, flagged_event: dict, now_utc) -> datetime:
        return (
            now_utc - timedelta(minutes=flagged_event.get("mins_to", 0))
            if flagged_event.get("mins_to", 0) <= 0
            else now_utc + timedelta(minutes=flagged_event["mins_to"])
        )

    def _max_risk_level(self, events: list) -> str:
        order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "EXTREME": 3}
        best  = "LOW"
        for e in events:
            lvl = e.get("volatility", {}).get("level", "LOW")
            if order.get(lvl, 0) > order.get(best, 0):
                best = lvl
        return best

    def get_weekly_calendar(self, events: list | None = None) -> dict:
        events = events if events is not None else self._fetch_events()[0]
        by_day: dict[str, list] = {}
        for e in events:
            if not e.get("high_impact"):
                continue
            if e["currency"] not in self.WATCHED_CURRENCIES:
                continue
            day_key = e["time"].strftime("%Y-%m-%d")
            by_day.setdefault(day_key, []).append({
                "time":       e["time"].strftime("%H:%M UTC"),
                "currency":   e["currency"],
                "event":      e["title"],
                "volatility": self.estimate_volatility(e["title"]),
            })
        for day_key in by_day:
            by_day[day_key].sort(key=lambda x: x["time"])
        return dict(sorted(by_day.items()))

    def print_weekly_calendar(self, calendar: dict | None = None) -> None:
        calendar = calendar if calendar is not None else self.get_weekly_calendar()
        bar = "═" * 48
        log.info(bar)
        log.info("  📅  WEEKLY ECONOMIC CALENDAR  (Day 43)")
        log.info(bar)
        if not calendar:
            log.info("  No high-impact events found this week.")
        for day, events in calendar.items():
            log.info(f"  {day}")
            for e in events:
                tag = "⚠️ " if e["volatility"]["level"] in ("HIGH", "EXTREME") else "  "
                log.info(f"    {tag}{e['time']}  {e['currency']}  {e['event']}  [{e['volatility']['level']}]")
        log.info(bar)

    # ── Fetch chain ────────────────────────────────────────────
    def _fetch_events(self) -> tuple[list, str]:
        # ── Layer 0: shared FairEconomy cache (Day 92) ──
        events = fetch_faireconomy(self.WATCHED_CURRENCIES, self.HIGH_IMPACT_KEYWORDS)
        if events:
            return events, "faireconomy_json"

        # ── Layer 1: cloudscraper ──
        if _CLOUDSCRAPER_AVAILABLE:
            html = self._fetch_html_cloudscraper()
            if html:
                events = self._parse_ff(html)
                if events:
                    return events, "forexfactory_cloudscraper"

        # ── Layer 2: plain requests (1 retry) ──
        html = self._fetch_html_requests_with_retry()
        if html:
            events = self._parse_ff(html)
            if events:
                return events, "forexfactory_requests"

        # ── Layer 3: hardcoded fallback ──
        log.warning("Live Forex Factory fetch fully failed → hardcoded fallback")
        fallback_events = self._build_hardcoded_events()
        if fallback_events:
            return fallback_events, "hardcoded_fallback"

        return [], "none"

    def _fetch_html_cloudscraper(self) -> str | None:
        try:
            if self._scraper is None:
                self._scraper = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "mobile": False}
                )
            resp = self._scraper.get(
                "https://www.forexfactory.com/calendar",
                headers=self.FF_HEADERS, timeout=15,
            )
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            log.warning(f"cloudscraper fetch failed: {e}")
            return None

    def _fetch_html_requests_with_retry(self) -> str | None:
        url      = "https://www.forexfactory.com/calendar"
        last_err = None
        for attempt in range(1, self.FETCH_MAX_RETRIES + 1):
            try:
                resp = requests.get(url, headers=self.FF_HEADERS, timeout=10)
                resp.raise_for_status()
                return resp.text
            except Exception as e:
                last_err = e
                log.warning(f"Forex Factory fetch failed (attempt {attempt}/{self.FETCH_MAX_RETRIES}): {e}")
                if attempt < self.FETCH_MAX_RETRIES:
                    time.sleep(self.FETCH_RETRY_DELAY_S * attempt)
        log.warning(f"Forex Factory fetch exhausted retries — last error: {last_err}")
        return None

    def _build_hardcoded_events(self) -> list:
        now_utc = datetime.now(pytz.utc)
        events  = []
        for weekday, hour, minute, currency, title in HARDCODED_WEEKLY_EVENTS:
            days_ahead = (weekday - now_utc.weekday()) % 7
            event_date = (now_utc + timedelta(days=days_ahead)).date()
            event_dt   = datetime(
                event_date.year, event_date.month, event_date.day,
                hour, minute, tzinfo=pytz.utc,
            )
            events.append({"title": title, "currency": currency, "high_impact": True, "time": event_dt})
            events.append({"title": title, "currency": currency, "high_impact": True, "time": event_dt - timedelta(days=7)})
        return events

    def _parse_ff(self, html: str) -> list:
        soup   = BeautifulSoup(html, "html.parser")
        events = []
        now    = datetime.now(pytz.utc)
        rows   = soup.select("tr.calendar__row")
        current_date = now.date()
        current_time = None

        for row in rows:
            try:
                date_cell = row.select_one(".calendar__date span")
                if date_cell and date_cell.text.strip():
                    try:
                        parsed = datetime.strptime(
                            f"{date_cell.text.strip()} {now.year}", "%a %b %d %Y"
                        )
                        current_date = parsed.date()
                    except ValueError:
                        pass

                time_cell = row.select_one(".calendar__time")
                if time_cell and time_cell.text.strip():
                    t_text = time_cell.text.strip()
                    if ":" in t_text:
                        try:
                            current_time = datetime.strptime(t_text, "%I:%M%p").time()
                        except ValueError:
                            pass

                if current_time is None:
                    continue

                cur_cell = row.select_one(".calendar__currency")
                if not cur_cell:
                    continue
                currency = cur_cell.text.strip().upper()
                if currency not in self.WATCHED_CURRENCIES:
                    continue

                impact_cell = row.select_one(".calendar__impact span")
                impact_cls  = impact_cell.get("class", []) if impact_cell else []
                is_high     = any("red" in c or "high" in c for c in impact_cls)

                title_cell = row.select_one(".calendar__event-title")
                title      = title_cell.text.strip() if title_cell else ""

                if not is_high:
                    is_high = any(kw.lower() in title.lower() for kw in self.HIGH_IMPACT_KEYWORDS)

                naive_dt = datetime.combine(current_date, current_time)
                eastern  = pytz.timezone("US/Eastern")
                utc_dt   = eastern.localize(naive_dt).astimezone(pytz.utc)

                events.append({"title": title, "currency": currency, "high_impact": is_high, "time": utc_dt})
            except Exception:
                continue

        log.info(f"Parsed {len(events)} events from Forex Factory")
        return events

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
            "risk_level":         "LOW",
            "aftermath":          {"in_confirmation_window": False, "advice": ""},
            "source":             "none",
        }

    def currency_strength(self, ind_ctx: dict) -> dict:
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
        label = "STRONG" if score >= 2 else "WEAK" if score <= -2 else "NEUTRAL"
        return {"score": score, "label": label}

    def save_event_memory(self, event: dict, reaction_pips: float = 0) -> None:
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
            json.dump(history[-100:], f, indent=2)
        log.info(f"News memory saved: {event.get('event')}")

    def print_summary(self, result: dict) -> None:
        bar     = "═" * 44
        allowed = result["trade_allowed"]
        log.info(bar)
        log.info(f"  {'✅' if allowed else '⛔'}  NEWS FILTER  (Day 43)")
        log.info(bar)
        log.info(f"  Trade allowed : {allowed}")
        log.info(f"  Reason        : {result['reason']}")
        log.info(f"  Risk level    : {result.get('risk_level', 'LOW')}")
        log.info(f"  Data source   : {result.get('source', 'unknown')}")
        if result.get("aftermath", {}).get("in_confirmation_window"):
            log.info(f"  ⏳ Aftermath  : {result['aftermath']['advice']}")
        if result.get("flagged_events"):
            log.info("  ── Flagged ──")
            for ev in result["flagged_events"]:
                vol = ev.get("volatility", {})
                log.info(
                    f"    {ev['currency']} {ev['event']} @ {ev['time']} "
                    f"[{vol.get('level','?')} | {vol.get('pips', ('?','?'))} pips]"
                )
        if result.get("upcoming_events"):
            log.info("  ── Upcoming (3h) ──")
            for ev in result["upcoming_events"]:
                vol = ev.get("volatility", {})
                log.info(f"    {ev['currency']} {ev['event']} @ {ev['time']} [{vol.get('level','?')}]")
        log.info(bar)

    def get_ai_context(self, result: dict) -> dict:
        return {
            "news_trade_allowed": result["trade_allowed"],
            "news_reason":        result["reason"],
            "news_flagged_count": len(result.get("flagged_events", [])),
            "upcoming_events":    result.get("upcoming_events", []),
            "risk_level":         result.get("risk_level", "LOW"),
            "aftermath":          result.get("aftermath", {}),
            "source":             result.get("source", "unknown"),
            "trade_allowed":      result["trade_allowed"],
        }