import { promises as fs } from "fs";
import path from "path";
import { NextResponse } from "next/server";

type ConfigState = {
  enabled?: boolean;
  execution_mode?: string;
  starting_balance?: number;
  symbols?: string[];
  symbol_enabled?: Record<string, boolean>;
  symbol_buy_enabled?: Record<string, boolean>;
  symbol_sell_enabled?: Record<string, boolean>;
  lookback?: number;
  min_trades?: number;
  loop_sleep?: number;
  risk?: {
    risk_percent?: number;
    max_concurrent_trades?: number;
    trade_amount_usd?: number;
    cooldown_seconds?: number;
  };
  profit_locks?: {
    first_activation?: number;
    trailing_activation?: number;
    trailing_gap?: number;
  };
};

type PaperPosition = {
  price?: number;
  size?: number;
  entry_time?: number;
  reason?: string;
};

type PaperState = {
  balance?: number;
  positions?: Record<string, PaperPosition>;
};

type StrategyState = {
  entry_price?: Record<string, number>;
  profit_lock?: Record<string, number | null>;
  peak_pnl?: Record<string, number>;
  last_signal?: Record<string, string>;
  last_momentum?: Record<string, number>;
};

type TradeEntry = {
  time?: number;
  symbol?: string;
  side?: string;
  price?: number;
  size?: number;
  balance?: number;
  pnl?: number;
  reason?: string;
};

type PositionRow = {
  symbol: string;
  units: number;
  entryPrice: number;
  currentPrice: number | null;
  lockPrice: number | null;
  costBasis: number;
  marketValue: number;
  allocationPct: number;
  unrealizedValue: number;
  unrealizedPct: number;
  peakPnlPct: number;
  profitLockPct: number | null;
  status: string;
  entryTime: number | null;
  thesis: string;
};

type SymbolControl = {
  symbol: string;
  buyEnabled: boolean;
  sellEnabled: boolean;
  hasOpenPosition: boolean;
};

const STATE_DIR = path.resolve(process.cwd(), "..", "crypto_bot", "state");
const CONFIG_PATH = path.join(STATE_DIR, "config.json");
const PAPER_STATE_PATH = path.join(STATE_DIR, "paper_state.json");
const STRATEGY_STATE_PATH = path.join(STATE_DIR, "strategy_state.json");
const TRADES_PATH = path.join(STATE_DIR, "trades.json");
const LOG_PATH = path.join(STATE_DIR, "bot.log");
const LOG_TAIL_BYTES = 256 * 1024;

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

async function readLogTail(filePath: string, bytes: number): Promise<string> {
  let handle:
    | Awaited<ReturnType<typeof fs.open>>
    | undefined;

  try {
    handle = await fs.open(filePath, "r");
    const stat = await handle.stat();
    const bytesToRead = Math.min(bytes, stat.size);

    if (bytesToRead <= 0) {
      return "";
    }

    const buffer = Buffer.alloc(bytesToRead);
    await handle.read(buffer, 0, bytesToRead, stat.size - bytesToRead);
    return buffer.toString("utf8");
  } catch {
    return "";
  } finally {
    await handle?.close();
  }
}

async function readLatestPrices(symbols: string[]) {
  const prices: Record<string, number> = {};
  let lastSnapshotAt: string | null = null;
  const wanted = new Set(symbols);

  if (wanted.size === 0) {
    return { prices, lastSnapshotAt };
  }

  const tail = await readLogTail(LOG_PATH, LOG_TAIL_BYTES);
  const lines = tail.split(/\r?\n/);
  const snapshotPattern =
    /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\|\s+INFO\s+\|\s+SNAPSHOT\s+([A-Z0-9-]+)\s+\|\s+price=([0-9.]+)/;

  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const match = lines[index].match(snapshotPattern);
    if (!match) {
      continue;
    }

    if (!lastSnapshotAt) {
      lastSnapshotAt = match[1];
    }

    const symbol = match[2];
    if (!wanted.has(symbol) || symbol in prices) {
      continue;
    }

    prices[symbol] = Number(match[3]);

    if (Object.keys(prices).length >= wanted.size) {
      break;
    }
  }

  return { prices, lastSnapshotAt };
}

function round(value: number, digits = 2) {
  if (!Number.isFinite(value)) {
    return 0;
  }

  return Number(value.toFixed(digits));
}

function sum(values: number[]) {
  return values.reduce((total, value) => total + value, 0);
}

function normalizeSymbol(value: unknown) {
  if (typeof value !== "string") {
    return "";
  }
  return value.trim().toUpperCase();
}

function normalizeSymbols(values: unknown) {
  if (!Array.isArray(values)) {
    return [];
  }

  const seen = new Set<string>();
  const symbols: string[] = [];

  for (const value of values) {
    const symbol = normalizeSymbol(value);
    if (!symbol || seen.has(symbol)) {
      continue;
    }

    seen.add(symbol);
    symbols.push(symbol);
  }

  return symbols;
}

