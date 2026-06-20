# memory/knowledge_store.py  —  Day 16 | Vector Knowledge Memory

"""
AI-এর Long-Term Memory।

Short-term (SQLite):  "What happened?"
Long-term (ChromaDB): "Have I seen this before?"
"""

import json
import uuid
from pathlib import Path
from datetime import datetime

try:
    import chromadb
    from chromadb.utils import embedding_functions
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False


class KnowledgeStore:
    """
    AI Trader-এর vector memory।

    store.add_memory("EURUSD bearish trend, RSI oversold near support")
    store.search_memory("bearish reversal setup at support")
    """

    def __init__(self, path: str = "memory/chroma_db"):
        if not CHROMA_AVAILABLE:
            raise ImportError(
                "ChromaDB not installed.\n"
                "Run: pip install chromadb sentence-transformers"
            )

        Path(path).mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(path=path)

        self.ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )

        self.collection = self.client.get_or_create_collection(
            name="trading_memory",
            embedding_function=self.ef,
        )

        print(f"✅ KnowledgeStore ready | Memories: {self.collection.count()}")

    # ── Add Memories ───────────────────────────────────────────

    def add_memory(self, text: str, metadata: dict = None) -> str:
        """
        যেকোনো trading knowledge save করো।

        store.add_memory(
            "EURUSD bullish engulfing at daily support. Result: WIN +45 pips.",
            metadata={"type": "trade", "result": "WIN", "pair": "EURUSD"}
        )
        """
        mem_id = str(uuid.uuid4())
        meta = {
            "date": datetime.now().isoformat(),
            "type": "general",
        }
        if metadata:
            meta.update(metadata)

        self.collection.add(
            documents=[text],
            metadatas=[meta],
            ids=[mem_id],
        )
        return mem_id

    def add_trade_memory(self, trade: dict, result: str, lesson: str):
        """
        Trade শেষে automatically memory তৈরি করো।

        trade = {
            "pair": "EURUSD", "signal": "BUY",
            "entry": 1.085, "rsi": 35,
            "pattern": "hammer", "regime": "TRENDING",
            "confidence": 75
        }
        """
        text = (
            f"{trade.get('pair')} {trade.get('signal')} trade. "
            f"Regime: {trade.get('regime', 'unknown')}. "
            f"RSI: {trade.get('rsi', 'N/A')}. "
            f"Pattern: {trade.get('pattern', 'none')}. "
            f"Confidence: {trade.get('confidence', 0)}%. "
            f"Result: {result}. "
            f"Lesson: {lesson}"
        )

        return self.add_memory(text, metadata={
            "type":       "trade",
            "pair":       trade.get("pair", ""),
            "signal":     trade.get("signal", ""),
            "result":     result,
            "pattern":    trade.get("pattern", ""),
            "regime":     trade.get("regime", ""),
            "confidence": str(trade.get("confidence", 0)),
        })

    def add_rule(self, rule: str):
        """Trading rule permanently store করো।"""
        return self.add_memory(rule, metadata={"type": "rule"})

    def add_lesson(self, lesson: str, pair: str = ""):
        """ভুল থেকে শেখা lesson store করো।"""
        return self.add_memory(lesson, metadata={"type": "lesson", "pair": pair})

    # ── Search ────────────────────────────────────────────────

    def search_memory(self, query: str, limit: int = 3) -> list[dict]:
        """
        Current situation-এর মতো past cases খুঁজে দাও।

        results = store.search_memory(
            "EURUSD bearish trend RSI low near support hammer pattern"
        )
        """
        if self.collection.count() == 0:
            return []

        results = self.collection.query(
            query_texts=[query],
            n_results=min(limit, self.collection.count()),
        )

        output = []
        docs      = results.get("documents", [[]])[0]
        metas     = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for doc, meta, dist in zip(docs, metas, distances):
            similarity = round((1 - dist) * 100, 1)
            output.append({
                "memory":     doc,
                "metadata":   meta,
                "similarity": similarity,
            })

        return output

    def search_similar_trades(self, current: dict) -> list[dict]:
        """
        Current market condition-এর মতো past trades খুঁজো।

        current = {
            "pair": "EURUSD",
            "trend": "bearish",
            "rsi": 35,
            "pattern": "hammer",
            "regime": "TRENDING",
        }
        """
        query = (
            f"{current.get('pair', '')} "
            f"{current.get('trend', '')} trend "
            f"RSI {current.get('rsi', '')} "
            f"pattern {current.get('pattern', 'none')} "
            f"regime {current.get('regime', '')}"
        )
        return self.search_memory(query, limit=5)

    # ── Bulk Seed ─────────────────────────────────────────────

    def seed_trading_rules(self):
        """
        Core trading rules একবার store করো।
        AI এগুলো সবসময় মনে রাখবে।
        """
        rules = [
            "Never trade against the higher timeframe trend. If daily is bearish, avoid buying on lower timeframes.",
            "Never enter immediately after high-impact news events. Wait at least 30 minutes.",
            "Only enter when risk-reward ratio is at least 1:2. Never settle for less.",
            "Maximum 1% account risk per trade. Never risk more regardless of confidence.",
            "Wait for candle close confirmation before entering. Never enter mid-candle.",
            "If RSI is oversold in a strong downtrend, it can go lower. Oversold is not a buy signal alone.",
            "Support and resistance zones are more powerful on higher timeframes (4H, Daily).",
            "During high volatility (news events, session open), widen stop loss or avoid trading.",
            "Do not revenge trade after a loss. Stick to the plan.",
            "If confidence is below 65%, do not enter. Wait for a better setup.",
            "London-New York overlap session has highest volume and best setups.",
            "A bullish engulfing at strong support on 4H timeframe is a high probability setup.",
            "Stop loss should always be placed beyond the nearest structure (swing high/low).",
            "Never move stop loss to breakeven too early — give the trade room to breathe.",
            "Take profits at the next resistance level, not greedily targeting all-time highs.",
        ]

        for rule in rules:
            self.add_rule(rule)

        print(f"✅ {len(rules)} trading rules stored in knowledge base")

    # ── Context for LLM ───────────────────────────────────────

    def get_context_for_llm(self, current_condition: dict) -> str:
        """
        LLM prompt-এ যোগ করার জন্য past experience summary।

        Usage in ai_analyst.py:
            memory_context = store.get_context_for_llm(current)
            prompt = f"...{memory_context}..."
        """
        memories = self.search_similar_trades(current_condition)

        if not memories:
            return "No similar past experiences found."

        lines = ["Past similar situations:"]
        for i, m in enumerate(memories, 1):
            sim = m["similarity"]
            mem = m["memory"]
            lines.append(f"\n{i}. [{sim}% match] {mem}")

        return "\n".join(lines)

    # ── Stats ─────────────────────────────────────────────────

    def stats(self) -> dict:
        count = self.collection.count()
        return {"total_memories": count}

    def print_stats(self):
        s = self.stats()
        print(f"\n🧠 KnowledgeStore: {s['total_memories']} memories stored")