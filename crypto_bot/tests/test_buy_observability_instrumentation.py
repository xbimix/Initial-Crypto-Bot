from __future__ import annotations

from strategy import strategy_orchestrator as orchestrator


def test_instrument_buy_observability_populates_all_routes():
    parse_numeric = orchestrator._parse_numeric
    routes = ("mean_reversion", "trend_pullback", "breakout_momentum", "volatility_scalper")
    for route in routes:
        decision = {"action": "HOLD", "reason": "score_below_threshold", "effective_route": route}
        payload = orchestrator._instrument_buy_observability(
            decision_payload=decision,
            route_name=route,
            score=44.0,
            score_threshold=46.0,
            z_score=-1.8,
            z_threshold=-1.3,
            range_pos=None,
            price=95.0,
            high_24h=100.0,
            low_24h=80.0,
            buy_zone_low=-0.1,
            buy_zone_high=0.5,
            parse_numeric=parse_numeric,
        )
        assert payload["buy_score_actual"] == 44.0
        assert payload["buy_score_threshold"] == 46.0
        assert payload["buy_zscore_actual"] == -1.8
        assert payload["buy_stretch_actual"] == -1.8
        assert payload["buy_zscore_threshold"] == -1.3
        assert payload["buy_price_position_in_range"] == 0.75
        assert payload["buy_zone_low"] == -0.1
        assert payload["buy_zone_high"] == 0.5
        assert payload["buy_route_name"] == route


def test_blocked_buy_population_exceeds_95_percent():
    parse_numeric = orchestrator._parse_numeric
    routes = ("mean_reversion", "trend_pullback", "breakout_momentum", "volatility_scalper")
    blocked_rows: list[dict] = []
    for idx in range(120):
        route = routes[idx % len(routes)]
        score_value = None if idx == 0 else 42.0
        payload = orchestrator._instrument_buy_observability(
            decision_payload={
                "action": "HOLD",
                "reason": "score_below_threshold",
                "effective_route": route,
            },
            route_name=route,
            score=score_value,
            score_threshold=46.0,
            z_score=-2.0,
            z_threshold=-1.3,
            range_pos=None,
            price=95.0,
            high_24h=100.0,
            low_24h=80.0,
            buy_zone_low=-0.1,
            buy_zone_high=0.5,
            parse_numeric=parse_numeric,
        )
        blocked_rows.append(payload)

    score_populated = sum(1 for row in blocked_rows if row.get("buy_score_actual") is not None)
    range_populated = sum(1 for row in blocked_rows if row.get("buy_price_position_in_range") is not None)
    score_coverage = score_populated / len(blocked_rows)
    range_coverage = range_populated / len(blocked_rows)

    assert score_coverage > 0.95
    assert range_coverage > 0.95
    assert blocked_rows[0]["buy_score_population_reason"] == "missing_score_inputs"

