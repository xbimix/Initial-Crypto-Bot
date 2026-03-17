import re
import time
import json
import hmac
from collections import defaultdict, deque
from datetime import datetime, timezone
import os
from pathlib import Path

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

from api.revolut_account_sync import read_account_snapshot, sync_account_snapshot
from api.revolut_universe import get_universe_snapshot
from utils.config_loader import load_config, update_config
from utils.logger import setup_logger
from utils.runtime_events import append_runtime_event
from utils.runtime_guard import (
    check_disk_space,
    check_timestamp_sanity,
    cleanup_stale_locks,
    cleanup_temp_files,
)
from utils.state_snapshot import create_state_snapshot, ensure_daily_snapshot
from utils.state_storage import get_state_storage
from utils.state_validator import validate_state_files
from utils.token_regimes import (
    TOKEN_REGIME_MEAN_REVERSION,
    TOKEN_REGIME_VALUES,
    normalize_symbol as normalize_token_symbol,
    normalize_token_regime,
    is_valid_token_regime,
)

logger = setup_logger("control")
app = Flask(__name__)

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
PAPER_STATE_PATH = STATE_DIR / "paper_state.json"
STRATEGY_STATE_PATH = STATE_DIR / "strategy_state.json"
TRADES_PATH = STATE_DIR / "trades.json"
MANUAL_ACTION_CACHE_PATH = STATE_DIR / "manual_action_cache.json"
LOG_PATH = STATE_DIR / "bot.log"
LOG_TAIL_BYTES = 256 * 1024
CONTROL_HOST = os.getenv("REVBOT_CONTROL_HOST", "127.0.0.1").strip() or "127.0.0.1"
try:
    CONTROL_PORT = int(os.getenv("REVBOT_CONTROL_PORT", "8001"))
except ValueError:
    CONTROL_PORT = 8001
STRICT_STARTUP = os.getenv("REVBOT_CONTROL_STRICT_STARTUP", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SNAPSHOT_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\|\s+INFO\s+\|\s+SNAPSHOT\s+([A-Z0-9-]+)\s+\|\s+price=([0-9.]+)"
)
REQUIRED_STATE_JSON_FILES = (
    PAPER_STATE_PATH,
    STRATEGY_STATE_PATH,
    TRADES_PATH,
)
AUDIT_LOG_PATH = STATE_DIR / "audit_actions.jsonl"
MUTATING_ENDPOINTS = {
    "/config",
    "/control",
    "/kill",
    "/symbols",
    "/scalper",
    "/token-regime",
    "/risk",
    "/cooldown",
    "/close-all",
    "/manual-sell",
    "/universe-track",
}
LOCAL_LOOPBACKS = {"127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"}
try:
    MUTATING_PAYLOAD_MAX_BYTES = max(
        1024,
        int(os.getenv("REVBOT_MUTATING_PAYLOAD_MAX_BYTES", "65536")),
    )
except ValueError:
    MUTATING_PAYLOAD_MAX_BYTES = 65536
try:
    RATE_LIMIT_WINDOW_SECONDS = max(
        1,
        int(os.getenv("REVBOT_RATE_LIMIT_WINDOW_SECONDS", "60")),
    )
except ValueError:
    RATE_LIMIT_WINDOW_SECONDS = 60
try:
    RATE_LIMIT_MAX_REQUESTS = max(
        1,
        int(os.getenv("REVBOT_RATE_LIMIT_MAX_REQUESTS", "120")),
    )
except ValueError:
    RATE_LIMIT_MAX_REQUESTS = 120
ALLOW_NON_LOCAL_REQUESTS = os.getenv("REVBOT_ALLOW_NON_LOCAL_REQUESTS", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
try:
    MANUAL_ACTION_CACHE_LIMIT = max(50, int(os.getenv("REVBOT_MANUAL_ACTION_CACHE_LIMIT", "500")))
except ValueError:
    MANUAL_ACTION_CACHE_LIMIT = 500
_startup_status = None
STORAGE = get_state_storage()
_rate_limit_buckets: dict[str, deque[float]] = defaultdict(deque)


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_error(message, *, status=400, code="bad_request", details=None):
    payload = {
        "status": "error",
        "error": str(message),
        "code": code,
    }
    if details is not None:
        payload["details"] = details
    return jsonify(payload), status


def _is_mutating_request() -> bool:
    method = str(request.method or "").upper()
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False
    path = request.path or ""
    return path in MUTATING_ENDPOINTS


def _extract_client_ip() -> str:
    if request.access_route:
        route_ip = str(request.access_route[0] or "").strip()
        if route_ip:
            return route_ip
    remote = str(request.remote_addr or "").strip()
    return remote


def _is_local_request() -> bool:
    client_ip = _extract_client_ip().lower()
    if not client_ip:
        return False
    if client_ip in LOCAL_LOOPBACKS:
        return True
    if client_ip.startswith("127."):
        return True
    return False


def _extract_auth_token() -> str:
    bearer = str(request.headers.get("Authorization", "") or "").strip()
    if bearer.lower().startswith("bearer "):
        return bearer[7:].strip()
    direct = str(request.headers.get("X-Revbot-Token", "") or "").strip()
    if direct:
        return direct
    return ""


def _extract_actor() -> str:
    actor = str(request.headers.get("X-Revbot-Actor", "") or "").strip()
    if actor:
        return actor
    ip = _extract_client_ip()
    if ip:
        return f"ip:{ip}"
    return "unknown"


def _resolve_expected_auth_token() -> str:
    env_token = os.getenv("REVBOT_CONTROL_AUTH_TOKEN", "").strip()
    if env_token:
        return env_token

    try:
        cfg = load_config()
    except Exception:
        return ""

    if isinstance(cfg, dict):
        value = cfg.get("control_auth_token")
        if isinstance(value, str) and value.strip():
            return value.strip()
        control_cfg = cfg.get("control")
        if isinstance(control_cfg, dict):
            nested = control_cfg.get("auth_token")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return ""


def _check_payload_size():
    if not _is_mutating_request():
        return None

    content_length = request.content_length
    if content_length is not None and content_length > MUTATING_PAYLOAD_MAX_BYTES:
        return _json_error(
            "Payload too large",
            status=413,
            code="payload_too_large",
            details={"max_bytes": MUTATING_PAYLOAD_MAX_BYTES},
        )

    if content_length is None:
        payload = request.get_data(cache=True, as_text=False)
        if len(payload) > MUTATING_PAYLOAD_MAX_BYTES:
            return _json_error(
                "Payload too large",
                status=413,
                code="payload_too_large",
                details={"max_bytes": MUTATING_PAYLOAD_MAX_BYTES},
            )
    return None


def _check_rate_limit():
    if not _is_mutating_request():
        return None

    client_ip = _extract_client_ip() or "unknown"
    bucket_key = f"{client_ip}:{request.path}"
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS

    bucket = _rate_limit_buckets[bucket_key]
    while bucket and bucket[0] < window_start:
        bucket.popleft()

    if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
        return _json_error(
            "Too many requests",
            status=429,
            code="rate_limited",
            details={
                "limit": RATE_LIMIT_MAX_REQUESTS,
                "window_seconds": RATE_LIMIT_WINDOW_SECONDS,
            },
        )

    bucket.append(now)
    return None


def _check_mutating_auth():
    if not _is_mutating_request():
        return None

    expected = _resolve_expected_auth_token()
    if not expected:
        return _json_error(
            "Mutating auth token is not configured",
            status=503,
            code="auth_not_configured",
        )

    provided = _extract_auth_token()
    if not provided or not hmac.compare_digest(provided, expected):
        return _json_error(
            "Unauthorized",
            status=401,
            code="unauthorized",
        )

    return None


def _write_audit_event(action: str, *, old=None, new=None, result=None, extra=None):
    now = datetime.now(timezone.utc)
    event = {
        "time_utc": now.isoformat(),
        "day_utc": now.date().isoformat(),
        "action": action,
        "path": request.path,
        "method": request.method,
        "actor": getattr(g, "revbot_actor", _extract_actor()),
        "remote_addr": _extract_client_ip(),
    }
    if old is not None:
        event["old"] = old
    if new is not None:
        event["new"] = new
    if result is not None:
        event["result"] = result
    if isinstance(extra, dict) and extra:
        event["extra"] = extra

    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, separators=(",", ":")) + "\n")


