import random

def fetch_ohlcv(symbol, limit=120):
    data = []
    price = 100.0

    for _ in range(limit):
        open_p = price
        high = open_p * (1 + random.uniform(0, 0.01))
        low = open_p * (1 - random.uniform(0, 0.01))
        close = random.uniform(low, high)
        volume = random.uniform(10, 100)

        data.append({
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume
        })

        price = close

    return data
