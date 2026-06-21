# FOREX AI — Autonomous Trading System

An AI-powered autonomous forex trading platform that combines technical analysis, Smart Money Concepts (SMC), LLM reasoning, and automated risk management to trade forex markets through MetaTrader 5 or paper trading simulation.

## Architecture

```
Market Data (yfinance / MT5)
         ↓
    Market Agent (data fetch, indicators, regime)
         ↓
    Analysis Agent
    ├── Session Analysis (London/NY/Tokyo)
    ├── Pattern Detection (candlestick, advanced)
    ├── Support/Resistance + Fibonacci
    ├── Market Bias Engine
    ├── Signal Engine (rule-based scoring)
    ├── Sentiment Analysis
    ├── SMC Engine (BOS, CHoCH, Order Blocks, FVG)
    ├── Liquidity Engine (sweeps, zones)
    ├── Intermarket Analysis (DXY, Gold, Yields, VIX)
    ├── Currency Strength Calculator
    ├── News Filter
    ├── AI Analyst (Groq/Gemini LLM)
    └── Master Analyst (Anthropic Claude)
         ↓
    Decision Agent (weighted voting: Master×3, LLM×2, Rule×1)
         ↓
    Risk Engine (1% risk, daily loss limit, correlation check)
    + Circuit Breaker (kill switch)
    + Trade Permission (news, confidence, session gates)
         ↓
    Approval Mode (Analysis / Supervised / Autonomous)
         ↓
    Execution Router
    ├── Paper Trader (simulation with slippage/spread/commission)
    └── MT5 Demo (real broker, demo account)
         ↓
    Position Management (SL/TP, breakeven, trailing, multi-TP)
         ↓
    Learning System
    ├── Trade Memory (vector DB pattern matching)
    ├── Mistake Analyzer
    ├── Confidence Engine (dynamic adjustment)
    └── Auto Optimizer
         ↓
    Dashboard (Streamlit) + Telegram Bot + DB Logging
```

## Quick Start

### 1. Prerequisites

- Python 3.10+
- MetaTrader 5 (only for live/demo mode — paper mode works without it)
- At least one LLM API key (Groq free tier recommended)

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/abdullahalhossain-bd/forex_ai.git
cd forex_ai

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration

```bash
# Copy the environment template
cp .env.example .env

# Edit .env with your API keys
# Minimum required: GROQ_API_KEY (free at https://console.groq.com)
```

**Required API Keys (at least one):**
| Provider | Key | Free Tier | Purpose |
|----------|-----|-----------|---------|
| Groq | `GROQ_API_KEY` | Yes (14 req/min) | Primary LLM analyst |
| Gemini | `GEMINI_API_KEY` | Yes (15 req/min) | Fallback LLM |
| Anthropic | `ANTHROPIC_API_KEY` | No | Master Analyst (optional) |

**Optional API Keys:**
| Provider | Key | Free Tier | Purpose |
|----------|-----|-----------|---------|
| Telegram | `TELEGRAM_TOKEN` | Yes | Trade alerts & commands |
| Alpha Vantage | `ALPHA_VANTAGE_API_KEY` | Yes (25/day) | Market data |
| Finnhub | `FINNHUB_API_KEY` | Yes | News & data |
| Twelve Data | `TWELVE_DATA_API_KEY` | Yes (8/min) | Market data |
| FRED | `FRED_API_KEY` | Yes | Economic data |

### 4. Run the System

```bash
# Start autonomous trading (paper mode by default)
python main.py

# Initialize only (verify everything works)
python main.py --mode init

# Force paper trading mode
python main.py --paper

# Trade specific pairs
python main.py --pairs EURUSD,GBPUSD,USDJPY

# Use 1-hour timeframe
python main.py --timeframe 1h

# Disable Telegram
python main.py --no-telegram
```

### 5. Streamlit Dashboard

```bash
streamlit run dashboard/app.py
```

## Execution Modes

| Mode | .env Value | Description |
|------|-----------|-------------|
| Paper | `EXECUTION_MODE=paper` | Simulated trading with slippage/spread/commission. **No real money at risk.** |
| MT5 Demo | `EXECUTION_MODE=mt5_demo` | Real MT5 demo account. Requires MT5 terminal running + credentials. |

## Approval Modes

| Mode | .env Value | Behavior |
|------|-----------|----------|
| Analysis Only | `APPROVAL_MODE=1` | AI watches and analyzes, never executes trades |
| Supervised | `APPROVAL_MODE=2` | AI suggests trades, human must approve via Telegram |
| Autonomous | `APPROVAL_MODE=3` | AI makes and executes all decisions automatically |

## Risk Management

The system implements multiple layers of risk protection:

- **1% Risk Per Trade**: Maximum 1% of account balance risked per trade
- **3% Daily Loss Limit**: Trading stops if daily losses exceed 3%
- **Correlation Filter**: Prevents opening same-direction trades on correlated pairs
- **Circuit Breaker**: Automatic trading pause on consecutive losses or low win rate
- **Margin Check**: Validates sufficient margin before placing orders
- **News Filter**: Blocks trading during high-impact news events
- **Session Filter**: Reduces trade quality during low-volume sessions

## Advanced Trade Management

### Multiple Take Profit
```
BUY EURUSD @ 1.0850
  TP1: 1.0900 (50% position close) — R:R 1:1
  TP2: 1.0950 (30% position close) — R:R 2:1
  TP3: 1.1000 (20% runner)         — R:R 3:1
```

### Dynamic Stop Loss
- **Breakeven**: Moves SL to entry when price moves 1R in favor
- **Trailing Stop**: ATR-based trailing that only tightens
- **Structure SL**: Moves SL to recent swing high/low
- **ATR SL**: Default stop loss based on ATR × multiplier

## Project Structure

```
forex_ai/
├── main.py                    # Central controller entry point
├── config.py                  # Unified configuration
├── .env.example               # Environment variable template
├── requirements.txt           # Python dependencies
│
├── agents/                    # Multi-agent decision system
│   ├── analysis_agent.py      # Main analysis pipeline (12 steps)
│   ├── decision_agent.py      # Weighted voting decision maker
│   ├── learning_agent.py      # Decision tracking & feedback
│   ├── market_agent.py        # Data fetch & indicator calculation
│   ├── risk_agent.py          # Risk calculation agent
│   ├── master_analyst.py      # Claude-powered elite analyst
│   └── chart_agent.py         # Chart visualization agent
│
├── ai/                        # LLM integration
│   ├── ai_analyst.py          # Groq/Gemini analyst
│   ├── automated_retraining.py # Model retraining (optional)
│   └── model_versioning.py    # Model version management (optional)
│
├── analysis/                  # Market analysis modules
│   ├── smc_engine.py          # Smart Money Concepts engine
│   ├── liquidity_engine.py    # Liquidity zone & sweep detection
│   ├── session_analyzer.py    # Session intelligence
│   ├── currency_strength.py   # Currency strength calculator
│   ├── intermarket.py         # Intermarket correlation (DXY/Gold/VIX)
│   ├── order_block.py         # Order block detection
│   ├── fvg_detector.py        # Fair Value Gap detection
│   ├── smart_money.py         # SMC analysis
│   ├── fibonacci.py           # Fibonacci retracement engine
│   ├── patterns.py            # Candlestick pattern detection
│   ├── advanced_patterns.py   # Advanced chart patterns
│   ├── support_resistance.py  # S/R zone detection
│   ├── market_regime.py       # Market regime classifier
│   ├── market_bias.py         # Market bias engine
│   ├── sentiment.py           # Sentiment analysis
│   └── mtf_analyzer.py        # Multi-timeframe analysis
│
├── broker/                    # MT5 integration
│   ├── mt5_connection.py      # MT5 connection manager
│   ├── order_manager.py       # Order placement & management
│   ├── position_manager.py    # Position tracking & management
│   ├── market_data_manager.py # Data feed orchestrator
│   ├── mt5_data.py            # Raw MT5 data feed
│   ├── account_manager.py     # Account info & validation
│   ├── symbol_manager.py      # Symbol resolution
│   ├── spread_monitor.py      # Spread monitoring
│   ├── health_monitor.py      # Connection health
│   ├── data_validator.py      # Data quality checks
│   └── economic_calendar.py   # Economic events
│
├── core/                      # Core system modules
│   ├── trading_engine.py      # Trading engine (Day 37)
│   ├── trader.py              # Main AITrader + AutonomousTraderSystem
│   ├── trade_management.py    # Advanced trade management
│   ├── constants.py           # Unified constants (PIP_SIZE, etc.)
│   ├── exceptions.py          # Exception hierarchy
│   ├── approval_mode.py       # Human approval system
│   └── monitoring_system.py   # System health monitor
│
├── risk/                      # Risk management
│   ├── risk_engine.py         # Core risk engine
│   ├── circuit_breaker.py     # Kill switch
│   ├── trade_permission.py    # Multi-check trade gate
│   ├── drawdown_controller.py # Drawdown protection
│   ├── exposure_manager.py    # Portfolio exposure
│   ├── position_allocator.py  # Kelly Criterion sizing
│   ├── portfolio_manager.py   # Portfolio-level risk
│   ├── autonomous_risk.py     # Advanced risk orchestrator
│   └── capital_manager.py     # Capital allocation
│
├── execution/                 # Trade execution
│   ├── execution_router.py    # Paper vs MT5 router
│   └── paper_trader.py        # Paper trading engine
│
├── strategy/                  # Signal generation
│   └── signal_engine.py       # Rule-based signal scoring
│
├── scanner/                   # Market scanning
│   ├── market_scanner.py      # Multi-pair scanner
│   ├── correlation_filter.py  # Correlation filtering
│   └── opportunity_ranker.py  # Opportunity ranking
│
├── learning/                  # Self-learning system
│   ├── confidence_engine.py   # Dynamic confidence adjustment
│   ├── mistake_analyzer.py    # Trade mistake analysis
│   ├── lesson_memory.py       # Lesson storage
│   └── auto_optimizer.py      # Strategy optimization
│
├── memory/                    # Trade memory & history
│   ├── trade_memory.py        # Trade pattern memory
│   ├── pattern_memory.py      # Pattern recognition
│   ├── learning.py            # Learning engine
│   └── history.py             # Analysis history
│
├── alerts/                    # Notifications
│   └── telegram_bot.py        # Telegram alerts & commands
│
├── dashboard/                 # Streamlit dashboard
│   ├── app.py                 # Main dashboard
│   ├── pages/                 # Dashboard pages
│   └── components/            # Dashboard components
│
├── database/                  # Data persistence
│   └── db.py                  # SQLite database
│
├── data/                      # Data fetching
│   ├── fetcher.py             # OHLCV data fetcher
│   ├── indicators.py          # Technical indicators
│   └── validator.py           # Data validation
│
├── backtest/                  # Backtesting
│   ├── engine.py              # Backtest engine
│   └── simulator.py           # Trade simulator
│
├── tests/                     # Test suite
│   ├── conftest.py            # Shared fixtures
│   ├── test_constants.py      # Constants tests
│   ├── test_data.py           # Data pipeline tests
│   ├── test_indicators.py     # Indicator tests
│   ├── test_signal.py         # Signal engine tests
│   ├── test_risk.py           # Risk engine tests
│   ├── test_mt5_connection.py # MT5 connection tests
│   ├── test_order.py          # Order execution tests
│   ├── test_database.py       # Database tests
│   └── test_trade_management.py # Trade management tests
│
└── utils/                     # Utilities
    ├── logger.py              # Logging setup
    └── session.py             # Session detection
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/help` | List all commands |
| `/status` | Current system status |
| `/pause` | Pause trading |
| `/resume` | Resume trading |
| `/calendar` | Weekly economic calendar |
| `/daily` | Daily performance report |

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test
pytest tests/test_risk.py -v