@app.before_request
def _enforce_mutating_safety():
    if not _is_mutating_request():
        return None

    g.revbot_actor = _extract_actor()
    if not ALLOW_NON_LOCAL_REQUESTS and not _is_local_request():
        return _json_error(
            "Non-local requests are not allowed",
            status=403,
            code="non_local_forbidden",
        )

    payload_check = _check_payload_size()
    if payload_check is not None:
        return payload_check

    auth_check = _check_mutating_auth()
    if auth_check is not None:
        return auth_check

    rate_check = _check_rate_limit()
    if rate_check is not None:
        return rate_check
    return None


def _probe_directory_writable(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / f".control_write_probe.{os.getpid()}.{int(time.time() * 1000)}"
    marker.write_text("ok", encoding="utf-8")
    marker.unlink(missing_ok=True)


def _run_startup_checks():
    checks = []
    ok = True

    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        checks.append({"name": "state_dir_exists", "ok": True})
    except Exception as exc:
        checks.append({"name": "state_dir_exists", "ok": False, "detail": str(exc)})
        ok = False

    try:
        _probe_directory_writable(STATE_DIR)
        checks.append({"name": "state_dir_writable", "ok": True})
    except Exception as exc:
        checks.append({"name": "state_dir_writable", "ok": False, "detail": str(exc)})
        ok = False

    lock_cleanup = cleanup_stale_locks(STATE_DIR)
    checks.append(
        {
            "name": "stale_lock_cleanup",
            "ok": True,
            "removed_count": lock_cleanup.get("removed_count", 0),
        }
    )

    temp_cleanup = cleanup_temp_files(STATE_DIR)
    checks.append(
        {
            "name": "temp_file_cleanup",
            "ok": True,
            "removed_count": temp_cleanup.get("removed_count", 0),
        }
    )

    disk = check_disk_space(STATE_DIR)
    checks.append(
        {
            "name": "disk_space",
            "ok": bool(disk.get("ok", False)),
            "free_mb": disk.get("free_mb"),
            "required_min_free_mb": disk.get("required_min_free_mb"),
        }
    )
    if not disk.get("ok", False):
        ok = False

    timestamp_check = check_timestamp_sanity(STATE_DIR)
    checks.append(
        {
            "name": "timestamp_sanity",
            "ok": bool(timestamp_check.get("ok", False)),
            "future_files": timestamp_check.get("future_files", []),
        }
    )
    if not timestamp_check.get("ok", False):
        ok = False

    expected_token = _resolve_expected_auth_token()
    auth_ok = bool(expected_token)
    checks.append({"name": "mutating_auth_configured", "ok": auth_ok})

    checks.append(
        {
            "name": "non_local_requests_allowed",
            "ok": True,
            "value": bool(ALLOW_NON_LOCAL_REQUESTS),
        }
    )

    for path in REQUIRED_STATE_JSON_FILES:
        exists = path.exists()
        checks.append({"name": f"{path.name}_present", "ok": exists})
        if not exists:
            continue

        try:
            STORAGE.read(path, strict=True)
            checks.append({"name": f"{path.name}_json_valid", "ok": True})
        except Exception as exc:
            checks.append({"name": f"{path.name}_json_valid", "ok": False, "detail": str(exc)})
            ok = False

    state_validation = validate_state_files(STATE_DIR, strict_files_exist=False)
    checks.append(
        {
            "name": "state_integrity",
            "ok": bool(state_validation.get("ok", False)),
            "error_count": len(state_validation.get("errors", [])),
        }
    )
    if not state_validation.get("ok", False):
        ok = False

    try:
        cfg = load_config()
        checks.append({"name": "config_loadable", "ok": isinstance(cfg, dict)})
        if not isinstance(cfg, dict):
            ok = False
    except Exception as exc:
        checks.append({"name": "config_loadable", "ok": False, "detail": str(exc)})
        ok = False

    return {
        "ok": ok,
        "checkedAt": _now_utc_iso(),
        "checks": checks,
    }


def _refresh_startup_status():
    global _startup_status
    _startup_status = _run_startup_checks()
    return _startup_status


_startup_status = _refresh_startup_status()


def _normalize_symbol(value):
    return normalize_token_symbol(value)


def _normalize_symbols(raw_symbols):
    if not isinstance(raw_symbols, list):
        return []

    seen = set()
    normalized = []
    for raw_symbol in raw_symbols:
        symbol = _normalize_symbol(raw_symbol)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    return normalized


def _parse_enabled_map(value):
    if not isinstance(value, dict):
        return {}

    enabled_map = {}
    for raw_symbol, raw_enabled in value.items():
        symbol = _normalize_symbol(raw_symbol)
        if not symbol:
            continue
        enabled_map[symbol] = raw_enabled is not False
    return enabled_map


def _parse_token_regime_map(value):
    if not isinstance(value, dict):
        return {}

    output = {}
    for raw_symbol, raw_regime in value.items():
        symbol = _normalize_symbol(raw_symbol)
        if not symbol:
            continue
        output[symbol] = normalize_token_regime(raw_regime, default=TOKEN_REGIME_MEAN_REVERSION)
    return output


def _is_enabled(enabled_map, symbol):
    return enabled_map.get(symbol, True) is not False


def _normalize_strategy_name(value):
    raw = str(value or "").strip().lower()
    if raw in {"volatility_scalper", "vol_scalper", "scalper"}:
        return "volatility_scalper"
    return "mean_reversion"


def _to_float(value, fallback=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _normalized_action_id(value):
    if not isinstance(value, str):
        return ""
    return value.strip()


def _read_manual_action_cache():
    cache = STORAGE.read(MANUAL_ACTION_CACHE_PATH, default={})
    if not isinstance(cache, dict):
        return {}
    return cache


def _save_manual_action_cache(cache):
    if not isinstance(cache, dict):
        cache = {}
    STORAGE.write(MANUAL_ACTION_CACHE_PATH, cache, use_lock=False)


def _get_cached_manual_action(action_name: str, action_id: str):
    if not action_id:
        return None
    cache = _read_manual_action_cache()
    key = f"{action_name}:{action_id}"
    payload = cache.get(key)
    if isinstance(payload, dict):
        replay = dict(payload)
        replay["idempotent_replay"] = True
        return replay
    return None


def _store_cached_manual_action(action_name: str, action_id: str, payload):
    if not action_id or not isinstance(payload, dict):
        return

    cache = _read_manual_action_cache()
    key = f"{action_name}:{action_id}"
    cache[key] = payload

    if len(cache) > MANUAL_ACTION_CACHE_LIMIT:
        overflow = len(cache) - MANUAL_ACTION_CACHE_LIMIT
        for old_key in list(cache.keys())[:overflow]:
            cache.pop(old_key, None)

    _save_manual_action_cache(cache)


def _remove_strategy_symbol(state, symbol):
    if not isinstance(state, dict):
        return {}

    for key in (
        "entry_price",
        "entry_time",
        "profit_lock",
        "peak_pnl",
        "last_signal",
        "last_momentum",
        "last_regime",
        "last_score",
        "last_volatility",
        "last_configured_regime",
        "last_detected_regime",
        "last_detected_regime_confidence",
        "last_detected_regime_confidence_label",
        "last_effective_strategy",
        "last_auto_fallback_reason",
    ):
        section = state.get(key)
        if isinstance(section, dict):
            section.pop(symbol, None)

    return state


def _read_latest_snapshot_price(symbol):
    if not LOG_PATH.exists():
        return None

    try:
        file_size = LOG_PATH.stat().st_size
        bytes_to_read = min(LOG_TAIL_BYTES, file_size)
        if bytes_to_read <= 0:
            return None

        with open(LOG_PATH, "rb") as handle:
            handle.seek(file_size - bytes_to_read)
            tail = handle.read(bytes_to_read).decode("utf-8", errors="ignore")

        for line in reversed(tail.splitlines()):
            match = SNAPSHOT_PATTERN.match(line)
            if not match:
                continue
            if match.group(2) != symbol:
                continue

            try:
                value = float(match.group(3))
                return value if value > 0 else None
            except ValueError:
                return None

        return None
    except Exception as exc:
        logger.warning(f"Manual sell price lookup failed for {symbol}: {exc}")
        return None


def _apply_control_action(action, reason=None):
    action_key = str(action).strip().upper()

    if action_key not in {"START", "STOP", "KILL"}:
        return None, f"Unknown action: {action}"

    def _mutate(cfg):
        if not isinstance(cfg, dict):
            cfg = {}

        if action_key == "START":
            cfg["enabled"] = True
            cfg["trading_enabled"] = True
            cfg["emergency_stop"] = False
            cfg.pop("emergency_stop_at", None)
            cfg.pop("emergency_stop_reason", None)
            logger.info("Bot process enabled and trading armed via control server")
        elif action_key == "STOP":
            cfg["enabled"] = True
            cfg["trading_enabled"] = False
            cfg["emergency_stop"] = False
            logger.info("Bot process kept online; trading disarmed via control server")
        else:
            cfg["enabled"] = False
            cfg["trading_enabled"] = False
            cfg["emergency_stop"] = True
            cfg["emergency_stop_at"] = time.time()
            cfg["emergency_stop_reason"] = reason or "manual_kill"
            logger.warning("Emergency stop activated")

        return cfg

    cfg = update_config(_mutate)
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "trading_enabled": bool(cfg.get("trading_enabled", False)),
        "emergency_stop": bool(cfg.get("emergency_stop", False)),
        "action": action_key,
    }, None


@app.route("/status", methods=["GET"])
def status():
    cfg = load_config()

    symbols = _normalize_symbols(cfg.get("symbols", []))
    symbol_enabled = _parse_enabled_map(cfg.get("symbol_enabled", {}))
    symbol_buy_enabled = _parse_enabled_map(cfg.get("symbol_buy_enabled", {}))
    symbol_sell_enabled = _parse_enabled_map(cfg.get("symbol_sell_enabled", {}))
    token_regimes = _parse_token_regime_map(cfg.get("token_regimes", {}))

    buy_enabled_symbols = [
        symbol
        for symbol in symbols
        if _is_enabled(symbol_buy_enabled if symbol in symbol_buy_enabled else symbol_enabled, symbol)
    ]
    sell_enabled_symbols = [
        symbol
        for symbol in symbols
        if _is_enabled(symbol_sell_enabled if symbol in symbol_sell_enabled else symbol_enabled, symbol)
    ]

    risk = cfg.get("risk", {})
    if not isinstance(risk, dict):
        risk = {}
    trade_window = risk.get("trade_window_utc", {})
    if not isinstance(trade_window, dict):
        trade_window = {}
    symbol_cooldown = risk.get("symbol_cooldown_seconds", {})
    if not isinstance(symbol_cooldown, dict):
        symbol_cooldown = {}

    return jsonify(
        {
            "enabled": bool(cfg.get("enabled", False)),
            "trading_enabled": bool(cfg.get("trading_enabled", False)),
            "emergency_stop": bool(cfg.get("emergency_stop", False)),
            "execution_mode": cfg.get("execution_mode"),
            "symbols": symbols,
            "token_regimes": token_regimes,
            "buy_enabled_symbols": buy_enabled_symbols,
            "sell_enabled_symbols": sell_enabled_symbols,
            "loop_sleep": cfg.get("loop_sleep"),
            "cooldown_seconds": risk.get("cooldown_seconds"),
            "max_concurrent_trades": risk.get("max_concurrent_trades"),
            "max_concurrent_trades_per_token": risk.get(
                "max_concurrent_trades_per_token"
            ),
            "max_trade_amount_usd": risk.get("max_trade_amount_usd"),
            "trade_amount_usd": risk.get("trade_amount_usd"),
            "max_portfolio_exposure_pct": risk.get("max_portfolio_exposure_pct"),
            "max_exposure_per_token_pct": risk.get("max_exposure_per_token_pct"),
            "daily_loss_limit_usd": risk.get("daily_loss_limit_usd"),
            "daily_loss_auto_pause": risk.get("daily_loss_auto_pause"),
            "daily_loss_close_all": risk.get("daily_loss_close_all"),
            "signal_confirmation_cycles": risk.get("signal_confirmation_cycles"),
            "trade_window_utc": trade_window,
            "symbol_cooldown_seconds": symbol_cooldown,
        }
    )


@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "control",
            "time": _now_utc_iso(),
        }
    )


