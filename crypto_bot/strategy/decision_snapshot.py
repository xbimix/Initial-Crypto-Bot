def snapshot(symbol, decision, extra=None):
    snap = {
        "symbol": symbol,
        "action": decision["action"],
        "price": decision["price"],
        "momentum": decision["momentum"],
        "reason": decision["reason"],
    }
    if extra:
        snap.update(extra)
    return snap


# def snapshot(symbol, price, signal, blocked_reason=None):
#     return {
#         "symbol": symbol,
#         "price": price,
#         "score": signal["score"],
#         "regime": signal["regime"],
#         "indicators": signal["indicators"],
#         "blocked": blocked_reason,
#     }
