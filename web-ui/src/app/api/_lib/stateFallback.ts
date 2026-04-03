import { promises as fs } from "fs";
import * as fsSync from "node:fs";
import path from "path";

type ConfigState = Record<string, unknown>;
type JsonMap = Record<string, unknown>;

type ManualSellBody = {
  symbol?: unknown;
  actionId?: unknown;
  action_id?: unknown;
};

type ManualStoplossBody = {
  symbol?: unknown;
  enabled?: unknown;
  type?: unknown;
  value?: unknown;
  action?: unknown;
};

type RiskBody = {
  maxConcurrentTrades?: unknown;
  maxConcurrentTradesPerToken?: unknown;
  maxTradeAmountUsd?: unknown;
  tradeAmountUsd?: unknown;
  maxPortfolioExposurePct?: unknown;
  maxExposurePerTokenPct?: unknown;
  dailyLossLimitUsd?: unknown;
  dailyLossAutoPause?: unknown;
  dailyLossCloseAll?: unknown;
  signalConfirmationCycles?: unknown;
  tradeWindowEnabled?: unknown;
  tradeWindowStartHourUtc?: unknown;
  tradeWindowEndHourUtc?: unknown;
};

type SymbolsBody = {
  symbol?: unknown;
  side?: unknown;
  enabled?: unknown;
};

type UniverseTrackBody = {
  symbol?: unknown;
  tracked?: unknown;
};

type ScalperBody = {
  symbol?: unknown;
  enabled?: unknown;
};

type TokenRegimeBody = {
  symbol?: unknown;
  regime?: unknown;
};

type CooldownBody = {
  symbol?: unknown;
  cooldownSeconds?: unknown;
};

type CloseAllBody = {
  reason?: unknown;
  actionId?: unknown;
  action_id?: unknown;
};

const LEGACY_STATE_DIR_CANDIDATES = [
  path.resolve(process.cwd(), "..", "crypto_bot", "state"),
  path.resolve(process.cwd(), "crypto_bot", "state"),
];
const BOT_DATA_DIR = String(process.env.BOT_DATA_DIR ?? "").trim();
const LEGACY_OVERRIDE_DIR = String(process.env.REVBOT_STATE_DIR ?? "").trim();
const STATE_DIR = LEGACY_OVERRIDE_DIR
  ? path.resolve(LEGACY_OVERRIDE_DIR)
  : BOT_DATA_DIR
    ? path.resolve(BOT_DATA_DIR, "state")
    : path.resolve(process.cwd(), "..", ".runtime", "state");
const READ_FALLBACK_DIRS = LEGACY_OVERRIDE_DIR
  ? []
  : LEGACY_STATE_DIR_CANDIDATES.filter((candidate) => path.resolve(candidate) !== path.resolve(STATE_DIR));

export function resolvePrimaryStateDir(): string {
  return STATE_DIR;
}

export function resolveStateFileCandidates(fileName: string): string[] {
  const normalized = String(fileName ?? "").replace(/^[\\/]+/, "");
  const out = [path.join(STATE_DIR, normalized)];
  for (const fallbackDir of READ_FALLBACK_DIRS) {
    out.push(path.join(fallbackDir, normalized));
  }
  return out;
}
const CONFIG_PATH = path.join(STATE_DIR, "config.json");
const PAPER_STATE_PATH = path.join(STATE_DIR, "paper_state.json");
const STRATEGY_STATE_PATH = path.join(STATE_DIR, "strategy_state.json");
const TRADES_PATH = path.join(STATE_DIR, "trades.json");
const MANUAL_STOPLOSS_PATH = path.join(STATE_DIR, "manual_stoploss.json");
const REVOLUT_ACCOUNT_SNAPSHOT_PATH = path.join(STATE_DIR, "revolut_account_snapshot.json");
const REVOLUT_UNIVERSE_SNAPSHOT_PATH = path.join(STATE_DIR, "revolut_universe_snapshot.json");
const AUDIT_LOG_PATH = path.join(STATE_DIR, "audit_actions.jsonl");
const MANUAL_ACTION_CACHE_PATH = path.join(STATE_DIR, "manual_action_cache.json");
const LOG_PATH = path.join(STATE_DIR, "bot.log");
const STATE_TXN_LOCK_PATH = path.join(STATE_DIR, ".state_txn.lock");
const LOG_TAIL_BYTES = 256 * 1024;
const LOCK_TIMEOUT_MS = 8000;
const LOCK_STALE_MS = 120_000;
const LOCK_POLL_MS = 50;
const MANUAL_ACTION_CACHE_LIMIT = 500;
const TOKEN_REGIME_VALUES = [
  "AUTO",
  "MEAN_REVERSION",
  "TREND_PULLBACK",
  "BREAKOUT_MOMENTUM",
  "OBSERVE_ONLY",
] as const;

const SNAPSHOT_PATTERN =
  /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\|\s+INFO\s+\|\s+SNAPSHOT\s+([A-Z0-9-]+)\s+\|\s+price=([0-9.]+)/;

function resolveReadPath(filePath: string): string {
  if (fsSync.existsSync(filePath)) {
    return filePath;
  }
  const relative = path.relative(STATE_DIR, filePath);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    return filePath;
  }
  for (const fallbackDir of READ_FALLBACK_DIRS) {
    const candidate = path.join(fallbackDir, relative);
    if (fsSync.existsSync(candidate)) {
      return candidate;
    }
  }
  return filePath;
}

async function appendAuditEvent(
  action: string,
  payload: {
    old?: unknown;
    new?: unknown;
    result?: unknown;
    actor?: string;
  },
) {
  const now = new Date();
  const event = {
    time_utc: now.toISOString(),
    day_utc: now.toISOString().slice(0, 10),
    action,
    actor: String(payload.actor ?? "web-ui-fallback"),
    old: payload.old ?? null,
    new: payload.new ?? null,
    result: payload.result ?? null,
  };
  await fs.mkdir(path.dirname(AUDIT_LOG_PATH), { recursive: true });
  await fs.appendFile(
    AUDIT_LOG_PATH,
    `${JSON.stringify(event)}\n`,
    "utf8",
  );
}

export class RouteError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "RouteError";
  }
}

function normalizeSymbol(value: unknown): string {
  if (typeof value !== "string") {
    return "";
  }
  return value.trim().toUpperCase();
}

