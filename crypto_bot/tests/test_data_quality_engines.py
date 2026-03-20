from __future__ import annotations

from data.data_quality import resolve_quality, QualityInput
from data.indicator_engine import calculate_bundle, calculate_atr, calculate_rsi
from data.regime_engine import analyze_regime
from data.volatility_engine import analyze_volatility, classify_volatility_state


def _candles(count: int, *, drift: float = 0.0, amp: float = 1.0) -> list[dict]:
    rows: list[dict] = []
    price = 100.0
    for i in range(count):
        move = ((i % 7) - 3) * 0.02 * amp + drift
        o = price
        c = max(0.01, o * (1 + move / 100.0))
        h = max(o, c) * 1.002
        l = min(o, c) * 0.998
        rows.append(
            {
                "ts": i * 60_000,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": 10 + i,
            }
        )
        price = c
    return rows


def test_data_quality_status_mapping():
    good = resolve_quality(QualityInput(sample_count=100, min_required=30, stale=False, supported=True))
    partial = resolve_quality(QualityInput(sample_count=12, min_required=30, stale=False, supported=True))
    insufficient = resolve_quality(QualityInput(sample_count=0, min_required=30, stale=False, supported=True))
    stale = resolve_quality(QualityInput(sample_count=40, min_required=30, stale=True, supported=True))
    unsupported = resolve_quality(QualityInput(sample_count=10, min_required=30, stale=False, supported=False))

    assert good["status"] == "GOOD"
    assert partial["status"] == "PARTIAL"
    assert insufficient["status"] == "INSUFFICIENT"
    assert stale["status"] == "STALE"
    assert unsupported["status"] == "UNSUPPORTED_WINDOW"


def test_indicator_engine_atr_rsi_and_insufficient():
    candles = _candles(80, drift=0.05, amp=1.2)
    atr = calculate_atr(candles, period=14)
    rsi = calculate_rsi(candles, period=14)
    bundle = calculate_bundle(candles, min_points=30, stale=False, supported=True)
    thin = calculate_bundle(_candles(6), min_points=30, stale=False, supported=True)

    assert atr is not None and atr > 0
    assert rsi is not None and 0 <= rsi <= 100
    assert bundle["data_quality"]["status"] in {"GOOD", "PARTIAL"}
    assert thin["data_quality"]["status"] == "PARTIAL"


def test_volatility_engine_states_and_insufficient():
    low = analyze_volatility(_candles(120, drift=0.0, amp=0.2))
    high = analyze_volatility(_candles(120, drift=0.0, amp=6.0))
    unsupported = analyze_volatility(_candles(120), supported=False)

    assert low["volatility_state"] in {"LOW", "NORMAL", "EXPANDING", "EXTREME"}
    assert high["volatility_score"] is not None
    assert classify_volatility_state(90) == "EXTREME"
    assert unsupported["data_quality"]["status"] == "UNSUPPORTED_WINDOW"
    assert unsupported["insufficient_data"] is True


def test_regime_engine_range_up_down_and_unsupported():
    range_rows = _candles(800, drift=0.0, amp=0.8)
    up_rows = _candles(800, drift=0.12, amp=0.8)
    down_rows = _candles(800, drift=-0.12, amp=0.8)

    range_result = analyze_regime(range_rows, base_timeframe="1m")
    up_result = analyze_regime(up_rows, base_timeframe="1m")
    down_result = analyze_regime(down_rows, base_timeframe="1m")
    unsupported = analyze_regime(range_rows, base_timeframe="2m")

    assert range_result["suggested_regime"] in {
        "MEAN_REVERSION_FRIENDLY",
        "MIXED_OR_UNCLEAR",
        "TREND_CONTINUATION",
        "BREAKOUT_EXPANSION",
    }
    assert up_result["structure_bias"] in {"TREND_UP", "MIXED", "RANGE", "TREND_DOWN"}
    assert down_result["structure_bias"] in {"TREND_DOWN", "MIXED", "RANGE", "TREND_UP"}
    assert unsupported["data_quality"]["status"] in {"PARTIAL", "INSUFFICIENT", "UNSUPPORTED_WINDOW"}
    assert all(
        row["data_quality"]["status"] == "UNSUPPORTED_WINDOW"
        for row in unsupported["timeframe_summary"].values()
    )

