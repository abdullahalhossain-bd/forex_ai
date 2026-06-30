# Self-Learning Autonomous Multi-Agent Financial AI

A production-grade Forex trading AI system with MT5 integration, multi-agent architecture, and self-learning capabilities.

## Architecture

```
MT5 / Twelve Data (candles + ticks)
    ↓
Data Orchestrator (MT5 first → API fallback)
    ↓
Market Understanding (72 indicators + SMC + structure + divergence)
    ↓
Regime Detection (market_regime + MTF structure)
    ↓
Intelligence Layer (20+ modules):
  ├─ SMC + Advanced (Mitigation + Inducement)
  ├─ Ichimoku + Volume Profile + Volatility Squeeze
  ├─ Retail Sentiment (OANDA → Myfxbook → Synthetic RSI)
  ├─ Institutional Flow (COT + displacement)
  ├─ Economic Calendar (Trading Econ → Investing RSS → FF)
  ├─ Economic Surprise (actual vs forecast)
  ├─ FRED Macro (CPI, Unemployment, Yields, Fed Rate)
  ├─ NewsAPI Sentiment (breaking news)
  ├─ Correlation + Volatility (risk adjustment)
  ├─ Microstructure (tick speed + spread + volume burst)
  ├─ Forecast Engine (conservative extra vote, 10% weight)
  └─ Strategy Selector (regime → strategy family)
    ↓
Master Decision Engine (LLM: OpenRouter → Cerebras → SambaNova → Groq → Gemini)
    ↓
Risk Engine (correlation-adjusted + sync_open_positions fix)
    ↓
Execution (MT5 / SimulatedExecutor)
  ├─ Execution Quality Monitor (slippage tracking)
  ├─ Network Monitor (latency → scalping gate)
  └─ Watchdog (health + auto-restart)
    ↓
Learning Loop (Expectancy + Confidence Engine)
```

## Installation

```bash
# 1. Clone the repository
git clone <repo_url>
cd forex_ai

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your API keys and MT5 credentials
```

## Environment Setup

### Required API Keys

| API | Purpose | Free Tier | Get Key |
|-----|---------|-----------|---------|
| Twelve Data | Forex candles (MT5 fallback) | 800 req/day | https://twelvedata.com |
| FRED | Macro economic data (CPI, rates) | Unlimited | https://fredaccount.stlouisfed.org/apikeys |
| OpenRouter | LLM inference (free models) | Free models | https://openrouter.ai |
| NewsAPI | Breaking news sentiment | 100 req/day | https://newsapi.org |

### Optional API Keys

| API | Purpose | Get Key |
|-----|---------|---------|
| Groq | LLM (primary, fastest) | https://console.groq.com |
| Cerebras | LLM (fastest inference) | https://inference.cerebras.ai |
| SambaNova | LLM (free tier) | https://cloud.sambanova.ai |
| Polygon.io | Historical forex data | https://polygon.io |
| Trading Economics | Economic calendar | https://tradingeconomics.com/api.aspx |
| OANDA | Retail sentiment + order book | https://www.oanda.com/apply/demo/ |

### MT5 Setup (Windows only)

1. Install MetaTrader 5 terminal
2. Open a demo account
3. Note your login, password, and server name
4. Set in `.env`:
   ```
   MT5_LOGIN=your_login
   MT5_PASSWORD=your_password
   MT5_SERVER=your_broker_server
   SIMULATION_MODE=false
   ```

### Telegram Bot Setup

1. Create a bot via @BotFather on Telegram
2. Get your chat ID (message @userinfobot)
3. Set in `.env`:
   ```
   TELEGRAM_TOKEN=your_bot_token
   TELEGRAM_CHAT_ID=your_chat_id
   ENABLE_TELEGRAM=true
   ```

## Running the System

### Start autonomous trading
```bash
python main.py
```

### Signal diagnostic mode
```bash
python main.py --mode diagnostic --pairs EURUSD,GBPUSD
```
Shows where signals die in the pipeline — useful when the bot isn't trading.

### Initialize system only (no trading)
```bash
python main.py --mode init
```

### System status
```bash
python main.py --mode status
```

### Health snapshot
```bash
python main.py --mode health
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/status` | System status overview |
| `/positions` | List open MT5 positions |
| `/close <ticket>` | Close a position by ticket |
| `/symbols` | List configured pairs + spread |
| `/indicators EURUSD` | Latest indicator snapshot |
| `/source` | Active data source (MT5/API) |
| `/account` | MT5 account balance/equity/margin |
| `/pause` | Pause trading |
| `/resume` | Resume trading |
| `/calendar` | Economic calendar |
| `/daily` | Daily report |

## Risk System