function normalizeSymbols(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }

  const seen = new Set<string>();
  const output: string[] = [];

  for (const raw of value) {
    const symbol = normalizeSymbol(raw);
    if (!symbol || seen.has(symbol)) {
      continue;
    }
    seen.add(symbol);
    output.push(symbol);
  }

  return output;
}

function parseEnabledMap(value: unknown): Record<string, boolean> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }

  const output: Record<string, boolean> = {};
  for (const [rawSymbol, rawEnabled] of Object.entries(value as JsonMap)) {
    const symbol = normalizeSymbol(rawSymbol);
    if (!symbol) {
      continue;
    }
    output[symbol] = rawEnabled !== false;
  }
  return output;
}

function normalizeStrategyName(value: unknown): "mean_reversion" | "volatility_scalper" {
  const raw = String(value ?? "").trim().toLowerCase();
  if (raw === "volatility_scalper" || raw === "vol_scalper" || raw === "scalper") {
    return "volatility_scalper";
  }
  return "mean_reversion";
}

function normalizeTokenRegime(value: unknown): (typeof TOKEN_REGIME_VALUES)[number] | null {
  if (typeof value !== "string") {
    return null;
  }
  const raw = value.trim().toUpperCase();
  return TOKEN_REGIME_VALUES.includes(raw as (typeof TOKEN_REGIME_VALUES)[number])
    ? raw as (typeof TOKEN_REGIME_VALUES)[number]
    : null;
}

function parseTokenRegimeMap(value: unknown): Record<string, (typeof TOKEN_REGIME_VALUES)[number]> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }

  const output: Record<string, (typeof TOKEN_REGIME_VALUES)[number]> = {};
  for (const [rawSymbol, rawRegime] of Object.entries(value as JsonMap)) {
    const symbol = normalizeSymbol(rawSymbol);
    const regime = normalizeTokenRegime(rawRegime);
    if (!symbol || regime === null) {
      continue;
    }
    output[symbol] = regime;
  }
  return output;
}

