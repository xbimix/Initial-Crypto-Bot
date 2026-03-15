import { promises as fs } from "fs";
import path from "path";
import { NextResponse } from "next/server";

type ConfigState = {
  enabled?: boolean;
  execution_mode?: string;
  starting_balance?: number;
  min_atr?: number;
  min_score_to_buy?: number;
  symbols?: string[];
  symbol_strategies?: Record<string, unknown>;
  strategy_overrides?: Record<string, unknown>;
  volatility_scalper?: {
    enabled?: boolean;
    symbols?: string[];
    min_atr?: number;
    min_trades?: number;
    max_spread_bps?: number;
    min_momentum?: number;
    entry_z_score_max?: number;
    min_score_to_buy?: number;
    max_range_pos?: number;
  };
  symbol_enabled?: Record<string, boolean>;
  symbol_buy_enabled?: Record<string, boolean>;
  symbol_sell_enabled?: Record<string, boolean>;
  volatility_filters?: {
    min_atr?: number;
    min_atr_pct?: number;
  };
  lookback?: number;
  min_trades?: number;
  loop_sleep?: number;
  risk?: {
    risk_percent?: number;
    max_concurrent_trades?: number;
    max_concurrent_trades_per_token?: number;
    max_trade_amount_usd?: number;
    trade_amount_usd?: number;
    cooldown_seconds?: number;
    max_portfolio_exposure_pct?: number;
    max_exposure_per_token_pct?: number;
    daily_loss_limit_usd?: number;
    daily_loss_auto_pause?: boolean;
    daily_loss_close_all?: boolean;
    stale_losing_review_age_hours?: number;
    stale_losing_review_unrealized_pnl_pct?: number;
    signal_confirmation_cycles?: number;
    trade_window_utc?: {
      enabled?: boolean;
      start_hour_utc?: number;
      end_hour_utc?: number;
    };
    symbol_cooldown_seconds?: Record<string, number>;
  };
  profit_locks?: {
    first_activation?: number;
    trailing_activation?: number;
    trailing_gap?: number;
  };
  market_regime?: {
    preferred_buy_zone?: [number, number];
    min_z_score?: number;
    min_score_to_buy?: number;
    min_atr?: number;
    blocked_regimes?: string[];
    hard_blocked_regimes?: string[];
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
  advisoryStaleLosingReview: boolean;
  advisoryReviewAgeHours: number | null;
  advisoryThresholdAgeHours: number;
  advisoryThresholdUnrealizedPnlPct: number;
  advisoryMaxDrawdownPctDuringTrade: number;
  advisoryMaxDrawdownPriceDuringTrade: number | null;
  advisoryMaxDrawdownAt: number | null;
  thesis: string;
};

type SymbolControl = {
  symbol: string;
  buyEnabled: boolean;
  sellEnabled: boolean;
  hasOpenPosition: boolean;
  scalperEnabled: boolean;
  cooldownOverrideSeconds: number | null;
  buyExecutable: boolean;
  buyExecutableReason: string;
  regime: string | null;
  volatilityPct: number | null;
  strategyScorePct: number | null;
  buyOpportunityPct: number | null;
  capitalEfficiencyScore: number | null;
  capitalWasteRank: number | null;
  capitalWasteAllocationPct: number | null;
  capitalWasteUnrealizedPct: number | null;
  capitalWasteAgeHours: number | null;
};

type SnapshotMetrics = {
  price: number | null;
  vwap: number | null;
  atrRaw: number | null;
  momNorm: number | null;
  points: number | null;
  low24h: number | null;
  high24h: number | null;
  spreadBps: number | null;
  quality: string | null;
};

type SnapshotPoint = {
  tsEpoch: number;
  price: number;
};

type CapitalEfficiencyRow = {
  symbol: string;
  costBasis: number;
  unrealizedPct: number;
  ageHours: number | null;
  allocationPct: number;
  score: number;
  wasteScore: number;
  rank: number;
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

function parseLogTimestampToEpoch(raw: string): number | null {
  const isoLike = raw.replace(" ", "T");
  const localParsed = Date.parse(isoLike);
  if (!Number.isNaN(localParsed)) {
    return localParsed / 1000;
  }
  const utcParsed = Date.parse(`${isoLike}Z`);
  if (Number.isNaN(utcParsed)) {
    return null;
  }
  return utcParsed / 1000;
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
    points: asNumber(values.points),
    low24h: asNumber(values["24h_low"]),
    high24h: asNumber(values["24h_high"]),
    spreadBps: asNumber(values.spread_bps),
    quality: values.quality ?? null,
  };
}

async function readLatestSnapshots(symbols: string[]) {
  const snapshots: Record<string, SnapshotMetrics> = {};
  const snapshotHistory: Record<string, SnapshotPoint[]> = {};
  let lastSnapshotAt: string | null = null;
  const wanted = new Set(symbols);

  if (wanted.size === 0) {
    return { snapshots, snapshotHistory, lastSnapshotAt };
  }

  const tail = await readLogTail(LOG_PATH, LOG_TAIL_BYTES);
  const lines = tail.split(/\r?\n/);
  const snapshotPattern =
    /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\|\s+INFO\s+\|\s+SNAPSHOT\s+([A-Z0-9-]+)\s+\|\s+(.+)$/;

  for (let index = 0; index < lines.length; index += 1) {
    const match = lines[index].match(snapshotPattern);
    if (!match) {
      continue;
    }

    const symbol = match[2];
    if (!wanted.has(symbol)) {
      continue;
    }

    const parsed = parseSnapshotMetrics(match[3]);
    snapshots[symbol] = parsed;
    lastSnapshotAt = match[1];

    if (parsed.price !== null && parsed.price > 0) {
      const tsEpoch = parseLogTimestampToEpoch(match[1]);
      if (tsEpoch !== null) {
        if (!(symbol in snapshotHistory)) {
          snapshotHistory[symbol] = [];
        }
        snapshotHistory[symbol].push({
          tsEpoch,
          price: parsed.price,
        });
      }
    }
  }

  return { snapshots, snapshotHistory, lastSnapshotAt };
}

function findMinPricePointSinceEntry(
  history: SnapshotPoint[],
  entryTimeEpoch: number | null,
) {
  let minPoint: SnapshotPoint | null = null;
  for (const point of history) {
    if (
      entryTimeEpoch !== null
      && entryTimeEpoch > 0
      && point.tsEpoch < entryTimeEpoch
    ) {
      continue;
    }
    if (minPoint === null || point.price < minPoint.price) {
      minPoint = point;
    }
  }
  return minPoint;
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

function isWithinTradeWindowUtc(config: ConfigState, nowUtc = new Date()) {
  const windowCfg = config.risk?.trade_window_utc;
  if (!windowCfg || windowCfg.enabled !== true) {
    return true;
  }

  const startHour = Math.max(
    0,
    Math.min(23, Math.floor(Number(windowCfg.start_hour_utc ?? 0))),
  );
  const endHour = Math.max(
    0,
    Math.min(23, Math.floor(Number(windowCfg.end_hour_utc ?? 23))),
  );
  const hour = nowUtc.getUTCHours();

  if (startHour === endHour) {
    return true;
  }
  if (startHour < endHour) {
    return hour >= startHour && hour < endHour;
  }
  return hour >= startHour || hour < endHour;
}

function computeDailyRealizedPnlUtc(
  trades: TradeEntry[],
  nowUtc = new Date(),
) {
  const dayStartUtc = Date.UTC(
    nowUtc.getUTCFullYear(),
    nowUtc.getUTCMonth(),
    nowUtc.getUTCDate(),
    0,
    0,
    0,
    0,
  ) / 1000;

  return trades.reduce((total, trade) => {
    if (String(trade.side ?? "").toUpperCase() !== "SELL") {
      return total;
    }
    const tradeTime = Number(trade.time ?? 0);
    if (!Number.isFinite(tradeTime) || tradeTime < dayStartUtc) {
      return total;
    }
    return total + Number(trade.pnl ?? 0);
  }, 0);
}

type BuyExecutableStatus = {
  buyExecutable: boolean;
  buyExecutableReason: string;
};

function blockedBuy(reason: string): BuyExecutableStatus {
  return {
    buyExecutable: false,
    buyExecutableReason: reason,
  };
}

function executableBuyReady(): BuyExecutableStatus {
  return {
    buyExecutable: true,
    buyExecutableReason: "Ready",
  };
}

function parseBlockedRegimeSet(config: ConfigState) {
  const regimeCfg = config.market_regime ?? {};
  const rawBlocked =
    regimeCfg.hard_blocked_regimes
    ?? regimeCfg.blocked_regimes
    ?? ["unknown"];
  const blocked = new Set<string>();

  if (!Array.isArray(rawBlocked)) {
    return blocked;
  }

  for (const value of rawBlocked) {
    const regime = String(value ?? "").trim().toLowerCase();
    if (regime) {
      blocked.add(regime);
    }
  }

  return blocked;
}

function parseQualityBlockReason(quality: string | null) {
  const raw = String(quality ?? "").trim().toLowerCase();
  if (!raw || raw === "ok") {
    return null;
  }

  const reasons = raw
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (reasons.includes("spread_too_wide")) {
    return "Spread too wide";
  }
  if (reasons.includes("order_book_tape_mismatch")) {
    return "Book/tape mismatch";
  }
  if (reasons.includes("warming_up_history")) {
    return "History warming up";
  }

  return "Data quality blocked";
}

function computeBuyExecutableStatus({
  buyEnabled,
  hasOpenPosition,
  openPositionsForSymbol,
  snapshot,
  score,
  regimeRaw,
  strategyMode,
  config,
  openPositions,
  currentAllocatedUsd,
  currentSymbolAllocatedUsd,
  totalEquityUsd,
  estimatedNextTradeUsd,
  dailyBuyPaused,
  insideTradeWindowUtc,
}: {
  buyEnabled: boolean;
  hasOpenPosition: boolean;
  openPositionsForSymbol: number;
  snapshot: SnapshotMetrics | null;
  score: number | null;
  regimeRaw: string | null;
  strategyMode: string;
  config: ConfigState;
  openPositions: number;
  currentAllocatedUsd: number;
  currentSymbolAllocatedUsd: number;
  totalEquityUsd: number;
  estimatedNextTradeUsd: number;
  dailyBuyPaused: boolean;
  insideTradeWindowUtc: boolean;
}): BuyExecutableStatus {
  if (!buyEnabled) {
    return blockedBuy("BUY toggle off");
  }

  if (!insideTradeWindowUtc) {
    return blockedBuy("Outside UTC window");
  }

  if (dailyBuyPaused) {
    return blockedBuy("Daily loss auto-pause");
  }

  const maxConcurrentTradesPerToken = Number(
    config.risk?.max_concurrent_trades_per_token ?? 1,
  );
  if (
    Number.isFinite(maxConcurrentTradesPerToken)
    && openPositionsForSymbol >= maxConcurrentTradesPerToken
  ) {
    return blockedBuy(
      `Token max reached (${openPositionsForSymbol}/${Math.trunc(maxConcurrentTradesPerToken)})`,
    );
  }

  if (hasOpenPosition) {
    return blockedBuy("Position already open");
  }

  if (!snapshot) {
    return blockedBuy("No snapshot");
  }

  const qualityReason = parseQualityBlockReason(snapshot.quality);
  if (qualityReason !== null) {
    return blockedBuy(qualityReason);
  }

  const blockedRegimes = parseBlockedRegimeSet(config);
  const regime = String(regimeRaw ?? "unknown").trim().toLowerCase() || "unknown";
  if (blockedRegimes.has(regime)) {
    return blockedBuy(`Regime blocked (${formatRegimeLabel(regime) ?? regime})`);
  }

  const maxConcurrentTrades = Number(config.risk?.max_concurrent_trades ?? 1);
  if (
    Number.isFinite(maxConcurrentTrades)
    && openPositions >= maxConcurrentTrades
  ) {
    return blockedBuy(
      `Max trades reached (${openPositions}/${Math.trunc(maxConcurrentTrades)})`,
    );
  }

  const maxTradeAmountUsd = asFiniteNumber(
    config.risk?.max_trade_amount_usd ?? config.starting_balance ?? null,
  );
  if (
    maxTradeAmountUsd !== null
    && (currentAllocatedUsd + estimatedNextTradeUsd) > maxTradeAmountUsd
  ) {
    return blockedBuy(
      `Trade cap reached (${round(currentAllocatedUsd, 0)}/${round(maxTradeAmountUsd, 0)})`,
    );
  }

  if (totalEquityUsd > 0) {
    const maxPortfolioExposurePct = Math.max(
      Number(config.risk?.max_portfolio_exposure_pct ?? 100),
      1,
    );
    const maxTokenExposurePct = Math.max(
      Number(config.risk?.max_exposure_per_token_pct ?? 100),
      1,
    );
    const nextPortfolioExposurePct = (
      (currentAllocatedUsd + estimatedNextTradeUsd)
      / totalEquityUsd
    ) * 100;
    const nextTokenExposurePct = (
      (currentSymbolAllocatedUsd + estimatedNextTradeUsd)
      / totalEquityUsd
    ) * 100;

    if (nextPortfolioExposurePct > maxPortfolioExposurePct) {
      return blockedBuy(
        `Portfolio exposure limit (${nextPortfolioExposurePct.toFixed(1)}% > ${maxPortfolioExposurePct.toFixed(1)}%)`,
      );
    }

    if (nextTokenExposurePct > maxTokenExposurePct) {
      return blockedBuy(
        `Token exposure limit (${nextTokenExposurePct.toFixed(1)}% > ${maxTokenExposurePct.toFixed(1)}%)`,
      );
    }
  }

  const price = snapshot.price;
  const vwap = snapshot.vwap;
  const atrRaw = snapshot.atrRaw;
  const momentum = snapshot.momNorm;
  const points = snapshot.points;
  const spreadBps = snapshot.spreadBps;
  const low24h = snapshot.low24h;
  const high24h = snapshot.high24h;

  if (price === null || price <= 0) {
    return blockedBuy("Price unavailable");
  }

  if (
    low24h === null
    || high24h === null
    || !Number.isFinite(low24h)
    || !Number.isFinite(high24h)
    || high24h <= low24h
  ) {
    return blockedBuy("Insufficient range data");
  }

  const rangePos = (price - low24h) / (high24h - low24h);

  const zScore = (
    vwap !== null
    && atrRaw !== null
    && atrRaw > 0
  )
    ? (price - vwap) / atrRaw
    : null;

  const minTrades = Math.max(Number(config.min_trades ?? 3), 1);
  const mode = normalizeStrategyName(strategyMode);
  if (mode === "volatility_scalper") {
    const scalperCfg = config.volatility_scalper ?? {};
    const requiredTrades = Math.max(Number(scalperCfg.min_trades ?? 6), minTrades);
    if (points === null || points < requiredTrades) {
      return blockedBuy(`Need ${Math.trunc(requiredTrades)} trades`);
    }

    if (atrRaw === null || atrRaw <= 0) {
      return blockedBuy("Missing volatility");
    }

    const minAtr = Math.max(Number(scalperCfg.min_atr ?? 0.008), 0);
    if (atrRaw < minAtr) {
      return blockedBuy("Scalper volatility too low");
    }

    const maxSpreadBps = Math.max(Number(scalperCfg.max_spread_bps ?? 120), 0);
    if (spreadBps !== null && spreadBps > maxSpreadBps) {
      return blockedBuy("Spread too wide");
    }

    const maxRangePos = asFiniteNumber(scalperCfg.max_range_pos);
    if (maxRangePos !== null && rangePos > maxRangePos) {
      return blockedBuy("Too extended");
    }

    const entryZMax = Number(scalperCfg.entry_z_score_max ?? -0.1);
    if (zScore !== null && zScore > entryZMax) {
      return blockedBuy("Wait for pullback");
    }

    const minMomentum = Number(scalperCfg.min_momentum ?? 0.2);
    if (momentum === null || momentum < minMomentum) {
      return blockedBuy("Momentum not ready");
    }

    const minScore = Math.max(Number(scalperCfg.min_score_to_buy ?? 55), 0);
    if (score === null) {
      return blockedBuy("Score pending");
    }
    if (score < minScore) {
      return blockedBuy("Score below threshold");
    }

    return executableBuyReady();
  }

  if (points === null || points < minTrades) {
    return blockedBuy(`Need ${Math.trunc(minTrades)} trades`);
  }

  if (vwap === null || atrRaw === null || atrRaw <= 0) {
    return blockedBuy("Insufficient data");
  }

  let buyZoneLow = 0.05;
  let buyZoneHigh = 0.30;
  const configuredZone = config.market_regime?.preferred_buy_zone;
  if (Array.isArray(configuredZone) && configuredZone.length === 2) {
    const low = Number(configuredZone[0]);
    const high = Number(configuredZone[1]);
    if (Number.isFinite(low) && Number.isFinite(high) && low < high) {
      buyZoneLow = clamp(low, 0, 1);
      buyZoneHigh = clamp(high, 0, 1);
    }
  }

  const baseMinAtr = Number(
    config.volatility_filters?.min_atr
    ?? config.market_regime?.min_atr
    ?? config.min_atr
    ?? 0.003,
  );
  const minAtrPct = Number(config.volatility_filters?.min_atr_pct ?? baseMinAtr);
  const effectiveMinAtr = Math.max(baseMinAtr, minAtrPct);
  if (atrRaw < effectiveMinAtr) {
    return blockedBuy("ATR below minimum");
  }

  if (rangePos > buyZoneHigh) {
    return blockedBuy("Above buy zone");
  }

  if (rangePos < buyZoneLow) {
    return blockedBuy("Below buy zone");
  }

  const minZScore = Number(config.market_regime?.min_z_score ?? -1.5);
  if (zScore !== null && zScore > minZScore) {
    return blockedBuy("No volatility stretch");
  }

  const minScoreToBuy = Number(
    config.market_regime?.min_score_to_buy
    ?? config.min_score_to_buy
    ?? 60,
  );
  if (score === null) {
    return blockedBuy("Score pending");
  }
  if (score < minScoreToBuy) {
    return blockedBuy("Score below threshold");
  }

  return executableBuyReady();
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

  const { snapshots, snapshotHistory, lastSnapshotAt } = await readLatestSnapshots(allSymbols);
  const openPositionsCount = positionSymbols.length;
  const startingBalance = Number(config.starting_balance ?? 10000);
  const cashBalance = Number(paper.balance ?? 0);
  const riskPercent = Number(config.risk?.risk_percent ?? 0.02);
  const defaultTradeAmount = startingBalance * riskPercent;
  const tradeAmountUsd = Number(config.risk?.trade_amount_usd ?? defaultTradeAmount);
  const maxConcurrentTrades = Number(config.risk?.max_concurrent_trades ?? 1);
  const maxConcurrentTradesPerToken = Number(
    config.risk?.max_concurrent_trades_per_token ?? 1,
  );
  const maxTradeAmountUsd = Number(
    config.risk?.max_trade_amount_usd ?? startingBalance,
  );
  const symbolCostBasisUsd: Record<string, number> = {};
  for (const symbol of positionSymbols) {
    const position = positions[symbol] ?? {};
    symbolCostBasisUsd[symbol] = Number(position.price ?? 0) * Number(position.size ?? 0);
  }
  const currentAllocatedUsd = sum(Object.values(symbolCostBasisUsd));
  const totalEquityEstimateUsd = cashBalance + currentAllocatedUsd;
  const estimatedNextTradeUsd = Math.min(
    Math.max(cashBalance, 0),
    Math.max(Number.isFinite(tradeAmountUsd) ? tradeAmountUsd : 0, 0),
  );
  const cooldownOverrideMap = parseNumberMap(config.risk?.symbol_cooldown_seconds);
  const nowUtc = new Date();
  const insideTradeWindowUtc = isWithinTradeWindowUtc(config, nowUtc);
  const dailyRealizedPnlUsd = computeDailyRealizedPnlUtc(trades, nowUtc);
  const dailyLossLimitUsd = Math.max(
    Number(config.risk?.daily_loss_limit_usd ?? 0),
    0,
  );
  const dailyLossAutoPause = config.risk?.daily_loss_auto_pause !== false;
  const dailyLossCloseAll = config.risk?.daily_loss_close_all === true;
  const dailyBuyPaused = dailyLossLimitUsd > 0
    && dailyLossAutoPause
    && dailyRealizedPnlUsd <= -dailyLossLimitUsd;
  const staleLosingReviewAgeHours = Math.max(
    asFiniteNumber(config.risk?.stale_losing_review_age_hours) ?? 36,
    0,
  );
  const staleLosingReviewUnrealizedPnlPct = Math.min(
    asFiniteNumber(config.risk?.stale_losing_review_unrealized_pnl_pct) ?? -10,
    0,
  );
  const nowEpochSeconds = Date.now() / 1000;
  const capitalEfficiencyBySymbol: Record<string, CapitalEfficiencyRow> = {};

  {
    const positionBaseRows = positionSymbols.map((symbol) => {
      const position = positions[symbol] ?? {};
      const entryPrice = Number(
        strategy.entry_price?.[symbol] ?? position.price ?? 0,
      );
      const units = Number(position.size ?? 0);
      const costBasis = entryPrice > 0 && units > 0 ? entryPrice * units : 0;
      const currentPrice = snapshots[symbol]?.price ?? null;
      const unrealizedPct = currentPrice === null || entryPrice <= 0
        ? 0
        : ((currentPrice - entryPrice) / entryPrice) * 100;
      const entryTimeRaw = asFiniteNumber(position.entry_time);
      const ageHours = (
        entryTimeRaw === null || entryTimeRaw <= 0
      )
        ? null
        : Math.max((nowEpochSeconds - entryTimeRaw) / 3600, 0);

      return {
        symbol,
        costBasis,
        unrealizedPct,
        ageHours,
      };
    });

    const totalOpenCostBasis = sum(positionBaseRows.map((row) => row.costBasis));
    const scoredRows: CapitalEfficiencyRow[] = positionBaseRows.map((row) => {
      const allocationPct = totalOpenCostBasis <= 0
        ? 0
        : (row.costBasis / totalOpenCostBasis) * 100;
      const ageSeverity = clamp((row.ageHours ?? 24) / 72, 0, 1);
      const capitalSeverity = clamp(allocationPct / 40, 0, 1);
      const lossSeverity = clamp(Math.max(-row.unrealizedPct, 0) / 20, 0, 1);
      const inefficiency = row.unrealizedPct < 0
        ? (0.5 * lossSeverity) + (0.3 * capitalSeverity) + (0.2 * ageSeverity)
        : (0.15 * capitalSeverity * ageSeverity);
      const score = clamp(100 - (inefficiency * 100), 0, 100);
      const wasteScore = 100 - score;

      return {
        symbol: row.symbol,
        costBasis: row.costBasis,
        unrealizedPct: row.unrealizedPct,
        ageHours: row.ageHours,
        allocationPct,
        score,
        wasteScore,
        rank: 0,
      };
    });

    const ranked = [...scoredRows].sort(
      (left, right) => (
        right.wasteScore - left.wasteScore
      ) || left.symbol.localeCompare(right.symbol),
    );
    ranked.forEach((row, index) => {
      row.rank = index + 1;
      capitalEfficiencyBySymbol[row.symbol] = row;
    });
  }

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
    const buyEnabled = buyMap[symbol] ?? legacyMap[symbol] ?? true;
    const hasOpenPosition = symbol in positions;
    const capitalEfficiency = capitalEfficiencyBySymbol[symbol];
    const symbolAllocatedUsd = symbolCostBasisUsd[symbol] ?? 0;
    const executableStatus = computeBuyExecutableStatus({
      buyEnabled,
      hasOpenPosition,
      openPositionsForSymbol: hasOpenPosition ? 1 : 0,
      snapshot,
      score,
      regimeRaw,
      strategyMode,
      config,
      openPositions: openPositionsCount,
      currentAllocatedUsd,
      currentSymbolAllocatedUsd: symbolAllocatedUsd,
      totalEquityUsd: totalEquityEstimateUsd,
      estimatedNextTradeUsd,
      dailyBuyPaused,
      insideTradeWindowUtc,
    });

    return {
      symbol,
      buyEnabled,
      sellEnabled: sellMap[symbol] ?? legacyMap[symbol] ?? true,
      hasOpenPosition,
      scalperEnabled: strategyMode === "volatility_scalper",
      cooldownOverrideSeconds: cooldownOverrideMap[symbol] ?? null,
      buyExecutable: executableStatus.buyExecutable,
      buyExecutableReason: executableStatus.buyExecutableReason,
      regime: formatRegimeLabel(regimeRaw),
      volatilityPct:
        volatilityRaw === null ? null : Number(volatilityRaw) * 100,
      strategyScorePct: score,
      buyOpportunityPct: computeBuyOpportunityPct(
        snapshot,
        config,
      ),
      capitalEfficiencyScore: capitalEfficiency?.score ?? null,
      capitalWasteRank: capitalEfficiency?.rank ?? null,
      capitalWasteAllocationPct: capitalEfficiency?.allocationPct ?? null,
      capitalWasteUnrealizedPct: capitalEfficiency?.unrealizedPct ?? null,
      capitalWasteAgeHours: capitalEfficiency?.ageHours ?? null,
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
    const entryTimeRaw = asFiniteNumber(position.entry_time);
    const minPointSinceEntry = findMinPricePointSinceEntry(
      snapshotHistory[symbol] ?? [],
      entryTimeRaw,
    );
    let advisoryMaxDrawdownPriceDuringTrade =
      minPointSinceEntry?.price ?? null;
    let advisoryMaxDrawdownAt = minPointSinceEntry?.tsEpoch ?? null;
    if (
      currentPrice !== null
      && currentPrice > 0
      && (
        advisoryMaxDrawdownPriceDuringTrade === null
        || currentPrice < advisoryMaxDrawdownPriceDuringTrade
      )
    ) {
      advisoryMaxDrawdownPriceDuringTrade = currentPrice;
      advisoryMaxDrawdownAt = null;
    }
    const drawdownReferencePrice = advisoryMaxDrawdownPriceDuringTrade
      ?? (currentPrice !== null && currentPrice > 0 ? currentPrice : entryPrice);
    const advisoryMaxDrawdownPctDuringTrade = entryPrice <= 0
      ? 0
      : Math.min(((drawdownReferencePrice - entryPrice) / entryPrice) * 100, 0);
    const advisoryReviewAgeHours = (
      entryTimeRaw === null || entryTimeRaw <= 0
    )
      ? null
      : Math.max((nowEpochSeconds - entryTimeRaw) / 3600, 0);
    const advisoryStaleLosingReview = (
      advisoryReviewAgeHours !== null
      && currentPrice !== null
      && entryPrice > 0
      && advisoryReviewAgeHours >= staleLosingReviewAgeHours
      && unrealizedPct <= staleLosingReviewUnrealizedPnlPct
    );
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
      entryTime: entryTimeRaw,
      advisoryStaleLosingReview,
      advisoryReviewAgeHours,
      advisoryThresholdAgeHours: staleLosingReviewAgeHours,
      advisoryThresholdUnrealizedPnlPct: staleLosingReviewUnrealizedPnlPct,
      advisoryMaxDrawdownPctDuringTrade,
      advisoryMaxDrawdownPriceDuringTrade,
      advisoryMaxDrawdownAt,
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

  const investedCapital = sum(positionRows.map((row) => row.costBasis));
  const unrealizedPnl = sum(positionRows.map((row) => row.unrealizedValue));
  const realizedPnl = sum(
    trades.map((trade) => Number(trade.pnl ?? 0)),
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
  const staleLosingReviewRows = positionRows.filter(
    (row) => row.advisoryStaleLosingReview,
  );
  const worstDrawdownRow = positionRows.reduce<PositionRow | null>(
    (worst, row) => {
      if (!worst) {
        return row;
      }
      return row.advisoryMaxDrawdownPctDuringTrade < worst.advisoryMaxDrawdownPctDuringTrade
        ? row
        : worst;
    },
    null,
  );

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
      maxConcurrentTradesPerToken: round(maxConcurrentTradesPerToken, 0),
      maxTradeAmountUsd: round(maxTradeAmountUsd, 2),
      maxPortfolioExposurePct: round(
        Number(config.risk?.max_portfolio_exposure_pct ?? 100),
        2,
      ),
      maxExposurePerTokenPct: round(
        Number(config.risk?.max_exposure_per_token_pct ?? 100),
        2,
      ),
      tradeAmountUsd: round(tradeAmountUsd, 2),
      riskPercent: round(riskPercent * 100, 2),
      signalConfirmationCycles: Math.max(
        1,
        Math.trunc(Number(config.risk?.signal_confirmation_cycles ?? 1)),
      ),
      tradeWindowEnabled: config.risk?.trade_window_utc?.enabled === true,
      tradeWindowStartHourUtc: Math.max(
        0,
        Math.min(23, Math.trunc(Number(config.risk?.trade_window_utc?.start_hour_utc ?? 0))),
      ),
      tradeWindowEndHourUtc: Math.max(
        0,
        Math.min(23, Math.trunc(Number(config.risk?.trade_window_utc?.end_hour_utc ?? 23))),
      ),
      insideTradeWindowUtc,
      dailyLossLimitUsd: round(dailyLossLimitUsd, 2),
      dailyLossAutoPause,
      dailyLossCloseAll,
      dailyRealizedPnlUsd: round(dailyRealizedPnlUsd, 2),
      dailyBuyPaused,
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
      maxDrawdownDuringTradePct: round(
        worstDrawdownRow?.advisoryMaxDrawdownPctDuringTrade ?? 0,
        2,
      ),
      maxDrawdownDuringTradeSymbol: worstDrawdownRow?.symbol ?? null,
      staleLosingReviewCount: staleLosingReviewRows.length,
      staleLosingReviewSymbols: staleLosingReviewRows.map((row) => row.symbol),
      staleLosingReviewThresholdAgeHours: round(staleLosingReviewAgeHours, 2),
      staleLosingReviewThresholdUnrealizedPnlPct: round(
        staleLosingReviewUnrealizedPnlPct,
        2,
      ),
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
      symbolCooldownOverrides: cooldownOverrideMap,
    },
    symbolControls: symbolControls.map((control) => ({
      ...control,
      cooldownOverrideSeconds:
        control.cooldownOverrideSeconds === null
          ? null
          : round(control.cooldownOverrideSeconds, 1),
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
      capitalEfficiencyScore:
        control.capitalEfficiencyScore === null
          ? null
          : round(control.capitalEfficiencyScore, 1),
      capitalWasteRank: control.capitalWasteRank,
      capitalWasteAllocationPct:
        control.capitalWasteAllocationPct === null
          ? null
          : round(control.capitalWasteAllocationPct, 2),
      capitalWasteUnrealizedPct:
        control.capitalWasteUnrealizedPct === null
          ? null
          : round(control.capitalWasteUnrealizedPct, 2),
      capitalWasteAgeHours:
        control.capitalWasteAgeHours === null
          ? null
          : round(control.capitalWasteAgeHours, 2),
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
      advisoryReviewAgeHours:
        row.advisoryReviewAgeHours === null
          ? null
          : round(row.advisoryReviewAgeHours, 2),
      advisoryMaxDrawdownPctDuringTrade: round(
        row.advisoryMaxDrawdownPctDuringTrade,
        2,
      ),
      advisoryMaxDrawdownPriceDuringTrade:
        row.advisoryMaxDrawdownPriceDuringTrade === null
          ? null
          : round(row.advisoryMaxDrawdownPriceDuringTrade, 6),
      advisoryMaxDrawdownAt:
        row.advisoryMaxDrawdownAt === null
          ? null
          : round(row.advisoryMaxDrawdownAt, 3),
    })),
  });
}
