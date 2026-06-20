# learning/mistake_analyzer.py
# ============================================================
# Day 19 | Advanced AI Self-Learning Loop & Mistake Analyzer
# ============================================================

import json
from datetime import datetime
from memory.trade_memory import TradeMemory
from utils.logger import get_logger

log = get_logger(__name__)

class AdvancedMistakeAnalyzer:
    """
    LLM এবং ভেক্টর মেমোরির সমন্বয়ে গঠিত ক্লোজড ট্রেড অ্যানালাইসিস লুপ।
    এটি প্রতিটি ট্রেডের গভীরে গিয়ে ভুল এবং সাফল্যের মূল কারণ অনুসন্ধান করে।
    """
    
    def __init__(self, llm_client=None):
        self.memory = TradeMemory()
        self.llm = llm_client  # আপনার প্রজেক্টের LLM/Gemini ক্লায়েন্ট এখানে পাস হবে
        
    def analyze_closed_trade(self, trade_id: int):
        """ট্রেড ক্লোজ হওয়ার পর সেলফ-লার্নিং লুপ ট্রিগার করার মেইন মেথড।"""
        trade = self.memory.db.get_trade_by_id(trade_id)
        if not trade:
            log.error(f"❌ Trade #{trade_id} not found in database.")
            return
            
        result = trade.get("result")
        pnl = trade.get("pnl", 0)
        
        if result == "LOSS":
            log.info(f"🔍 Analyzing LOSS for Trade #{trade_id}...")
            self._process_loss_trade(trade, pnl)
        elif result == "WIN" and pnl > 0:
            log.info(f"🏆 Analyzing WIN for Trade #{trade_id}...")
            self._process_win_trade(trade, pnl)
            
    def _process_loss_trade(self, trade: dict, pnl: float):
        """লস ট্রেডের রুট কজ এবং ভেক্টর মেমোরি ম্যাচিং অ্যানালাইসিস।"""
        trade_snapshot = json.loads(trade.get("chart_snapshot", "{}")) if isinstance(trade.get("chart_snapshot"), str) else trade.get("chart_snapshot", {})
        
        # ১. ভেক্টর মেমোরি থেকে একই ধরণের অতীতের লস খোঁজা
        similar_past_failures = ""
        if self.memory.vector:
            query_str = f"{trade.get('pair')} LOSS {trade_snapshot.get('trend')} trend RSI {trade_snapshot.get('rsi')} pattern {trade_snapshot.get('pattern')}"
            similar_memories = self.memory.vector.search_memory(query_str, limit=2)
            if similar_memories:
                similar_past_failures = "\n".join([f"- Past Lesson: {m['memory']}" for m in similar_memories])

        # ২. LLM এর জন্য প্রম্পট রেডি করা (রুট কজ বের করতে)
        prompt = f"""
        You are the Post-Trade Audit Engine of an AI Trading Bot. 
        Analyze this LOSS trade and determine the structural mistake or market context that caused it.

        [TRADE DETAILS]
        Pair: {trade.get('pair')}
        Signal: {trade.get('signal')}
        Entry: {trade.get('entry')} | SL: {trade.get('sl')} | TP: {trade.get('tp')}
        Risk-Reward: 1:{trade.get('rr_ratio')}
        Bot Confidence: {trade.get('confidence')}%
        PnL: {pnl}

        [MARKET CONTEXT AT ENTRY]
        Trend: {trade_snapshot.get('trend')}
        Regime: {trade_snapshot.get('regime')}
        RSI: {trade_snapshot.get('rsi')}
        Pattern: {trade_snapshot.get('pattern')}

        [SIMILAR PAST LESSONS FOUND]
        {similar_past_failures if similar_past_failures else "No repetitive pattern found yet."}

        Provide a structured breakdown in JSON format only:
        {{
            "error_type": "Short label of the mistake (e.g., Counter-Trend Entry, Low Liquidity, Bad R:R)",
            "what_happened": "Detailed explanation of why this failed based on indicators & context.",
            "lesson": "A strict actionable rule for the future to prevent this specific failure.",
            "confidence_adjustment": -5  // Recommendation to lower confidence for this specific setup (Range: -20 to 0)
        }}
        """
        
        # ৩. LLM এক্সিকিউশন এবং মেমোরি আপডেট
        try:
            # উদাহরণস্বরূপ একটি মক বা ডাইনামিক কল (আপনার LLM আর্কিটেকচার অনুযায়ী রূপান্তর করে নেবেন)
            if self.llm:
                response = self.llm.generate(prompt)
                analysis = json.loads(response)
            else:
                # Fallback to automated heuristic if LLM client isn't passed
                analysis = {
                    "error_type": "Market Variance",
                    "what_happened": f"Trade executed with {trade.get('confidence')}% confidence but market invalidated the setup.",
                    "lesson": "Maintain system discipline. Review higher timeframe structure next time.",
                    "confidence_adjustment": -2
                }
                
            # SQLite ও ভেক্টর ডাটাবেজে সেভ করা
            mistake_data = {
                "trade_id": trade.get("id"),
                "pair": trade.get("pair"),
                "error_type": analysis.get("error_type"),
                "what_happened": analysis.get("what_happened"),
                "lesson": analysis.get("lesson")
            }
            self.memory.db.save_mistake(mistake_data)
            
            # Pattern memory ও ভেক্টরে পুশ
            self.memory.pattern.add_losing_pattern({
                "pair": trade.get("pair"),
                "signal": trade.get("signal"),
                "pattern": trade_snapshot.get("pattern"),
                "regime": trade_snapshot.get("regime"),
                "rsi": trade_snapshot.get("rsi"),
                "pnl": pnl
            }, lesson=analysis.get("lesson"))
            
            if self.memory.vector:
                self.memory.vector.add_lesson(
                    f"CRITICAL LESSON for {trade.get('pair')} [{analysis.get('error_type')}]: {analysis.get('lesson')}", 
                    pair=trade.get("pair")
                )
                
            log.info(f"💡 Advanced Loop Completed. Lesson Learned: {analysis.get('lesson')}")
            
        except Exception as e:
            log.error(f"⚠️ Failed to run LLM Mistake Audit: {e}")

    def _process_win_trade(self, trade: dict, pnl: float):
        """সফল ট্রেডগুলোর পজিটিভ রিইনফোর্সমেন্ট অ্যানালাইসিস (Bonus Task)।"""
        trade_snapshot = json.loads(trade.get("chart_snapshot", "{}")) if isinstance(trade.get("chart_snapshot"), str) else trade.get("chart_snapshot", {})
        
        # উইনিং স্ট্র্যাটেজি লক করা
        positive_lesson = f"Successful {trade.get('signal')} trade on {trade.get('pair')} during {trade_snapshot.get('regime')} market with {trade_snapshot.get('pattern')} pattern. R:R was 1:{trade.get('rr_ratio')}."
        
        self.memory.pattern.add_winning_pattern({
            "pair": trade.get("pair"),
            "signal": trade.get("signal"),
            "pattern": trade_snapshot.get("pattern"),
            "regime": trade_snapshot.get("regime"),
            "rsi": trade_snapshot.get("rsi"),
            "pnl": pnl,
            "rr": trade.get("rr_ratio")
        })
        
        if self.memory.vector:
            self.memory.vector.add_memory(
                f"VALIDATED SETUP: {positive_lesson} Keep replication high when these alpha factors align.",
                metadata={"type": "winning_reinforcement", "pair": trade.get("pair")}
            )
        log.info(f"🎯 Win reinforcement logged for Trade #{trade.get('id')}")