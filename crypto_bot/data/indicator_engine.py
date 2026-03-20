from __future__ import annotations

from data.data_quality import QualityInput, resolve_quality


def _closes(candles: list[dict]) -> list[float]:
    return [float(row["close"]) for row in candles if row.get("close") is not None]


def _highs(candles: list[dict]) -> list[float]:
    return [float(row["high"]) for row in candles if row.get("high") is not None]


def _lows(candles: list[dict]) -> list[float]:
    return [float(row["low"]) for row in candles if row.get("low") is not None]


def _volumes(candles: list[dict]) -> list[float]:
    return [float(row.get("volume") or 0.0) for row in candles]


def calculate_atr(candles: list[dict], period: int = 14) -> float | None:
    if len(candles) < max(int(period) + 1, 2):
        return None
    highs = _highs(candles)
    lows = _lows(candles)
    closes = _closes(candles)
    if len(highs) != len(candles) or len(lows) != len(candles) or len(closes) != len(candles):
        return None

    trs: list[float] = []
    for i in range(1, len(candles)):
        h = highs[i]
        l = lows[i]
        prev_close = closes[i - 1]
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
    if len(trs) < int(period):
        return None
    last = trs[-int(period):]
    return sum(last) / len(last)


def calculate_rsi(candles: list[dict], period: int = 14) -> float | None:
    closes = _closes(candles)
    if len(closes) < int(period) + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    window_gains = gains[-int(period):]
    window_losses = losses[-int(period):]
    avg_gain = sum(window_gains) / len(window_gains)
    avg_loss = sum(window_losses) / len(window_losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_return_volatility(candles: list[dict], period: int = 20) -> float | None:
    closes = _closes(candles)
    if len(closes) < int(period) + 1:
        return None
    returns: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        curr = closes[i]
        if prev <= 0:
            continue
        returns.append((curr - prev) / prev)
    if len(returns) < int(period):
        return None
    data = returns[-int(period):]
    mean = sum(data) / len(data)
    variance = sum((x - mean) ** 2 for x in data) / len(data)
    return variance ** 0.5


def calculate_bundle(
    candles: list[dict],
    *,
    min_points: int = 30,
    stale: bool = False,
    supported: bool = True,
) -> dict:
    closes = _closes(candles)
    highs = _highs(candles)
    lows = _lows(candles)
    volumes = _volumes(candles)
    count = len(candles)

    if count == 0 or not closes:
        quality = resolve_quality(
            QualityInput(
                sample_count=count,
                min_required=min_points,
                stale=stale,
                supported=supported,
                reason="no_candles",
            )
        )
        return {
            "atr": None,
            "rsi": None,
            "return_volatility": None,
            "candle_range_pct": None,
            "momentum": None,
            "recent_high": None,
            "recent_low": None,
            "compression_score": None,
            "expansion_score": None,
            "vwap": None,
            "data_quality": quality,
        }

    atr = calculate_atr(candles, period=14)
    rsi = calculate_rsi(candles, period=14)
    return_vol = calculate_return_volatility(candles, period=20)
    recent_high = max(highs[-20:]) if highs else None
    recent_low = min(lows[-20:]) if lows else None
    latest_close = closes[-1]
    prev_close = closes[-2] if len(closes) >= 2 else latest_close
    momentum = ((latest_close - prev_close) / prev_close) if prev_close > 0 else None
    candle_range_pct = (
        ((highs[-1] - lows[-1]) / latest_close)
        if highs and lows and latest_close > 0
        else None
    )
    typical = [
        (float(row["high"]) + float(row["low"]) + float(row["close"])) / 3.0
        for row in candles
        if row.get("high") is not None and row.get("low") is not None and row.get("close") is not None
    ]
    volume_sum = sum(volumes)
    vwap = (
        (sum(tp * vol for tp, vol in zip(typical, volumes)) / volume_sum)
        if volume_sum > 0 and len(typical) == len(volumes)
        else None
    )
    norm_vol = return_vol if return_vol is not None else 0.0
    compression_score = max(0.0, min(100.0, (1.0 - min(norm_vol / 0.02, 1.0)) * 100.0))
    expansion_score = max(0.0, min(100.0, min(norm_vol / 0.02, 1.0) * 100.0))

    quality_reason = "ok"
    if count < min_points:
        quality_reason = "insufficient_history"
    elif any(item is None for item in (atr, rsi, return_vol)):
        quality_reason = "partial_indicator_coverage"
    quality = resolve_quality(
        QualityInput(
            sample_count=count,
            min_required=min_points,
            stale=stale,
            supported=supported,
            reason=quality_reason,
        )
    )
    return {
        "atr": atr,
        "rsi": rsi,
        "return_volatility": return_vol,
        "candle_range_pct": candle_range_pct,
        "momentum": momentum,
        "recent_high": recent_high,
        "recent_low": recent_low,
        "compression_score": compression_score,
        "expansion_score": expansion_score,
        "vwap": vwap,
        "data_quality": quality,
    }

