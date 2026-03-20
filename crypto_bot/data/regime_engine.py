from __future__ import annotations

from data.data_quality import QualityInput, resolve_quality
from data.revolut_candle_fetcher import timeframe_to_interval_minutes


WINDOWS = ("1h", "4h", "8h", "12h", "16h", "24h", "3d", "7d")


def _parse_minutes(window: str) -> int:
    raw = str(window).strip().lower()
    val = int(raw[:-1])
    unit = raw[-1]
    if unit == "h":
        return val * 60
    if unit == "d":
        return val * 1440
    raise ValueError(f"Unsupported window: {window}")


def _sample_window(candles: list[dict], window: str, base_timeframe: str) -> list[dict]:
    base_minutes = timeframe_to_interval_minutes(base_timeframe)
    window_minutes = _parse_minutes(window)
    needed = max(2, int(window_minutes / base_minutes))
    return candles[-needed:]


def _structure_features(rows: list[dict]) -> dict:
    if len(rows) < 3:
        return {
            "slope": 0.0,
            "amplitude": 0.0,
            "higher_highs": 0,
            "lower_highs": 0,
            "higher_lows": 0,
            "lower_lows": 0,
            "median_high_zone": None,
            "median_low_zone": None,
            "structure_bias": "UNCLEAR",
        }
    highs = [float(r["high"]) for r in rows]
    lows = [float(r["low"]) for r in rows]
    closes = [float(r["close"]) for r in rows]
    first = closes[0]
    last = closes[-1]
    slope = ((last - first) / first) if first > 0 else 0.0
    amplitude = ((max(highs) - min(lows)) / last) if last > 0 else 0.0
    hh = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i - 1])
    lh = sum(1 for i in range(1, len(highs)) if highs[i] < highs[i - 1])
    hl = sum(1 for i in range(1, len(lows)) if lows[i] > lows[i - 1])
    ll = sum(1 for i in range(1, len(lows)) if lows[i] < lows[i - 1])

    if hh >= lh and hl >= ll and slope > 0.01:
        bias = "TREND_UP"
    elif lh > hh and ll > hl and slope < -0.01:
        bias = "TREND_DOWN"
    elif abs(slope) <= 0.01:
        bias = "RANGE"
    else:
        bias = "MIXED"
    return {
        "slope": slope,
        "amplitude": amplitude,
        "higher_highs": hh,
        "lower_highs": lh,
        "higher_lows": hl,
        "lower_lows": ll,
        "median_high_zone": (sorted(highs)[len(highs) // 2]),
        "median_low_zone": (sorted(lows)[len(lows) // 2]),
        "structure_bias": bias,
    }


def analyze_regime(
    candles: list[dict],
    *,
    base_timeframe: str = "1m",
    stale: bool = False,
) -> dict:
    timeframe_summary: dict[str, dict] = {}
    bias_votes: dict[str, int] = {"TREND_UP": 0, "TREND_DOWN": 0, "RANGE": 0, "MIXED": 0}

    for window in WINDOWS:
        supported = True
        try:
            _parse_minutes(window)
            timeframe_to_interval_minutes(base_timeframe)
        except Exception:
            supported = False

        window_rows = _sample_window(candles, window, base_timeframe) if supported else []
        features = _structure_features(window_rows)
        q = resolve_quality(
            QualityInput(
                sample_count=len(window_rows),
                min_required=12,
                stale=stale,
                supported=supported,
                reason="window_insufficient" if len(window_rows) < 12 else "ok",
            )
        )
        insufficient = q["status"] in {"INSUFFICIENT", "UNSUPPORTED_WINDOW", "PARTIAL"}
        if not insufficient:
            bias_votes[features["structure_bias"]] = bias_votes.get(features["structure_bias"], 0) + 1

        timeframe_summary[window] = {
            "window": window,
            "structure": features["structure_bias"],
            "amplitude": features["amplitude"],
            "slope": features["slope"],
            "median_high": features["median_high_zone"],
            "median_low": features["median_low_zone"],
            "sample": len(window_rows),
            "insufficientData": insufficient,
            "data_quality": q,
        }

    suggested = max(bias_votes.items(), key=lambda kv: kv[1])[0]
    if suggested == "TREND_UP":
        suggested_regime = "TREND_CONTINUATION"
    elif suggested == "TREND_DOWN":
        suggested_regime = "BREAKOUT_EXPANSION"
    elif suggested == "RANGE":
        suggested_regime = "MEAN_REVERSION_FRIENDLY"
    else:
        suggested_regime = "MIXED_OR_UNCLEAR"

    usable = sum(1 for row in timeframe_summary.values() if not row["insufficientData"])
    confidence = min(100.0, max(0.0, usable / len(WINDOWS) * 100.0))
    label = "HIGH" if confidence >= 70 else "MEDIUM" if confidence >= 45 else "LOW"
    structure_bias = suggested
    volatility_state = "NORMAL"
    participation_state = "NORMAL"
    explanation = (
        f"Derived from {usable}/{len(WINDOWS)} supported windows. "
        f"Structure bias={structure_bias.lower()}."
    )
    top_quality = resolve_quality(
        QualityInput(
            sample_count=usable,
            min_required=4,
            stale=stale,
            supported=True,
            reason="overall_window_coverage",
        )
    )
    return {
        "suggested_regime": suggested_regime,
        "confidence_score": confidence,
        "confidence_label": label,
        "structure_bias": structure_bias,
        "volatility_state": volatility_state,
        "participation_state": participation_state,
        "explanation": explanation,
        "timeframe_summary": timeframe_summary,
        "data_quality": top_quality,
    }

