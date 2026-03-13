import time

from data.market_data import fetch_market_snapshot
from strategy.strategy_engine import evaluate_symbol
from trading.executor import Executor
from utils.config_loader import load_config
from utils.logger import setup_logger

logger = setup_logger("main")

HEARTBEAT_INTERVAL = 60
_buy_signal_streak: dict[str, int] = {}


def _normalize_symbols(raw_symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []

    for symbol in raw_symbols:
        if not isinstance(symbol, str):
            continue
        cleaned = symbol.strip().upper()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)

    return normalized


def _symbols_for_scan(cfg: dict, executor: Executor | None) -> list[str]:
    configured_symbols = _normalize_symbols(cfg.get("symbols", []))
    open_symbols = executor.open_symbols() if executor else []
    return _normalize_symbols(configured_symbols + open_symbols)


def _is_action_enabled(cfg: dict, symbol: str, action: str) -> bool:
    legacy_map = cfg.get("symbol_enabled", {})
    buy_map = cfg.get("symbol_buy_enabled", {})
    sell_map = cfg.get("symbol_sell_enabled", {})

    if not isinstance(legacy_map, dict):
        legacy_map = {}
    if not isinstance(buy_map, dict):
        buy_map = {}
    if not isinstance(sell_map, dict):
        sell_map = {}

    action_key = str(action).upper()
    if action_key == "BUY":
        if symbol in buy_map:
            return buy_map.get(symbol) is not False
    elif action_key == "SELL":
        if symbol in sell_map:
            return sell_map.get(symbol) is not False
    else:
        return True

    # Backward compatibility with old single-toggle config.
    if symbol in legacy_map:
        return legacy_map.get(symbol) is not False

    return True


def _signal_confirmation_cycles(cfg: dict) -> int:
    risk_cfg = cfg.get("risk", {})
    if not isinstance(risk_cfg, dict):
        return 1

    try:
        return max(1, int(float(risk_cfg.get("signal_confirmation_cycles", 1))))
    except (TypeError, ValueError):
        return 1


def main():
    logger.info("RevBot starting (paper mode default)")
    executor: Executor | None = None
    last_heartbeat = 0.0

    while True:
        try:
            cfg = load_config()

            if cfg.get("emergency_stop", False):
                logger.warning("Emergency stop active - waiting for START command")
                time.sleep(2)
                continue

            if not cfg.get("enabled", False):
                logger.info("Bot disabled - waiting")
                time.sleep(5)
                continue

            if executor is None:
                executor = Executor(cfg)
            else:
                executor.update_config(cfg)

            executor.enforce_daily_loss_controls(snapshot_fetcher=fetch_market_snapshot)

            now = time.time()
            if now - last_heartbeat > HEARTBEAT_INTERVAL:
                logger.info("Heartbeat - bot running")
                last_heartbeat = now

            symbols = _symbols_for_scan(cfg, executor)
            if not symbols:
                logger.info("No symbols configured - waiting")
                time.sleep(max(int(cfg.get("loop_sleep", 10)), 1))
                continue

            for symbol in symbols:
                market = fetch_market_snapshot(symbol, cfg)
                if market is None:
                    continue

                decision = evaluate_symbol(market, cfg)
                action = decision.get("action")
                if action != "HOLD":
                    if action == "BUY":
                        required_cycles = _signal_confirmation_cycles(cfg)
                        streak = _buy_signal_streak.get(symbol, 0) + 1
                        _buy_signal_streak[symbol] = streak
                        if streak < required_cycles:
                            logger.info(
                                f"{symbol} -> BUY blocked "
                                f"(signal confirmation {streak}/{required_cycles})"
                            )
                            time.sleep(0.2)
                            continue
                    else:
                        _buy_signal_streak.pop(symbol, None)

                    if not _is_action_enabled(cfg, symbol, action):
                        logger.info(
                            f"{symbol} -> {action} blocked (symbol {action} toggle off)"
                        )
                        time.sleep(0.2)
                        continue
                    executor.handle_decision(decision)
                else:
                    _buy_signal_streak.pop(symbol, None)

                time.sleep(0.2)

            time.sleep(max(int(cfg.get("loop_sleep", 10)), 1))
        except Exception as exc:
            logger.exception(f"Main loop error: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    main()
