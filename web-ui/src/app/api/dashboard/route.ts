import { promises as fs } from "fs";
import { NextResponse } from "next/server";
import { resolveStateFileCandidates } from "../_lib/stateFallback";
import { analyzeVolatilityOpportunity } from "../../lib/volatilityOpportunityRadar.mjs";
import { analyzeRegimeGovernor } from "../../lib/regimeGovernorAnalyzer.mjs";

export const dynamic = "force-dynamic";
export const revalidate = 0;

type ConfigState = {
  enabled?: boolean;
  trading_enabled?: boolean;
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
  token_regimes?: Record<string, unknown>;
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
    initial_lock?: number;
    levels?: unknown;
    trailing_activation?: number;
    trailing_gap?: number;
    max_negative_z_score?: number;
  };
  market_regime?: {
    preferred_buy_zone?: [number, number];
    min_z_score?: number;
    min_score_to_buy?: number;
    min_atr?: number;
    blocked_regimes?: string[];
    hard_blocked_regimes?: string[];
    max_negative_z_score?: number;
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
  last_configured_regime?: Record<string, string>;
  last_detected_regime?: Record<string, string>;
  last_detected_regime_confidence?: Record<string, number>;
  last_detected_regime_confidence_inferred?: Record<string, boolean>;
  last_detected_regime_confidence_label?: Record<string, string>;
  last_detected_regime_stability?: Record<string, number>;
  last_detected_regime_persistence?: Record<string, number>;
  last_detected_regime_stability_inferred?: Record<string, boolean>;
  last_detected_regime_persistence_inferred?: Record<string, boolean>;
  last_regime_data_quality_status?: Record<string, string>;
  last_regime_key_windows_supported?: Record<string, boolean>;
  last_suggested_regime_v2?: Record<string, string>;
  last_detection_source?: Record<string, string>;
  last_detection_timestamp_epoch?: Record<string, number>;
  last_effective_strategy?: Record<string, string>;
  last_effective_route?: Record<string, string>;
  last_route_eval_ts?: Record<string, number>;
  last_regime_eval_ts?: Record<string, number>;
  last_auto_fallback_reason?: Record<string, string>;
  last_fallback_reason?: Record<string, string>;
  last_ready_for_non_mr_route?: Record<string, boolean>;
  last_non_mr_ready_reason?: Record<string, string>;
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
  exitDiagnostics: {
    canExitNow: boolean;
    blockedBy: string;
    nextGate: string;
    reason: string;
    pnlPct: number | null;
    firstActivationPct: number;
    toFirstActivationPct: number | null;
    currentLockPct: number | null;
    lockPrice: number | null;
    toLockPct: number | null;
    peakPnlPct: number;
    trailingArmed: boolean;
    trailingActivationPct: number;
    zScore: number | null;
    maxNegativeZScore: number;
    structuralBreakEligible: boolean;
  };
};

type SymbolControl = {
  symbol: string;
  configuredRegime: string;
  detectedRegime: string | null;
  detectedRegimeConfidenceLabel: string;
  detectedRegimeConfidenceScore: number | null;
  detectedRegimeConfidenceInferred?: boolean;
  detectedRegimeStabilityScore: number | null;
  detectedRegimePersistenceScore: number | null;
  detectedRegimeStabilityInferred?: boolean;
  detectedRegimePersistenceInferred?: boolean;
  detectedRegimeDataQualityStatus: string;
  detectedRegimeKeyWindowsSupported: boolean;
  suggestedRegimeV2: string | null;
  detectionSource: string;
  detectionTimestampEpoch: number | null;
  routeEvalTimestampEpoch: number | null;
  regimeEvalTimestampEpoch: number | null;
  detectionTimestampAt: string | null;
  detectedRegimeExplanation: string;
  detectedRegimeStructureBias: string;
  detectedRegimeVolatilityState: string;
  detectedRegimeParticipationState: string;
  detectedRegimeTrendScore: number | null;
  detectedRegimeRangeScore: number | null;
  detectedRegimeBreakoutScore: number | null;
  detectedRegimeMixedScore: number | null;
  effectiveStrategy: string;
  effectiveRoute: string;
  autoFallbackReason: string | null;
  fallbackReason: string | null;
  readyForNonMrRoute: boolean;
  nonMrReadyReason: string | null;
  buyEnabled: boolean;
  sellEnabled: boolean;
  hasOpenPosition: boolean;
  scalperEnabled: boolean;
  cooldownOverrideSeconds: number | null;
  buyExecutable: boolean;
  buyExecutableReason: string;
  price: number | null;
  change24hPct: number | null;
  low24h: number | null;
  high24h: number | null;
  regime: string | null;
  volatilityPct: number | null;
  strategyScorePct: number | null;
  buyOpportunityPct: number | null;
  capitalEfficiencyScore: number | null;
  capitalWasteRank: number | null;
  capitalWasteAllocationPct: number | null;
  capitalWasteUnrealizedPct: number | null;
  capitalWasteAgeHours: number | null;
  rotationShortTermScore: number | null;
  rotationMediumTermScore: number | null;
  rotationDelta: number | null;
  rotationStatus: string;
  rotationShortTermWinRatePct: number | null;
  rotationShortTermAvgRealizedPnlUsd: number | null;
  rotationShortTermAvgHoldHours: number | null;
  rotationShortTermAvgRecoveryHours: number | null;
  rotationShortTermStaleReviewFrequencyPct: number | null;
  rotationShortTermAvgMaxDrawdownPct: number | null;
  rotationMediumTermWinRatePct: number | null;
  rotationMediumTermAvgRealizedPnlUsd: number | null;
  rotationMediumTermAvgHoldHours: number | null;
  rotationMediumTermAvgRecoveryHours: number | null;
  rotationMediumTermStaleReviewFrequencyPct: number | null;
  rotationMediumTermAvgMaxDrawdownPct: number | null;
  volatilityOpportunityScore: number | null;
  volatilityOpportunityLabel: string | null;
  volatilityOpportunityReason: string;
  volatilityOpportunityConfidenceLabel: string;
  volatilityOpportunityStretchScore: number | null;
  volatilityOpportunityVolatilitySpikeScore: number | null;
  volatilityOpportunityBounceContextScore: number | null;
  volatilityOpportunityLiquidityQualityScore: number | null;
  volatilityOpportunityObservedHistorySpanMinutes: number;
  volatilityOpportunityObservedPointCount: number;
  volatilityOpportunityInsufficientData: boolean;
  volatilityOpportunityInsufficientReasonCode: string | null;
  volatilityOpportunityInsufficientReasonMessage: string | null;
  volatilityDataQualityStatus: string;
  volatilityDataQualityReason: string;
  regimeDataQualityStatus: string;
  regimeDataQualityReason: string;
};