@app.route("/revolut-account", methods=["GET"])
def revolut_account():
    force = str(request.args.get("force", "0")).strip().lower() in {"1", "true", "yes", "on"}
    if force:
        snapshot = sync_account_snapshot()
    else:
        snapshot = read_account_snapshot(default={})
        if not snapshot:
            snapshot = sync_account_snapshot()
    return jsonify(snapshot)


@app.route("/revolut-universe", methods=["GET"])
def revolut_universe():
    cfg = load_config()
    force = str(request.args.get("force", "0")).strip().lower() in {"1", "true", "yes", "on"}
    snapshot = get_universe_snapshot(cfg, force_refresh=force)
    return jsonify(snapshot)


@app.route("/ready", methods=["GET"])
def ready():
    status_payload = _refresh_startup_status()
    if status_payload.get("ok"):
        payload = dict(status_payload)
        payload["status"] = "ok"
        return jsonify(payload)
    payload = dict(status_payload)
    payload["status"] = "error"
    payload["error"] = "startup_checks_failed"
    payload["code"] = "not_ready"
    return jsonify(payload), 503


@app.errorhandler(Exception)
def handle_exception(exc):
    if isinstance(exc, HTTPException):
        return _json_error(
            exc.description or "HTTP error",
            status=exc.code or 500,
            code="http_error",
        )

    logger.exception(f"Unhandled control server error: {exc}")
    return _json_error("Internal server error", status=500, code="internal_error")