function parseEnabledMap(values: unknown) {
  if (!values || typeof values !== "object" || Array.isArray(values)) {
    return {};
  }

  const enabled: Record<string, boolean> = {};
  for (const [rawSymbol, rawValue] of Object.entries(
    values as Record<string, unknown>,
  )) {
    const symbol = normalizeSymbol(rawSymbol);
    if (!symbol) {
      continue;
    }
    enabled[symbol] = rawValue !== false;
  }

  return enabled;
}

function uniqueSymbols(...collections: Array<readonly string[]>) {
  const seen = new Set<string>();
  const output: string[] = [];

  for (const collection of collections) {
    for (const rawSymbol of collection) {
      const symbol = normalizeSymbol(rawSymbol);
      if (!symbol || seen.has(symbol)) {
        continue;
      }

      seen.add(symbol);
      output.push(symbol);
    }
  }

  return output;
}

function buildEquityCurve(
  startingBalance: number,
  trades: TradeEntry[],
  currentEquity: number,
) {
  const points: number[] = [];
  const openCostBySymbol = new Map<string, number>();

  points.push(round(startingBalance, 2));

  for (const trade of trades) {
    const symbol = trade.symbol ?? "";
    const cost = Number(trade.price ?? 0) * Number(trade.size ?? 0);
    const cash = Number(trade.balance ?? 0);

    if (trade.side === "BUY") {
      openCostBySymbol.set(symbol, cost);
    } else if (trade.side === "SELL") {
      openCostBySymbol.delete(symbol);
    }

    const deployed = sum(Array.from(openCostBySymbol.values()));
    points.push(round(cash + deployed, 2));
  }

  points.push(round(currentEquity, 2));
  return points.slice(-18);
}

