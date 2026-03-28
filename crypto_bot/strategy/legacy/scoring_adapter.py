"""
Legacy scoring adapter.

This module is the only allowed import surface for legacy indicator scoring.
Do not extend legacy scoring behavior here; keep this as a compatibility wrapper.
"""

from strategy.scoring import score_indicators as _legacy_score_indicators


def score_indicators(*, regime, indicators, range_pos):
    return _legacy_score_indicators(regime=regime, indicators=indicators, range_pos=range_pos)