@app.route("/config", methods=["GET"])
def get_config():
    return jsonify(load_config())


@app.route("/config", methods=["POST"])
def update_config_route():
    updates = request.get_json(silent=True) or {}
    if not isinstance(updates, dict):
        return _json_error("Request body must be an object")

    before_cfg = load_config()
    old_values = {
        key: before_cfg.get(key)
        for key in updates.keys()
    } if isinstance(before_cfg, dict) else {}

    def _mutate(cfg):
        cfg.update(updates)
        return cfg

    cfg = update_config(_mutate)
    logger.info(f"Config updated: {updates}")
    _write_audit_event(
        "config_update",
        old=old_values,
        new=updates,
        result={"status": "ok"},
    )
    return jsonify({"status": "ok", "config": cfg})


@app.route("/control", methods=["POST"])
def control():
    data = request.get_json(silent=True) or {}
    action = data.get("action", "")
    reason = data.get("reason")

    payload, error = _apply_control_action(action, reason=reason)
    if error:
        return _json_error(error)

    _write_audit_event(
        "control_action",
        new={"action": str(action).upper(), "reason": reason},
        result=payload,
    )
    return jsonify(payload)


@app.route("/kill", methods=["POST"])
def kill():
    data = request.get_json(silent=True) or {}
    reason = data.get("reason") if isinstance(data, dict) else None

    payload, error = _apply_control_action("KILL", reason=reason)
    if error:
        return _json_error(error)

    _write_audit_event(
        "kill_action",
        new={"action": "KILL", "reason": reason},
        result=payload,
    )
    return jsonify(payload)


@app.route("/symbols", methods=["POST"])
def update_symbols():
    body = request.get_json(silent=True) or {}
    symbol = _normalize_symbol(body.get("symbol"))
    side_raw = body.get("side")
    enabled = body.get("enabled")

    if not symbol:
        return _json_error("Missing symbol")

    if enabled is None or not isinstance(enabled, bool):
        return _json_error("enabled must be a boolean")

    side = None
    if side_raw is not None:
        if not isinstance(side_raw, str):
            return _json_error("side must be buy, sell, or omitted")
        side = side_raw.strip().lower()
        if side not in {"buy", "sell"}:
            return _json_error("side must be buy, sell, or omitted")

    cfg_before = load_config()
    old_payload = {}
    if isinstance(cfg_before, dict):
        old_payload = {
            "symbols": cfg_before.get("symbols"),
            "symbol_enabled": cfg_before.get("symbol_enabled"),
            "symbol_buy_enabled": cfg_before.get("symbol_buy_enabled"),
            "symbol_sell_enabled": cfg_before.get("symbol_sell_enabled"),
        }

    result = {}

    def _mutate(cfg):
        nonlocal result

        symbols = _normalize_symbols(cfg.get("symbols", []))
        if symbol not in symbols:
            symbols.append(symbol)

        legacy_map = _parse_enabled_map(cfg.get("symbol_enabled", {}))
        buy_map = _parse_enabled_map(cfg.get("symbol_buy_enabled", {}))
        sell_map = _parse_enabled_map(cfg.get("symbol_sell_enabled", {}))

        if side == "buy":
            buy_map[symbol] = enabled
        elif side == "sell":
            sell_map[symbol] = enabled
        else:
            buy_map[symbol] = enabled
            sell_map[symbol] = enabled
            legacy_map[symbol] = enabled

        cfg["symbols"] = symbols
        cfg["symbol_enabled"] = legacy_map
        cfg["symbol_buy_enabled"] = buy_map
        cfg["symbol_sell_enabled"] = sell_map

        result = {
            "symbol": symbol,
            "side": side,
            "enabled": enabled,
            "symbols": symbols,
            "symbol_buy_enabled": buy_map,
            "symbol_sell_enabled": sell_map,
            "symbol_enabled": legacy_map,
        }
        return cfg

    update_config(_mutate)
    _write_audit_event(
        "symbols_update",
        old=old_payload,
        new={"symbol": symbol, "side": side, "enabled": enabled},
        result=result,
    )
    return jsonify(result)