export async function GET() {
  const [config, paper, strategy, trades] = await Promise.all([
    readJson<ConfigState>(CONFIG_PATH, {}),
    readJson<PaperState>(PAPER_STATE_PATH, {}),
    readJson<StrategyState>(STRATEGY_STATE_PATH, {}),
    readJson<TradeEntry[]>(TRADES_PATH, []),
  ]);

  const positions = paper.positions ?? {};
  const positionSymbols = Object.keys(positions);
  const configuredSymbols = normalizeSymbols(config.symbols);
  const legacyMap = parseEnabledMap(config.symbol_enabled);
  const buyMap = parseEnabledMap(config.symbol_buy_enabled);
  const sellMap = parseEnabledMap(config.symbol_sell_enabled);
  const allSymbols = uniqueSymbols(
    configuredSymbols,
    Object.keys(legacyMap),
    Object.keys(buyMap),
    Object.keys(sellMap),
    positionSymbols,
  );

  const symbolControls: SymbolControl[] = allSymbols.map((symbol) => ({
    symbol,
    buyEnabled: buyMap[symbol] ?? legacyMap[symbol] ?? true,
    sellEnabled: sellMap[symbol] ?? legacyMap[symbol] ?? true,
    hasOpenPosition: symbol in positions,
  }));
  const buyEnabledSymbolsCount = symbolControls.filter(
    (control) => control.buyEnabled,
  ).length;
  const sellEnabledSymbolsCount = symbolControls.filter(
    (control) => control.sellEnabled,
  ).length;
  const buyDisabledSymbolsCount = symbolControls.length - buyEnabledSymbolsCount;
  const sellDisabledSymbolsCount =
    symbolControls.length - sellEnabledSymbolsCount;

  const { prices, lastSnapshotAt } = await readLatestPrices(positionSymbols);

  const firstActivation = Number(
    config.profit_locks?.first_activation ?? 0.02,
  );
  const trailingActivation = Number(
    config.profit_locks?.trailing_activation ?? 0.1,
  );
  const trailingGap = Number(config.profit_locks?.trailing_gap ?? 0.02);

  const draftRows = positionSymbols.map((symbol) => {
    const position = positions[symbol] ?? {};
    const entryPrice = Number(
      strategy.entry_price?.[symbol] ?? position.price ?? 0,
    );
    const units = Number(position.size ?? 0);
    const currentPrice = symbol in prices ? prices[symbol] : null;
    const costBasis = entryPrice * units;
    const marketValue = (currentPrice ?? entryPrice) * units;
    const unrealizedValue =
      currentPrice === null ? 0 : (currentPrice - entryPrice) * units;
    const unrealizedPct =
      currentPrice === null || entryPrice <= 0
        ? 0
        : ((currentPrice - entryPrice) / entryPrice) * 100;
    const profitLock = strategy.profit_lock?.[symbol] ?? null;
    const peakPnlPct = Number(strategy.peak_pnl?.[symbol] ?? 0) * 100;

    let status = "Watching";
    if (profitLock !== null) {
      status =
        peakPnlPct >= trailingActivation * 100 ? "Trailing" : "Locked";
    } else if (peakPnlPct >= firstActivation * 100) {
      status = "Arming";
    }

    return {
      symbol,
      units,
      entryPrice,
      currentPrice,
      lockPrice:
        profitLock === null ? null : entryPrice * (1 + profitLock),
      costBasis,
      marketValue,
      unrealizedValue,
      unrealizedPct,
      peakPnlPct,
      profitLockPct:
        profitLock === null ? null : Number(profitLock) * 100,
      status,
      entryTime: position.entry_time ?? null,
      thesis: position.reason ?? "state_sync",
    };
  });

  const openValue = sum(draftRows.map((row) => row.marketValue));
  const positionRows: PositionRow[] = draftRows
    .map((row) => ({
      ...row,
      allocationPct:
        openValue <= 0 ? 0 : (row.marketValue / openValue) * 100,
    }))
    .sort((left, right) => right.marketValue - left.marketValue);

  const cashBalance = Number(paper.balance ?? 0);
  const investedCapital = sum(positionRows.map((row) => row.costBasis));
  const unrealizedPnl = sum(positionRows.map((row) => row.unrealizedValue));
  const realizedPnl = sum(
    trades.map((trade) => Number(trade.pnl ?? 0)),
  );
  const startingBalance = Number(config.starting_balance ?? 10000);
  const riskPercent = Number(config.risk?.risk_percent ?? 0.02);
  const defaultTradeAmount = startingBalance * riskPercent;
  const tradeAmountUsd = Number(
    config.risk?.trade_amount_usd ?? defaultTradeAmount,
  );
  const maxConcurrentTrades = Number(
    config.risk?.max_concurrent_trades ?? 1,
  );
  const totalEquity = cashBalance + openValue;
  const netPnl = realizedPnl + unrealizedPnl;
  const netReturnPct =
    startingBalance <= 0
      ? 0
      : ((totalEquity - startingBalance) / startingBalance) * 100;
  const sortedTrades = [...trades].sort(
    (left, right) => Number(left.time ?? 0) - Number(right.time ?? 0),
  );
  const lastTrade = sortedTrades[sortedTrades.length - 1] ?? null;
  const buyCount = sortedTrades.filter((trade) => trade.side === "BUY").length;
  const sellCount = sortedTrades.filter((trade) => trade.side === "SELL").length;
  const chartPoints = buildEquityCurve(startingBalance, sortedTrades, totalEquity);

  return NextResponse.json({
    generatedAt: new Date().toISOString(),
    summary: {
      enabled: Boolean(config.enabled),
      executionMode: config.execution_mode ?? "paper",
      trackedSymbols: symbolControls.length,
      activeSymbols: buyEnabledSymbolsCount,
      disabledSymbols: buyDisabledSymbolsCount,
      sellEnabledSymbols: sellEnabledSymbolsCount,
      sellDisabledSymbols: sellDisabledSymbolsCount,
      cooldownSeconds: Number(
        config.risk?.cooldown_seconds ?? 0,
      ),
      maxConcurrentTrades: round(maxConcurrentTrades, 0),
      tradeAmountUsd: round(tradeAmountUsd, 2),
      riskPercent: round(riskPercent * 100, 2),
      loopSeconds: Number(config.loop_sleep ?? 0),
      lookback: Number(config.lookback ?? 0),
      minTrades: Number(config.min_trades ?? 0),
      startingBalance: round(startingBalance, 2),
      cashBalance: round(cashBalance, 2),
      investedCapital: round(investedCapital, 2),
      openValue: round(openValue, 2),
      totalEquity: round(totalEquity, 2),
      realizedPnl: round(realizedPnl, 2),
      unrealizedPnl: round(unrealizedPnl, 2),
      netPnl: round(netPnl, 2),
      netReturnPct: round(netReturnPct, 2),
      openPositions: positionRows.length,
      openExposurePct:
        totalEquity <= 0 ? 0 : round((openValue / totalEquity) * 100, 2),
      firstActivationPct: round(firstActivation * 100, 2),
      trailingActivationPct: round(trailingActivation * 100, 2),
      trailingGapPct: round(trailingGap * 100, 2),
      lastTradeAt: lastTrade?.time ?? null,
      lastTradeReason: lastTrade?.reason ?? null,
      lastSnapshotAt,
      buyCount,
      sellCount,
    },
    symbolControls,
    chart: {
      points: chartPoints,
      min: round(Math.min(...chartPoints), 2),
      max: round(Math.max(...chartPoints), 2),
    },
    positions: positionRows.map((row) => ({
      ...row,
      units: round(row.units, 6),
      entryPrice: round(row.entryPrice, 6),
      currentPrice:
        row.currentPrice === null ? null : round(row.currentPrice, 6),
      lockPrice:
        row.lockPrice === null ? null : round(row.lockPrice, 6),
      costBasis: round(row.costBasis, 2),
      marketValue: round(row.marketValue, 2),
      allocationPct: round(row.allocationPct, 2),
      unrealizedValue: round(row.unrealizedValue, 2),
      unrealizedPct: round(row.unrealizedPct, 2),
      peakPnlPct: round(row.peakPnlPct, 2),
      profitLockPct:
        row.profitLockPct === null ? null : round(row.profitLockPct, 2),
    })),
  });
}