function removeStrategySymbolState(state: JsonMap, symbol: string): JsonMap {
  for (const key of [
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
    "last_detection_source",
    "last_detection_timestamp_epoch",
    "last_effective_strategy",
    "last_effective_route",
    "last_route_eval_ts",
    "last_regime_eval_ts",
    "last_fallback_reason",
    "last_non_mr_ready_reason",
    "last_ready_for_non_mr_route",
    "last_auto_fallback_reason",
  ] as const) {
    const section = toObject(state[key]);
    if (Object.keys(section).length > 0 && Object.prototype.hasOwnProperty.call(section, symbol)) {
      delete section[symbol];
      state[key] = section;
    }
  }
  return state;
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function readJson<T>(filePath: string, fallback: T): Promise<T> {
  try {
    const raw = await fs.readFile(resolveReadPath(filePath), "utf8");
    const normalized = raw.replace(/^\uFEFF/, "");
    if (!normalized.trim()) {
      return fallback;
    }
    return JSON.parse(normalized) as T;
  } catch {
    return fallback;
  }
}

async function writeJsonAtomic(filePath: string, value: unknown) {
  const tmpPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  const payload = `${JSON.stringify(value, null, 2)}\n`;

  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(tmpPath, payload, "utf8");
  await fs.rename(tmpPath, filePath);
}

async function withLock<T>(
  lockPath: string,
  work: () => Promise<T>,
  timeoutMs = LOCK_TIMEOUT_MS,
): Promise<T> {
  await fs.mkdir(path.dirname(lockPath), { recursive: true });
  const startedAt = Date.now();

  while (true) {
    try {
      const handle = await fs.open(lockPath, "wx");
      await handle.writeFile(String(process.pid));
      await handle.close();
      break;
    } catch (error: unknown) {
      const code =
        typeof error === "object" && error && "code" in error
          ? String((error as { code?: unknown }).code)
          : "";

      if (code !== "EEXIST") {
        throw error;
      }

      try {
        const stat = await fs.stat(lockPath);
        if (Date.now() - stat.mtimeMs > LOCK_STALE_MS) {
          await fs.unlink(lockPath);
          continue;
        }
      } catch {
        continue;
      }

      if (Date.now() - startedAt > timeoutMs) {
        throw new RouteError(503, "State lock timeout");
      }

      await sleep(LOCK_POLL_MS);
    }
  }

  try {
    return await work();
  } finally {
    await fs.unlink(lockPath).catch(() => undefined);
  }
}

async function withFileLock<T>(
  targetPath: string,
  work: () => Promise<T>,
): Promise<T> {
  return withLock(`${targetPath}.lock`, work);
}

async function withStateTransaction<T>(work: () => Promise<T>): Promise<T> {
  return withLock(STATE_TXN_LOCK_PATH, work, 12_000);
}

function toObject(value: unknown): JsonMap {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return value as JsonMap;
}

function asFiniteNumber(value: unknown): number | null {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function normalizeStoplossType(value: unknown): "pct" | "price" {
  const raw = String(value ?? "").trim().toLowerCase();
  return raw === "price" ? "price" : "pct";
}

function sanitizeManualStoplossMap(value: unknown): Record<string, JsonMap> {
  const map = toObject(value);
  const output: Record<string, JsonMap> = {};
  for (const [rawSymbol, rawRule] of Object.entries(map)) {
    const symbol = normalizeSymbol(rawSymbol);
    const rule = toObject(rawRule);
    if (!symbol || Object.keys(rule).length === 0) {
      continue;
    }
    const enabled = rule.enabled === true;
    const type = normalizeStoplossType(rule.type);
    const numericValue = asFiniteNumber(rule.value);
    const valueNumber = (
      numericValue !== null
      && Number.isFinite(numericValue)
      && numericValue > 0
    )
      ? numericValue
      : null;
    output[symbol] = {
      enabled: enabled && valueNumber !== null,
      type,
      value: valueNumber,
      updated_at: asFiniteNumber(rule.updated_at) ?? Date.now() / 1000,
      trigger_price: asFiniteNumber(rule.trigger_price),
      last_trigger_at: asFiniteNumber(rule.last_trigger_at),
      last_trigger_price: asFiniteNumber(rule.last_trigger_price),
    };
  }
  return output;
}

function normalizeActionId(value: unknown): string {
  if (typeof value !== "string") {
    return "";
  }
  return value.trim();
}

async function readManualActionCache(): Promise<JsonMap> {
  return toObject(await readJson<JsonMap>(MANUAL_ACTION_CACHE_PATH, {}));
}

async function writeManualActionCache(cache: JsonMap) {
  await writeJsonAtomic(MANUAL_ACTION_CACHE_PATH, cache);
}

async function getCachedManualAction(
  actionName: "manual_sell" | "close_all",
  actionId: string,
): Promise<JsonMap | null> {
  if (!actionId) {
    return null;
  }
  const cache = await readManualActionCache();
  const key = `${actionName}:${actionId}`;
  const payload = toObject(cache[key]);
  if (Object.keys(payload).length === 0) {
    return null;
  }
  return {
    ...payload,
    idempotent_replay: true,
  };
}

async function storeManualAction(
  actionName: "manual_sell" | "close_all",
  actionId: string,
  payload: JsonMap,
) {
  if (!actionId) {
    return;
  }
  const cache = await readManualActionCache();
  const key = `${actionName}:${actionId}`;
  cache[key] = payload;

  const keys = Object.keys(cache);
  if (keys.length > MANUAL_ACTION_CACHE_LIMIT) {
    const removeCount = keys.length - MANUAL_ACTION_CACHE_LIMIT;
    for (const staleKey of keys.slice(0, removeCount)) {
      delete cache[staleKey];
    }
  }

  await writeManualActionCache(cache);
}

function parseAction(value: unknown): "START" | "STOP" | "KILL" {
  const action = String(value ?? "").trim().toUpperCase();
  if (action === "START" || action === "STOP" || action === "KILL") {
    return action;
  }
  throw new RouteError(400, `Unknown action: ${action || "empty"}`);
}

export function shouldUseLocalFallback(status: number): boolean {
  return status >= 500 || status === 404 || status === 405;
}

export function formatRouteError(error: unknown) {
  if (error instanceof RouteError) {
    return { status: error.status, payload: { error: error.message } };
  }

  const message = error instanceof Error ? error.message : "Unknown error";
  return { status: 500, payload: { error: message } };
}

export async function readRevolutAccountLocal() {
  const snapshot = toObject(await readJson<JsonMap>(REVOLUT_ACCOUNT_SNAPSHOT_PATH, {}));
  if (Object.keys(snapshot).length === 0) {
    return {
      last_sync_time: null,
      sync_status: "degraded",
      sync_error: "backend_unavailable_and_no_local_account_snapshot",
      assets: [],
      asset_count: 0,
      estimated_total_quote_value: 0,
      fallback: true,
    };
  }
  return {
    ...snapshot,
    fallback: true,
  };
}

export async function readRevolutUniverseLocal() {
  const snapshot = toObject(await readJson<JsonMap>(REVOLUT_UNIVERSE_SNAPSHOT_PATH, {}));
  if (Object.keys(snapshot).length === 0) {
    return {
      generated_at: null,
      sync_status: "degraded",
      sync_error: "backend_unavailable_and_no_local_universe_snapshot",
      rows: [],
      summary: {
        total_symbols: 0,
        eligible_count: 0,
        tracked_count: 0,
        ineligible_count: 0,
        top_score: 0,
      },
      fallback: true,
    };
  }
  return {
    ...snapshot,
    fallback: true,
  };
}

async function readLatestSnapshotPrice(symbol: string): Promise<number | null> {
  try {
    const handle = await fs.open(resolveReadPath(LOG_PATH), "r");
    try {
      const stat = await handle.stat();
      const bytesToRead = Math.min(LOG_TAIL_BYTES, stat.size);
      if (bytesToRead <= 0) {
        return null;
      }

      const buffer = Buffer.alloc(bytesToRead);
      await handle.read(buffer, 0, bytesToRead, stat.size - bytesToRead);
      const tail = buffer.toString("utf8");
      const lines = tail.split(/\r?\n/);

      for (let index = lines.length - 1; index >= 0; index -= 1) {
        const match = lines[index].match(SNAPSHOT_PATTERN);
        if (!match || match[2] !== symbol) {
          continue;
        }

        const value = Number(match[3]);
        return Number.isFinite(value) && value > 0 ? value : null;
      }

      return null;
    } finally {
      await handle.close();
    }
  } catch {
    return null;
  }
}

export async function applyControlLocal(body: {
  action?: unknown;
  reason?: unknown;
}) {
  const action = parseAction(body.action);
  const reason = typeof body.reason === "string" ? body.reason.trim() : "";

  return withFileLock(CONFIG_PATH, async () => {
    const cfg = toObject(await readJson<ConfigState>(CONFIG_PATH, {}));

    if (action === "START") {
      cfg.enabled = true;
      cfg.trading_enabled = true;
      cfg.emergency_stop = false;
      delete cfg.emergency_stop_at;
      delete cfg.emergency_stop_reason;
    } else if (action === "STOP") {
      cfg.enabled = true;
      cfg.trading_enabled = false;
      cfg.emergency_stop = false;
    } else {
      cfg.enabled = false;
      cfg.trading_enabled = false;
      cfg.emergency_stop = true;
      cfg.emergency_stop_at = Date.now() / 1000;
      cfg.emergency_stop_reason = reason || "manual_kill";
    }

    await writeJsonAtomic(CONFIG_PATH, cfg);
    const payload = {
      action,
      enabled: Boolean(cfg.enabled),
      trading_enabled: Boolean(cfg.trading_enabled),
      emergency_stop: Boolean(cfg.emergency_stop),
      fallback: true,
    };
    await appendAuditEvent("control_action_fallback", {
      new: { action, reason },
      result: payload,
    });
    return payload;
  });
}

export async function updateUniverseTrackLocal(body: UniverseTrackBody) {
  const symbol = normalizeSymbol(body.symbol);
  if (!symbol) {
    throw new RouteError(400, "Missing symbol");
  }
  if (typeof body.tracked !== "boolean") {
    throw new RouteError(400, "tracked must be a boolean");
  }
  const tracked = body.tracked;

  return withStateTransaction(async () => {
    const cfg = toObject(await readJson<ConfigState>(CONFIG_PATH, {}));
    const paperState = toObject(await readJson<JsonMap>(PAPER_STATE_PATH, {}));
    const positions = toObject(paperState.positions);
    const openPosition = toObject(positions[symbol]);
    const openPositionSize = asFiniteNumber(openPosition.size) ?? 0;
    if (!tracked && openPositionSize > 0) {
      throw new RouteError(409, `Cannot remove ${symbol} while an open position exists`);
    }

    let symbols = normalizeSymbols(cfg.symbols);
    const buyMap = parseEnabledMap(cfg.symbol_buy_enabled);
    const sellMap = parseEnabledMap(cfg.symbol_sell_enabled);
    const legacyMap = parseEnabledMap(cfg.symbol_enabled);
    const tokenRegimes = parseTokenRegimeMap(cfg.token_regimes);
    const symbolStrategies = toObject(cfg.symbol_strategies);
    const strategyOverrides = toObject(cfg.strategy_overrides);
    const risk = toObject(cfg.risk);
    const symbolCooldownSeconds = toObject(risk.symbol_cooldown_seconds);

    if (tracked) {
      if (!symbols.includes(symbol)) {
        symbols.push(symbol);
      }
      buyMap[symbol] = true;
      sellMap[symbol] = true;
      legacyMap[symbol] = true;
    } else {
      symbols = symbols.filter((value) => value !== symbol);
      delete buyMap[symbol];
      delete sellMap[symbol];
      delete legacyMap[symbol];
      delete tokenRegimes[symbol];
      delete symbolStrategies[symbol];
      delete strategyOverrides[symbol];
      delete symbolCooldownSeconds[symbol];
    }

    cfg.symbols = symbols;
    cfg.symbol_buy_enabled = buyMap;
    cfg.symbol_sell_enabled = sellMap;
    cfg.symbol_enabled = legacyMap;
    cfg.token_regimes = tokenRegimes;
    cfg.symbol_strategies = symbolStrategies;
    cfg.strategy_overrides = strategyOverrides;
    risk.symbol_cooldown_seconds = symbolCooldownSeconds;
    cfg.risk = risk;
    await writeJsonAtomic(CONFIG_PATH, cfg);
    if (!tracked) {
      const strategyState = toObject(await readJson<JsonMap>(STRATEGY_STATE_PATH, {}));
      await writeJsonAtomic(STRATEGY_STATE_PATH, removeStrategySymbolState(strategyState, symbol));
    }

    const payload = {
      symbol,
      tracked,
      symbols,
      symbol_buy_enabled: buyMap,
      symbol_sell_enabled: sellMap,
      symbol_enabled: legacyMap,
      fallback: true,
    };
    await appendAuditEvent("universe_track_update_fallback", {
      new: { symbol, tracked },
      result: payload,
    });
    return payload;
  });
}

export async function updateSymbolsLocal(body: SymbolsBody) {
  const symbol = normalizeSymbol(body.symbol);
  if (!symbol) {
    throw new RouteError(400, "Missing symbol");
  }

  if (typeof body.enabled !== "boolean") {
    throw new RouteError(400, "enabled must be a boolean");
  }
  const enabled = body.enabled;

  let side: "buy" | "sell" | null = null;
  if (body.side !== undefined) {
    if (typeof body.side !== "string") {
      throw new RouteError(400, "side must be buy, sell, or omitted");
    }
    const normalized = body.side.trim().toLowerCase();
    if (normalized !== "buy" && normalized !== "sell") {
      throw new RouteError(400, "side must be buy, sell, or omitted");
    }
    side = normalized;
  }

  return withFileLock(CONFIG_PATH, async () => {
    const cfg = toObject(await readJson<ConfigState>(CONFIG_PATH, {}));
    const symbols = normalizeSymbols(cfg.symbols);
    if (!symbols.includes(symbol)) {
      symbols.push(symbol);
    }

    const legacyMap = parseEnabledMap(cfg.symbol_enabled);
    const buyMap = parseEnabledMap(cfg.symbol_buy_enabled);
    const sellMap = parseEnabledMap(cfg.symbol_sell_enabled);

    if (side === "buy") {
      buyMap[symbol] = enabled;
    } else if (side === "sell") {
      sellMap[symbol] = enabled;
    } else {
      buyMap[symbol] = enabled;
      sellMap[symbol] = enabled;
      legacyMap[symbol] = enabled;
    }

    cfg.symbols = symbols;
    cfg.symbol_enabled = legacyMap;
    cfg.symbol_buy_enabled = buyMap;
    cfg.symbol_sell_enabled = sellMap;
    await writeJsonAtomic(CONFIG_PATH, cfg);

    const payload = {
      symbol,
      side,
      enabled,
      symbols,
      symbol_buy_enabled: buyMap,
      symbol_sell_enabled: sellMap,
      symbol_enabled: legacyMap,
      fallback: true,
    };
    await appendAuditEvent("symbols_update_fallback", {
      new: { symbol, side, enabled },
      result: payload,
    });
    return payload;
  });
}

export async function updateScalperLocal(body: ScalperBody) {
  const symbol = normalizeSymbol(body.symbol);
  if (!symbol) {
    throw new RouteError(400, "Missing symbol");
  }

  if (typeof body.enabled !== "boolean") {
    throw new RouteError(400, "enabled must be a boolean");
  }
  const enabled = body.enabled;

  return withFileLock(CONFIG_PATH, async () => {
    const cfg = toObject(await readJson<ConfigState>(CONFIG_PATH, {}));
    const symbols = normalizeSymbols(cfg.symbols);
    if (!symbols.includes(symbol)) {
      symbols.push(symbol);
    }

    const symbolStrategies = toObject(cfg.symbol_strategies);
    symbolStrategies[symbol] = enabled ? "volatility_scalper" : "mean_reversion";

    const volatilityScalper = toObject(cfg.volatility_scalper);
    const scalperSymbols = normalizeSymbols(volatilityScalper.symbols);
    if (enabled) {
      if (!scalperSymbols.includes(symbol)) {
        scalperSymbols.push(symbol);
      }
    } else {
      volatilityScalper.symbols = scalperSymbols.filter((item) => item !== symbol);
    }
    if (enabled) {
      volatilityScalper.symbols = scalperSymbols;
    }

    cfg.symbols = symbols;
    cfg.symbol_strategies = symbolStrategies;
    cfg.volatility_scalper = volatilityScalper;
    await writeJsonAtomic(CONFIG_PATH, cfg);

    const payload = {
      symbol,
      enabled,
      strategy: normalizeStrategyName(symbolStrategies[symbol]),
      symbol_strategies: symbolStrategies,
      volatility_scalper: volatilityScalper,
      fallback: true,
    };
    await appendAuditEvent("scalper_update_fallback", {
      new: { symbol, enabled },
      result: payload,
    });
    return payload;
  });
}

export async function updateTokenRegimeLocal(body: TokenRegimeBody) {
  const symbol = normalizeSymbol(body.symbol);
  if (!symbol) {
    throw new RouteError(400, "Missing symbol");
  }

  const regime = normalizeTokenRegime(body.regime);
  if (regime === null) {
    throw new RouteError(
      400,
      `regime must be one of: ${TOKEN_REGIME_VALUES.join(", ")}`,
    );
  }

  return withFileLock(CONFIG_PATH, async () => {
    const cfg = toObject(await readJson<ConfigState>(CONFIG_PATH, {}));
    const symbols = normalizeSymbols(cfg.symbols);
    if (!symbols.includes(symbol)) {
      symbols.push(symbol);
    }

    const tokenRegimes = parseTokenRegimeMap(cfg.token_regimes);
    tokenRegimes[symbol] = regime;

    cfg.symbols = symbols;
    cfg.token_regimes = tokenRegimes;
    await writeJsonAtomic(CONFIG_PATH, cfg);

    const payload = {
      symbol,
      configured_regime: regime,
      token_regimes: tokenRegimes,
      fallback: true,
    };
    await appendAuditEvent("token_regime_update_fallback", {
      new: { symbol, configured_regime: regime },
      result: payload,
    });
    return payload;
  });
}

export async function updateRiskLocal(body: RiskBody) {
  if (
    body.maxConcurrentTrades === undefined &&
    body.maxConcurrentTradesPerToken === undefined &&
    body.maxTradeAmountUsd === undefined &&
    body.tradeAmountUsd === undefined &&
    body.maxPortfolioExposurePct === undefined &&
    body.maxExposurePerTokenPct === undefined &&
    body.dailyLossLimitUsd === undefined &&
    body.dailyLossAutoPause === undefined &&
    body.dailyLossCloseAll === undefined &&
    body.signalConfirmationCycles === undefined &&
    body.tradeWindowEnabled === undefined &&
    body.tradeWindowStartHourUtc === undefined &&
    body.tradeWindowEndHourUtc === undefined
  ) {
    throw new RouteError(400, "No risk values provided");
  }

  let maxConcurrentTrades: number | null = null;
  if (body.maxConcurrentTrades !== undefined) {
    const value = asFiniteNumber(body.maxConcurrentTrades);
    if (value === null) {
      throw new RouteError(400, "maxConcurrentTrades must be a number");
    }
    maxConcurrentTrades = Math.max(1, Math.floor(value));
  }

  let tradeAmountUsd: number | null = null;
  if (body.tradeAmountUsd !== undefined) {
    const value = asFiniteNumber(body.tradeAmountUsd);
    if (value === null) {
      throw new RouteError(400, "tradeAmountUsd must be a number");
    }
    tradeAmountUsd = Math.max(1, value);
  }

  let maxConcurrentTradesPerToken: number | null = null;
  if (body.maxConcurrentTradesPerToken !== undefined) {
    const value = asFiniteNumber(body.maxConcurrentTradesPerToken);
    if (value === null) {
      throw new RouteError(400, "maxConcurrentTradesPerToken must be a number");
    }
    maxConcurrentTradesPerToken = Math.max(1, Math.floor(value));
  }

  let maxTradeAmountUsd: number | null = null;
  if (body.maxTradeAmountUsd !== undefined) {
    const value = asFiniteNumber(body.maxTradeAmountUsd);
    if (value === null) {
      throw new RouteError(400, "maxTradeAmountUsd must be a number");
    }
    maxTradeAmountUsd = Math.max(1, value);
  }

  let maxPortfolioExposurePct: number | null = null;
  if (body.maxPortfolioExposurePct !== undefined) {
    const value = asFiniteNumber(body.maxPortfolioExposurePct);
    if (value === null) {
      throw new RouteError(400, "maxPortfolioExposurePct must be a number");
    }
    maxPortfolioExposurePct = Math.max(1, Math.min(100, value));
  }

  let maxExposurePerTokenPct: number | null = null;
  if (body.maxExposurePerTokenPct !== undefined) {
    const value = asFiniteNumber(body.maxExposurePerTokenPct);
    if (value === null) {
      throw new RouteError(400, "maxExposurePerTokenPct must be a number");
    }
    maxExposurePerTokenPct = Math.max(1, Math.min(100, value));
  }

  let dailyLossLimitUsd: number | null = null;
  if (body.dailyLossLimitUsd !== undefined) {
    const value = asFiniteNumber(body.dailyLossLimitUsd);
    if (value === null) {
      throw new RouteError(400, "dailyLossLimitUsd must be a number");
    }
    dailyLossLimitUsd = Math.max(0, value);
  }

  let dailyLossAutoPause: boolean | null = null;
  if (body.dailyLossAutoPause !== undefined) {
    if (typeof body.dailyLossAutoPause !== "boolean") {
      throw new RouteError(400, "dailyLossAutoPause must be a boolean");
    }
    dailyLossAutoPause = body.dailyLossAutoPause;
  }

  let dailyLossCloseAll: boolean | null = null;
  if (body.dailyLossCloseAll !== undefined) {
    if (typeof body.dailyLossCloseAll !== "boolean") {
      throw new RouteError(400, "dailyLossCloseAll must be a boolean");
    }
    dailyLossCloseAll = body.dailyLossCloseAll;
  }

  let signalConfirmationCycles: number | null = null;
  if (body.signalConfirmationCycles !== undefined) {
    const value = asFiniteNumber(body.signalConfirmationCycles);
    if (value === null) {
      throw new RouteError(400, "signalConfirmationCycles must be a number");
    }
    signalConfirmationCycles = Math.max(1, Math.floor(value));
  }

  let tradeWindowEnabled: boolean | null = null;
  if (body.tradeWindowEnabled !== undefined) {
    if (typeof body.tradeWindowEnabled !== "boolean") {
      throw new RouteError(400, "tradeWindowEnabled must be a boolean");
    }
    tradeWindowEnabled = body.tradeWindowEnabled;
  }

  let tradeWindowStartHourUtc: number | null = null;
  if (body.tradeWindowStartHourUtc !== undefined) {
    const value = asFiniteNumber(body.tradeWindowStartHourUtc);
    if (value === null) {
      throw new RouteError(400, "tradeWindowStartHourUtc must be a number");
    }
    const hour = Math.floor(value);
    if (hour < 0 || hour > 23) {
      throw new RouteError(400, "tradeWindowStartHourUtc must be between 0 and 23");
    }
    tradeWindowStartHourUtc = hour;
  }

  let tradeWindowEndHourUtc: number | null = null;
  if (body.tradeWindowEndHourUtc !== undefined) {
    const value = asFiniteNumber(body.tradeWindowEndHourUtc);
    if (value === null) {
      throw new RouteError(400, "tradeWindowEndHourUtc must be a number");
    }
    const hour = Math.floor(value);
    if (hour < 0 || hour > 23) {
      throw new RouteError(400, "tradeWindowEndHourUtc must be between 0 and 23");
    }
    tradeWindowEndHourUtc = hour;
  }

  return withFileLock(CONFIG_PATH, async () => {
    const cfg = toObject(await readJson<ConfigState>(CONFIG_PATH, {}));
    const risk = toObject(cfg.risk);

    if (maxConcurrentTrades !== null) {
      risk.max_concurrent_trades = maxConcurrentTrades;
    }
    if (maxConcurrentTradesPerToken !== null) {
      risk.max_concurrent_trades_per_token = maxConcurrentTradesPerToken;
    }
    if (maxTradeAmountUsd !== null) {
      risk.max_trade_amount_usd = maxTradeAmountUsd;
    }
    if (tradeAmountUsd !== null) {
      risk.trade_amount_usd = tradeAmountUsd;
    }
    if (maxPortfolioExposurePct !== null) {
      risk.max_portfolio_exposure_pct = maxPortfolioExposurePct;
    }
    if (maxExposurePerTokenPct !== null) {
      risk.max_exposure_per_token_pct = maxExposurePerTokenPct;
    }
    if (dailyLossLimitUsd !== null) {
      risk.daily_loss_limit_usd = dailyLossLimitUsd;
    }
    if (dailyLossAutoPause !== null) {
      risk.daily_loss_auto_pause = dailyLossAutoPause;
    }
    if (dailyLossCloseAll !== null) {
      risk.daily_loss_close_all = dailyLossCloseAll;
    }
    if (signalConfirmationCycles !== null) {
      risk.signal_confirmation_cycles = signalConfirmationCycles;
    }

    const tradeWindow = toObject(risk.trade_window_utc);
    if (tradeWindowEnabled !== null) {
      tradeWindow.enabled = tradeWindowEnabled;
    }
    if (tradeWindowStartHourUtc !== null) {
      tradeWindow.start_hour_utc = tradeWindowStartHourUtc;
    }
    if (tradeWindowEndHourUtc !== null) {
      tradeWindow.end_hour_utc = tradeWindowEndHourUtc;
    }
    if (Object.keys(tradeWindow).length > 0) {
      risk.trade_window_utc = tradeWindow;
    }

    cfg.risk = risk;
    await writeJsonAtomic(CONFIG_PATH, cfg);

    const payload = {
      risk,
      maxConcurrentTrades: risk.max_concurrent_trades,
      maxConcurrentTradesPerToken: risk.max_concurrent_trades_per_token,
      maxTradeAmountUsd: risk.max_trade_amount_usd,
      tradeAmountUsd: risk.trade_amount_usd,
      maxPortfolioExposurePct: risk.max_portfolio_exposure_pct,
      maxExposurePerTokenPct: risk.max_exposure_per_token_pct,
      dailyLossLimitUsd: risk.daily_loss_limit_usd,
      dailyLossAutoPause: risk.daily_loss_auto_pause,
      dailyLossCloseAll: risk.daily_loss_close_all,
      signalConfirmationCycles: risk.signal_confirmation_cycles,
      tradeWindowUtc: risk.trade_window_utc,
      fallback: true,
    };
    await appendAuditEvent("risk_update_fallback", {
      new: body,
      result: payload,
    });
    return payload;
  });
}

export async function updateCooldownLocal(body: CooldownBody) {
  const symbol = normalizeSymbol(body.symbol);
  if (!symbol) {
    throw new RouteError(400, "Missing symbol");
  }

  let cooldownSeconds: number | null = null;
  if (body.cooldownSeconds !== undefined && body.cooldownSeconds !== null) {
    const value = asFiniteNumber(body.cooldownSeconds);
    if (value === null) {
      throw new RouteError(400, "cooldownSeconds must be a number");
    }
    cooldownSeconds = Math.max(1, value);
  }

  return withFileLock(CONFIG_PATH, async () => {
    const cfg = toObject(await readJson<ConfigState>(CONFIG_PATH, {}));
    const symbols = normalizeSymbols(cfg.symbols);
    if (!symbols.includes(symbol)) {
      symbols.push(symbol);
    }

    const risk = toObject(cfg.risk);
    const symbolCooldown = toObject(risk.symbol_cooldown_seconds);

    if (cooldownSeconds === null) {
      delete symbolCooldown[symbol];
    } else {
      symbolCooldown[symbol] = cooldownSeconds;
    }

    risk.symbol_cooldown_seconds = symbolCooldown;
    cfg.symbols = symbols;
    cfg.risk = risk;
    await writeJsonAtomic(CONFIG_PATH, cfg);

    const payload = {
      symbol,
      cooldownSeconds: symbolCooldown[symbol] ?? null,
      symbolCooldownSeconds: symbolCooldown,
      fallback: true,
    };
    await appendAuditEvent("cooldown_update_fallback", {
      new: { symbol, cooldownSeconds },
      result: payload,
    });
    return payload;
  });
}

export async function closeAllLocal(body: CloseAllBody) {
  const rawReason = String(body.reason ?? "").trim();
  const reason = rawReason || "manual_close_all";
  const actionId = normalizeActionId(body.action_id ?? body.actionId);

  return withStateTransaction(async () => {
    const cached = await getCachedManualAction("close_all", actionId);
    if (cached) {
      await appendAuditEvent("close_all_fallback", {
        new: { reason, actionId },
        result: cached,
      });
      return cached;
    }

    const paperState = toObject(await readJson<JsonMap>(PAPER_STATE_PATH, {}));
    const strategyState = toObject(
      await readJson<JsonMap>(STRATEGY_STATE_PATH, {}),
    );
    const tradesRaw = await readJson<unknown>(TRADES_PATH, []);
    const trades = Array.isArray(tradesRaw) ? tradesRaw.slice() : [];

    const positions = toObject(paperState.positions);
    const symbols = Object.keys(positions);
    if (symbols.length === 0) {
      const payload = {
        status: "ok",
        closedCount: 0,
        totalPnl: 0,
        balance: asFiniteNumber(paperState.balance) ?? 0,
        reason,
        fallback: true,
      };
      await storeManualAction("close_all", actionId, payload);
      await appendAuditEvent("close_all_fallback", {
        new: { reason, actionId },
        result: payload,
      });
      return payload;
    }

    let balance = asFiniteNumber(paperState.balance) ?? 0;
    let totalPnl = 0;
    const closed: Array<{
      symbol: string;
      price: number;
      size: number;
      pnl: number;
    }> = [];

    for (const symbol of symbols) {
      const position = toObject(positions[symbol]);
      const entryPrice = asFiniteNumber(position.price);
      const size = asFiniteNumber(position.size);
      if (!entryPrice || entryPrice <= 0 || !size || size <= 0) {
        continue;
      }

      const marketPrice = await readLatestSnapshotPrice(symbol);
      const sellPrice = marketPrice && marketPrice > 0 ? marketPrice : entryPrice;
      const pnl = (sellPrice - entryPrice) * size;
      const proceeds = sellPrice * size;
      balance += proceeds;
      totalPnl += pnl;

      delete positions[symbol];

      for (const key of [
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
      ]) {
        const section = toObject(strategyState[key]);
        delete section[symbol];
        strategyState[key] = section;
      }

      trades.push({
        time: Date.now() / 1000,
        symbol,
        side: "SELL",
        price: sellPrice,
        size,
        pnl,
        balance,
        reason,
      });

      closed.push({
        symbol,
        price: sellPrice,
        size,
        pnl,
      });
    }

    paperState.positions = positions;
    paperState.balance = balance;

    await writeJsonAtomic(PAPER_STATE_PATH, paperState);
    await writeJsonAtomic(STRATEGY_STATE_PATH, strategyState);
    await writeJsonAtomic(TRADES_PATH, trades);

    const payload = {
      status: "ok",
      closedCount: closed.length,
      closed,
      totalPnl,
      balance,
      reason,
      fallback: true,
    };
    await storeManualAction("close_all", actionId, payload);
    await appendAuditEvent("close_all_fallback", {
      new: { reason, actionId },
      result: payload,
    });
    return payload;
  });
}

export async function manualSellLocal(body: ManualSellBody) {
  const symbol = normalizeSymbol(body.symbol);
  const actionId = normalizeActionId(body.action_id ?? body.actionId);
  if (!symbol) {
    throw new RouteError(400, "Missing symbol");
  }

  return withStateTransaction(async () => {
    const cached = await getCachedManualAction("manual_sell", actionId);
    if (cached) {
      await appendAuditEvent("manual_sell_fallback", {
        new: { symbol, actionId },
        result: cached,
      });
      return cached;
    }

    const paperState = toObject(await readJson<JsonMap>(PAPER_STATE_PATH, {}));
    const strategyState = toObject(
      await readJson<JsonMap>(STRATEGY_STATE_PATH, {}),
    );
    const tradesRaw = await readJson<unknown>(TRADES_PATH, []);
    const trades = Array.isArray(tradesRaw) ? tradesRaw.slice() : [];

    const positions = toObject(paperState.positions);
    const position = toObject(positions[symbol]);
    if (Object.keys(position).length === 0) {
      throw new RouteError(404, `No open position for ${symbol}`);
    }

    const entryPrice = asFiniteNumber(position.price);
    const size = asFiniteNumber(position.size);
    if (!entryPrice || entryPrice <= 0 || !size || size <= 0) {
      throw new RouteError(422, `Invalid position data for ${symbol}`);
    }

    const marketPrice = await readLatestSnapshotPrice(symbol);
    const sellPrice = marketPrice && marketPrice > 0 ? marketPrice : entryPrice;
    if (!(sellPrice > 0)) {
      throw new RouteError(422, `Unable to determine sell price for ${symbol}`);
    }

    const previousBalance = asFiniteNumber(paperState.balance) ?? 0;
    const pnl = (sellPrice - entryPrice) * size;
    const proceeds = sellPrice * size;
    const nextBalance = previousBalance + proceeds;

    delete positions[symbol];
    paperState.positions = positions;
    paperState.balance = nextBalance;

    for (const key of [
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
    ]) {
      const section = toObject(strategyState[key]);
      delete section[symbol];
      strategyState[key] = section;
    }

    const trade = {
      time: Date.now() / 1000,
      symbol,
      side: "SELL",
      price: sellPrice,
      size,
      pnl,
      balance: nextBalance,
      reason: "manual_user_sell",
    };

    trades.push(trade);

    await writeJsonAtomic(PAPER_STATE_PATH, paperState);
    await writeJsonAtomic(STRATEGY_STATE_PATH, strategyState);
    await writeJsonAtomic(TRADES_PATH, trades);

    const payload = {
      status: "ok",
      symbol,
      price: sellPrice,
      size,
      pnl,
      balance: nextBalance,
      reason: trade.reason,
      fallback: true,
    };
    await storeManualAction("manual_sell", actionId, payload);
    await appendAuditEvent("manual_sell_fallback", {
      new: { symbol, actionId },
      result: payload,
    });
    return payload;
  });
}

export async function readManualStoplossLocal() {
  const raw = await readJson<JsonMap>(MANUAL_STOPLOSS_PATH, {});
  const rules = sanitizeManualStoplossMap(raw);
  const activeCount = Object.values(rules).filter((rule) => rule.enabled === true).length;
  return {
    status: "ok",
    rules,
    activeCount,
    updatedAt: Date.now() / 1000,
    fallback: true,
  };
}

export async function updateManualStoplossLocal(body: ManualStoplossBody) {
  const symbol = normalizeSymbol(body.symbol);
  if (!symbol) {
    throw new RouteError(400, "Missing symbol");
  }

  const enabled = body.enabled === true;
  const type = normalizeStoplossType(body.type);
  const numericValue = asFiniteNumber(body.value);
  const value = enabled && numericValue !== null && numericValue > 0
    ? numericValue
    : null;

  if (enabled && value === null) {
    throw new RouteError(400, "value must be a positive number when enabled");
  }

  return withStateTransaction(async () => {
    const stoplossMap = sanitizeManualStoplossMap(
      await readJson<JsonMap>(MANUAL_STOPLOSS_PATH, {}),
    );
    const previous = toObject(stoplossMap[symbol]);

    const paperState = toObject(await readJson<JsonMap>(PAPER_STATE_PATH, {}));
    const positions = toObject(paperState.positions);
    const position = toObject(positions[symbol]);
    const entryPrice = asFiniteNumber(position.price);

    let triggerPrice: number | null = null;
    if (enabled && value !== null) {
      if (type === "price") {
        triggerPrice = value;
      } else if (entryPrice !== null && entryPrice > 0) {
        triggerPrice = entryPrice * (1 - value / 100);
      }
    }

    stoplossMap[symbol] = {
      enabled,
      type,
      value,
      updated_at: Date.now() / 1000,
      trigger_price: triggerPrice,
      last_trigger_at: asFiniteNumber(previous.last_trigger_at),
      last_trigger_price: asFiniteNumber(previous.last_trigger_price),
    };

    await writeJsonAtomic(MANUAL_STOPLOSS_PATH, stoplossMap);
    await appendAuditEvent("manual_stoploss_update_fallback", {
      old: previous,
      new: {
        symbol,
        enabled,
        type,
        value,
      },
      result: {
        trigger_price: triggerPrice,
      },
    });

    return {
      status: "ok",
      symbol,
      rule: stoplossMap[symbol],
      fallback: true,
    };
  });
}

export async function runManualStoplossCheckLocal() {
  return withStateTransaction(async () => {
    const stoplossMap = sanitizeManualStoplossMap(
      await readJson<JsonMap>(MANUAL_STOPLOSS_PATH, {}),
    );
    const triggered: JsonMap[] = [];
    const skipped: JsonMap[] = [];

    if (Object.keys(stoplossMap).length === 0) {
      return {
        status: "ok",
        triggered,
        skipped,
        checkedAt: Date.now() / 1000,
        fallback: true,
      };
    }

    const paperState = toObject(await readJson<JsonMap>(PAPER_STATE_PATH, {}));
    const strategyState = toObject(await readJson<JsonMap>(STRATEGY_STATE_PATH, {}));
    const tradesRaw = await readJson<unknown>(TRADES_PATH, []);
    const trades = Array.isArray(tradesRaw) ? tradesRaw.slice() : [];

    const positions = toObject(paperState.positions);
    let balance = asFiniteNumber(paperState.balance) ?? 0;
    const nowTs = Date.now() / 1000;

    for (const [symbol, rawRule] of Object.entries(stoplossMap)) {
      const rule = toObject(rawRule);
      if (rule.enabled !== true) {
        continue;
      }

      const position = toObject(positions[symbol]);
      if (Object.keys(position).length === 0) {
        skipped.push({ symbol, reason: "no_open_position" });
        continue;
      }

      const entryPrice = asFiniteNumber(position.price);
      const size = asFiniteNumber(position.size);
      if (
        entryPrice === null
        || entryPrice <= 0
        || size === null
        || size <= 0
      ) {
        skipped.push({ symbol, reason: "invalid_position" });
        continue;
      }

      const type = normalizeStoplossType(rule.type);
      const value = asFiniteNumber(rule.value);
      if (value === null || value <= 0) {
        skipped.push({ symbol, reason: "invalid_rule" });
        continue;
      }

      const triggerPrice = type === "price"
        ? value
        : entryPrice * (1 - value / 100);
      if (!(triggerPrice > 0)) {
        skipped.push({ symbol, reason: "invalid_trigger_price" });
        continue;
      }

      const marketPrice = await readLatestSnapshotPrice(symbol);
      if (marketPrice === null || marketPrice <= 0) {
        skipped.push({ symbol, reason: "price_unavailable" });
        continue;
      }

      if (marketPrice > triggerPrice) {
        continue;
      }

      const pnl = (marketPrice - entryPrice) * size;
      const proceeds = marketPrice * size;
      balance += proceeds;

      delete positions[symbol];
      for (const key of [
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
      ]) {
        const section = toObject(strategyState[key]);
        delete section[symbol];
        strategyState[key] = section;
      }

      trades.push({
        time: nowTs,
        symbol,
        side: "SELL",
        price: marketPrice,
        size,
        pnl,
        balance,
        reason: `manual_user_stoploss_${type}`,
      });

      stoplossMap[symbol] = {
        ...rule,
        enabled: false,
        type,
        value,
        trigger_price: triggerPrice,
        last_trigger_at: nowTs,
        last_trigger_price: marketPrice,
        updated_at: nowTs,
      };

      triggered.push({
        symbol,
        triggerType: type,
        triggerValue: value,
        triggerPrice,
        sellPrice: marketPrice,
        pnl,
      });
    }

    paperState.positions = positions;
    paperState.balance = balance;
    await writeJsonAtomic(PAPER_STATE_PATH, paperState);
    await writeJsonAtomic(STRATEGY_STATE_PATH, strategyState);
    await writeJsonAtomic(TRADES_PATH, trades);
    await writeJsonAtomic(MANUAL_STOPLOSS_PATH, stoplossMap);

    if (triggered.length > 0) {
      await appendAuditEvent("manual_stoploss_trigger_fallback", {
        new: { triggered },
        result: { triggeredCount: triggered.length },
      });
    }

    return {
      status: "ok",
      triggered,
      skipped,
      checkedAt: nowTs,
      fallback: true,
    };
  });
}
