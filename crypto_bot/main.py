import time
from data.market_data import fetch_ohlcv
from strategy.strategy_engine import generate_signal
from trading.executor import execute_trade

SYMBOL = "BTC-USD"

def main():
    print("Bot running... CTRL+C to stop")

    while True:
        ohlcv = fetch_ohlcv(SYMBOL)
        signal = generate_signal(ohlcv)

        print(f"Score: {signal['score']} | {signal['reasons']}")

        execute_trade(signal, SYMBOL)

        time.sleep(15)

if __name__ == "__main__":
    main()