@app.route("/universe-track", methods=["POST"])
def update_universe_track():
    body = request.get_json(silent=True) or {}
    symbol = _normalize_symbol(body.get("symbol"))
    tracked = body.get("tracked")

    if not symbol:
        return _json_error("Missing symbol")
    if not isinstance(tracked, bool):
        return _json_error("tracked must be a boolean")

    cfg_before = load_config()
    old_payload = {}
    if isinstance(cfg_before, dict):
        old_payload = {
            "symbols": cfg_before.get("symbols"),
            "symbol_buy_enabled": cfg_before.get("symbol_buy_enabled"),
            "symbol_sell_enabled": cfg_before.get("symbol_sell_enabled"),
        }

    result = {}

    def _mutate(cfg):
        nonlocal result

        symbols = _normalize_symbols(cfg.get("symbols", []))
        buy_map = _parse_enabled_map(cfg.get("symbol_buy_enabled", {}))
        sell_map = _parse_enabled_map(cfg.get("symbol_sell_enabled", {}))
        legacy_map = _parse_enabled_map(cfg.get("symbol_enabled", {}))

        if tracked:
            if symbol not in symbols:
                symbols.append(symbol)
            buy_map[symbol] = True
            sell_map[symbol] = True
            legacy_map[symbol] = True
        else:
            symbols = [item for item in symbols if item != symbol]
            buy_map[symbol] = False
            # Keep SELL enabled so open-position exits remain safe.
            sell_map[symbol] = True
            legacy_map[symbol] = False

        cfg["symbols"] = symbols
        cfg["symbol_buy_enabled"] = buy_map
        cfg["symbol_sell_enabled"] = sell_map
        cfg["symbol_enabled"] = legacy_map

        result = {
            "symbol": symbol,
            "tracked": tracked,
            "symbols": symbols,
            "symbol_buy_enabled": buy_map,
            "symbol_sell_enabled": sell_map,
            "symbol_enabled": legacy_map,
        }
        return cfg

    update_config(_mutate)
    _write_audit_event(
        "universe_track_update",
        old=old_payload,
        new={"symbol": symbol, "tracked": tracked},
        result=result,
    )
    return jsonify(result)


@app.route("/scalper", methods=["POST"])
def update_scalper():
    body = request.get_json(silent=True) or {}
    symbol = _normalize_symbol(body.get("symbol"))
    enabled = body.get("enabled")

    if not symbol:
        return _json_error("Missing symbol")

    if not isinstance(enabled, bool):
        return _json_error("enabled must be a boolean")

    cfg_before = load_config()
    old_payload = {}
    if isinstance(cfg_before, dict):
        old_payload = {
            "symbol_strategies": cfg_before.get("symbol_strategies"),
            "volatility_scalper": cfg_before.get("volatility_scalper"),
        }

    result = {}

    def _mutate(cfg):
        nonlocal result

        symbols = _normalize_symbols(cfg.get("symbols", []))
        if symbol not in symbols:
            symbols.append(symbol)

        symbol_strategies = cfg.get("symbol_strategies", {})
        if not isinstance(symbol_strategies, dict):
            symbol_strategies = {}

        symbol_strategies[symbol] = (
            "volatility_scalper"
            if enabled
            else "mean_reversion"
        )

        scalper_cfg = cfg.get("volatility_scalper", {})
        if not isinstance(scalper_cfg, dict):
            scalper_cfg = {}

        scalper_symbols = _normalize_symbols(scalper_cfg.get("symbols", []))
        if enabled:
            if symbol not in scalper_symbols:
                scalper_symbols.append(symbol)
        else:
            scalper_symbols = [item for item in scalper_symbols if item != symbol]

        scalper_cfg["symbols"] = scalper_symbols
        cfg["symbols"] = symbols
        cfg["symbol_strategies"] = symbol_strategies
        cfg["volatility_scalper"] = scalper_cfg

        result = {
            "symbol": symbol,
            "enabled": enabled,
            "strategy": _normalize_strategy_name(symbol_strategies.get(symbol)),
            "symbol_strategies": symbol_strategies,
            "volatility_scalper": scalper_cfg,
        }
        return cfg

    update_config(_mutate)
    _write_audit_event(
        "scalper_update",
        old=old_payload,
        new={"symbol": symbol, "enabled": enabled},
        result=result,
    )
    return jsonify(result)


@app.route("/token-regime", methods=["POST"])
def update_token_regime():
    body = request.get_json(silent=True) or {}
    symbol = _normalize_symbol(body.get("symbol"))
    regime_raw = body.get("regime")

    if not symbol:
        return _json_error("Missing symbol")

    if regime_raw is None or not isinstance(regime_raw, str):
        return _json_error(
            "regime must be one of: " + ", ".join(TOKEN_REGIME_VALUES)
        )

    if not is_valid_token_regime(regime_raw):
        return _json_error(
            "regime must be one of: " + ", ".join(TOKEN_REGIME_VALUES)
        )

    configured_regime = normalize_token_regime(regime_raw, default=TOKEN_REGIME_MEAN_REVERSION)
    cfg_before = load_config()
    old_payload = {}
    if isinstance(cfg_before, dict):
        old_payload = {
            "token_regimes": cfg_before.get("token_regimes"),
        }

    result = {}

    def _mutate(cfg):
        nonlocal result
        symbols = _normalize_symbols(cfg.get("symbols", []))
        if symbol not in symbols:
            symbols.append(symbol)

        token_regimes = _parse_token_regime_map(cfg.get("token_regimes", {}))
        token_regimes[symbol] = configured_regime

        cfg["symbols"] = symbols
        cfg["token_regimes"] = token_regimes
        result = {
            "symbol": symbol,
            "configured_regime": configured_regime,
            "token_regimes": token_regimes,
        }
        return cfg

    update_config(_mutate)
    _write_audit_event(
        "token_regime_update",
        old=old_payload,
        new={"symbol": symbol, "configured_regime": configured_regime},
        result=result,
    )
    return jsonify(result)


