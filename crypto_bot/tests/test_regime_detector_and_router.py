from __future__ import annotations

import time

from strategy.regime import detect_regime
from strategy.regime_router import resolve_entry_route


def _detect_snapshot(**overrides):
    base = {
        "symbol": "TEST-USD",
        "price": 100.0,
        "high_24h": 110.0,
        "low_24h": 90.0,
        "momentum_norm": 0.0,
        "atr": 0.00030,
        "rsi": 50.0,
        "ema_50": 100.0,
        "ema_200": 100.0,
        "ema_50_slope": 0.0,
        "adx": 22.0,
        "recent_prices": [99.8, 100.1, 99.9, 100.2, 100.0, 100.1, 99.95, 100.05],
    }
    base.update(overrides)
    return base


def _router_cfg() -> dict:
    return {
        "token_regimes": {"TEST-USD": "AUTO"},
        "strategy_defaults": {
            "router": {
                "auto_use_multitimeframe_advisory": True,
                "auto_use_route_quality_gates": False,
                "auto_require_core_candle_readiness": True,
                "auto_min_confidence": 60,
                "auto_min_stability": 50,
                "auto_min_persistence": 50,
                "auto_trend_min_confidence": 60,
                "auto_trend_min_stability": 50,
                "auto_trend_min_persistence": 50,
                "auto_breakout_min_confidence": 60,
                "auto_breakout_min_stability": 50,
                "auto_breakout_min_persistence": 50,
            }
        },
    }


def _route_snapshot(regime_code: str, **overrides) -> dict:
    now = time.time()
    base = {
        "symbol": "TEST-USD",
        "router_eval_ts": now,
        "core_candle_readiness": {"ready": True, "reason": "ok"},
        "regime_advisory": {
            "suggestedRegime": regime_code,
            "confidenceScore": 90.0,
            "stabilityScore": 85.0,
            "persistenceScore": 84.0,
            "analysisAnchorEpoch": now,
            "breakoutScore": 55.0,
            "dataQuality": {"status": "GOOD", "supportedKeyWindows": True},
        },
    }
    base.update(overrides)
    return base


def test_regime_detector_trend_up():
    regime = detect_regime(
        _detect_snapshot(
            price=103.0,
            ema_50=101.0,
            ema_200=99.0,
            ema_50_slope=0.08,
            adx=26.0,
            recent_prices=[99.0, 99.7, 100.5, 101.2, 101.7, 102.2, 102.6, 102.9],
        )
    )
    assert regime == "trend_up"


def test_regime_detector_trend_down():
    regime = detect_regime(
        _detect_snapshot(
            price=96.0,
            ema_50=98.0,
            ema_200=101.0,
            ema_50_slope=-0.08,
            adx=27.0,
            momentum_norm=-0.25,
            recent_prices=[101.0, 100.1, 99.5, 98.7, 98.0, 97.3, 96.7, 96.2],
        )
    )
    assert regime == "trend_down"


def test_regime_detector_range():
    regime = detect_regime(
        _detect_snapshot(
            price=100.2,
            momentum_norm=0.03,
            atr=0.00032,
            adx=20.0,
            ema_50=100.1,
            ema_200=100.0,
            ema_50_slope=0.0,
            recent_prices=[99.8, 100.2, 99.9, 100.3, 100.0, 100.1, 99.95, 100.05],
        )
    )
    assert regime == "range"


def test_regime_detector_breakout_up():
    regime = detect_regime(
        _detect_snapshot(
            price=105.4,
            momentum_norm=0.42,
            volume_ratio=1.3,
            atr=0.00035,
            recent_prices=[101.0, 101.5, 102.0, 102.3, 102.6, 103.1, 103.6, 104.8],
            high_24h=106.0,
            low_24h=96.0,
        )
    )
    assert regime == "breakout_up"


def test_regime_detector_breakout_down():
    regime = detect_regime(
        _detect_snapshot(
            price=94.4,
            momentum_norm=-0.44,
            volume_ratio=1.2,
            atr=0.00035,
            recent_prices=[99.8, 99.2, 98.7, 98.1, 97.6, 97.1, 96.5, 95.2],
            high_24h=101.0,
            low_24h=94.0,
        )
    )
    assert regime == "breakout_down"


