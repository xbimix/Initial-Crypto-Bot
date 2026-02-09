
MAX_RISK_PER_TRADE = 0.02          # 2% hard cap
MAX_CONCURRENT_TRADES = 1
MIN_COOLDOWN_SECONDS = 60
MAX_COOLDOWN_SECONDS = 3600

SUPPORTED_SYMBOLS = {
    "BTC/USDT",
    "ETH/USDT",
    "BNB/USDT",
    "SOL/USDT",
    "XRP/USDT",
    "ADA/USDT",
    "DOGE/USDT",
    "DOT/USDT",
    "LTC/USDT",
    "LINK/USDT",
    "UNI/USDT",
    "ATOM/USDT",
    "XLM/USDT",
    "AVAX/USDT",
    "MATIC/USDT",
    "SUI/USDT",
    "SEI/USDT"
}


#### config.json   old structure, for reference
# // {
# //   "enabled": true,
# //   "execution_mode": "paper",
# //   "starting_balance": 10000,

# //   "symbols": [
# //     "BTC-USD",
# //     "ETH-USD",
# //     "SOL-USD",
# //     "BNB-USD",
# //     "XRP-USD",
# //     "ADA-USD",
# //     "DOT-USD",
# //     "XLM-USD",
# //     "SUI-USD",
# //     "SEI-USD"
# //   ],

# //   "lookback": 200,
# //   "min_trades": 2,

# //   "risk": {
# //     "risk_percent": 0.02,
# //     "max_concurrent_trades": 1,
# //     "cooldown_seconds": 90
# //   },

# //   "market_regime": {
# //     "type": "bear",
# //     "max_buy_range_pct": 0.30,
# //     "preferred_buy_zone": [0.20, 0.30]
# //   },

# //   "profit_locks": {
# //     "levels": [0.02, 0.04, 0.06, 0.08],
# //     "floor_after_first": -0.01
# //   }
# // }