@app.route("/risk", methods=["POST"])
def update_risk():
    body = request.get_json(silent=True) or {}
    max_concurrent_raw = body.get("maxConcurrentTrades")
    max_concurrent_per_token_raw = body.get("maxConcurrentTradesPerToken")
    max_trade_amount_raw = body.get("maxTradeAmountUsd")
    trade_amount_raw = body.get("tradeAmountUsd")
    max_portfolio_exposure_raw = body.get("maxPortfolioExposurePct")
    max_token_exposure_raw = body.get("maxExposurePerTokenPct")
    daily_loss_limit_raw = body.get("dailyLossLimitUsd")
    daily_loss_auto_pause_raw = body.get("dailyLossAutoPause")
    daily_loss_close_all_raw = body.get("dailyLossCloseAll")
    signal_confirmation_cycles_raw = body.get("signalConfirmationCycles")
    trade_window_enabled_raw = body.get("tradeWindowEnabled")
    trade_window_start_hour_raw = body.get("tradeWindowStartHourUtc")
    trade_window_end_hour_raw = body.get("tradeWindowEndHourUtc")

    if (
        max_concurrent_raw is None
        and max_concurrent_per_token_raw is None
        and max_trade_amount_raw is None
        and trade_amount_raw is None
        and max_portfolio_exposure_raw is None
        and max_token_exposure_raw is None
        and daily_loss_limit_raw is None
        and daily_loss_auto_pause_raw is None
        and daily_loss_close_all_raw is None
        and signal_confirmation_cycles_raw is None
        and trade_window_enabled_raw is None
        and trade_window_start_hour_raw is None
        and trade_window_end_hour_raw is None
    ):
        return _json_error("No risk values provided")

    try:
        max_concurrent = (
            None
            if max_concurrent_raw is None
            else max(1, int(float(max_concurrent_raw)))
        )
    except (TypeError, ValueError):
        return _json_error("maxConcurrentTrades must be a number")

    try:
        max_concurrent_per_token = (
            None
            if max_concurrent_per_token_raw is None
            else max(1, int(float(max_concurrent_per_token_raw)))
        )
    except (TypeError, ValueError):
        return _json_error("maxConcurrentTradesPerToken must be a number")

    try:
        max_trade_amount = (
            None
            if max_trade_amount_raw is None
            else max(1.0, float(max_trade_amount_raw))
        )
    except (TypeError, ValueError):
        return _json_error("maxTradeAmountUsd must be a number")

    try:
        trade_amount = (
            None
            if trade_amount_raw is None
            else max(1.0, float(trade_amount_raw))
        )
    except (TypeError, ValueError):
        return _json_error("tradeAmountUsd must be a number")

    try:
        max_portfolio_exposure = (
            None
            if max_portfolio_exposure_raw is None
            else max(1.0, min(100.0, float(max_portfolio_exposure_raw)))
        )
    except (TypeError, ValueError):
        return _json_error("maxPortfolioExposurePct must be a number")

    try:
        max_token_exposure = (
            None
            if max_token_exposure_raw is None
            else max(1.0, min(100.0, float(max_token_exposure_raw)))
        )
    except (TypeError, ValueError):
        return _json_error("maxExposurePerTokenPct must be a number")

    try:
        daily_loss_limit = (
            None
            if daily_loss_limit_raw is None
            else max(0.0, float(daily_loss_limit_raw))
        )
    except (TypeError, ValueError):
        return _json_error("dailyLossLimitUsd must be a number")

    if daily_loss_auto_pause_raw is not None and not isinstance(daily_loss_auto_pause_raw, bool):
        return _json_error("dailyLossAutoPause must be a boolean")
    daily_loss_auto_pause = daily_loss_auto_pause_raw if isinstance(daily_loss_auto_pause_raw, bool) else None

    if daily_loss_close_all_raw is not None and not isinstance(daily_loss_close_all_raw, bool):
        return _json_error("dailyLossCloseAll must be a boolean")
    daily_loss_close_all = daily_loss_close_all_raw if isinstance(daily_loss_close_all_raw, bool) else None

    try:
        signal_confirmation_cycles = (
            None
            if signal_confirmation_cycles_raw is None
            else max(1, int(float(signal_confirmation_cycles_raw)))
        )
    except (TypeError, ValueError):
        return _json_error("signalConfirmationCycles must be a number")

    if trade_window_enabled_raw is not None and not isinstance(trade_window_enabled_raw, bool):
        return _json_error("tradeWindowEnabled must be a boolean")
    trade_window_enabled = trade_window_enabled_raw if isinstance(trade_window_enabled_raw, bool) else None

    try:
        trade_window_start_hour = (
            None
            if trade_window_start_hour_raw is None
            else int(float(trade_window_start_hour_raw))
        )
    except (TypeError, ValueError):
        return _json_error("tradeWindowStartHourUtc must be a number")

    try:
        trade_window_end_hour = (
            None
            if trade_window_end_hour_raw is None
            else int(float(trade_window_end_hour_raw))
        )
    except (TypeError, ValueError):
        return _json_error("tradeWindowEndHourUtc must be a number")

    if trade_window_start_hour is not None and not (0 <= trade_window_start_hour <= 23):
        return _json_error("tradeWindowStartHourUtc must be between 0 and 23")
    if trade_window_end_hour is not None and not (0 <= trade_window_end_hour <= 23):
        return _json_error("tradeWindowEndHourUtc must be between 0 and 23")

    cfg_before = load_config()
    old_risk = cfg_before.get("risk") if isinstance(cfg_before, dict) else None

    result = {}

    def _mutate(cfg):
        nonlocal result

        risk = cfg.get("risk", {})
        if not isinstance(risk, dict):
            risk = {}

        if max_concurrent is not None:
            risk["max_concurrent_trades"] = max_concurrent
        if max_concurrent_per_token is not None:
            risk["max_concurrent_trades_per_token"] = max_concurrent_per_token
        if max_trade_amount is not None:
            risk["max_trade_amount_usd"] = max_trade_amount
        if trade_amount is not None:
            risk["trade_amount_usd"] = trade_amount
        if max_portfolio_exposure is not None:
            risk["max_portfolio_exposure_pct"] = max_portfolio_exposure
        if max_token_exposure is not None:
            risk["max_exposure_per_token_pct"] = max_token_exposure
        if daily_loss_limit is not None:
            risk["daily_loss_limit_usd"] = daily_loss_limit
        if daily_loss_auto_pause is not None:
            risk["daily_loss_auto_pause"] = daily_loss_auto_pause
        if daily_loss_close_all is not None:
            risk["daily_loss_close_all"] = daily_loss_close_all
        if signal_confirmation_cycles is not None:
            risk["signal_confirmation_cycles"] = signal_confirmation_cycles

        trade_window = risk.get("trade_window_utc", {})
        if not isinstance(trade_window, dict):
            trade_window = {}
        if trade_window_enabled is not None:
            trade_window["enabled"] = trade_window_enabled
        if trade_window_start_hour is not None:
            trade_window["start_hour_utc"] = trade_window_start_hour
        if trade_window_end_hour is not None:
            trade_window["end_hour_utc"] = trade_window_end_hour
        if trade_window:
            risk["trade_window_utc"] = trade_window

        cfg["risk"] = risk
        result = {
            "risk": risk,
            "maxConcurrentTrades": risk.get("max_concurrent_trades"),
            "maxConcurrentTradesPerToken": risk.get("max_concurrent_trades_per_token"),
            "maxTradeAmountUsd": risk.get("max_trade_amount_usd"),
            "tradeAmountUsd": risk.get("trade_amount_usd"),
            "maxPortfolioExposurePct": risk.get("max_portfolio_exposure_pct"),
            "maxExposurePerTokenPct": risk.get("max_exposure_per_token_pct"),
            "dailyLossLimitUsd": risk.get("daily_loss_limit_usd"),
            "dailyLossAutoPause": risk.get("daily_loss_auto_pause"),
            "dailyLossCloseAll": risk.get("daily_loss_close_all"),
            "signalConfirmationCycles": risk.get("signal_confirmation_cycles"),
            "tradeWindowUtc": risk.get("trade_window_utc"),
        }
        return cfg

    update_config(_mutate)
    _write_audit_event(
        "risk_update",
        old={"risk": old_risk},
        new=body,
        result=result,
    )
    return jsonify(result)