type SnapshotMetrics = {
  price: number | null;
  change24hPct: number | null;
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

type ClosedTradeRow = {
  tradeId: string;
  symbol: string;
  entryTime: number | null;
  exitTime: number;
  holdHours: number | null;
  pnlUsd: number;
  pnlPct: number | null;
  staleReviewHit: boolean;
  maxDrawdownPct: number;
};

type RotationWindowMetrics = {
  tradeCount: number;
  winRatePct: number | null;
  avgRealizedPnlUsd: number | null;
  avgRealizedPnlPct: number | null;
  avgHoldHours: number | null;
  avgRecoveryHours: number | null;
  staleReviewFrequencyPct: number | null;
  avgMaxDrawdownPct: number | null;
};

type MarketSyncHealth = {
  generated_at?: string;
  adaptive_budget?: {
    base_cap?: number;
    effective_cap?: number;
    under_pressure?: boolean;
    pressure?: {
      rate_limited_count?: number;
      throttle_sleep_seconds_sum?: number;
      throttle_event_count?: number;
      window_seconds?: number;
    };
  };
  sync?: {
    enabled?: boolean;
    attempted_jobs?: number;
    requests?: number;
    inserted?: number;
    new_inserted?: number;
    updated_existing?: number;
    candidate_new?: number;
    eligible_closed?: number;
    skipped_existing?: number;
    skipped_partial?: number;
    errors?: number;
    degraded?: number;
  };
  coverage?: {
    fresh_counts_by_timeframe?: Record<string, number>;
    stale_symbol_timeframes?: number;
    total_rows?: number;
    rows_updated_last_24h?: number;
    status_counts?: Record<string, number>;
  };
  endpoint_telemetry?: {
    fetch_calls?: number;
    success_calls?: number;
    failed_calls?: number;
    official_success_calls?: number;
    public_success_calls?: number;
    active_capabilities?: Record<string, {
      status?: string;
      success_count?: number;
      failure_count?: number;
      last_status_code?: number;
    }>;
  };
  slo?: {
    status?: string;
    coverage_ok?: boolean;
    quality_ok?: boolean;
    throughput_ok?: boolean;
    fresh_1h?: number;
    fresh_4h?: number;
    fresh_24h?: number;
    stale_symbol_timeframes?: number;
    requests?: number;
    new_inserted?: number;
    errors?: number;
    degraded?: number;
  };
};

type SymbolRotationAdvisory = {
  shortTermScore: number | null;
  mediumTermScore: number | null;
  rotationDelta: number | null;
  status: string;
  shortTermMetrics: RotationWindowMetrics;
  mediumTermMetrics: RotationWindowMetrics;
};

const BACKEND = "http://127.0.0.1:8001";
const CONFIG_PATH = resolveStateFileCandidates("config.json");
const PAPER_STATE_PATH = resolveStateFileCandidates("paper_state.json");
const STRATEGY_STATE_PATH = resolveStateFileCandidates("strategy_state.json");
const TRADES_PATH = resolveStateFileCandidates("trades.json");
const LOG_PATH = resolveStateFileCandidates("bot.log");
const PRICE_HISTORY_PATH = resolveStateFileCandidates("revolut_universe_price_history.json");
const MARKET_SYNC_HEALTH_PATH = resolveStateFileCandidates("market_sync_health.json");
const LOG_TAIL_BYTES = 256 * 1024;
const MAX_SNAPSHOT_HISTORY_POINTS = 6000;
const MIN_SNAPSHOT_ANALYTICS_POINTS = 30;

async function readJson<T>(filePath: string | string[], fallback: T): Promise<T> {
  const candidates = Array.isArray(filePath) ? filePath : [filePath];
  for (const candidate of candidates) {
    try {
      const raw = await fs.readFile(candidate, "utf8");
      const normalized = raw.replace(/^\uFEFF/, "");
      if (!normalized.trim()) {
        return fallback;
      }
      return JSON.parse(normalized) as T;
    } catch {
      continue;
    }
  }
  return fallback;
}

async function readLogTail(filePath: string | string[], bytes: number): Promise<string> {
  const candidates = Array.isArray(filePath) ? filePath : [filePath];
  for (const candidate of candidates) {
    let handle:
      | Awaited<ReturnType<typeof fs.open>>
      | undefined;

    try {
      handle = await fs.open(candidate, "r");
      const stat = await handle.stat();
      const bytesToRead = Math.min(bytes, stat.size);

      if (bytesToRead <= 0) {
        continue;
      }

      const buffer = Buffer.alloc(bytesToRead);
      await handle.read(buffer, 0, bytesToRead, stat.size - bytesToRead);
      return buffer.toString("utf8");
    } catch {
      continue;
    } finally {
      await handle?.close();
    }
  }
  return "";
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
    change24hPct:
      asNumber(values.change_24h_pct)
      ?? asNumber(values["24h_change_pct"])
      ?? asNumber(values["24h_change"])
      ?? null,
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

function mergeSnapshotMetricValue<T extends number | string | null>(
  incoming: T | undefined,
  existing: T | undefined,
): T {
  if (incoming !== undefined && incoming !== null) {
    return incoming;
  }
  if (existing !== undefined && existing !== null) {
    return existing;
  }
  return null as T;
}

function mergeSnapshotMetrics(
  existing: SnapshotMetrics | undefined,
  incoming: SnapshotMetrics,
): SnapshotMetrics {
  return {
    price: mergeSnapshotMetricValue(incoming.price, existing?.price),
    change24hPct: mergeSnapshotMetricValue(incoming.change24hPct, existing?.change24hPct),
    vwap: mergeSnapshotMetricValue(incoming.vwap, existing?.vwap),
    atrRaw: mergeSnapshotMetricValue(incoming.atrRaw, existing?.atrRaw),
    momNorm: mergeSnapshotMetricValue(incoming.momNorm, existing?.momNorm),
    points: mergeSnapshotMetricValue(incoming.points, existing?.points),
    low24h: mergeSnapshotMetricValue(incoming.low24h, existing?.low24h),
    high24h: mergeSnapshotMetricValue(incoming.high24h, existing?.high24h),
    spreadBps: mergeSnapshotMetricValue(incoming.spreadBps, existing?.spreadBps),
    quality: mergeSnapshotMetricValue(incoming.quality, existing?.quality),
  };
}

function deriveSnapshotMetricsFromHistory(
  points: SnapshotPoint[],
): Partial<SnapshotMetrics> {
  if (!Array.isArray(points) || points.length === 0) {
    return {};
  }
  const latest = points[points.length - 1];
  const recent24h = points.slice(-1440);
  const shortWindow = points.slice(-60);
  const baselineWindow = points.slice(-240);
  const low24h = recent24h.length > 0
    ? Math.min(...recent24h.map((row) => row.price))
    : null;
  const high24h = recent24h.length > 0
    ? Math.max(...recent24h.map((row) => row.price))
    : null;
  const first24hPrice = recent24h.length > 0 ? recent24h[0].price : null;
  const change24hPct = (
    first24hPrice !== null
    && Number.isFinite(first24hPrice)
    && first24hPrice > 0
    && Number.isFinite(latest.price)
    && latest.price > 0
  )
    ? ((latest.price - first24hPrice) / first24hPrice) * 100
    : null;
  const vwap = baselineWindow.length > 0
    ? baselineWindow.reduce((sum, row) => sum + row.price, 0) / baselineWindow.length
    : null;
  let atrRaw: number | null = null;
  if (baselineWindow.length >= 2) {
    const ranges: number[] = [];
    for (let index = 1; index < baselineWindow.length; index += 1) {
      const prev = baselineWindow[index - 1].price;
      const curr = baselineWindow[index].price;
      if (prev <= 0 || curr <= 0) {
        continue;
      }
      ranges.push(Math.abs(curr - prev));
    }
    if (ranges.length > 0) {
      atrRaw = ranges.reduce((sum, value) => sum + value, 0) / ranges.length;
    }
  }
  let momNorm: number | null = null;
  if (shortWindow.length >= 2 && latest.price > 0) {
    const lookback = shortWindow[0].price;
    if (lookback > 0) {
      momNorm = ((latest.price - lookback) / lookback) * 100;
    }
  }
  return {
    price: latest.price,
    change24hPct,
    points: points.length,
    low24h,
    high24h,
    vwap,
    atrRaw,
    momNorm,
  };
}

async function readLatestSnapshots(
  symbols: string[],
  preferredCanonicalSymbols: string[] = [],
) {
  const snapshots: Record<string, SnapshotMetrics> = {};
  const snapshotHistory: Record<string, SnapshotPoint[]> = {};
  const canonicalSymbols = new Set<string>();
  let lastSnapshotAt: string | null = null;
  const wanted = new Set(symbols);

  if (wanted.size === 0) {
    return { snapshots, snapshotHistory, lastSnapshotAt };
  }

  const canonicalPriority = uniqueSymbols(
    preferredCanonicalSymbols,
    symbols,
  ).slice(0, 40);
  try {
    const symbolParam = canonicalPriority.join(",");
    const controller = new AbortController();
    const timeoutHandle = setTimeout(() => controller.abort(), 6000);
    const response = await fetch(
      `${BACKEND}/market-data/candles-batch?timeframe=1m&limit=1800&symbols=${encodeURIComponent(symbolParam)}`,
      { cache: "no-store", signal: controller.signal },
    ).finally(() => clearTimeout(timeoutHandle));
    if (response.ok) {
      const payload = await response.json() as {
        symbols?: Record<
          string,
          {
            status?: string;
            points?: Array<{ tsEpoch?: number; price?: number }>;
            latest?: { tsEpoch?: number; price?: number } | null;
            meta?: { stale?: boolean };
          }
        >;
      };
      const symbolRows = payload?.symbols ?? {};
      for (const symbol of symbols) {
        const row = symbolRows[symbol];
        if (!row || row.status !== "ok" || !Array.isArray(row.points) || row.points.length === 0) {
          continue;
        }
        const points = row.points
          .map((point) => ({
            tsEpoch: Number(point?.tsEpoch ?? 0),
            price: Number(point?.price ?? 0),
          }))
          .filter((point) => Number.isFinite(point.tsEpoch) && point.tsEpoch > 0 && Number.isFinite(point.price) && point.price > 0)
          .sort((left, right) => left.tsEpoch - right.tsEpoch);
        if (points.length === 0) {
          continue;
        }
        canonicalSymbols.add(symbol);
        snapshotHistory[symbol] = points.slice(-MAX_SNAPSHOT_HISTORY_POINTS);
        const latest = points[points.length - 1];
        snapshots[symbol] = {
          price: latest.price,
          change24hPct: null,
          vwap: null,
          atrRaw: null,
          momNorm: null,
          points: points.length,
          low24h: null,
          high24h: null,
          spreadBps: null,
          quality: row.meta?.stale ? "stale" : "ok",
        };
        lastSnapshotAt = new Date(latest.tsEpoch * 1000).toISOString().replace("T", " ").slice(0, 19);
      }
    }
  } catch {
    // Keep legacy fallback path below.
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
    const canonicalPrice = canonicalSymbols.has(symbol)
      ? snapshots[symbol]?.price ?? null
      : null;
    const merged = mergeSnapshotMetrics(snapshots[symbol], parsed);
    snapshots[symbol] = (
      canonicalPrice !== null
      && Number.isFinite(canonicalPrice)
      && canonicalPrice > 0
    )
      ? { ...merged, price: canonicalPrice }
      : merged;
    lastSnapshotAt = match[1];

    if (parsed.price !== null && parsed.price > 0) {
      if (canonicalSymbols.has(symbol)) {
        continue;
      }
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

  const symbolsNeedingSupplement = symbols.filter((symbol) => {
    const points = Array.isArray(snapshotHistory[symbol]) ? snapshotHistory[symbol].length : 0;
    return points < MIN_SNAPSHOT_ANALYTICS_POINTS;
  });
  const priceHistory = symbolsNeedingSupplement.length > 0
    ? await readJson<Record<string, Array<{ ts?: number; tsEpoch?: number; price?: number }>>>(
      PRICE_HISTORY_PATH,
      {},
    )
    : {};
  for (const symbol of symbols) {
    const rows = Array.isArray(priceHistory[symbol]) ? priceHistory[symbol] : [];
    if (!(symbol in snapshotHistory)) {
      snapshotHistory[symbol] = [];
    }
    const shouldSupplementFromPriceHistory = (
      !canonicalSymbols.has(symbol)
      || snapshotHistory[symbol].length < MIN_SNAPSHOT_ANALYTICS_POINTS
    );
    if (shouldSupplementFromPriceHistory) {
      for (const row of rows.slice(-MAX_SNAPSHOT_HISTORY_POINTS)) {
        const tsEpoch = Number(row?.tsEpoch ?? row?.ts ?? 0);
        const price = Number(row?.price ?? 0);
        if (!Number.isFinite(tsEpoch) || tsEpoch <= 0 || !Number.isFinite(price) || price <= 0) {
          continue;
        }
        snapshotHistory[symbol].push({ tsEpoch, price });
        snapshots[symbol] = mergeSnapshotMetrics(snapshots[symbol], {
          price,
          change24hPct: null,
          vwap: null,
          atrRaw: null,
          momNorm: null,
          points: null,
          low24h: null,
          high24h: null,
          spreadBps: null,
          quality: "ok",
        });
        if (lastSnapshotAt === null || tsEpoch > Number(parseLogTimestampToEpoch(lastSnapshotAt) ?? 0)) {
          lastSnapshotAt = new Date(tsEpoch * 1000).toISOString().replace("T", " ").slice(0, 19);
        }
      }
    }
    snapshotHistory[symbol].sort((left, right) => left.tsEpoch - right.tsEpoch);
    const deduped: SnapshotPoint[] = [];
    for (const row of snapshotHistory[symbol]) {
      const prev = deduped[deduped.length - 1];
      if (prev && prev.tsEpoch === row.tsEpoch && prev.price === row.price) {
        continue;
      }
      deduped.push(row);
    }
    snapshotHistory[symbol] = deduped.slice(-MAX_SNAPSHOT_HISTORY_POINTS);

    const latest = snapshotHistory[symbol][snapshotHistory[symbol].length - 1];
    if (latest) {
      const derived = deriveSnapshotMetricsFromHistory(snapshotHistory[symbol]);
      snapshots[symbol] = mergeSnapshotMetrics(snapshots[symbol], {
        price: derived.price ?? latest.price,
        change24hPct: derived.change24hPct ?? null,
        vwap: derived.vwap ?? null,
        atrRaw: derived.atrRaw ?? null,
        momNorm: derived.momNorm ?? null,
        points: derived.points ?? snapshotHistory[symbol].length,
        low24h: derived.low24h ?? null,
        high24h: derived.high24h ?? null,
        spreadBps: null,
        quality: snapshots[symbol]?.quality ?? "ok",
      });
      if (lastSnapshotAt === null || latest.tsEpoch > Number(parseLogTimestampToEpoch(lastSnapshotAt) ?? 0)) {
        lastSnapshotAt = new Date(latest.tsEpoch * 1000).toISOString().replace("T", " ").slice(0, 19);
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

function buildClosedTradesBySymbol(
  trades: TradeEntry[],
  staleReviewAgeHours: number,
  staleReviewUnrealizedPnlPct: number,
) {
  const sortedTrades = [...trades].sort(
    (left, right) => Number(left.time ?? 0) - Number(right.time ?? 0),
  );
  const buyQueueBySymbol: Record<string, TradeEntry[]> = {};
  const closedBySymbol: Record<string, ClosedTradeRow[]> = {};

  for (let index = 0; index < sortedTrades.length; index += 1) {
    const trade = sortedTrades[index];
    const symbol = normalizeSymbol(trade.symbol);
    const side = String(trade.side ?? "").toUpperCase();
    const tradeTime = asFiniteNumber(trade.time);
    if (!symbol || tradeTime === null || tradeTime <= 0) {
      continue;
    }

    if (side === "BUY") {
      if (!(symbol in buyQueueBySymbol)) {
        buyQueueBySymbol[symbol] = [];
      }
      buyQueueBySymbol[symbol].push(trade);
      continue;
    }

    if (side !== "SELL") {
      continue;
    }

    const buyQueue = buyQueueBySymbol[symbol] ?? [];
    const matchedBuy = buyQueue.length > 0 ? buyQueue.shift() ?? null : null;
    buyQueueBySymbol[symbol] = buyQueue;

    const entryPrice = matchedBuy === null ? null : asFiniteNumber(matchedBuy.price);
    const exitPrice = asFiniteNumber(trade.price);
    const entryTime = matchedBuy === null ? null : asFiniteNumber(matchedBuy.time);
    const pnlUsd = asFiniteNumber(trade.pnl) ?? 0;
    const holdHours = (
      entryTime === null || entryTime <= 0
    )
      ? null
      : Math.max((tradeTime - entryTime) / 3600, 0);
    const pnlPct = (
      entryPrice !== null
      && entryPrice > 0
      && exitPrice !== null
      && exitPrice > 0
    )
      ? ((exitPrice - entryPrice) / entryPrice) * 100
      : null;
    const staleReviewHit = (
      holdHours !== null
      && pnlPct !== null
      && holdHours >= staleReviewAgeHours
      && pnlPct <= staleReviewUnrealizedPnlPct
    );
    const maxDrawdownPct = pnlPct === null ? 0 : Math.min(pnlPct, 0);

    if (!(symbol in closedBySymbol)) {
      closedBySymbol[symbol] = [];
    }
    closedBySymbol[symbol].push({
      tradeId: `${symbol}:${tradeTime}:${index}`,
      symbol,
      entryTime,
      exitTime: tradeTime,
      holdHours,
      pnlUsd,
      pnlPct,
      staleReviewHit,
      maxDrawdownPct,
    });
  }

  for (const rows of Object.values(closedBySymbol)) {
    rows.sort((left, right) => right.exitTime - left.exitTime);
  }
  return closedBySymbol;
}

function selectRollingWindowRows(
  rows: ClosedTradeRow[],
  nowEpochSeconds: number,
  dayWindow: number,
  tradeWindow: number,
) {
  if (!Array.isArray(rows) || rows.length === 0) {
    return [];
  }
  const cutoffEpoch = nowEpochSeconds - (dayWindow * 86400);
  const byDays = rows.filter((row) => row.exitTime >= cutoffEpoch);
  const byTrades = rows.slice(0, Math.max(1, Math.trunc(tradeWindow)));
  const deduped = new Map<string, ClosedTradeRow>();
  for (const row of byDays) {
    deduped.set(row.tradeId, row);
  }
  for (const row of byTrades) {
    deduped.set(row.tradeId, row);
  }
  return Array.from(deduped.values()).sort((left, right) => right.exitTime - left.exitTime);
}

function average(values: number[]) {
  if (values.length === 0) {
    return null;
  }
  return sum(values) / values.length;
}

function computeRotationWindowMetrics(rows: ClosedTradeRow[]): RotationWindowMetrics {
  if (!Array.isArray(rows) || rows.length === 0) {
    return {
      tradeCount: 0,
      winRatePct: null,
      avgRealizedPnlUsd: null,
      avgRealizedPnlPct: null,
      avgHoldHours: null,
      avgRecoveryHours: null,
      staleReviewFrequencyPct: null,
      avgMaxDrawdownPct: null,
    };
  }

  const wins = rows.filter((row) => row.pnlUsd > 0);
  const pnlUsdValues = rows.map((row) => row.pnlUsd);
  const pnlPctValues = rows
    .map((row) => row.pnlPct)
    .filter((value): value is number => value !== null);
  const holdValues = rows
    .map((row) => row.holdHours)
    .filter((value): value is number => value !== null);
  const recoveryValues = rows
    .filter((row) => row.pnlUsd > 0)
    .map((row) => row.holdHours)
    .filter((value): value is number => value !== null);
  const staleHits = rows.filter((row) => row.staleReviewHit).length;
  const maxDrawdownValues = rows.map((row) => row.maxDrawdownPct);

  return {
    tradeCount: rows.length,
    winRatePct: (wins.length / rows.length) * 100,
    avgRealizedPnlUsd: average(pnlUsdValues),
    avgRealizedPnlPct: average(pnlPctValues),
    avgHoldHours: average(holdValues),
    avgRecoveryHours: average(recoveryValues),
    staleReviewFrequencyPct: (staleHits / rows.length) * 100,
    avgMaxDrawdownPct: average(maxDrawdownValues),
  };
}

function computeRotationScore(metrics: RotationWindowMetrics) {
  if (metrics.tradeCount <= 0 || metrics.winRatePct === null) {
    return null;
  }

  const winNorm = clamp(metrics.winRatePct / 100, 0, 1);
  const pnlNorm = clamp(((metrics.avgRealizedPnlPct ?? 0) + 6) / 12, 0, 1);
  const holdNorm = metrics.avgHoldHours === null
    ? 0.5
    : clamp(1 - (metrics.avgHoldHours / 72), 0, 1);
  const recoveryNorm = metrics.avgRecoveryHours === null
    ? holdNorm
    : clamp(1 - (metrics.avgRecoveryHours / 96), 0, 1);
  const stalePenalty = clamp((metrics.staleReviewFrequencyPct ?? 0) / 100, 0, 1);
  const drawdownPenalty = clamp(
    Math.abs(Math.min(metrics.avgMaxDrawdownPct ?? 0, 0)) / 15,
    0,
    1,
  );

  const base = (
    (0.35 * winNorm)
    + (0.30 * pnlNorm)
    + (0.15 * holdNorm)
    + (0.10 * recoveryNorm)
    + (0.10 * (1 - stalePenalty))
  );
  return clamp((base - (0.15 * drawdownPenalty)) * 100, 0, 100);
}

function classifyRotationStatus(
  shortScore: number | null,
  mediumScore: number | null,
  delta: number | null,
  shortMetrics: RotationWindowMetrics,
  mediumMetrics: RotationWindowMetrics,
) {
  const short = shortScore ?? mediumScore ?? 50;
  const medium = mediumScore ?? shortScore ?? 50;
  const rotationDelta = delta ?? 0;
  const staleFrequency = shortMetrics.staleReviewFrequencyPct
    ?? mediumMetrics.staleReviewFrequencyPct
    ?? 0;
  const drawdown = shortMetrics.avgMaxDrawdownPct
    ?? mediumMetrics.avgMaxDrawdownPct
    ?? 0;

  if (
    short < 35
    && medium < 40
    && staleFrequency >= 30
    && drawdown <= -8
  ) {
    return "Capital Trap Risk";
  }
  if (short >= 68 && medium >= 60 && rotationDelta >= 6) {
    return "Rising";
  }
  if (short >= 65 && medium >= 65 && Math.abs(rotationDelta) <= 6) {
    return "Strong";
  }
  if (short <= 32 && medium <= 40 && rotationDelta <= -6) {
    return "Cold";
  }
  if (rotationDelta <= -8 || (short < medium && short < 52)) {
    return "Weakening";
  }
  return "Neutral";
}

function buildSymbolRotationAdvisory(
  rows: ClosedTradeRow[],
  nowEpochSeconds: number,
): SymbolRotationAdvisory {
  const shortRows = selectRollingWindowRows(rows, nowEpochSeconds, 7, 10);
  const mediumRows = selectRollingWindowRows(rows, nowEpochSeconds, 30, 30);
  const shortMetrics = computeRotationWindowMetrics(shortRows);
  const mediumMetrics = computeRotationWindowMetrics(mediumRows);
  const shortTermScore = computeRotationScore(shortMetrics);
  const mediumTermScore = computeRotationScore(mediumMetrics);
  const rotationDelta = (
    shortTermScore === null || mediumTermScore === null
  )
    ? null
    : shortTermScore - mediumTermScore;
  const status = classifyRotationStatus(
    shortTermScore,
    mediumTermScore,
    rotationDelta,
    shortMetrics,
    mediumMetrics,
  );

  return {
    shortTermScore,
    mediumTermScore,
    rotationDelta,
    status,
    shortTermMetrics: shortMetrics,
    mediumTermMetrics: mediumMetrics,
  };
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

function roundPrice(value: number) {
  if (!Number.isFinite(value)) {
    return 0;
  }
  const abs = Math.abs(value);
  const digits = abs > 0 && abs < 1 ? 8 : 6;
  return Number(value.toFixed(digits));
}

function sum(values: number[]) {
  return values.reduce((total, value) => total + value, 0);
}

function normalizeSymbol(value: unknown) {
  if (typeof value !== "string") {
    return "";
  }
  return value
    .trim()
    .toUpperCase()
    .replace(/[/_]+/g, "-");
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

function parseTextMap(values: unknown) {
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
    const normalized = rawValue.trim();
    if (!normalized) {
      continue;
    }
    output[symbol] = normalized;
  }

  return output;
}

const TOKEN_REGIME_VALUES = new Set([
  "AUTO",
  "MEAN_REVERSION",
  "TREND_PULLBACK",
  "BREAKOUT_MOMENTUM",
  "OBSERVE_ONLY",
]);

function parseTokenRegimeMap(values: unknown) {
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
    const normalized = rawValue.trim().toUpperCase();
    if (!TOKEN_REGIME_VALUES.has(normalized)) {
      continue;
    }
    output[symbol] = normalized;
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

function normalizeEffectiveStrategy(value: unknown) {
  const raw = String(value ?? "").trim().toLowerCase();
  if (raw === "trend_pullback") {
    return "trend_pullback";
  }
  if (raw === "breakout_momentum") {
    return "breakout_momentum";
  }
  if (raw === "observe_only") {
    return "observe_only";
  }
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

function confidenceLabelFromScore(score: number | null) {
  if (score === null || !Number.isFinite(score)) {
    return null;
  }
  if (score >= 70) {
    return "HIGH";
  }
  if (score >= 45) {
    return "MEDIUM";
  }
  return "LOW";
}

function confidenceScoreFromLabel(label: unknown) {
  const normalized = String(label ?? "").trim().toUpperCase();
  if (normalized === "HIGH") {
    return 85;
  }
  if (normalized === "MEDIUM") {
    return 62;
  }
  if (normalized === "LOW") {
    return 35;
  }
  return null;
}

function resolveRegimeCspBackfill(args: {
  confidenceScore: number | null;
  runtimeStability: number | null;
  runtimePersistence: number | null;
  advisoryStability: number | null;
  advisoryPersistence: number | null;
  runtimeStabilityInferred: boolean;
  runtimePersistenceInferred: boolean;
  advisoryStabilityInferred: boolean;
  advisoryPersistenceInferred: boolean;
}) {
  const confidenceScore = asFiniteNumber(args.confidenceScore);
  let stabilityScore = asFiniteNumber(args.runtimeStability)
    ?? asFiniteNumber(args.advisoryStability);
  let persistenceScore = asFiniteNumber(args.runtimePersistence)
    ?? asFiniteNumber(args.advisoryPersistence);
  let stabilityInferred = Boolean(args.runtimeStabilityInferred || args.advisoryStabilityInferred);
  let persistenceInferred = Boolean(args.runtimePersistenceInferred || args.advisoryPersistenceInferred);

  if (stabilityScore === null && confidenceScore !== null) {
    stabilityScore = confidenceScore;
    stabilityInferred = true;
  }
  if (persistenceScore === null && confidenceScore !== null) {
    persistenceScore = confidenceScore;
    persistenceInferred = true;
  }

  return {
    stabilityScore,
    persistenceScore,
    stabilityInferred,
    persistenceInferred,
  };
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

function deriveConfiguredEffectiveStrategy(
  configuredRegime: string,
  strategyMode: string,
) {
  if (configuredRegime === "OBSERVE_ONLY") {
    return "observe_only";
  }
  if (configuredRegime === "TREND_PULLBACK") {
    return "trend_pullback";
  }
  if (configuredRegime === "BREAKOUT_MOMENTUM") {
    return "breakout_momentum";
  }
  return normalizeEffectiveStrategy(strategyMode);
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

function normalizeProfitLevels(raw: unknown): Array<[number, number]> {
  const defaults: Array<[number, number]> = [
    [0.04, 0.03],
    [0.05, 0.04],
    [0.06, 0.05],
    [0.08, 0.06],
  ];
  if (!Array.isArray(raw)) {
    return defaults;
  }
  const rows: Array<[number, number]> = [];
  for (const item of raw) {
    if (!Array.isArray(item) || item.length < 2) {
      continue;
    }
    const trigger = asFiniteNumber(item[0]);
    const lock = asFiniteNumber(item[1]);
    if (trigger === null || lock === null) {
      continue;
    }
    rows.push([trigger, lock]);
  }
  return rows.length > 0 ? rows : defaults;
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
  const [config, paper, strategy, trades, marketSyncHealth] = await Promise.all([
    readJson<ConfigState>(CONFIG_PATH, {}),
    readJson<PaperState>(PAPER_STATE_PATH, {}),
    readJson<StrategyState>(STRATEGY_STATE_PATH, {}),
    readJson<TradeEntry[]>(TRADES_PATH, []),
    readJson<MarketSyncHealth>(MARKET_SYNC_HEALTH_PATH, {}),
  ]);

  const positions = paper.positions ?? {};
  const positionSymbols = Object.keys(positions);
  const configuredSymbols = normalizeSymbols(config.symbols);
  const legacyMap = parseEnabledMap(config.symbol_enabled);
  const buyMap = parseEnabledMap(config.symbol_buy_enabled);
  const sellMap = parseEnabledMap(config.symbol_sell_enabled);
  const symbolStrategies = parseStrategyMap(config.symbol_strategies);
  const strategyOverrides = parseStrategyMap(config.strategy_overrides);
  const tokenRegimes = parseTokenRegimeMap(config.token_regimes);
  const scalperSymbols = parseScalperSymbolSet(config);
  const regimeMap = parseStringMap(strategy.last_regime);
  const scoreMap = parseNumberMap(strategy.last_score);
  const volatilityMap = parseNumberMap(strategy.last_volatility);
  const runtimeConfiguredRegimeMap = parseTokenRegimeMap(strategy.last_configured_regime);
  const runtimeDetectedRegimeMap = parseTextMap(strategy.last_detected_regime);
  const runtimeDetectedRegimeConfidenceMap = parseNumberMap(strategy.last_detected_regime_confidence);
  const runtimeDetectedRegimeConfidenceInferredMap = parseEnabledMap(
    strategy.last_detected_regime_confidence_inferred,
  );
  const runtimeDetectedRegimeConfidenceLabelMap = parseTextMap(strategy.last_detected_regime_confidence_label);
  const runtimeDetectedRegimeStabilityMap = parseNumberMap(strategy.last_detected_regime_stability);
  const runtimeDetectedRegimePersistenceMap = parseNumberMap(strategy.last_detected_regime_persistence);
  const runtimeDetectedRegimeStabilityInferredMap = parseEnabledMap(strategy.last_detected_regime_stability_inferred);
  const runtimeDetectedRegimePersistenceInferredMap = parseEnabledMap(strategy.last_detected_regime_persistence_inferred);
  const runtimeDetectedRegimeDataQualityStatusMap = parseTextMap(strategy.last_regime_data_quality_status);
  const runtimeDetectedRegimeKeyWindowsSupportedMap = parseEnabledMap(strategy.last_regime_key_windows_supported);
  const runtimeSuggestedRegimeV2Map = parseTextMap(strategy.last_suggested_regime_v2);
  const runtimeDetectionSourceMap = parseTextMap(strategy.last_detection_source);
  const runtimeDetectionTimestampEpochMap = parseNumberMap(strategy.last_detection_timestamp_epoch);
  const runtimeEffectiveStrategyMap = parseTextMap(strategy.last_effective_strategy);
  const runtimeEffectiveRouteMap = parseTextMap(strategy.last_effective_route);
  const runtimeRouteEvalTimestampEpochMap = parseNumberMap(strategy.last_route_eval_ts);
  const runtimeRegimeEvalTimestampEpochMap = parseNumberMap(strategy.last_regime_eval_ts);
  const runtimeAutoFallbackReasonMap = parseTextMap(strategy.last_auto_fallback_reason);
  const runtimeFallbackReasonMap = parseTextMap(strategy.last_fallback_reason);
  const runtimeReadyForNonMrRouteMap = parseEnabledMap(strategy.last_ready_for_non_mr_route);
  const runtimeNonMrReadyReasonMap = parseTextMap(strategy.last_non_mr_ready_reason);
  const allSymbols = uniqueSymbols(
    configuredSymbols,
    Object.keys(legacyMap),
    Object.keys(buyMap),
    Object.keys(sellMap),
    Object.keys(symbolStrategies),
    Object.keys(strategyOverrides),
    Object.keys(tokenRegimes),
    Object.keys(runtimeConfiguredRegimeMap),
    Array.from(scalperSymbols),
    positionSymbols,
  );

  const { snapshots, snapshotHistory, lastSnapshotAt } = await readLatestSnapshots(
    allSymbols,
    positionSymbols,
  );
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
  const closedTradesBySymbol = buildClosedTradesBySymbol(
    trades,
    staleLosingReviewAgeHours,
    staleLosingReviewUnrealizedPnlPct,
  );
  const rotationBySymbol: Record<string, SymbolRotationAdvisory> = {};
  for (const symbol of allSymbols) {
    rotationBySymbol[symbol] = buildSymbolRotationAdvisory(
      closedTradesBySymbol[symbol] ?? [],
      nowEpochSeconds,
    );
  }
  const volatilityOpportunityBySymbol: Record<string, ReturnType<typeof analyzeVolatilityOpportunity>> = {};
  const regimeAdvisoryBySymbol: Record<string, ReturnType<typeof analyzeRegimeGovernor>> = {};
  for (const symbol of allSymbols) {
    const history = snapshotHistory[symbol] ?? [];
    const anchorNow = history.length > 0
      ? history[history.length - 1].tsEpoch
      : nowEpochSeconds;
    volatilityOpportunityBySymbol[symbol] = analyzeVolatilityOpportunity({
      symbol,
      pricePoints: history,
      latestSnapshot: snapshots[symbol] ?? null,
      nowEpoch: anchorNow,
      wallClockEpoch: nowEpochSeconds,
    });
    regimeAdvisoryBySymbol[symbol] = analyzeRegimeGovernor({
      symbol,
      pricePoints: history,
      latestSnapshot: snapshots[symbol] ?? null,
      nowEpoch: anchorNow,
    });
  }
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
    const runtimeScore = scoreMap[symbol] ?? null;
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
    const rotation = rotationBySymbol[symbol];
    const volatilityOpportunity = volatilityOpportunityBySymbol[symbol];
    const regimeAdvisory = regimeAdvisoryBySymbol[symbol];
    const configuredRegime = tokenRegimes[symbol]
      ?? runtimeConfiguredRegimeMap[symbol]
      ?? "MEAN_REVERSION";
    const runtimeDetectedRegime = runtimeDetectedRegimeMap[symbol] ?? null;
    const runtimeDetectedRegimeConfidence = runtimeDetectedRegimeConfidenceMap[symbol] ?? null;
    const runtimeDetectedRegimeConfidenceInferred =
      runtimeDetectedRegimeConfidenceInferredMap[symbol] ?? false;
    const runtimeDetectedRegimeConfidenceLabel = runtimeDetectedRegimeConfidenceLabelMap[symbol] ?? null;
    const runtimeDetectedRegimeStability = runtimeDetectedRegimeStabilityMap[symbol] ?? null;
    const runtimeDetectedRegimePersistence = runtimeDetectedRegimePersistenceMap[symbol] ?? null;
    const runtimeDetectedRegimeStabilityInferred = runtimeDetectedRegimeStabilityInferredMap[symbol] ?? false;
    const runtimeDetectedRegimePersistenceInferred = runtimeDetectedRegimePersistenceInferredMap[symbol] ?? false;
    const runtimeDetectedRegimeDataQualityStatus = runtimeDetectedRegimeDataQualityStatusMap[symbol] ?? null;
    const runtimeDetectedRegimeKeyWindowsSupported = runtimeDetectedRegimeKeyWindowsSupportedMap[symbol] ?? false;
    const runtimeSuggestedRegimeV2 = runtimeSuggestedRegimeV2Map[symbol] ?? null;
    const detectedRegime = runtimeDetectedRegime ?? regimeAdvisory?.suggestedRegime ?? null;
    const advisoryConfidenceScore = asFiniteNumber(
      regimeAdvisory?.confidenceScore ?? regimeAdvisory?.confidence_score ?? null,
    );
    const advisoryConfidenceLabelRaw = (
      regimeAdvisory?.confidenceLabel
      ?? regimeAdvisory?.confidence_label
      ?? null
    );
    const detectedRegimeConfidenceScore = (
      runtimeDetectedRegimeConfidence
      ?? advisoryConfidenceScore
      ?? confidenceScoreFromLabel(runtimeDetectedRegimeConfidenceLabel ?? advisoryConfidenceLabelRaw)
    );
    const detectedRegimeConfidenceLabel = (
      runtimeDetectedRegimeConfidenceLabel
      ?? advisoryConfidenceLabelRaw
      ?? confidenceLabelFromScore(detectedRegimeConfidenceScore)
      ?? "LOW"
    ).toUpperCase();
    const detectedRegimeConfidenceInferred = runtimeDetectedRegimeConfidenceInferred
      || (runtimeDetectedRegimeConfidence === null && detectedRegimeConfidenceScore !== null);
    const advisoryStabilityScore = asFiniteNumber(
      regimeAdvisory?.stability_score ?? regimeAdvisory?.stabilityScore ?? null,
    );
    const advisoryPersistenceScore = asFiniteNumber(
      regimeAdvisory?.persistence_score ?? regimeAdvisory?.persistenceScore ?? null,
    );
    const cspBackfill = resolveRegimeCspBackfill({
      confidenceScore: detectedRegimeConfidenceScore,
      runtimeStability: runtimeDetectedRegimeStability,
      runtimePersistence: runtimeDetectedRegimePersistence,
      advisoryStability: advisoryStabilityScore,
      advisoryPersistence: advisoryPersistenceScore,
      runtimeStabilityInferred: runtimeDetectedRegimeStabilityInferred,
      runtimePersistenceInferred: runtimeDetectedRegimePersistenceInferred,
      advisoryStabilityInferred:
        (regimeAdvisory?.stability_inferred === true)
        || (regimeAdvisory?.stabilityInferred === true),
      advisoryPersistenceInferred:
        (regimeAdvisory?.persistence_inferred === true)
        || (regimeAdvisory?.persistenceInferred === true),
    });
    const effectiveStrategy = normalizeEffectiveStrategy(
      runtimeEffectiveStrategyMap[symbol]
      ?? deriveConfiguredEffectiveStrategy(configuredRegime, strategyMode),
    );
    const effectiveRoute = normalizeEffectiveStrategy(
      runtimeEffectiveRouteMap[symbol]
      ?? runtimeEffectiveStrategyMap[symbol]
      ?? deriveConfiguredEffectiveStrategy(configuredRegime, strategyMode),
    );
    const autoFallbackReason = runtimeAutoFallbackReasonMap[symbol] ?? null;
    const fallbackReason = runtimeFallbackReasonMap[symbol] ?? autoFallbackReason;
    const readyForNonMrRoute = runtimeReadyForNonMrRouteMap[symbol] ?? false;
    const nonMrReadyReason = runtimeNonMrReadyReasonMap[symbol] ?? fallbackReason ?? null;
    const detectionSource = (
      runtimeDetectionSourceMap[symbol]
      ?? regimeAdvisory?.detectionSource
      ?? "advisory_multitimeframe"
    );
    const detectionTimestampEpoch = runtimeDetectionTimestampEpochMap[symbol]
      ?? regimeAdvisory?.analysisAnchorEpoch
      ?? null;
    const detectionTimestampAt = (
      detectionTimestampEpoch === null
      || !Number.isFinite(detectionTimestampEpoch)
    )
      ? null
      : new Date(detectionTimestampEpoch * 1000).toISOString();
    const routeEvalTimestampEpoch = runtimeRouteEvalTimestampEpochMap[symbol] ?? null;
    const regimeEvalTimestampEpoch = runtimeRegimeEvalTimestampEpochMap[symbol] ?? detectionTimestampEpoch ?? null;
    const regimeComponentScores = regimeAdvisory?.componentScores ?? null;
    const symbolAllocatedUsd = symbolCostBasisUsd[symbol] ?? 0;
    const executableStatus = computeBuyExecutableStatus({
      buyEnabled,
      hasOpenPosition,
      openPositionsForSymbol: hasOpenPosition ? 1 : 0,
      snapshot,
      score: runtimeScore,
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
    const buyOpportunityPct = computeBuyOpportunityPct(snapshot, config);
    const displayStrategyScore = runtimeScore ?? buyOpportunityPct;

    return {
      symbol,
      configuredRegime,
      detectedRegime,
      detectedRegimeConfidenceLabel,
      detectedRegimeConfidenceScore,
      detectedRegimeConfidenceInferred,
      detectedRegimeStabilityScore:
        cspBackfill.stabilityScore,
      detectedRegimePersistenceScore:
        cspBackfill.persistenceScore,
      detectedRegimeStabilityInferred:
        cspBackfill.stabilityInferred,
      detectedRegimePersistenceInferred:
        cspBackfill.persistenceInferred,
      detectedRegimeDataQualityStatus:
        (runtimeDetectedRegimeDataQualityStatus ?? regimeAdvisory?.data_quality?.status ?? "UNKNOWN").toUpperCase(),
      detectedRegimeKeyWindowsSupported:
        runtimeDetectedRegimeKeyWindowsSupported,
      suggestedRegimeV2: runtimeSuggestedRegimeV2 ?? detectedRegime,
      detectionSource,
      detectionTimestampEpoch,
      routeEvalTimestampEpoch,
      regimeEvalTimestampEpoch,
      detectionTimestampAt,
      detectedRegimeExplanation: regimeAdvisory?.explanation ?? "Insufficient advisory context",
      detectedRegimeStructureBias: regimeAdvisory?.components?.structureBias ?? "UNCLEAR",
      detectedRegimeVolatilityState: regimeAdvisory?.components?.volatilityState ?? "NORMAL",
      detectedRegimeParticipationState: regimeAdvisory?.components?.participationState ?? "NORMAL",
      detectedRegimeTrendScore: regimeComponentScores?.trend_score ?? regimeComponentScores?.trendScore ?? null,
      detectedRegimeRangeScore: regimeComponentScores?.range_score ?? regimeComponentScores?.rangeScore ?? null,
      detectedRegimeBreakoutScore: regimeComponentScores?.breakout_score ?? regimeComponentScores?.breakoutScore ?? null,
      detectedRegimeMixedScore: regimeComponentScores?.mixed_score ?? regimeComponentScores?.mixedScore ?? null,
      effectiveStrategy,
      effectiveRoute,
      autoFallbackReason,
      fallbackReason,
      readyForNonMrRoute,
      nonMrReadyReason,
      buyEnabled,
      sellEnabled: sellMap[symbol] ?? legacyMap[symbol] ?? true,
      hasOpenPosition,
      scalperEnabled: strategyMode === "volatility_scalper",
      cooldownOverrideSeconds: cooldownOverrideMap[symbol] ?? null,
      buyExecutable: executableStatus.buyExecutable,
      buyExecutableReason: executableStatus.buyExecutableReason,
      price: snapshot?.price ?? null,
      change24hPct: snapshot?.change24hPct ?? null,
      low24h: snapshot?.low24h ?? null,
      high24h: snapshot?.high24h ?? null,
      regime: formatRegimeLabel(regimeRaw),
      volatilityPct:
        volatilityRaw === null ? null : Number(volatilityRaw) * 100,
      strategyScorePct: displayStrategyScore,
      buyOpportunityPct,
      capitalEfficiencyScore: capitalEfficiency?.score ?? null,
      capitalWasteRank: capitalEfficiency?.rank ?? null,
      capitalWasteAllocationPct: capitalEfficiency?.allocationPct ?? null,
      capitalWasteUnrealizedPct: capitalEfficiency?.unrealizedPct ?? null,
      capitalWasteAgeHours: capitalEfficiency?.ageHours ?? null,
      rotationShortTermScore: rotation?.shortTermScore ?? null,
      rotationMediumTermScore: rotation?.mediumTermScore ?? null,
      rotationDelta: rotation?.rotationDelta ?? null,
      rotationStatus: rotation?.status ?? "Neutral",
      rotationShortTermWinRatePct: rotation?.shortTermMetrics.winRatePct ?? null,
      rotationShortTermAvgRealizedPnlUsd: rotation?.shortTermMetrics.avgRealizedPnlUsd ?? null,
      rotationShortTermAvgHoldHours: rotation?.shortTermMetrics.avgHoldHours ?? null,
      rotationShortTermAvgRecoveryHours: rotation?.shortTermMetrics.avgRecoveryHours ?? null,
      rotationShortTermStaleReviewFrequencyPct:
        rotation?.shortTermMetrics.staleReviewFrequencyPct ?? null,
      rotationShortTermAvgMaxDrawdownPct:
        rotation?.shortTermMetrics.avgMaxDrawdownPct ?? null,
      rotationMediumTermWinRatePct: rotation?.mediumTermMetrics.winRatePct ?? null,
      rotationMediumTermAvgRealizedPnlUsd:
        rotation?.mediumTermMetrics.avgRealizedPnlUsd ?? null,
      rotationMediumTermAvgHoldHours: rotation?.mediumTermMetrics.avgHoldHours ?? null,
      rotationMediumTermAvgRecoveryHours:
        rotation?.mediumTermMetrics.avgRecoveryHours ?? null,
      rotationMediumTermStaleReviewFrequencyPct:
        rotation?.mediumTermMetrics.staleReviewFrequencyPct ?? null,
      rotationMediumTermAvgMaxDrawdownPct:
        rotation?.mediumTermMetrics.avgMaxDrawdownPct ?? null,
      volatilityOpportunityScore: volatilityOpportunity?.score ?? null,
      volatilityOpportunityLabel: volatilityOpportunity?.label ?? null,
      volatilityOpportunityReason: volatilityOpportunity?.reason ?? "Insufficient data",
      volatilityOpportunityConfidenceLabel: volatilityOpportunity?.confidence_label ?? "LOW",
      volatilityOpportunityStretchScore: volatilityOpportunity?.stretch_score ?? null,
      volatilityOpportunityVolatilitySpikeScore:
        volatilityOpportunity?.volatility_spike_score ?? null,
      volatilityOpportunityBounceContextScore:
        volatilityOpportunity?.bounce_context_score ?? null,
      volatilityOpportunityLiquidityQualityScore:
        volatilityOpportunity?.liquidity_quality_score ?? null,
      volatilityOpportunityObservedHistorySpanMinutes:
        volatilityOpportunity?.observed_history_span_minutes ?? 0,
      volatilityOpportunityObservedPointCount:
        volatilityOpportunity?.observed_point_count ?? 0,
      volatilityOpportunityInsufficientData:
        volatilityOpportunity?.insufficient_data ?? true,
      volatilityOpportunityInsufficientReasonCode:
        volatilityOpportunity?.insufficient_reason_code ?? null,
      volatilityOpportunityInsufficientReasonMessage:
        volatilityOpportunity?.insufficient_reason_message ?? null,
      volatilityDataQualityStatus:
        volatilityOpportunity?.data_quality?.status
        ?? (volatilityOpportunity?.insufficient_data ? "INSUFFICIENT" : "GOOD"),
      volatilityDataQualityReason:
        volatilityOpportunity?.data_quality?.reason
        ?? (volatilityOpportunity?.insufficient_reason_code ?? "ok"),
      regimeDataQualityStatus:
        regimeAdvisory?.data_quality?.status
        ?? (regimeAdvisory?.confidenceScore && regimeAdvisory.confidenceScore > 45 ? "GOOD" : "PARTIAL"),
      regimeDataQualityReason:
        regimeAdvisory?.data_quality?.reason
        ?? "window_coverage",
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
  const initialLock = Number(
    config.profit_locks?.initial_lock ?? 0.01,
  );
  const profitLevels = normalizeProfitLevels(config.profit_locks?.levels);
  const trailingActivation = Number(
    config.profit_locks?.trailing_activation ?? 0.1,
  );
  const trailingGap = Number(config.profit_locks?.trailing_gap ?? 0.02);
  const maxNegativeZScore = Number(
    config.profit_locks?.max_negative_z_score
      ?? config.market_regime?.max_negative_z_score
      ?? -3.0,
  );

  const draftRows = positionSymbols.map((symbol) => {
    const position = positions[symbol] ?? {};
    const snapshot = snapshots[symbol] ?? null;
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

    const pnlPct = currentPrice === null || entryPrice <= 0
      ? null
      : ((currentPrice - entryPrice) / entryPrice) * 100;
    const firstActivationPct = firstActivation * 100;
    const trailingActivationPct = trailingActivation * 100;
    const peakRatio = peakPnlPct / 100;
    const zScore = (
      currentPrice !== null
      && snapshot?.vwap !== null
      && snapshot?.atrRaw !== null
      && snapshot.atrRaw > 0
    )
      ? (currentPrice - snapshot.vwap) / snapshot.atrRaw
      : null;
    let computedLockRatio = profitLock === null ? null : Number(profitLock);
    if (pnlPct !== null && pnlPct >= firstActivationPct) {
      if (computedLockRatio === null) {
        computedLockRatio = initialLock;
      }
      for (const [trigger, lock] of profitLevels) {
        if (pnlPct >= (trigger * 100)) {
          computedLockRatio = Math.max(computedLockRatio, lock);
        }
      }
      if (peakRatio >= trailingActivation) {
        computedLockRatio = Math.max(computedLockRatio, peakRatio - trailingGap);
      }
    }
    const currentLockPct = computedLockRatio === null ? null : computedLockRatio * 100;
    const computedLockPrice = (
      computedLockRatio === null || entryPrice <= 0
    )
      ? null
      : entryPrice * (1 + computedLockRatio);
    const toFirstActivationPct = pnlPct === null ? null : (firstActivationPct - pnlPct);
    const toLockPct = (
      pnlPct === null || currentLockPct === null
    )
      ? null
      : (pnlPct - currentLockPct);
    const structuralBreakEligible = (
      zScore !== null
      && computedLockRatio !== null
      && Math.abs(computedLockRatio - initialLock) < 1e-9
      && zScore < maxNegativeZScore
    );
    let blockedBy = "missing_live_price";
    let nextGate = "Need live spot price";
    let reason = "No current price snapshot available for sell-gate evaluation.";
    let canExitNow = false;
    if (pnlPct !== null) {
      if (pnlPct < firstActivationPct) {
        blockedBy = "waiting_for_first_lock";
        nextGate = `Reach ${firstActivationPct.toFixed(2)}% PnL`;
        reason = `Current PnL ${pnlPct.toFixed(2)}% is below first lock activation.`;
      } else if (currentLockPct !== null && pnlPct <= currentLockPct) {
        blockedBy = "profit_lock_exit_ready";
        nextGate = "Exit ready";
        reason = `PnL is at/below lock (${currentLockPct.toFixed(2)}%).`;
        canExitNow = true;
      } else if (structuralBreakEligible) {
        blockedBy = "structural_break_exit_ready";
        nextGate = "Exit ready";
        reason = `Z-score ${zScore?.toFixed(2)} is below structural break threshold ${maxNegativeZScore.toFixed(2)}.`;
        canExitNow = true;
      } else {
        blockedBy = "holding_above_lock";
        nextGate = currentLockPct === null
          ? "Build lock context"
          : `Drop to lock ${currentLockPct.toFixed(2)}%`;
        reason = currentLockPct === null
          ? "Position is armed but lock has not been persisted yet."
          : `PnL is still above lock by ${(toLockPct ?? 0).toFixed(2)}%.`;
      }
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
      exitDiagnostics: {
        canExitNow,
        blockedBy,
        nextGate,
        reason,
        pnlPct,
        firstActivationPct,
        toFirstActivationPct,
        currentLockPct,
        lockPrice: computedLockPrice,
        toLockPct,
        peakPnlPct,
        trailingArmed: peakPnlPct >= trailingActivationPct,
        trailingActivationPct,
        zScore,
        maxNegativeZScore,
        structuralBreakEligible,
      },
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
  const rotationStatusCounts = {
    Rising: 0,
    Strong: 0,
    Neutral: 0,
    Weakening: 0,
    Cold: 0,
    "Capital Trap Risk": 0,
  };
  for (const control of symbolControls) {
    const status = control.rotationStatus in rotationStatusCounts
      ? control.rotationStatus as keyof typeof rotationStatusCounts
      : "Neutral";
    rotationStatusCounts[status] += 1;
  }
  const rotationTopRisingSymbols = [...symbolControls]
    .filter((control) => (
      control.rotationStatus === "Rising"
      || control.rotationStatus === "Strong"
    ))
    .sort((left, right) => (
      Number(right.rotationDelta ?? 0) - Number(left.rotationDelta ?? 0)
    ) || (
      Number(right.rotationShortTermScore ?? 0) - Number(left.rotationShortTermScore ?? 0)
    ))
    .slice(0, 5)
    .map((control) => control.symbol);
  const rotationTopColdSymbols = [...symbolControls]
    .filter((control) => (
      control.rotationStatus === "Cold"
      || control.rotationStatus === "Capital Trap Risk"
      || control.rotationStatus === "Weakening"
    ))
    .sort((left, right) => (
      Number(left.rotationShortTermScore ?? 100) - Number(right.rotationShortTermScore ?? 100)
    ) || (
      Number(left.rotationDelta ?? 0) - Number(right.rotationDelta ?? 0)
    ))
    .slice(0, 5)
    .map((control) => control.symbol);
  const rankedVolatilityOpportunity = [...symbolControls]
    .filter(
      (control) => (
        control.volatilityOpportunityScore !== null
        && !control.volatilityOpportunityInsufficientData
      ),
    )
    .sort((left, right) => (
      Number(right.volatilityOpportunityScore ?? -1)
      - Number(left.volatilityOpportunityScore ?? -1)
    ) || left.symbol.localeCompare(right.symbol));
  const topVolatilityOpportunitySymbols = rankedVolatilityOpportunity
    .slice(0, 5)
    .map((control) => control.symbol);
  const highestVolatilityOpportunityScore = rankedVolatilityOpportunity.length > 0
    ? Number(rankedVolatilityOpportunity[0].volatilityOpportunityScore ?? 0)
    : null;
  const highOpportunitySymbolCount = symbolControls.filter((control) => (
    !control.volatilityOpportunityInsufficientData
    && Number(control.volatilityOpportunityScore ?? -1) >= 70
  )).length;

  return NextResponse.json({
    generatedAt: new Date().toISOString(),
    summary: {
      enabled: Boolean(config.enabled),
      tradingEnabled: Boolean(config.trading_enabled),
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
      rotationRisingCount: rotationStatusCounts.Rising,
      rotationStrongCount: rotationStatusCounts.Strong,
      rotationNeutralCount: rotationStatusCounts.Neutral,
      rotationWeakeningCount: rotationStatusCounts.Weakening,
      rotationColdCount: rotationStatusCounts.Cold,
      rotationCapitalTrapRiskCount: rotationStatusCounts["Capital Trap Risk"],
      rotationTopRisingSymbols,
      rotationTopColdSymbols,
      topVolatilityOpportunitySymbols,
      highestVolatilityOpportunityScore:
        highestVolatilityOpportunityScore === null
          ? null
          : round(highestVolatilityOpportunityScore, 1),
      highOpportunitySymbolCount,
      symbolCooldownOverrides: cooldownOverrideMap,
      marketDataSyncHealth: {
        generatedAt: marketSyncHealth?.generated_at ?? null,
        adaptiveBudget: {
          baseCap: Number(marketSyncHealth?.adaptive_budget?.base_cap ?? 0),
          effectiveCap: Number(marketSyncHealth?.adaptive_budget?.effective_cap ?? 0),
          underPressure: marketSyncHealth?.adaptive_budget?.under_pressure === true,
          rateLimitedCount: Number(
            marketSyncHealth?.adaptive_budget?.pressure?.rate_limited_count ?? 0,
          ),
          throttleSleepSeconds: round(
            Number(marketSyncHealth?.adaptive_budget?.pressure?.throttle_sleep_seconds_sum ?? 0),
            2,
          ),
          throttleEventCount: Number(
            marketSyncHealth?.adaptive_budget?.pressure?.throttle_event_count ?? 0,
          ),
          windowSeconds: Number(
            marketSyncHealth?.adaptive_budget?.pressure?.window_seconds ?? 60,
          ),
        },
        sync: {
          enabled: marketSyncHealth?.sync?.enabled === true,
          attemptedJobs: Number(marketSyncHealth?.sync?.attempted_jobs ?? 0),
          requests: Number(marketSyncHealth?.sync?.requests ?? 0),
          inserted: Number(marketSyncHealth?.sync?.inserted ?? 0),
          newInserted: Number(marketSyncHealth?.sync?.new_inserted ?? 0),
          updatedExisting: Number(marketSyncHealth?.sync?.updated_existing ?? 0),
          candidateNew: Number(marketSyncHealth?.sync?.candidate_new ?? 0),
          eligibleClosed: Number(marketSyncHealth?.sync?.eligible_closed ?? 0),
          skippedExisting: Number(marketSyncHealth?.sync?.skipped_existing ?? 0),
          skippedPartial: Number(marketSyncHealth?.sync?.skipped_partial ?? 0),
          errors: Number(marketSyncHealth?.sync?.errors ?? 0),
          degraded: Number(marketSyncHealth?.sync?.degraded ?? 0),
        },
        coverage: {
          fresh1h: Number(marketSyncHealth?.coverage?.fresh_counts_by_timeframe?.["1h"] ?? 0),
          fresh4h: Number(marketSyncHealth?.coverage?.fresh_counts_by_timeframe?.["4h"] ?? 0),
          fresh24h: Number(marketSyncHealth?.coverage?.fresh_counts_by_timeframe?.["1d"] ?? 0),
          staleSymbolTimeframes: Number(marketSyncHealth?.coverage?.stale_symbol_timeframes ?? 0),
          totalRows: Number(marketSyncHealth?.coverage?.total_rows ?? 0),
          rowsUpdatedLast24h: Number(marketSyncHealth?.coverage?.rows_updated_last_24h ?? 0),
          statusCounts: marketSyncHealth?.coverage?.status_counts ?? {},
        },
        endpointTelemetry: {
          fetchCalls: Number(marketSyncHealth?.endpoint_telemetry?.fetch_calls ?? 0),
          successCalls: Number(marketSyncHealth?.endpoint_telemetry?.success_calls ?? 0),
          failedCalls: Number(marketSyncHealth?.endpoint_telemetry?.failed_calls ?? 0),
          officialSuccessCalls: Number(marketSyncHealth?.endpoint_telemetry?.official_success_calls ?? 0),
          publicSuccessCalls: Number(marketSyncHealth?.endpoint_telemetry?.public_success_calls ?? 0),
          activeCapabilities: marketSyncHealth?.endpoint_telemetry?.active_capabilities ?? {},
        },
        slo: {
          status: String(marketSyncHealth?.slo?.status ?? "UNKNOWN"),
          coverageOk: marketSyncHealth?.slo?.coverage_ok === true,
          qualityOk: marketSyncHealth?.slo?.quality_ok === true,
          throughputOk: marketSyncHealth?.slo?.throughput_ok === true,
          fresh1h: Number(marketSyncHealth?.slo?.fresh_1h ?? 0),
          fresh4h: Number(marketSyncHealth?.slo?.fresh_4h ?? 0),
          fresh24h: Number(marketSyncHealth?.slo?.fresh_24h ?? 0),
          staleSymbolTimeframes: Number(marketSyncHealth?.slo?.stale_symbol_timeframes ?? 0),
          requests: Number(marketSyncHealth?.slo?.requests ?? 0),
          newInserted: Number(marketSyncHealth?.slo?.new_inserted ?? 0),
          errors: Number(marketSyncHealth?.slo?.errors ?? 0),
          degraded: Number(marketSyncHealth?.slo?.degraded ?? 0),
        },
      },
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
      detectedRegime: control.detectedRegime,
      detectedRegimeConfidenceLabel: control.detectedRegimeConfidenceLabel,
      detectedRegimeConfidenceScore:
        control.detectedRegimeConfidenceScore === null
          ? null
          : round(control.detectedRegimeConfidenceScore, 1),
      detectedRegimeConfidenceInferred:
        control.detectedRegimeConfidenceInferred === true,
      detectedRegimeStabilityScore:
        control.detectedRegimeStabilityScore === null
          ? null
          : round(control.detectedRegimeStabilityScore, 1),
      detectedRegimePersistenceScore:
        control.detectedRegimePersistenceScore === null
          ? null
          : round(control.detectedRegimePersistenceScore, 1),
      detectedRegimeStabilityInferred: control.detectedRegimeStabilityInferred === true,
      detectedRegimePersistenceInferred: control.detectedRegimePersistenceInferred === true,
      detectedRegimeDataQualityStatus: control.detectedRegimeDataQualityStatus,
      detectedRegimeKeyWindowsSupported: control.detectedRegimeKeyWindowsSupported,
      suggestedRegimeV2: control.suggestedRegimeV2,
      detectionSource: control.detectionSource,
      detectionTimestampEpoch:
        control.detectionTimestampEpoch === null
          ? null
          : round(control.detectionTimestampEpoch, 3),
      routeEvalTimestampEpoch:
        control.routeEvalTimestampEpoch === null
          ? null
          : round(control.routeEvalTimestampEpoch, 3),
      regimeEvalTimestampEpoch:
        control.regimeEvalTimestampEpoch === null
          ? null
          : round(control.regimeEvalTimestampEpoch, 3),
      detectionTimestampAt: control.detectionTimestampAt,
      detectedRegimeExplanation: control.detectedRegimeExplanation,
      detectedRegimeStructureBias: control.detectedRegimeStructureBias,
      detectedRegimeVolatilityState: control.detectedRegimeVolatilityState,
      detectedRegimeParticipationState: control.detectedRegimeParticipationState,
      detectedRegimeTrendScore:
        control.detectedRegimeTrendScore === null
          ? null
          : round(control.detectedRegimeTrendScore, 2),
      detectedRegimeRangeScore:
        control.detectedRegimeRangeScore === null
          ? null
          : round(control.detectedRegimeRangeScore, 2),
      detectedRegimeBreakoutScore:
        control.detectedRegimeBreakoutScore === null
          ? null
          : round(control.detectedRegimeBreakoutScore, 2),
      detectedRegimeMixedScore:
        control.detectedRegimeMixedScore === null
          ? null
          : round(control.detectedRegimeMixedScore, 2),
      effectiveStrategy: control.effectiveStrategy,
      effectiveRoute: control.effectiveRoute,
      autoFallbackReason: control.autoFallbackReason,
      fallbackReason: control.fallbackReason,
      readyForNonMrRoute: control.readyForNonMrRoute,
      nonMrReadyReason: control.nonMrReadyReason,
      price:
        control.price === null
          ? null
          : round(control.price, 8),
      change24hPct:
        control.change24hPct === null
          ? null
          : round(control.change24hPct, 3),
      low24h:
        control.low24h === null
          ? null
          : round(control.low24h, 8),
      high24h:
        control.high24h === null
          ? null
          : round(control.high24h, 8),
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
      rotationShortTermScore:
        control.rotationShortTermScore === null
          ? null
          : round(control.rotationShortTermScore, 1),
      rotationMediumTermScore:
        control.rotationMediumTermScore === null
          ? null
          : round(control.rotationMediumTermScore, 1),
      rotationDelta:
        control.rotationDelta === null
          ? null
          : round(control.rotationDelta, 1),
      rotationStatus: control.rotationStatus,
      rotationShortTermWinRatePct:
        control.rotationShortTermWinRatePct === null
          ? null
          : round(control.rotationShortTermWinRatePct, 2),
      rotationShortTermAvgRealizedPnlUsd:
        control.rotationShortTermAvgRealizedPnlUsd === null
          ? null
          : round(control.rotationShortTermAvgRealizedPnlUsd, 2),
      rotationShortTermAvgHoldHours:
        control.rotationShortTermAvgHoldHours === null
          ? null
          : round(control.rotationShortTermAvgHoldHours, 2),
      rotationShortTermAvgRecoveryHours:
        control.rotationShortTermAvgRecoveryHours === null
          ? null
          : round(control.rotationShortTermAvgRecoveryHours, 2),
      rotationShortTermStaleReviewFrequencyPct:
        control.rotationShortTermStaleReviewFrequencyPct === null
          ? null
          : round(control.rotationShortTermStaleReviewFrequencyPct, 2),
      rotationShortTermAvgMaxDrawdownPct:
        control.rotationShortTermAvgMaxDrawdownPct === null
          ? null
          : round(control.rotationShortTermAvgMaxDrawdownPct, 2),
      rotationMediumTermWinRatePct:
        control.rotationMediumTermWinRatePct === null
          ? null
          : round(control.rotationMediumTermWinRatePct, 2),
      rotationMediumTermAvgRealizedPnlUsd:
        control.rotationMediumTermAvgRealizedPnlUsd === null
          ? null
          : round(control.rotationMediumTermAvgRealizedPnlUsd, 2),
      rotationMediumTermAvgHoldHours:
        control.rotationMediumTermAvgHoldHours === null
          ? null
          : round(control.rotationMediumTermAvgHoldHours, 2),
      rotationMediumTermAvgRecoveryHours:
        control.rotationMediumTermAvgRecoveryHours === null
          ? null
          : round(control.rotationMediumTermAvgRecoveryHours, 2),
      rotationMediumTermStaleReviewFrequencyPct:
        control.rotationMediumTermStaleReviewFrequencyPct === null
          ? null
          : round(control.rotationMediumTermStaleReviewFrequencyPct, 2),
      rotationMediumTermAvgMaxDrawdownPct:
        control.rotationMediumTermAvgMaxDrawdownPct === null
          ? null
          : round(control.rotationMediumTermAvgMaxDrawdownPct, 2),
      volatilityOpportunityScore:
        control.volatilityOpportunityScore === null
          ? null
          : round(control.volatilityOpportunityScore, 1),
      volatilityOpportunityLabel: control.volatilityOpportunityLabel,
      volatilityOpportunityReason: control.volatilityOpportunityReason,
      volatilityOpportunityConfidenceLabel:
        control.volatilityOpportunityConfidenceLabel,
      volatilityOpportunityStretchScore:
        control.volatilityOpportunityStretchScore === null
          ? null
          : round(control.volatilityOpportunityStretchScore, 1),
      volatilityOpportunityVolatilitySpikeScore:
        control.volatilityOpportunityVolatilitySpikeScore === null
          ? null
          : round(control.volatilityOpportunityVolatilitySpikeScore, 1),
      volatilityOpportunityBounceContextScore:
        control.volatilityOpportunityBounceContextScore === null
          ? null
          : round(control.volatilityOpportunityBounceContextScore, 1),
      volatilityOpportunityLiquidityQualityScore:
        control.volatilityOpportunityLiquidityQualityScore === null
          ? null
          : round(control.volatilityOpportunityLiquidityQualityScore, 1),
      volatilityOpportunityObservedHistorySpanMinutes: round(
        control.volatilityOpportunityObservedHistorySpanMinutes,
        1,
      ),
      volatilityOpportunityObservedPointCount:
        control.volatilityOpportunityObservedPointCount,
      volatilityOpportunityInsufficientData:
        control.volatilityOpportunityInsufficientData,
      volatilityOpportunityInsufficientReasonCode:
        control.volatilityOpportunityInsufficientReasonCode,
      volatilityOpportunityInsufficientReasonMessage:
        control.volatilityOpportunityInsufficientReasonMessage,
      volatilityDataQualityStatus: control.volatilityDataQualityStatus,
      volatilityDataQualityReason: control.volatilityDataQualityReason,
      regimeDataQualityStatus: control.regimeDataQualityStatus,
      regimeDataQualityReason: control.regimeDataQualityReason,
    })),
    chart: {
      points: chartPoints,
      min: round(Math.min(...chartPoints), 2),
      max: round(Math.max(...chartPoints), 2),
    },
    positions: positionRows.map((row) => ({
      ...row,
      units: round(row.units, 6),
      entryPrice: roundPrice(row.entryPrice),
      currentPrice:
        row.currentPrice === null ? null : roundPrice(row.currentPrice),
      lockPrice:
        row.lockPrice === null ? null : roundPrice(row.lockPrice),
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
          : roundPrice(row.advisoryMaxDrawdownPriceDuringTrade),
      advisoryMaxDrawdownAt:
        row.advisoryMaxDrawdownAt === null
          ? null
          : round(row.advisoryMaxDrawdownAt, 3),
      exitDiagnostics: {
        ...row.exitDiagnostics,
        pnlPct:
          row.exitDiagnostics.pnlPct === null
            ? null
            : round(row.exitDiagnostics.pnlPct, 2),
        firstActivationPct: round(row.exitDiagnostics.firstActivationPct, 2),
        toFirstActivationPct:
          row.exitDiagnostics.toFirstActivationPct === null
            ? null
            : round(row.exitDiagnostics.toFirstActivationPct, 2),
        currentLockPct:
          row.exitDiagnostics.currentLockPct === null
            ? null
            : round(row.exitDiagnostics.currentLockPct, 2),
        lockPrice:
          row.exitDiagnostics.lockPrice === null
            ? null
            : roundPrice(row.exitDiagnostics.lockPrice),
        toLockPct:
          row.exitDiagnostics.toLockPct === null
            ? null
            : round(row.exitDiagnostics.toLockPct, 2),
        peakPnlPct: round(row.exitDiagnostics.peakPnlPct, 2),
        trailingActivationPct: round(row.exitDiagnostics.trailingActivationPct, 2),
        zScore:
          row.exitDiagnostics.zScore === null
            ? null
            : round(row.exitDiagnostics.zScore, 3),
        maxNegativeZScore: round(row.exitDiagnostics.maxNegativeZScore, 3),
      },
    })),
  }, {
    headers: {
      "Cache-Control": "no-store, no-cache, must-revalidate, proxy-revalidate",
      Pragma: "no-cache",
      Expires: "0",
    },
  });
}
