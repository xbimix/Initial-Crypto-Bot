def score_indicators(regime, indicators):
    weights = {
        "trend": {
            "rsi": 0.2,
            "ma": 0.5,
            "vol": 0.1,
            "structure": 0.2,
        },
        "range": {
            "rsi": 0.5,
            "ma": 0.2,
            "vol": 0.2,
            "structure": 0.1,
        },
        "chop": {
            "rsi": 0.2,
            "ma": 0.2,
            "vol": 0.4,
            "structure": 0.2,
        },
    }

    w = weights[regime]

    score = (
        indicators["rsi"] * w["rsi"]
        + indicators["ma"] * w["ma"]
        + indicators["vol"] * w["vol"]
        + indicators["structure"] * w["structure"]
    )

    return round(score, 2)