def test_regime_detector_momentum_up():
    regime = detect_regime(
        _detect_snapshot(
            ema_50=None,
            ema_200=None,
            price=100.9,
            rsi=66.0,
            momentum_norm=0.33,
            atr=0.00030,
            recent_prices=[100.0, 100.1, 100.2, 100.25, 100.3, 100.4, 100.45, 100.6],
        )
    )
    assert regime == "momentum_up"


def test_regime_detector_volatile():
    regime = detect_regime(
        _detect_snapshot(
            price=100.1,
            adx=24.0,
            momentum_norm=0.02,
            atr=0.0011,
            recent_prices=[99.0, 101.0, 98.8, 101.2, 99.1, 101.1, 99.3, 100.1],
        )
    )
    assert regime == "volatile"


def test_regime_detector_low_vol():
    regime = detect_regime(
        _detect_snapshot(
            price=100.0,
            adx=25.0,
            momentum_norm=0.01,
            atr=0.00008,
            recent_prices=[99.95, 100.0, 100.02, 99.99, 100.01, 100.0, 100.01, 99.99],
        )
    )
    assert regime == "low_vol"


def test_regime_detector_choppy():
    regime = detect_regime(
        _detect_snapshot(
            adx=9.5,
            momentum_norm=0.01,
            ema_50=100.00,
            ema_200=100.03,
            atr=0.00022,
            recent_prices=[100.1, 99.9, 100.12, 99.88, 100.11, 99.89, 100.1, 99.9],
        )
    )
    assert regime == "choppy"


def test_router_maps_all_primary_regimes_to_expected_routes():
    mapping = {
        "TREND_UP": "trend_pullback",
        "BREAKOUT_UP": "breakout_momentum",
        "MOMENTUM_UP": "breakout_momentum",
        "RANGE": "mean_reversion",
        "LOW_VOL": "mean_reversion",
        "TREND_DOWN": "observe_only",
        "BREAKOUT_DOWN": "observe_only",
        "VOLATILE": "observe_only",
        "CHOPPY": "observe_only",
        "UNKNOWN": "observe_only",
    }
    cfg = _router_cfg()
    for regime_code, expected_route in mapping.items():
        decision = resolve_entry_route(
            cfg=cfg,
            symbol="TEST-USD",
            snapshot=_route_snapshot(regime_code),
            default_strategy="mean_reversion",
            shadow_state={},
        )
        assert decision["effective_route"] == expected_route


def test_router_does_not_backdoor_downside_or_choppy_to_mean_reversion():
    cfg = _router_cfg()
    for regime_code in ("TREND_DOWN", "BREAKOUT_DOWN", "CHOPPY", "UNKNOWN"):
        decision = resolve_entry_route(
            cfg=cfg,
            symbol="TEST-USD",
            snapshot=_route_snapshot(regime_code),
            default_strategy="mean_reversion",
            shadow_state={},
        )
        assert decision["effective_route"] != "mean_reversion"
        assert decision["effective_route"] == "observe_only"


def test_router_allows_volatile_breakout_override_when_explicitly_confirmed():
    cfg = _router_cfg()
    cfg["strategy_defaults"]["router"]["auto_volatile_breakout_min"] = 90
    cfg["strategy_defaults"]["router"]["auto_volatile_breakout_min_confidence"] = 85
    decision = resolve_entry_route(
        cfg=cfg,
        symbol="TEST-USD",
        snapshot=_route_snapshot(
            "VOLATILE",
            regime_advisory={
                "suggestedRegime": "VOLATILE",
                "confidenceScore": 92.0,
                "stabilityScore": 90.0,
                "persistenceScore": 90.0,
                "analysisAnchorEpoch": time.time(),
                "breakoutScore": 94.0,
                "dataQuality": {"status": "GOOD", "supportedKeyWindows": True},
            },
        ),
        default_strategy="mean_reversion",
        shadow_state={},
    )
    assert decision["effective_route"] == "breakout_momentum"
