import { promises as fs } from "fs";
import path from "path";

type ConfigState = Record<string, unknown>;
type JsonMap = Record<string, unknown>;

type ManualSellBody = {
  symbol?: unknown;
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

type ScalperBody = {
  symbol?: unknown;
  enabled?: unknown;
};

type CooldownBody = {
  symbol?: unknown;
  cooldownSeconds?: unknown;
};

type CloseAllBody = {
  reason?: unknown;
};

const STATE_DIR = path.resolve(process.cwd(), "..", "crypto_bot", "state");
const CONFIG_PATH = path.join(STATE_DIR, "config.json");
const PAPER_STATE_PATH = path.join(STATE_DIR, "paper_state.json");
const STRATEGY_STATE_PATH = path.join(STATE_DIR, "strategy_state.json");
const TRADES_PATH = path.join(STATE_DIR, "trades.json");
const LOG_PATH = path.join(STATE_DIR, "bot.log");
const STATE_TXN_LOCK_PATH = path.join(STATE_DIR, ".state_txn.lock");
const LOG_TAIL_BYTES = 256 * 1024;
const LOCK_TIMEOUT_MS = 8000;
const LOCK_STALE_MS = 120_000;
const LOCK_POLL_MS = 50;

const SNAPSHOT_PATTERN =
  /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\|\s+INFO\s+\|\s+SNAPSHOT\s+([A-Z0-9-]+)\s+\|\s+price=([0-9.]+)/;

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

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function readJson<T>(filePath: string, fallback: T): Promise<T> {
  try {
    const raw = await fs.readFile(filePath, "utf8");
    if (!raw.trim()) {
      return fallback;
    }
    return JSON.parse(raw) as T;
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

async function readLatestSnapshotPrice(symbol: string): Promise<number | null> {
  try {
    const handle = await fs.open(LOG_PATH, "r");
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
      cfg.emergency_stop = false;
      delete cfg.emergency_stop_at;
      delete cfg.emergency_stop_reason;
    } else if (action === "STOP") {
      cfg.enabled = false;
    } else {
      cfg.enabled = false;
      cfg.emergency_stop = true;
      cfg.emergency_stop_at = Date.now() / 1000;
      cfg.emergency_stop_reason = reason || "manual_kill";
    }

    await writeJsonAtomic(CONFIG_PATH, cfg);

    return {
      action,
      enabled: Boolean(cfg.enabled),
      emergency_stop: Boolean(cfg.emergency_stop),
      fallback: true,
    };
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

    return {
      symbol,
      side,
      enabled,
      symbols,
      symbol_buy_enabled: buyMap,
      symbol_sell_enabled: sellMap,
      symbol_enabled: legacyMap,
      fallback: true,
    };
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

    return {
      symbol,
      enabled,
      strategy: normalizeStrategyName(symbolStrategies[symbol]),
      symbol_strategies: symbolStrategies,
      volatility_scalper: volatilityScalper,
      fallback: true,
    };
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

    return {
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

    return {
      symbol,
      cooldownSeconds: symbolCooldown[symbol] ?? null,
      symbolCooldownSeconds: symbolCooldown,
      fallback: true,
    };
  });
}

export async function closeAllLocal(body: CloseAllBody) {
  const rawReason = String(body.reason ?? "").trim();
  const reason = rawReason || "manual_close_all";

  return withStateTransaction(async () => {
    const paperState = toObject(await readJson<JsonMap>(PAPER_STATE_PATH, {}));
    const strategyState = toObject(
      await readJson<JsonMap>(STRATEGY_STATE_PATH, {}),
    );
    const tradesRaw = await readJson<unknown>(TRADES_PATH, []);
    const trades = Array.isArray(tradesRaw) ? tradesRaw.slice() : [];

    const positions = toObject(paperState.positions);
    const symbols = Object.keys(positions);
    if (symbols.length === 0) {
      return {
        status: "ok",
        closedCount: 0,
        totalPnl: 0,
        balance: asFiniteNumber(paperState.balance) ?? 0,
        reason,
        fallback: true,
      };
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

    return {
      status: "ok",
      closedCount: closed.length,
      closed,
      totalPnl,
      balance,
      reason,
      fallback: true,
    };
  });
}

export async function manualSellLocal(body: ManualSellBody) {
  const symbol = normalizeSymbol(body.symbol);
  if (!symbol) {
    throw new RouteError(400, "Missing symbol");
  }

  return withStateTransaction(async () => {
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

    return {
      status: "ok",
      symbol,
      price: sellPrice,
      size,
      pnl,
      balance: nextBalance,
      reason: trade.reason,
      fallback: true,
    };
  });
}