@app.route("/cooldown", methods=["POST"])
def update_symbol_cooldown():
    body = request.get_json(silent=True) or {}
    symbol = _normalize_symbol(body.get("symbol"))
    cooldown_seconds_raw = body.get("cooldownSeconds")

    if not symbol:
        return _json_error("Missing symbol")

    if cooldown_seconds_raw is None:
        cooldown_seconds = None
    else:
        cooldown_seconds = _to_float(cooldown_seconds_raw, fallback=None)
        if cooldown_seconds is None:
            return _json_error("cooldownSeconds must be a number")
        cooldown_seconds = max(1.0, cooldown_seconds)

    cfg_before = load_config()
    old_payload = {}
    if isinstance(cfg_before, dict):
        old_payload = {
            "symbol_cooldown_seconds": (
                cfg_before.get("risk", {}).get("symbol_cooldown_seconds", {})
                if isinstance(cfg_before.get("risk", {}), dict)
                else {}
            )
        }

    result = {}

    def _mutate(cfg):
        nonlocal result

        symbols = _normalize_symbols(cfg.get("symbols", []))
        if symbol not in symbols:
            symbols.append(symbol)

        risk = cfg.get("risk", {})
        if not isinstance(risk, dict):
            risk = {}

        symbol_cooldown = risk.get("symbol_cooldown_seconds", {})
        if not isinstance(symbol_cooldown, dict):
            symbol_cooldown = {}

        if cooldown_seconds is None:
            symbol_cooldown.pop(symbol, None)
        else:
            symbol_cooldown[symbol] = cooldown_seconds

        risk["symbol_cooldown_seconds"] = symbol_cooldown
        cfg["symbols"] = symbols
        cfg["risk"] = risk

        result = {
            "symbol": symbol,
            "cooldownSeconds": symbol_cooldown.get(symbol),
            "symbolCooldownSeconds": symbol_cooldown,
        }
        return cfg

    update_config(_mutate)
    _write_audit_event(
        "cooldown_update",
        old=old_payload,
        new={"symbol": symbol, "cooldownSeconds": cooldown_seconds},
        result=result,
    )
    return jsonify(result)


@app.route("/close-all", methods=["POST"])
def close_all_positions():
    body = request.get_json(silent=True) or {}
    reason = str(body.get("reason") or "manual_close_all").strip() or "manual_close_all"
    action_id = _normalized_action_id(body.get("action_id") or body.get("actionId"))

    with STORAGE.transaction(STATE_DIR, timeout=12.0):
        cached = _get_cached_manual_action("close_all", action_id)
        if cached is not None:
            _write_audit_event(
                "close_all",
                new={"reason": reason, "action_id": action_id},
                result={
                    "closedCount": cached.get("closedCount"),
                    "totalPnl": cached.get("totalPnl"),
                    "balance": cached.get("balance"),
                    "idempotent_replay": True,
                },
            )
            return jsonify(cached)

        paper_state = STORAGE.read(PAPER_STATE_PATH, default={})
        strategy_state = STORAGE.read(STRATEGY_STATE_PATH, default={})
        trades = STORAGE.read(TRADES_PATH, default=[])

        if not isinstance(paper_state, dict):
            paper_state = {}
        if not isinstance(strategy_state, dict):
            strategy_state = {}
        if not isinstance(trades, list):
            trades = []

        positions = paper_state.get("positions", {})
        if not isinstance(positions, dict):
            positions = {}

        if not positions:
            payload = {
                "status": "ok",
                "closedCount": 0,
                "totalPnl": 0.0,
                "balance": _to_float(paper_state.get("balance"), fallback=0.0) or 0.0,
                "reason": reason,
            }
            _store_cached_manual_action("close_all", action_id, payload)
            _write_audit_event(
                "close_all",
                new={"reason": reason, "action_id": action_id},
                result={
                    "closedCount": 0,
                    "totalPnl": 0.0,
                    "balance": payload.get("balance"),
                    "idempotent_replay": False,
                },
            )
            return jsonify(payload)

        try:
            balance = float(paper_state.get("balance", 0))
        except (TypeError, ValueError):
            balance = 0.0

        closed_items = []
        total_pnl = 0.0

        for symbol, raw_position in list(positions.items()):
            if not isinstance(raw_position, dict):
                continue

            entry_price = _to_float(raw_position.get("price"), fallback=None)
            size = _to_float(raw_position.get("size"), fallback=None)
            if entry_price is None or size is None or entry_price <= 0 or size <= 0:
                continue

            market_price = _read_latest_snapshot_price(symbol)
            sell_price = market_price if market_price and market_price > 0 else entry_price
            pnl = (sell_price - entry_price) * size
            proceeds = sell_price * size
            balance += proceeds
            total_pnl += pnl

            positions.pop(symbol, None)
            strategy_state = _remove_strategy_symbol(strategy_state, symbol)

            trade_entry = {
                "time": time.time(),
                "symbol": symbol,
                "side": "SELL",
                "price": sell_price,
                "size": size,
                "pnl": pnl,
                "balance": balance,
                "reason": reason,
            }
            trades.append(trade_entry)
            closed_items.append(
                {
                    "symbol": symbol,
                    "price": sell_price,
                    "size": size,
                    "pnl": pnl,
                }
            )

        paper_state["positions"] = positions
        paper_state["balance"] = balance

        STORAGE.write(PAPER_STATE_PATH, paper_state)
        STORAGE.write(STRATEGY_STATE_PATH, strategy_state)
        STORAGE.write(TRADES_PATH, trades)

    payload = {
        "status": "ok",
        "closedCount": len(closed_items),
        "closed": closed_items,
        "totalPnl": total_pnl,
        "balance": balance,
        "reason": reason,
    }
    _store_cached_manual_action("close_all", action_id, payload)
    _write_audit_event(
        "close_all",
        new={"reason": reason, "action_id": action_id},
        result={
            "closedCount": payload.get("closedCount"),
            "totalPnl": payload.get("totalPnl"),
            "balance": payload.get("balance"),
            "idempotent_replay": payload.get("idempotent_replay", False),
        },
    )

    logger.warning(
        f"Close-all executed: closed={len(closed_items)} total_pnl={total_pnl:.2f} reason={reason}"
    )
    return jsonify(payload)


