from __future__ import annotations

from pathlib import Path

from strategy import state_io as strategy_state_io
from utils.state_io import read_json_file, write_json_file


class _Logger:
    def __init__(self):
        self.warnings: list[str] = []
        self.infos: list[str] = []
        self.errors: list[str] = []

    def warning(self, msg):
        self.warnings.append(str(msg))

    def info(self, msg):
        self.infos.append(str(msg))

    def error(self, msg):
        self.errors.append(str(msg))

    def exception(self, msg):
        self.errors.append(str(msg))


def test_load_strategy_state_sanitizes_map_shape_and_symbol_keys(tmp_path: Path):
    path = tmp_path / "strategy_state.json"
    write_json_file(
        path,
        {
            "last_effective_route": {
                "btc-usd": "mean_reversion",
                "": "trend_pullback",
                7: "breakout_momentum",
            },
            "last_detected_regime": ["not-a-map"],
            "shadow_regime_state": {},
        },
    )
    logger = _Logger()
    last_effective_route: dict[str, str] = {}
    last_detected_regime: dict[str, str] = {}
    shadow_state: dict[str, dict] = {}

    strategy_state_io.load_strategy_state(
        strategy_state_file=path,
        read_json_file=read_json_file,
        normalize_shadow_state=lambda raw: raw if isinstance(raw, dict) else {},
        state_maps={
            "last_effective_route": last_effective_route,
            "last_detected_regime": last_detected_regime,
        },
        shadow_regime_state=shadow_state,
        logger=logger,
    )

    assert last_effective_route == {"BTC-USD": "mean_reversion"}
    assert last_detected_regime == {}
    assert any("dropped" in msg for msg in logger.warnings)
    assert any("malformed" in msg for msg in logger.warnings)


def test_sync_with_broker_state_handles_malformed_positions_shape(tmp_path: Path):
    paper_path = tmp_path / "paper_state.json"
    write_json_file(paper_path, {"positions": ["bad", "shape"]})
    logger = _Logger()
    entry_price = {"BTC-USD": 100.0}
    entry_time = {"BTC-USD": 1_000_000.0}
    profit_lock = {"BTC-USD": None}
    peak_pnl = {"BTC-USD": 0.0}
    last_momentum = {"BTC-USD": 0.1}
    last_signal = {"BTC-USD": "BUY"}
    extra_map = {"BTC-USD": "value"}
    saved = {"count": 0}

    strategy_state_io.sync_with_broker_state(
        paper_state_file=paper_path,
        read_json_file=read_json_file,
        parse_numeric=lambda value, fallback=None: float(value) if isinstance(value, (int, float)) else fallback,
        entry_price=entry_price,
        entry_time=entry_time,
        profit_lock=profit_lock,
        peak_pnl=peak_pnl,
        last_momentum=last_momentum,
        last_signal=last_signal,
        metadata_maps=(extra_map,),
        save_strategy_state=lambda: saved.__setitem__("count", saved["count"] + 1),
        logger=logger,
    )

    # With malformed positions, all position maps should be safely cleared.
    assert entry_price == {}
    assert entry_time == {}
    assert profit_lock == {}
    assert peak_pnl == {}
    assert last_momentum == {}
    assert last_signal == {}
    assert extra_map == {}
    assert saved["count"] == 1
    assert any("positions malformed" in msg for msg in logger.warnings)


def test_sync_with_broker_state_normalizes_broker_symbol_keys(tmp_path: Path):
    paper_path = tmp_path / "paper_state.json"
    write_json_file(
        paper_path,
        {
            "positions": {
                " btc-usd ": {
                    "price": 100.0,
                    "entry_time": 1_000_000.0,
                }
            }
        },
    )
    logger = _Logger()
    entry_price = {"BTC-USD": 100.0}
    entry_time = {"BTC-USD": 1_000_000.0}
    profit_lock = {"BTC-USD": None}
    peak_pnl = {"BTC-USD": 0.0}
    last_momentum = {"BTC-USD": 0.1}
    last_signal = {"BTC-USD": "BUY"}
    extra_map = {"BTC-USD": "value"}
    saved = {"count": 0}

    strategy_state_io.sync_with_broker_state(
        paper_state_file=paper_path,
        read_json_file=read_json_file,
        parse_numeric=lambda value, fallback=None: float(value) if isinstance(value, (int, float)) else fallback,
        entry_price=entry_price,
        entry_time=entry_time,
        profit_lock=profit_lock,
        peak_pnl=peak_pnl,
        last_momentum=last_momentum,
        last_signal=last_signal,
        metadata_maps=(extra_map,),
        save_strategy_state=lambda: saved.__setitem__("count", saved["count"] + 1),
        logger=logger,
    )

    assert entry_price == {"BTC-USD": 100.0}
    assert entry_time == {"BTC-USD": 1_000_000.0}
    assert saved["count"] == 0
    assert not any("removed stale state" in msg for msg in logger.infos)


def test_sync_with_broker_state_warns_for_malformed_broker_symbol_keys(tmp_path: Path):
    paper_path = tmp_path / "paper_state.json"
    write_json_file(
        paper_path,
        {
            "positions": {
                "BTCUSD": {"price": 100.0, "entry_time": 1_000_000.0},
                7: {"price": 100.0, "entry_time": 1_000_000.0},
            }
        },
    )
    logger = _Logger()
    entry_price = {"BTC-USD": 100.0}
    entry_time = {"BTC-USD": 1_000_000.0}
    profit_lock = {"BTC-USD": None}
    peak_pnl = {"BTC-USD": 0.0}
    last_momentum = {"BTC-USD": 0.1}
    last_signal = {"BTC-USD": "BUY"}
    saved = {"count": 0}

    strategy_state_io.sync_with_broker_state(
        paper_state_file=paper_path,
        read_json_file=read_json_file,
        parse_numeric=lambda value, fallback=None: float(value) if isinstance(value, (int, float)) else fallback,
        entry_price=entry_price,
        entry_time=entry_time,
        profit_lock=profit_lock,
        peak_pnl=peak_pnl,
        last_momentum=last_momentum,
        last_signal=last_signal,
        metadata_maps=(),
        save_strategy_state=lambda: saved.__setitem__("count", saved["count"] + 1),
        logger=logger,
    )

    assert entry_price == {}
    assert saved["count"] == 1
    assert any("malformed broker symbol key" in msg for msg in logger.warnings)