- **SAFE mode**: 80%+ confidence required, MAX_LOT=0.10, DAILY_LOSS_LIMIT=5%
- **ABSOLUTE_SAFETY**: hard kill-switch (broker disconnect, spread, news, margin)
- **Correlation Engine**: reduces position size when correlated pairs are open
- **Volatility Filter**: ATR > 2x average → lot reduced 50%
- **Expectancy Calculator**: proper formula `(Win% × AvgWin) − (Loss% × AvgLoss)`
- **sync_open_positions**: live PaperTrader state → no stale correlation blocks

## Folder Structure

```
forex_ai/
├── main.py                    # Entry point + diagnostic mode
├── config.py                  # Configuration (reads .env)
├── .env                       # Your secrets (NEVER commit)
├── .env.example               # Template
├── requirements.txt           # Python dependencies
│
├── agents/                    # Multi-agent pipeline
│   ├── market_agent.py        # Data collection + indicators
│   ├── analysis_agent.py      # Full analysis pipeline (20+ modules)
│   ├── decision_agent.py      # Signal voting + confidence
│   ├── master_analyst.py      # LLM brain (Groq/OpenRouter/Cerebras)
│   └── ...
│
├── analysis/                  # Analysis modules
│   ├── smc_engine.py          # Smart Money Concepts
│   ├── divergence.py          # RSI/MACD divergence
│   ├── ichimoku.py            # Ichimoku Cloud
│   ├── volatility.py          # Bollinger Squeeze
│   ├── volume_profile.py      # POC/HVN/LVN
│   ├── correlation_engine.py  # Currency correlation + volatility
│   ├── microstructure.py      # Tick-level analysis (MT5)
│   ├── retail_sentiment.py    # OANDA → Myfxbook → Synthetic
│   └── ...
│
├── core/                      # Core engine
│   ├── trader.py              # AITrader (per-pair cycle)
│   ├── master_decision.py     # Central decision engine
│   ├── runtime.py             # Lifecycle + service registry
│   ├── llm_key_manager.py     # Multi-key LLM rotation
│   └── ...
│
├── data/                      # Data layer
│   ├── data_orchestrator.py   # MT5 first → API fallback
│   ├── fetcher.py             # Multi-source OHLCV
│   ├── indicators_ext.py      # 72 indicators (pandas-ta)
│   └── ...
│
├── fundamental/               # Fundamental analysis
│   ├── fred_data.py           # FRED macro data
│   ├── economic_surprise.py   # Actual vs forecast
│   ├── economic_calendar_api.py
│   └── ...
│
├── risk/                      # Risk management
│   ├── risk_engine.py         # Position sizing + correlation
│   ├── expectancy.py          # Proper expectancy formula
│   └── ...
│
├── strategy/                  # Strategy layer
│   ├── selector.py            # Regime → strategy family
│   └── signal_engine.py       # Signal generation
│
├── system/                    # System monitoring
│   ├── watchdog.py            # Health + auto-restart
│   └── network_monitor.py     # Latency tracking
│
├── monitoring/                # Monitoring
│   ├── signal_debugger.py     # Pipeline debug (first_blocked_at)
│   └── execution_quality.py   # Slippage tracking
│
├── alerts/                    # Notifications
│   ├── telegram_bot.py        # Telegram bot
│   └── telegram_ext.py        # Extension commands
│
├── ml/                        # ML layer
│   ├── forecast_engine.py     # Conservative forecast (10% weight)
│   └── ...
│
├── broker/                    # MT5 integration
│   ├── mt5_connection.py      # MT5 connect/disconnect
│   ├── mt5_data.py            # Candle + tick data
│   └── ...
│
├── execution/                 # Order execution
│   ├── paper_trader.py        # Local simulation
│   └── execution_router.py    # MT5/Simulated routing
│
├── scripts/                   # Test & verification scripts
│   ├── test_day92_apis.py
│   ├── test_day93_integration.py
│   ├── test_day94_institutional_apis.py
│   ├── test_day95_alternatives.py
│   ├── verify_new_modules.py
│   └── ...
│
└── memory/                    # Persistent state
    ├── trader.db              # SQLite database
    ├── daily_risk.json        # Daily risk state
    └── ...
```

## Configuration

### Safe Mode (default)
```env
TEST_MODE=false
TRADING_MODE=SAFE
ABSOLUTE_SAFETY=true
MAX_LOT=0.10
DAILY_LOSS_LIMIT_PCT=5.0
MAX_OPEN_TRADES=3
SIMULATION_MODE=true  # set false on Windows with MT5
```

### Token Economy
```env
LOOP_INTERVAL_SEC=180        # 3 min between cycles
MAX_LLM_CALLS_PER_CYCLE=4
MAX_LLM_CALLS_PER_MIN=6
MASTER_ANALYST_MAX_TOKENS=800
AI_ANALYST_MAX_TOKENS=400
```

## License

This project is for educational purposes. Use at your own risk.