@app.route("/manual-sell", methods=["POST"])
def manual_sell():
    body = request.get_json(silent=True) or {}
    symbol = _normalize_symbol(body.get("symbol"))
    action_id = _normalized_action_id(body.get("action_id") or body.get("actionId"))

    if not symbol:
        return _json_error("Missing symbol")

    with STORAGE.transaction(STATE_DIR, timeout=12.0):
        cached = _get_cached_manual_action("manual_sell", action_id)
        if cached is not None:
            _write_audit_event(
                "manual_sell",
                new={"symbol": symbol, "action_id": action_id},
                result={
                    "price": cached.get("price"),
                    "size": cached.get("size"),
                    "pnl": cached.get("pnl"),
                    "balance": cached.get("balance"),
                    "idempotent_replay": True,
                },
            )
            return jsonify(cached)

        paper_state = STORAGE.read(PAPER_STATE_PATH, default={})
        strategy_state = STORAGE.read(STRATEGY_STATE_PATH, default={})
        trades = STORAGE.read(TRADES_PATH, default=[])

        if not isinstance(paper_state, dict):
            paper_state = {}
        if not isinstance(strategy_state, dict):
            strategy_state = {}
        if not isinstance(trades, list):
            trades = []

        positions = paper_state.get("positions", {})
        if not isinstance(positions, dict):
            positions = {}

        position = positions.get(symbol)
        if not isinstance(position, dict):
            return _json_error(f"No open position for {symbol}", status=404, code="not_found")

        try:
            entry_price = float(position.get("price", 0))
            size = float(position.get("size", 0))
        except (TypeError, ValueError):
            return _json_error(
                f"Invalid position data for {symbol}",
                status=422,
                code="invalid_position",
            )

        if entry_price <= 0 or size <= 0:
            return _json_error(
                f"Invalid position data for {symbol}",
                status=422,
                code="invalid_position",
            )

        market_price = _read_latest_snapshot_price(symbol)
        sell_price = market_price if market_price and market_price > 0 else entry_price
        if sell_price <= 0:
            return _json_error(
                f"Unable to determine sell price for {symbol}",
                status=422,
                code="price_unavailable",
            )

        try:
            previous_balance = float(paper_state.get("balance", 0))
        except (TypeError, ValueError):
            previous_balance = 0.0

        pnl = (sell_price - entry_price) * size
        proceeds = sell_price * size
        next_balance = previous_balance + proceeds

        positions.pop(symbol, None)
        paper_state["positions"] = positions
        paper_state["balance"] = next_balance

        strategy_state = _remove_strategy_symbol(strategy_state, symbol)

        trade_entry = {
            "time": time.time(),
            "symbol": symbol,
            "side": "SELL",
            "price": sell_price,
            "size": size,
            "pnl": pnl,
            "balance": next_balance,
            "reason": "manual_user_sell",
        }
        trades.append(trade_entry)

        STORAGE.write(PAPER_STATE_PATH, paper_state)
        STORAGE.write(STRATEGY_STATE_PATH, strategy_state)
        STORAGE.write(TRADES_PATH, trades)

    payload = {
        "status": "ok",
        "symbol": symbol,
        "price": sell_price,
        "size": size,
        "pnl": pnl,
        "balance": next_balance,
        "reason": trade_entry["reason"],
    }
    _store_cached_manual_action("manual_sell", action_id, payload)
    _write_audit_event(
        "manual_sell",
        new={"symbol": symbol, "action_id": action_id},
        result={
            "price": payload.get("price"),
            "size": payload.get("size"),
            "pnl": payload.get("pnl"),
            "balance": payload.get("balance"),
            "idempotent_replay": payload.get("idempotent_replay", False),
        },
    )

    logger.info(
        f"Manual SELL {symbol} @ {sell_price:.6f} size={size:.6f} pnl={pnl:.2f}"
    )

    return jsonify(payload)


def run():
    restart_cause = os.getenv("REVBOT_RESTART_CAUSE", "manual").strip() or "manual"

    try:
        snapshot_path = create_state_snapshot(reason="control_prestart", state_dir=STATE_DIR)
        logger.info(f"Control pre-start snapshot: {snapshot_path}")
    except Exception as exc:
        logger.warning(f"Control pre-start snapshot failed: {exc}")

    try:
        daily_snapshot = ensure_daily_snapshot(
            reason="daily_control_prestart",
            state_dir=STATE_DIR,
        )
        if daily_snapshot is not None:
            logger.info(f"Control daily snapshot created: {daily_snapshot}")
    except Exception as exc:
        logger.warning(f"Control daily snapshot failed: {exc}")

    startup_status = _refresh_startup_status()
    append_runtime_event(
        "process_start",
        service="control",
        restart_cause=restart_cause,
        startup_ok=bool(startup_status.get("ok", False)),
    )
    if not startup_status.get("ok", False):
        logger.error(f"Control startup checks failed: {startup_status}")
        if STRICT_STARTUP:
            raise RuntimeError("Control startup checks failed")

    logger.info(f"Control server starting on {CONTROL_HOST}:{CONTROL_PORT}")
    try:
        app.run(host=CONTROL_HOST, port=CONTROL_PORT, debug=False)
    finally:
        append_runtime_event(
            "process_exit",
            service="control",
            clean_shutdown=True,
        )
