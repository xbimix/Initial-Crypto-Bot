def snapshot(symbol, price, signal, blocked_reason=None):
    return {
        "symbol": symbol,
        "price": price,
        "score": signal["score"],
        "regime": signal["regime"],
        "indicators": signal["indicators"],
        "blocked": blocked_reason,
    }
