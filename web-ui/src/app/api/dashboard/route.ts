import { promises as fs } from "fs";
import path from "path";
import { NextResponse } from "next/server";

type ConfigState = {
  enabled?: boolean;
  execution_mode?: string;
  starting_balance?: number;
  symbols?: string[];
  symbol_strategies?: Record<string, unknown>;
  strategy_overrides?: Record<string, unknown>;
  volatility_scalper?: {
    enabled?: boolean;
    symbols?: string[];
  };
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
  market_regime?: {
    preferred_buy_zone?: [number, number];
    min_z_score?: number;
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
  last_regime?: Record<string, string>;
  last_score?: Record<string, number>;
  last_volatility?: Record<string, number>;
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
  scalperEnabled: boolean;
  regime: string | null;
  volatilityPct: number | null;
  strategyScorePct: number | null;
  buyOpportunityPct: number | null;
};

type SnapshotMetrics = {
  price: number | null;
  vwap: number | null;
  atrRaw: number | null;
  momNorm: number | null;
  low24h: number | null;
  high24h: number | null;
  spreadBps: number | null;
  quality: string | null;
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

function parseSnapshotMetrics(rawFields: string): SnapshotMetrics {
  const values: Record<string, string> = {};
  const fieldPattern = /([a-z0-9_]+)=([^\s]+)/gi;

  for (const match of rawFields.matchAll(fieldPattern)) {
    values[match[1]] = match[2];
  }

  const asNumber = (value: string | undefined): number | null => {
    if (!value) {
      return null;
    }
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  };

  return {
    price: asNumber(values.price),
    vwap: asNumber(values.vwap),
    atrRaw: asNumber(values.atr_raw),
    momNorm: asNumber(values.mom_norm),
    low24h: asNumber(values["24h_low"]),
    high24h: asNumber(values["24h_high"]),
    spreadBps: asNumber(values.spread_bps),
    quality: values.quality ?? null,
  };
}

async function readLatestSnapshots(symbols: string[]) {
  const snapshots: Record<string, SnapshotMetrics> = {};
  let lastSnapshotAt: string | null = null;
  const wanted = new Set(symbols);

  if (wanted.size === 0) {
    return { snapshots, lastSnapshotAt };
  }

  const tail = await readLogTail(LOG_PATH, LOG_TAIL_BYTES);
  const lines = tail.split(/\r?\n/);
  const snapshotPattern =
    /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\|\s+INFO\s+\|\s+SNAPSHOT\s+([A-Z0-9-]+)\s+\|\s+(.+)$/;

  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const match = lines[index].match(snapshotPattern);
    if (!match) {
      continue;
    }

    if (!lastSnapshotAt) {
      lastSnapshotAt = match[1];
    }

    const symbol = match[2];
    if (!wanted.has(symbol) || symbol in snapshots) {
      continue;
    }

    snapshots[symbol] = parseSnapshotMetrics(match[3]);

    if (Object.keys(snapshots).length >= wanted.size) {
      break;
    }
  }

  return { snapshots, lastSnapshotAt };
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function computeBuyOpportunityPct(
  snapshot: SnapshotMetrics | null,
  config: ConfigState,
) {
  if (!snapshot || snapshot.price === null || snapshot.price <= 0) {
    return null;
  }

  let buyZoneLow = 0.05;
  let buyZoneHigh = 0.3;
  const configuredZone = config.market_regime?.preferred_buy_zone;
  if (Array.isArray(configuredZone) && configuredZone.length === 2) {
    const low = Number(configuredZone[0]);
    const high = Number(configuredZone[1]);
    if (Number.isFinite(low) && Number.isFinite(high) && low < high) {
      buyZoneLow = clamp(low, 0, 1);
      buyZoneHigh = clamp(high, 0, 1);
    }
  }

  const minZScore = Number(config.market_regime?.min_z_score ?? -1.5);
  const price = snapshot.price;
  const low24h = snapshot.low24h;
  const high24h = snapshot.high24h;
  const vwap = snapshot.vwap;
  const atrRaw = snapshot.atrRaw;
  const momNorm = snapshot.momNorm;

  let rangePos: number | null = null;
  if (
    low24h !== null
    && high24h !== null
    && Number.isFinite(low24h)
    && Number.isFinite(high24h)
    && high24h > low24h
  ) {
    rangePos = (price - low24h) / (high24h - low24h);
  }

  let zoneScore = 10;
  if (rangePos !== null) {
    if (rangePos >= buyZoneLow && rangePos <= buyZoneHigh) {
      const zoneCenter = (buyZoneLow + buyZoneHigh) / 2;
      const zoneHalfWidth = Math.max((buyZoneHigh - buyZoneLow) / 2, 0.0001);
      const proximity = 1 - clamp(Math.abs(rangePos - zoneCenter) / zoneHalfWidth, 0, 1);
      zoneScore = 35 + proximity * 20;
    } else if (rangePos < buyZoneLow) {
      const distanceBelow = clamp(
        (buyZoneLow - rangePos) / Math.max(buyZoneLow, 0.0001),
        0,
        1,
      );
      zoneScore = 20 * (1 - distanceBelow);
    } else {
      zoneScore = 0;
    }
  }

  let zScore: number | null = null;
  if (vwap !== null && atrRaw !== null && atrRaw > 0) {
    zScore = (price - vwap) / atrRaw;
  }

  let stretchScore = 15;
  if (zScore !== null) {
    if (zScore <= minZScore) {
      const extraStretch = clamp(Math.abs(zScore - minZScore) / 2.5, 0, 1);
      stretchScore = 35 + extraStretch * 25;
    } else {
      const missAmount = clamp((zScore - minZScore) / 3, 0, 1);
      stretchScore = 20 * (1 - missAmount);
    }
  }

  let momentumScore = 7;
  if (momNorm !== null && Number.isFinite(momNorm)) {
    if (momNorm <= 0) {
      momentumScore = clamp(Math.abs(momNorm) / 4, 0, 1) * 15;
    } else {
      momentumScore = 15 - clamp(momNorm / 4, 0, 1) * 15;
    }
  }

  const quality = (snapshot.quality ?? "ok").toLowerCase();
  let penalty = 0;
  if (quality !== "ok") {
    if (quality.includes("spread_too_wide")) {
      penalty += 20;
    }
    if (quality.includes("order_book_tape_mismatch")) {
      penalty += 15;
    }
    if (quality.includes("warming_up_history")) {
      penalty += 10;
    }
    if (penalty === 0) {
      penalty += 8;
    }
  }

  if (snapshot.spreadBps !== null && snapshot.spreadBps > 150) {
    penalty += 8;
  }

  const score = clamp(zoneScore + stretchScore + momentumScore - penalty, 0, 100);
  return score;
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

function asFiniteNumber(value: unknown): number | null {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function parseStringMap(values: unknown) {
  if (!values || typeof values !== "object" || Array.isArray(values)) {
    return {};
  }

  const output: Record<string, string> = {};
  for (const [rawSymbol, rawValue] of Object.entries(
    values as Record<string, unknown>,
  )) {
    const symbol = normalizeSymbol(rawSymbol);
    if (!symbol || typeof rawValue !== "string") {
      continue;
    }

    const regime = rawValue.trim().toLowerCase();
    if (!regime) {
      continue;
    }
    output[symbol] = regime;
  }

  return output;
}

function normalizeStrategyName(value: unknown) {
  const raw = String(value ?? "").trim().toLowerCase();
  if (raw === "volatility_scalper" || raw === "vol_scalper" || raw === "scalper") {
    return "volatility_scalper";
  }
  return "mean_reversion";
}

function parseStrategyMap(values: unknown) {
  if (!values || typeof values !== "object" || Array.isArray(values)) {
    return {};
  }

  const output: Record<string, string> = {};
  for (const [rawSymbol, rawValue] of Object.entries(
    values as Record<string, unknown>,
  )) {
    const symbol = normalizeSymbol(rawSymbol);
    if (!symbol) {
      continue;
    }

    let mode: unknown = rawValue;
    if (rawValue && typeof rawValue === "object" && !Array.isArray(rawValue)) {
      const row = rawValue as Record<string, unknown>;
      mode = row.strategy ?? row.mode ?? rawValue;
    }

    output[symbol] = normalizeStrategyName(mode);
  }

  return output;
}

function parseNumberMap(values: unknown) {
  if (!values || typeof values !== "object" || Array.isArray(values)) {
    return {};
  }

  const output: Record<string, number> = {};
  for (const [rawSymbol, rawValue] of Object.entries(
    values as Record<string, unknown>,
  )) {
    const symbol = normalizeSymbol(rawSymbol);
    const numeric = asFiniteNumber(rawValue);
    if (!symbol || numeric === null) {
      continue;
    }
    output[symbol] = numeric;
  }

  return output;
}

function parseScalperSymbolSet(config: ConfigState) {
  const scalperCfg = config.volatility_scalper;
  const enabled = scalperCfg?.enabled !== false;
  if (!enabled) {
    return new Set<string>();
  }

  return new Set(normalizeSymbols(scalperCfg?.symbols));
}

function resolveStrategyMode(
  symbol: string,
  symbolStrategies: Record<string, string>,
  strategyOverrides: Record<string, string>,
  scalperSymbols: Set<string>,
) {
  if (symbol in symbolStrategies) {
    return symbolStrategies[symbol];
  }
  if (symbol in strategyOverrides) {
    return strategyOverrides[symbol];
  }
  if (scalperSymbols.has(symbol)) {
    return "volatility_scalper";
  }
  return "mean_reversion";
}

function deriveRegimeFromSnapshot(snapshot: SnapshotMetrics | null): string | null {
  if (!snapshot) {
    return null;
  }

  const momentum = snapshot.momNorm;
  const price = snapshot.price;
  const vwap = snapshot.vwap;

  if (momentum !== null && momentum <= -1.2) {
    return "dump";
  }
  if (momentum !== null && momentum >= 1.2) {
    return "spike";
  }

  if (price !== null && vwap !== null) {
    if (price > vwap && (momentum ?? 0) > 0.2) {
      return "trend_up";
    }
    if (price < vwap && (momentum ?? 0) < -0.2) {
      return "trend_down";
    }
  }

  if (momentum !== null && Math.abs(momentum) < 0.35) {
    return "range";
  }

  return "chop";
}

function formatRegimeLabel(value: string | null) {
  if (!value) {
    return null;
  }

  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
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
  const symbolStrategies = parseStrategyMap(config.symbol_strategies);
  const strategyOverrides = parseStrategyMap(config.strategy_overrides);
  const scalperSymbols = parseScalperSymbolSet(config);
  const regimeMap = parseStringMap(strategy.last_regime);
  const scoreMap = parseNumberMap(strategy.last_score);
  const volatilityMap = parseNumberMap(strategy.last_volatility);
  const allSymbols = uniqueSymbols(
    configuredSymbols,
    Object.keys(legacyMap),
    Object.keys(buyMap),
    Object.keys(sellMap),
    Object.keys(symbolStrategies),
    Object.keys(strategyOverrides),
    Array.from(scalperSymbols),
    positionSymbols,
  );

  const { snapshots, lastSnapshotAt } = await readLatestSnapshots(allSymbols);

  const symbolControls: SymbolControl[] = allSymbols.map((symbol) => {
    const snapshot = snapshots[symbol] ?? null;
    const regimeRaw = regimeMap[symbol] ?? deriveRegimeFromSnapshot(snapshot);
    const score = scoreMap[symbol] ?? null;
    const volatilityRaw = volatilityMap[symbol] ?? snapshot?.atrRaw ?? null;
    const strategyMode = resolveStrategyMode(
      symbol,
      symbolStrategies,
      strategyOverrides,
      scalperSymbols,
    );

    return {
      symbol,
      buyEnabled: buyMap[symbol] ?? legacyMap[symbol] ?? true,
      sellEnabled: sellMap[symbol] ?? legacyMap[symbol] ?? true,
      hasOpenPosition: symbol in positions,
      scalperEnabled: strategyMode === "volatility_scalper",
      regime: formatRegimeLabel(regimeRaw),
      volatilityPct:
        volatilityRaw === null ? null : Number(volatilityRaw) * 100,
      strategyScorePct: score,
      buyOpportunityPct: computeBuyOpportunityPct(
        snapshot,
        config,
      ),
    };
  });
  const buyEnabledSymbolsCount = symbolControls.filter(
    (control) => control.buyEnabled,
  ).length;
  const sellEnabledSymbolsCount = symbolControls.filter(
    (control) => control.sellEnabled,
  ).length;
  const buyDisabledSymbolsCount = symbolControls.length - buyEnabledSymbolsCount;
  const sellDisabledSymbolsCount =
    symbolControls.length - sellEnabledSymbolsCount;

  const bestBuyCandidate = symbolControls
    .filter((control) => (
      control.buyEnabled
      && !control.hasOpenPosition
      && control.buyOpportunityPct !== null
    ))
    .sort(
      (left, right) =>
        Number(right.buyOpportunityPct ?? 0) - Number(left.buyOpportunityPct ?? 0),
    )[0] ?? null;

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
    const currentPrice = snapshots[symbol]?.price ?? null;
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
      bestBuySymbol: bestBuyCandidate?.symbol ?? null,
      bestBuyOpportunityPct:
        bestBuyCandidate?.buyOpportunityPct === null
          ? null
          : round(Number(bestBuyCandidate?.buyOpportunityPct ?? 0), 1),
    },
    symbolControls: symbolControls.map((control) => ({
      ...control,
      volatilityPct:
        control.volatilityPct === null
          ? null
          : round(control.volatilityPct, 3),
      strategyScorePct:
        control.strategyScorePct === null
          ? null
          : round(control.strategyScorePct, 1),
      buyOpportunityPct:
        control.buyOpportunityPct === null
          ? null
          : round(control.buyOpportunityPct, 1),
    })),
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