# Run with coverage
pytest tests/ -v --cov=. --cov-report=term-missing
```

## Environment Variables Reference

See `.env.example` for the complete list. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `EXECUTION_MODE` | `paper` | `paper` or `mt5_demo` |
| `APPROVAL_MODE` | `3` | `1`=analysis, `2`=supervised, `3`=autonomous |
| `GROQ_API_KEY` | — | Groq API key (primary LLM) |
| `GEMINI_API_KEY` | — | Gemini API key (fallback LLM) |
| `TELEGRAM_TOKEN` | — | Telegram bot token |
| `TELEGRAM_CHAT_ID` | — | Your Telegram chat ID |
| `PAPER_BALANCE` | `10000` | Paper trading starting balance |
| `LOOP_INTERVAL_SEC` | `60` | Seconds between trading cycles |
| `MT5_LOGIN` | — | MT5 account login |
| `MT5_PASSWORD` | — | MT5 account password |
| `MT5_SERVER` | — | MT5 broker server |

## Troubleshooting

### "No module named 'MetaTrader5'"
MT5 is only needed for `mt5_demo` mode. Paper mode works fine without it. On Windows: `pip install MetaTrader5`

### "Groq init failed"
Check your `GROQ_API_KEY` in `.env`. Get a free key at https://console.groq.com

### "Daily loss limit hit"
The system automatically stops trading when daily losses exceed 3%. This is by design. Wait for the next trading day or adjust `MAX_DAILY_LOSS` in config.

### "Circuit breaker tripped"
The circuit breaker pauses trading after consecutive losses. Use `/resume` on Telegram or set `APPROVAL_MODE=3` to continue.

### Dashboard not loading
Install Streamlit: `pip install streamlit`, then run `streamlit run dashboard/app.py`

## Risk Warning

**This is an experimental AI trading system. Forex trading carries substantial risk of loss.**

- Always start with paper trading mode
- Never risk money you cannot afford to lose
- Past performance does not guarantee future results
- The AI can and will make losing trades
- Use `APPROVAL_MODE=2` (supervised) until you trust the system
- Monitor the system actively, especially in autonomous mode
- The developers are not responsible for any financial losses

## License

This project is provided for educational and research purposes. Use at your own risk.
