def detect_regime(snapshot: dict):
    """
    Adaptive regime detection
    Keeps original accumulation logic
    Adds structure awareness
    """

    momentum = snapshot.get("momentum_norm", 0)
    atr = snapshot.get("atr", 0)
    price = snapshot.get("price", 0)

    high = snapshot.get("high_24h", 0)
    low = snapshot.get("low_24h", 0)

    ema_50 = snapshot.get("ema_50")
    ema_200 = snapshot.get("ema_200")
    ema_50_slope = snapshot.get("ema_50_slope")

    # Safety
    if not price or high <= low:
        return "unknown"

    range_pos = (price - low) / (high - low)
    range_pct = (high - low) / price if price > 0 else 0

    # ================================
    # 1️⃣ HARD DUMP
    # ================================
    if momentum < -1.2:
        return "dump"

    # ================================
    # 2️⃣ TREND DOWN (structure aware)
    # ================================
    if (
    ema_50 is not None and
    ema_200 is not None and
    ema_50_slope is not None and
    price < ema_50 and
    ema_50 < ema_200 and
    ema_50_slope < 0
  ):
        return "trend_down"

    # ================================
    # 3️⃣ TREND UP
    # ================================
    if (
    ema_50 is not None and
    ema_200 is not None and
    ema_50_slope is not None and
    price > ema_50 and
    ema_50 > ema_200 and
    ema_50_slope > 0
    ):
        return "trend_up"

    # ================================
    # 4️⃣ VOLATILE SPIKE
    # ================================
    atr_pct = atr / price if price > 0 else 0

    if atr_pct > 0.015 and range_pos > 0.4:
       return "spike"

    # ================================
    # 5️⃣ ACCUMULATION (your alpha)
    # ================================
    if range_pos <= 0.30 and momentum > -0.2:
        return "accumulation"

    # ================================
    # 6️⃣ RANGE CHOP
    # ================================
    if range_pct < 0.04:
        return "range"

    return "chop"
