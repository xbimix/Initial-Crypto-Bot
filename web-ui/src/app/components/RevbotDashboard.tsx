"use client";

import { startTransition, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { buildMutatingAuthHeaders } from "../lib/mutatingAuthClient";

type DashboardPayload = {
  generatedAt: string;
  summary: {
    enabled: boolean;
    tradingEnabled: boolean;
    executionMode: string;
    trackedSymbols: number;
    activeSymbols: number;
    disabledSymbols: number;
    sellEnabledSymbols: number;
    sellDisabledSymbols: number;
    cooldownSeconds: number;
    maxConcurrentTrades: number;
    maxConcurrentTradesPerToken: number;
    maxTradeAmountUsd: number;
    maxPortfolioExposurePct: number;
    maxExposurePerTokenPct: number;
    tradeAmountUsd: number;
    riskPercent: number;
    signalConfirmationCycles: number;
    tradeWindowEnabled: boolean;
    tradeWindowStartHourUtc: number;
    tradeWindowEndHourUtc: number;
    insideTradeWindowUtc: boolean;
    dailyLossLimitUsd: number;
    dailyLossAutoPause: boolean;
    dailyLossCloseAll: boolean;
    dailyRealizedPnlUsd: number;
    dailyBuyPaused: boolean;
    loopSeconds: number;
    lookback: number;
    minTrades: number;
    startingBalance: number;
    cashBalance: number;
    investedCapital: number;
    openValue: number;
    totalEquity: number;
    realizedPnl: number;
    unrealizedPnl: number;
    netPnl: number;
    netReturnPct: number;
    openPositions: number;
    openExposurePct: number;
    firstActivationPct: number;
    trailingActivationPct: number;
    trailingGapPct: number;
    maxDrawdownDuringTradePct: number;
    maxDrawdownDuringTradeSymbol: string | null;
    staleLosingReviewCount: number;
    staleLosingReviewSymbols: string[];
    staleLosingReviewThresholdAgeHours: number;
    staleLosingReviewThresholdUnrealizedPnlPct: number;
    lastTradeAt: number | null;
    lastTradeReason: string | null;
    lastSnapshotAt: string | null;
    buyCount: number;
    sellCount: number;
    bestBuySymbol: string | null;
    bestBuyOpportunityPct: number | null;
    rotationRisingCount: number;
    rotationStrongCount: number;
    rotationNeutralCount: number;
    rotationWeakeningCount: number;
    rotationColdCount: number;
    rotationCapitalTrapRiskCount: number;
    rotationTopRisingSymbols: string[];
    rotationTopColdSymbols: string[];
    topVolatilityOpportunitySymbols: string[];
    highestVolatilityOpportunityScore: number | null;
    highOpportunitySymbolCount: number;
    symbolCooldownOverrides: Record<string, number>;
  };
  symbolControls: Array<{
    symbol: string;
    configuredRegime: string;
    detectedRegime: string | null;
    suggestedRegimeV2?: string | null;
    detectedRegimeConfidenceLabel: string;
    detectedRegimeConfidenceScore: number | null;
    detectedRegimeConfidenceInferred?: boolean;
    detectedRegimeStabilityScore: number | null;
    detectedRegimePersistenceScore?: number | null;
    detectedRegimeStabilityInferred?: boolean;
    detectedRegimePersistenceInferred?: boolean;
    detectedRegimeDataQualityStatus?: string;
    detectedRegimeKeyWindowsSupported?: boolean;
    detectionSource: string;
    detectionTimestampEpoch: number | null;
    routeEvalTimestampEpoch?: number | null;
    regimeEvalTimestampEpoch?: number | null;
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
    effectiveRoute?: string;
    autoFallbackReason: string | null;
    fallbackReason?: string | null;
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
  }>;
  chart: {
    points: number[];
    min: number;
    max: number;
  };
  positions: Array<{
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
  }>;
};

function buildActionId(prefix: string): string {
  const random = Math.random().toString(36).slice(2, 10);
  return `${prefix}-${Date.now()}-${random}`;
}

async function parseApiErrorMessage(response: Response, fallback: string): Promise<string> {
  let parsedMessage = "";
  try {
    const payload = await response.clone().json() as {
      error?: unknown;
      code?: unknown;
      details?: unknown;
    };
    if (typeof payload.error === "string" && payload.error.trim()) {
      parsedMessage = payload.error.trim();
    }
    if (typeof payload.code === "string" && payload.code.trim()) {
      parsedMessage = parsedMessage
        ? `${parsedMessage} [${payload.code.trim()}]`
        : payload.code.trim();
    }
  } catch {
    // Fall through to text body fallback.
  }

  if (!parsedMessage) {
    try {
      const text = (await response.text()).trim();
      if (text) {
        parsedMessage = text;
      }
    } catch {
      // Ignore and use generic fallback.
    }
  }

  if (!parsedMessage) {
    return `${fallback} (${response.status})`;
  }
  return `${fallback}: ${parsedMessage}`;
}

type RiskDraft = {
  maxConcurrentTrades: number;
  maxConcurrentTradesPerToken: number;
  maxTradeAmountUsd: number;
  maxPortfolioExposurePct: number;
  maxExposurePerTokenPct: number;
  tradeAmountUsd: number;
  signalConfirmationCycles: number;
  tradeWindowEnabled: boolean;
  tradeWindowStartHourUtc: number;
  tradeWindowEndHourUtc: number;
  dailyLossLimitUsd: number;
  dailyLossAutoPause: boolean;
  dailyLossCloseAll: boolean;
};

const RANGE_OPTIONS = [
  { id: "recent", label: "Live", points: 8 },
  { id: "session", label: "Session", points: 14 },
  { id: "all", label: "All", points: Number.POSITIVE_INFINITY },
] as const;

const TOKEN_REGIME_OPTIONS = [
  "MEAN_REVERSION",
  "AUTO",
  "TREND_PULLBACK",
  "BREAKOUT_MOMENTUM",
  "OBSERVE_ONLY",
] as const;

type RangeId = (typeof RANGE_OPTIONS)[number]["id"];

type PositionSortKey =
  | "attention"
  | "symbol"
  | "side"
  | "units"
  | "entry"
  | "price"
  | "change24h"
  | "high24h"
  | "low24h"
  | "value"
  | "allocation"
  | "pnl"
  | "pnlPct"
  | "lock"
  | "peak"
  | "age"
  | "worstDip"
  | "review"
  | "bounce"
  | "status";

type ControlSortKey =
  | "symbol"
  | "mode"
  | "configuredRegime"
  | "regime"
  | "confidence"
  | "volatility"
  | "dataQuality"
  | "price"
  | "change24h"
  | "high24h"
  | "low24h"
  | "buyOpportunity"
  | "buyExecutable"
  | "scalper"
  | "buy"
  | "sell";

type ManualStoplossType = "pct" | "price";

type ManualStoplossRule = {
  enabled: boolean;
  type: ManualStoplossType;
  value: number | null;
  updated_at?: number | null;
  trigger_price?: number | null;
  last_trigger_at?: number | null;
  last_trigger_price?: number | null;
};

type ManualStoplossDraft = {
  enabled: boolean;
  type: ManualStoplossType;
  valueText: string;
};

const COIN_NAME_BY_BASE: Record<string, string> = {
  ADA: "Cardano",
  ACH: "Alchemy Pay",
  ACX: "Across Protocol",
  API3: "API3",
  ARPA: "ARPA",
  ASM: "Assemble Protocol",
  BLZ: "Bluzelle",
  BNB: "BNB",
  BTC: "Bitcoin",
  CRV: "Curve DAO",
  DOT: "Polkadot",
  ETH: "Ethereum",
  GST: "Green Satoshi Token",
  HOPR: "HOPR",
  IMX: "Immutable",
  LCX: "LCX",
  PERP: "Perpetual Protocol",
  POLS: "Polkastarter",
  PONKE: "PONKE",
  PRIME: "Echelon Prime",
  SEI: "Sei",
  SOL: "Solana",
  SPA: "Sperax",
  SUI: "Sui",
  TAI: "TARS AI",
  XCN: "Onyxcoin",
  XLM: "Stellar",
  XRP: "XRP",
};

function coinName(symbol: string) {
  const base = String(symbol ?? "").split("-")[0]?.toUpperCase() ?? "";
  return COIN_NAME_BY_BASE[base] ?? (base || symbol);
}

const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

const priceFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 6,
});

const compactCurrencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 2,
});

const percentFormatter = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatCurrency(value: number) {
  return currencyFormatter.format(value);
}

function formatPrice(value: number) {
  return priceFormatter.format(value);
}

function formatCompactCurrency(value: number) {
  return compactCurrencyFormatter.format(value);
}

function formatPercent(value: number) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${percentFormatter.format(value)}%`;
}

function normalizeStoplossType(value: unknown): ManualStoplossType {
  return String(value ?? "").trim().toLowerCase() === "price" ? "price" : "pct";
}

function toManualStoplossRule(value: unknown): ManualStoplossRule | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const numericValue = Number(record.value);
  const valueNumber = Number.isFinite(numericValue) && numericValue > 0 ? numericValue : null;
  return {
    enabled: record.enabled === true && valueNumber !== null,
    type: normalizeStoplossType(record.type),
    value: valueNumber,
    updated_at: Number.isFinite(Number(record.updated_at)) ? Number(record.updated_at) : null,
    trigger_price: Number.isFinite(Number(record.trigger_price)) ? Number(record.trigger_price) : null,
    last_trigger_at: Number.isFinite(Number(record.last_trigger_at))
      ? Number(record.last_trigger_at)
      : null,
    last_trigger_price: Number.isFinite(Number(record.last_trigger_price))
      ? Number(record.last_trigger_price)
      : null,
  };
}

function buildManualStoplossDraft(rule: ManualStoplossRule | null | undefined): ManualStoplossDraft {
  return {
    enabled: rule?.enabled === true,
    type: rule?.type ?? "pct",
    valueText: rule?.value !== null && rule?.value !== undefined ? String(rule.value) : "",
  };
}

function formatUnits(value: number) {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 6,
  }).format(value);
}

function formatRelativeTime(unixSeconds: number | null) {
  if (!unixSeconds) {
    return "No trades yet";
  }

  const date = new Date(unixSeconds * 1000);
  return new Intl.DateTimeFormat("en-GB", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatSnapshotTime(value: string | null) {
  if (!value) {
    return "Awaiting live snapshots";
  }

  return value;
}

function statusTone(status: string) {
  switch (status) {
    case "Trailing":
      return "bg-emerald-500/15 text-emerald-200 ring-1 ring-emerald-400/30";
    case "Locked":
      return "bg-sky-500/15 text-sky-200 ring-1 ring-sky-400/30";
    case "Arming":
      return "bg-amber-500/15 text-amber-200 ring-1 ring-amber-400/30";
    default:
      return "bg-white/8 text-slate-200 ring-1 ring-white/10";
  }
}

function curveTone(value: number) {
  return value >= 0
    ? "text-emerald-300"
    : "text-rose-300";
}

function valueTone(value: number) {
  if (value > 0) {
    return "text-emerald-300";
  }

  if (value < 0) {
    return "text-rose-300";
  }

  return "text-slate-300";
}

function compareTone(current: number | null, basis: number) {
  if (current === null) {
    return "text-slate-300";
  }

  if (current > basis) {
    return "text-emerald-300";
  }

  if (current < basis) {
    return "text-rose-300";
  }

  return "text-slate-200";
}

function formatOpportunity(value: number | null) {
  if (value === null) {
    return "N/A";
  }

  return `${value.toFixed(1)}%`;
}

function formatDetectedRegime(value: string | null) {
  if (!value) {
    return "N/A";
  }
  return value
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatFailedGates(value: string | null | undefined) {
  const raw = String(value ?? "").trim();
  if (!raw) {
    return "None";
  }
  const [gateRaw, detailRaw] = raw.split(":", 2);
  const gate = formatDetectedRegime(gateRaw ?? raw);
  if (!detailRaw) {
    return gate;
  }
  const detail = detailRaw
    .split(",")
    .map((item) => item.trim().replace(/_/g, " "))
    .filter(Boolean)
    .join(", ");
  return detail ? `${gate} (${detail})` : gate;
}

function opportunityStyle(value: number | null) {
  if (value === null) {
    return {
      backgroundColor: "rgba(148, 163, 184, 0.14)",
      borderColor: "rgba(148, 163, 184, 0.35)",
      color: "#cbd5e1",
    };
  }

  if (value >= 70) {
    return {
      backgroundColor: "#16a34a",
      borderColor: "#16a34a",
      color: "#ffffff",
    };
  }

  if (value >= 45) {
    return {
      backgroundColor: "#0284c7",
      borderColor: "#0284c7",
      color: "#ffffff",
    };
  }

  if (value >= 25) {
    return {
      backgroundColor: "#d97706",
      borderColor: "#d97706",
      color: "#ffffff",
    };
  }

  return {
    backgroundColor: "#dc2626",
    borderColor: "#dc2626",
    color: "#ffffff",
  };
}

function executableStyle(enabled: boolean) {
  if (enabled) {
    return {
      backgroundColor: "#16a34a",
      borderColor: "#16a34a",
      color: "#ffffff",
    };
  }

  return {
    backgroundColor: "#dc2626",
    borderColor: "#dc2626",
    color: "#ffffff",
  };
}

function regimeStyle(value: string | null) {
  const regime = (value ?? "").toLowerCase();

  if (regime.includes("trend up") || regime.includes("accumulation")) {
    return {
      backgroundColor: "#16a34a",
      borderColor: "#16a34a",
      color: "#ffffff",
    };
  }

  if (regime.includes("trend down") || regime.includes("dump")) {
    return {
      backgroundColor: "#dc2626",
      borderColor: "#dc2626",
      color: "#ffffff",
    };
  }

  if (regime.includes("spike")) {
    return {
      backgroundColor: "#d97706",
      borderColor: "#d97706",
      color: "#ffffff",
    };
  }

  if (regime.includes("range") || regime.includes("chop")) {
    return {
      backgroundColor: "#0284c7",
      borderColor: "#0284c7",
      color: "#ffffff",
    };
  }

  return {
    backgroundColor: "rgba(148, 163, 184, 0.14)",
    borderColor: "rgba(148, 163, 184, 0.35)",
    color: "#cbd5e1",
  };
}

function rotationStatusStyle(status: string) {
  if (status === "Rising") {
    return {
      backgroundColor: "#16a34a",
      borderColor: "#16a34a",
      color: "#ffffff",
    };
  }
  if (status === "Strong") {
    return {
      backgroundColor: "#0284c7",
      borderColor: "#0284c7",
      color: "#ffffff",
    };
  }
  if (status === "Weakening") {
    return {
      backgroundColor: "#d97706",
      borderColor: "#d97706",
      color: "#ffffff",
    };
  }
  if (status === "Cold") {
    return {
      backgroundColor: "#dc2626",
      borderColor: "#dc2626",
      color: "#ffffff",
    };
  }
  if (status === "Capital Trap Risk") {
    return {
      backgroundColor: "#991b1b",
      borderColor: "#991b1b",
      color: "#ffffff",
    };
  }
  return {
    backgroundColor: "rgba(148, 163, 184, 0.14)",
    borderColor: "rgba(148, 163, 184, 0.35)",
    color: "#cbd5e1",
  };
}

function radarLabelStyle(label: string | null) {
  if (label === "HIGH") {
    return {
      backgroundColor: "#16a34a",
      borderColor: "#16a34a",
      color: "#ffffff",
    };
  }
  if (label === "MEDIUM") {
    return {
      backgroundColor: "#0284c7",
      borderColor: "#0284c7",
      color: "#ffffff",
    };
  }
  if (label === "LOW") {
    return {
      backgroundColor: "#d97706",
      borderColor: "#d97706",
      color: "#ffffff",
    };
  }
  return {
    backgroundColor: "rgba(148, 163, 184, 0.14)",
    borderColor: "rgba(148, 163, 184, 0.35)",
    color: "#cbd5e1",
  };
}

function volatilityLabel(label: string | null) {
  if (label === "HIGH") {
    return "High Opportunity";
  }
  if (label === "MEDIUM") {
    return "Moderate Opportunity";
  }
  if (label === "LOW") {
    return "Low Opportunity";
  }
  return "N/A";
}

function confidenceLabel(label: string | null) {
  if (label === "HIGH") {
    return "High Confidence";
  }
  if (label === "MEDIUM") {
    return "Medium Confidence";
  }
  if (label === "LOW") {
    return "Low Confidence";
  }
  return "N/A";
}

function confidenceScoreFromLabel(label: string | null) {
  if (label === "HIGH") {
    return 3;
  }
  if (label === "MEDIUM") {
    return 2;
  }
  if (label === "LOW") {
    return 1;
  }
  return 0;
}

function regimeInputFlag(value: number | null | undefined, inferred: boolean | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "M";
  }
  return inferred ? "I" : "N";
}

function dataQualityRank(status: string | null | undefined) {
  const value = String(status ?? "").toUpperCase();
  if (value === "GOOD") {
    return 5;
  }
  if (value === "PARTIAL") {
    return 4;
  }
  if (value === "STALE") {
    return 3;
  }
  if (value === "INSUFFICIENT") {
    return 2;
  }
  if (value === "UNSUPPORTED_WINDOW") {
    return 1;
  }
  return 0;
}

function dataQualityStyle(status: string | null | undefined) {
  const value = String(status ?? "").toUpperCase();
  if (value === "GOOD") {
    return {
      backgroundColor: "#16a34a",
      borderColor: "#16a34a",
      color: "#ffffff",
    };
  }
  if (value === "PARTIAL") {
    return {
      backgroundColor: "#0284c7",
      borderColor: "#0284c7",
      color: "#ffffff",
    };
  }
  if (value === "STALE") {
    return {
      backgroundColor: "#d97706",
      borderColor: "#d97706",
      color: "#ffffff",
    };
  }
  if (value === "INSUFFICIENT" || value === "UNSUPPORTED_WINDOW") {
    return {
      backgroundColor: "#dc2626",
      borderColor: "#dc2626",
      color: "#ffffff",
    };
  }
  return {
    backgroundColor: "rgba(148, 163, 184, 0.14)",
    borderColor: "rgba(148, 163, 184, 0.35)",
    color: "#cbd5e1",
  };
}

function formatHours(value: number | null) {
  if (value === null || !Number.isFinite(value) || value < 0) {
    return "N/A";
  }
  return `${value.toFixed(1)}h`;
}

function MiniChart({
  points,
  min,
  max,
}: {
  points: number[];
  min: number;
  max: number;
}) {
  const width = 900;
  const height = 300;
  const safePoints = points.length > 1 ? points : [points[0] ?? 0, points[0] ?? 0];
  const domain = max - min || 1;
  const step = width / Math.max(safePoints.length - 1, 1);

  const coordinates = safePoints.map((point, index) => {
    const x = index * step;
    const y = height - ((point - min) / domain) * (height - 20) - 10;
    return { x, y };
  });

  const path = coordinates
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
    .join(" ");

  const areaPath = `${path} L ${width} ${height} L 0 ${height} Z`;
  const guide = height / 2;
  const marker = coordinates[coordinates.length - 1];

  return (
    <div className="relative h-[320px] overflow-hidden rounded-lg border border-white/6 bg-[radial-gradient(circle_at_top_left,_rgba(96,165,250,0.15),_transparent_40%),linear-gradient(180deg,rgba(255,255,255,0.03),rgba(255,255,255,0.01))] p-4">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-full w-full"
        preserveAspectRatio="none"
        aria-label="Portfolio estimate curve"
      >
        <defs>
          <linearGradient id="equityGlow" x1="0%" x2="100%" y1="0%" y2="0%">
            <stop offset="0%" stopColor="rgba(125,211,252,0.55)" />
            <stop offset="45%" stopColor="rgba(165,180,252,0.65)" />
            <stop offset="100%" stopColor="rgba(244,114,182,0.75)" />
          </linearGradient>
          <linearGradient id="equityFill" x1="0%" x2="0%" y1="0%" y2="100%">
            <stop offset="0%" stopColor="rgba(148,163,184,0.22)" />
            <stop offset="100%" stopColor="rgba(15,23,42,0)" />
          </linearGradient>
        </defs>

        <line
          x1="0"
          y1={guide}
          x2={width}
          y2={guide}
          stroke="rgba(255,255,255,0.16)"
          strokeDasharray="2 8"
        />

        <path d={areaPath} fill="url(#equityFill)" />

        <path
          d={path}
          fill="none"
          stroke="url(#equityGlow)"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        <circle
          cx={marker.x}
          cy={marker.y}
          r="6"
          fill="rgba(248,250,252,0.9)"
          stroke="rgba(56,189,248,0.8)"
          strokeWidth="3"
        />
      </svg>

      <div className="pointer-events-none absolute right-5 top-5 rounded-md bg-black/35 px-3 py-1 text-xs text-slate-300">
        High {formatCompactCurrency(max)}
      </div>
      <div className="pointer-events-none absolute bottom-5 right-5 rounded-md bg-black/35 px-3 py-1 text-xs text-slate-400">
        Low {formatCompactCurrency(min)}
      </div>
    </div>
  );
}

export default function RevbotDashboard() {
  const [data, setData] = useState<DashboardPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState<RangeId>("session");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [busySymbol, setBusySymbol] = useState<string | null>(null);
  const [busyScalper, setBusyScalper] = useState<string | null>(null);
  const [busyRegime, setBusyRegime] = useState<string | null>(null);
  const [busyManualSell, setBusyManualSell] = useState<string | null>(null);
  const [busyManualStoploss, setBusyManualStoploss] = useState<string | null>(null);
  const [busyCloseAll, setBusyCloseAll] = useState(false);
  const [busyCooldown, setBusyCooldown] = useState(false);
  const [manualStoplossRules, setManualStoplossRules] = useState<Record<string, ManualStoplossRule>>({});
  const [manualStoplossDrafts, setManualStoplossDrafts] = useState<Record<string, ManualStoplossDraft>>({});
  const [riskDraft, setRiskDraft] = useState<RiskDraft | null>(null);
  const [volatilitySortKey, setVolatilitySortKey] = useState<
    "score" | "stretch" | "volatility" | "bounce"
  >("score");
  const [controlSort, setControlSort] = useState<{
    key: ControlSortKey;
    direction: "asc" | "desc";
  }>({
    key: "symbol",
    direction: "asc",
  });
  const [positionSort, setPositionSort] = useState<{
    key: PositionSortKey;
    direction: "asc" | "desc";
  }>({
    key: "attention",
    direction: "desc",
  });
  const [cooldownDraft, setCooldownDraft] = useState<{
    symbol: string;
    cooldownSeconds: number;
  } | null>(null);
  const [topTab, setTopTab] = useState<"overview" | "advancedTables" | "riskControls">("overview");
  const [advancedTab, setAdvancedTab] = useState<"analytics" | "riskControls">("analytics");
  const [riskDirty, setRiskDirty] = useState(false);
  const [savingRisk, setSavingRisk] = useState(false);
  const loadSeqRef = useRef(0);

  const syncManualStoplossDrafts = useCallback(
    (
      positions: DashboardPayload["positions"],
      rules: Record<string, ManualStoplossRule>,
      forceServerValues = false,
    ) => {
      setManualStoplossDrafts((previous) => {
        const next: Record<string, ManualStoplossDraft> = {};
        for (const position of positions) {
          const symbol = position.symbol;
          if (!forceServerValues && previous[symbol]) {
            next[symbol] = previous[symbol];
            continue;
          }
          next[symbol] = buildManualStoplossDraft(rules[symbol]);
        }
        return next;
      });
    },
    [],
  );

  const loadDashboard = useCallback(async () => {
    const loadSeq = ++loadSeqRef.current;
    try {
      const controller = new AbortController();
      const timeoutHandle = window.setTimeout(() => controller.abort(), 12000);
      const response = await fetch("/api/dashboard", {
        cache: "no-store",
        signal: controller.signal,
      }).finally(() => {
        window.clearTimeout(timeoutHandle);
      });
      if (!response.ok) {
        throw new Error(`Dashboard request failed (${response.status})`);
      }

      const payload = (await response.json()) as DashboardPayload;
      let stoplossRules: Record<string, ManualStoplossRule> = {};
      if (payload.positions.length > 0) {
        try {
          const stoplossResponse = await fetch("/api/manual-stoploss", { cache: "no-store" });
          if (stoplossResponse.ok) {
            const rawPayload = (await stoplossResponse.json()) as {
              rules?: Record<string, unknown>;
            };
            const rawRules = rawPayload.rules ?? {};
            if (rawRules && typeof rawRules === "object" && !Array.isArray(rawRules)) {
              const nextRules: Record<string, ManualStoplossRule> = {};
              for (const [symbol, rawRule] of Object.entries(rawRules)) {
                const parsed = toManualStoplossRule(rawRule);
                if (!parsed) {
                  continue;
                }
                nextRules[symbol] = parsed;
              }
              stoplossRules = nextRules;
            }
          }
        } catch {
          // fallback for stoploss state is optional at render time
        }
      }

      if (loadSeq !== loadSeqRef.current) {
        return;
      }

      startTransition(() => {
        setData(payload);
        setError(null);
      });
      setManualStoplossRules(stoplossRules);
      syncManualStoplossDrafts(payload.positions, stoplossRules);

      if (!riskDirty) {
        setRiskDraft({
          maxConcurrentTrades: payload.summary.maxConcurrentTrades,
          maxConcurrentTradesPerToken: payload.summary.maxConcurrentTradesPerToken,
          maxTradeAmountUsd: payload.summary.maxTradeAmountUsd,
          maxPortfolioExposurePct: payload.summary.maxPortfolioExposurePct,
          maxExposurePerTokenPct: payload.summary.maxExposurePerTokenPct,
          tradeAmountUsd: payload.summary.tradeAmountUsd,
          signalConfirmationCycles: payload.summary.signalConfirmationCycles,
          tradeWindowEnabled: payload.summary.tradeWindowEnabled,
          tradeWindowStartHourUtc: payload.summary.tradeWindowStartHourUtc,
          tradeWindowEndHourUtc: payload.summary.tradeWindowEndHourUtc,
          dailyLossLimitUsd: payload.summary.dailyLossLimitUsd,
          dailyLossAutoPause: payload.summary.dailyLossAutoPause,
          dailyLossCloseAll: payload.summary.dailyLossCloseAll,
        });
      }

      setCooldownDraft((prev) => {
        const firstSymbol = payload.symbolControls[0]?.symbol ?? "";
        const symbol = prev?.symbol || firstSymbol;
        if (!symbol) {
          return null;
        }
        const override = payload.summary.symbolCooldownOverrides[symbol];
        const fallback = payload.summary.cooldownSeconds || 90;
        return {
          symbol,
          cooldownSeconds: Number.isFinite(override) ? override : fallback,
        };
      });
    } catch (requestError) {
      if (loadSeq !== loadSeqRef.current) {
        return;
      }
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Unable to load dashboard";
      setError(message);
    }
  }, [riskDirty, syncManualStoplossDrafts]);

  function applyRiskDraft(changes: Partial<RiskDraft>) {
    if (!data) {
      return;
    }

    setRiskDraft((prev) => ({
      maxConcurrentTrades: prev?.maxConcurrentTrades ?? data.summary.maxConcurrentTrades,
      maxConcurrentTradesPerToken:
        prev?.maxConcurrentTradesPerToken ?? data.summary.maxConcurrentTradesPerToken,
      maxTradeAmountUsd: prev?.maxTradeAmountUsd ?? data.summary.maxTradeAmountUsd,
      maxPortfolioExposurePct:
        prev?.maxPortfolioExposurePct ?? data.summary.maxPortfolioExposurePct,
      maxExposurePerTokenPct:
        prev?.maxExposurePerTokenPct ?? data.summary.maxExposurePerTokenPct,
      tradeAmountUsd: prev?.tradeAmountUsd ?? data.summary.tradeAmountUsd,
      signalConfirmationCycles:
        prev?.signalConfirmationCycles ?? data.summary.signalConfirmationCycles,
      tradeWindowEnabled:
        prev?.tradeWindowEnabled ?? data.summary.tradeWindowEnabled,
      tradeWindowStartHourUtc:
        prev?.tradeWindowStartHourUtc ?? data.summary.tradeWindowStartHourUtc,
      tradeWindowEndHourUtc:
        prev?.tradeWindowEndHourUtc ?? data.summary.tradeWindowEndHourUtc,
      dailyLossLimitUsd: prev?.dailyLossLimitUsd ?? data.summary.dailyLossLimitUsd,
      dailyLossAutoPause:
        prev?.dailyLossAutoPause ?? data.summary.dailyLossAutoPause,
      dailyLossCloseAll:
        prev?.dailyLossCloseAll ?? data.summary.dailyLossCloseAll,
      ...changes,
    }));
    setRiskDirty(true);
  }

  async function runAction(action: "start" | "stop" | "kill" | "refresh") {
    if (busyAction !== null || busyCloseAll || savingRisk) {
      return;
    }
    if (action === "refresh") {
      await loadDashboard();
      return;
    }

    setBusyAction(action);

    try {
      const endpoint = action === "kill" ? "/api/kill" : "/api/control";
      const request =
        action === "kill"
          ? {
              method: "POST",
              headers: buildMutatingAuthHeaders(),
            }
          : {
              method: "POST",
              headers: buildMutatingAuthHeaders({ "Content-Type": "application/json" }),
              body: JSON.stringify({ action }),
            };

      const response = await fetch(endpoint, request);

      if (!response.ok) {
        throw new Error(await parseApiErrorMessage(response, "Action failed"));
      }

      await loadDashboard();
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Action failed";
      setError(message);
    } finally {
      setBusyAction(null);
    }
  }

  async function setSymbolAutoTrade(
    symbol: string,
    side: "buy" | "sell",
    enabled: boolean,
  ) {
    if (
      busyAction !== null
      || busySymbol !== null
      || busyScalper !== null
      || busyRegime !== null
      || savingRisk
    ) {
      return;
    }
    setBusySymbol(`${symbol}:${side}`);

    try {
      const response = await fetch("/api/symbols", {
        method: "POST",
        headers: buildMutatingAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ symbol, side, enabled }),
      });

      if (!response.ok) {
        throw new Error(await parseApiErrorMessage(response, "Symbol update failed"));
      }

      await loadDashboard();
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Symbol update failed";
      setError(message);
    } finally {
      setBusySymbol(null);
    }
  }

  async function setScalperMode(symbol: string, enabled: boolean) {
    if (
      busyAction !== null
      || busyScalper !== null
      || busySymbol !== null
      || busyRegime !== null
      || savingRisk
    ) {
      return;
    }
    setBusyScalper(symbol);

    try {
      const response = await fetch("/api/scalper", {
        method: "POST",
        headers: buildMutatingAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ symbol, enabled }),
      });

      if (!response.ok) {
        throw new Error(await parseApiErrorMessage(response, "Scalper update failed"));
      }

      await loadDashboard();
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Scalper update failed";
      setError(message);
    } finally {
      setBusyScalper(null);
    }
  }

  async function setTokenRegime(symbol: string, regime: string) {
    if (
      busyAction !== null
      || busyRegime !== null
      || busySymbol !== null
      || busyScalper !== null
      || savingRisk
    ) {
      return;
    }
    setBusyRegime(symbol);

    try {
      const response = await fetch("/api/token-regime", {
        method: "POST",
        headers: buildMutatingAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ symbol, regime }),
      });

      if (!response.ok) {
        throw new Error(await parseApiErrorMessage(response, "Regime update failed"));
      }

      await loadDashboard();
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Regime update failed";
      setError(message);
    } finally {
      setBusyRegime(null);
    }
  }

  async function saveRiskSettings() {
    if (!riskDraft || savingRisk) {
      return;
    }

    const maxConcurrentTrades = Math.max(
      1,
      Math.floor(Number(riskDraft.maxConcurrentTrades) || 1),
    );
    const maxConcurrentTradesPerToken = Math.max(
      1,
      Math.floor(Number(riskDraft.maxConcurrentTradesPerToken) || 1),
    );
    const maxTradeAmountUsd = Math.max(1, Number(riskDraft.maxTradeAmountUsd) || 1);
    const maxPortfolioExposurePct = Math.max(
      1,
      Math.min(100, Number(riskDraft.maxPortfolioExposurePct) || 100),
    );
    const maxExposurePerTokenPct = Math.max(
      1,
      Math.min(100, Number(riskDraft.maxExposurePerTokenPct) || 100),
    );
    const tradeAmountUsd = Math.max(1, Number(riskDraft.tradeAmountUsd) || 1);
    const signalConfirmationCycles = Math.max(
      1,
      Math.floor(Number(riskDraft.signalConfirmationCycles) || 1),
    );
    const tradeWindowStartHourUtc = Math.max(
      0,
      Math.min(23, Math.floor(Number(riskDraft.tradeWindowStartHourUtc) || 0)),
    );
    const tradeWindowEndHourUtc = Math.max(
      0,
      Math.min(23, Math.floor(Number(riskDraft.tradeWindowEndHourUtc) || 23)),
    );
    const dailyLossLimitUsd = Math.max(0, Number(riskDraft.dailyLossLimitUsd) || 0);

    setSavingRisk(true);
    try {
      const response = await fetch("/api/risk", {
        method: "POST",
        headers: buildMutatingAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          maxConcurrentTrades,
          maxConcurrentTradesPerToken,
          maxTradeAmountUsd,
          maxPortfolioExposurePct,
          maxExposurePerTokenPct,
          tradeAmountUsd,
          signalConfirmationCycles,
          tradeWindowEnabled: riskDraft.tradeWindowEnabled,
          tradeWindowStartHourUtc,
          tradeWindowEndHourUtc,
          dailyLossLimitUsd,
          dailyLossAutoPause: riskDraft.dailyLossAutoPause,
          dailyLossCloseAll: riskDraft.dailyLossCloseAll,
        }),
      });

      if (!response.ok) {
        throw new Error(await parseApiErrorMessage(response, "Risk settings update failed"));
      }

      setRiskDirty(false);
      await loadDashboard();
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Risk settings update failed";
      setError(message);
    } finally {
      setSavingRisk(false);
    }
  }

  async function saveCooldownOverride(removeOverride = false) {
    if (!cooldownDraft?.symbol || busyCooldown || busyAction !== null || savingRisk) {
      return;
    }

    setBusyCooldown(true);
    try {
      const payload = removeOverride
        ? { symbol: cooldownDraft.symbol, cooldownSeconds: null }
        : {
            symbol: cooldownDraft.symbol,
            cooldownSeconds: Math.max(1, Number(cooldownDraft.cooldownSeconds) || 1),
          };

      const response = await fetch("/api/cooldown", {
        method: "POST",
        headers: buildMutatingAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error(`Cooldown override failed (${response.status})`);
      }

      await loadDashboard();
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Cooldown override failed";
      setError(message);
    } finally {
      setBusyCooldown(false);
    }
  }

  async function closeAllPositions() {
    if (busyCloseAll || busyAction !== null || savingRisk) {
      return;
    }
    const currentData = data;
    if (!currentData) {
      setError("Dashboard data not loaded.");
      return;
    }

    if (currentData.positions.length === 0) {
      setError("No open positions to close.");
      return;
    }

    const totalEstimated = currentData.positions.reduce(
      (sum, position) => sum + position.unrealizedValue,
      0,
    );
    const pnlLabel = `${formatCurrency(totalEstimated)} (${formatPercent(
      currentData.summary.startingBalance > 0
        ? (totalEstimated / currentData.summary.startingBalance) * 100
        : 0,
    )})`;

    const confirmation = window.confirm(
      [
        `Close ALL open positions now? (${currentData.positions.length} positions)`,
        "",
        `Estimated combined PnL: ${pnlLabel}`,
        "This action will execute immediate SELL for every open position.",
      ].join("\n"),
    );
    if (!confirmation) {
      return;
    }

    setBusyCloseAll(true);
    try {
      const actionId = buildActionId("close-all");
      const response = await fetch("/api/close-all", {
        method: "POST",
        headers: buildMutatingAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ reason: "manual_close_all", actionId }),
      });
      if (!response.ok) {
        const details = await response.text();
        throw new Error(`Close-all failed (${response.status})${details ? `: ${details}` : ""}`);
      }

      await loadDashboard();
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Close-all failed";
      setError(message);
    } finally {
      setBusyCloseAll(false);
    }
  }

  async function manualSell(position: DashboardPayload["positions"][number]) {
    if (busyManualSell !== null || busyAction !== null || savingRisk) {
      return;
    }
    const directionLabel = position.unrealizedValue >= 0 ? "Estimated profit" : "Estimated loss";
    const currentPriceLabel =
      position.currentPrice === null
        ? "Unavailable (entry fallback may be used)"
        : formatCurrency(position.currentPrice);

    const confirmationText = [
      `Manual SELL ${position.symbol}?`,
      "",
      `Current price: ${currentPriceLabel}`,
      `Entry price: ${formatCurrency(position.entryPrice)}`,
      `Position value: ${formatCurrency(position.marketValue)}`,
      `${directionLabel}: ${formatCurrency(position.unrealizedValue)} (${formatPercent(position.unrealizedPct)})`,
      "",
      "This will close the position immediately.",
    ].join("\n");

    const approved = window.confirm(confirmationText);
    if (!approved) {
      return;
    }

    setBusyManualSell(position.symbol);
    try {
      const actionId = buildActionId(`manual-sell-${position.symbol}`);
      const response = await fetch("/api/manual-sell", {
        method: "POST",
        headers: buildMutatingAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ symbol: position.symbol, actionId }),
      });

      if (!response.ok) {
        const details = await response.text();
        throw new Error(`Manual sell failed (${response.status})${details ? `: ${details}` : ""}`);
      }

      await loadDashboard();
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Manual sell failed";
      setError(message);
    } finally {
      setBusyManualSell(null);
    }
  }

  function updateManualStoplossDraft(
    symbol: string,
    changes: Partial<ManualStoplossDraft>,
  ) {
    setManualStoplossDrafts((previous) => {
      const current = previous[symbol] ?? buildManualStoplossDraft(manualStoplossRules[symbol]);
      return {
        ...previous,
        [symbol]: {
          ...current,
          ...changes,
        },
      };
    });
  }

  async function saveManualStoploss(symbol: string) {
    if (busyManualStoploss !== null || busyAction !== null || savingRisk) {
      return;
    }
    const draft = manualStoplossDrafts[symbol] ?? buildManualStoplossDraft(manualStoplossRules[symbol]);
    const numericValue = Number(draft.valueText);
    const value = Number.isFinite(numericValue) && numericValue > 0 ? numericValue : null;

    if (draft.enabled && value === null) {
      setError("Stoploss value must be a positive number.");
      return;
    }

    setBusyManualStoploss(symbol);
    try {
      const response = await fetch("/api/manual-stoploss", {
        method: "POST",
        headers: buildMutatingAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          symbol,
          enabled: draft.enabled,
          type: draft.type,
          value,
        }),
      });
      if (!response.ok) {
        const details = await response.text();
        throw new Error(
          `Manual stoploss update failed (${response.status})${details ? `: ${details}` : ""}`,
        );
      }

      const payload = (await response.json()) as { rule?: unknown };
      const parsedRule = toManualStoplossRule(payload.rule);
      if (parsedRule) {
        setManualStoplossRules((previous) => ({ ...previous, [symbol]: parsedRule }));
        syncManualStoplossDrafts(
          data?.positions ?? [],
          { ...manualStoplossRules, [symbol]: parsedRule },
          true,
        );
      }

      setError(null);
      await loadDashboard();
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Manual stoploss update failed";
      setError(message);
    } finally {
      setBusyManualStoploss(null);
    }
  }

  function setControlSortKey(key: ControlSortKey) {
    setControlSort((previous) => {
      if (previous.key === key) {
        return {
          key,
          direction: previous.direction === "desc" ? "asc" : "desc",
        };
      }

      if (
        key === "symbol"
        || key === "mode"
        || key === "configuredRegime"
        || key === "regime"
        || key === "volatility"
      ) {
        return { key, direction: "asc" };
      }

      return { key, direction: "desc" };
    });
  }

  function controlSortIndicator(key: ControlSortKey) {
    if (controlSort.key !== key) {
      return "";
    }
    return controlSort.direction === "desc" ? "v" : "^";
  }

  function setPositionSortKey(key: PositionSortKey) {
    setPositionSort((previous) => {
      if (previous.key === key) {
        return {
          key,
          direction: previous.direction === "desc" ? "asc" : "desc",
        };
      }

      if (
        key === "symbol"
        || key === "side"
        || key === "status"
      ) {
        return { key, direction: "asc" };
      }

      if (key === "pnl" || key === "pnlPct" || key === "worstDip" || key === "change24h") {
        return { key, direction: "asc" };
      }

      return { key, direction: "desc" };
    });
  }

  useEffect(() => {
    let cancelled = false;

    const refresh = async () => {
      if (cancelled) {
        return;
      }

      await loadDashboard();
    };

    refresh();
    const timer = window.setInterval(refresh, 15000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [loadDashboard]);

  if (!data) {
    return (
      <main className="rb-page min-h-screen px-3 py-8 sm:px-4 lg:px-6">
        <div className="rb-shell mx-auto flex w-full max-w-[1720px] justify-center">
          <div className="hidden w-20 shrink-0 rounded-md border border-white/8 bg-black/40 lg:block" />
          <div className="flex-1 space-y-8">
            <section className="rounded-lg border border-sky-400/25 bg-sky-500/10 px-5 py-4 text-slate-100">
              <h1 className="text-lg font-semibold tracking-tight">RevBot Dashboard</h1>
              <p className="mt-1 text-sm text-slate-300">
                Loading live dashboard data...
              </p>
              {error ? (
                <div className="mt-3 rounded-md border border-rose-400/40 bg-rose-500/15 px-3 py-2 text-sm text-rose-100">
                  {error}
                </div>
              ) : null}
            </section>
            <div className="h-[420px] animate-pulse rounded-md border border-white/8 bg-white/[0.04]" />
            <div className="grid gap-6 lg:grid-cols-3">
              <div className="h-40 animate-pulse rounded-lg border border-white/8 bg-white/[0.04]" />
              <div className="h-40 animate-pulse rounded-lg border border-white/8 bg-white/[0.04]" />
              <div className="h-40 animate-pulse rounded-lg border border-white/8 bg-white/[0.04]" />
            </div>
            <div className="h-[420px] animate-pulse rounded-md border border-white/8 bg-white/[0.04]" />
          </div>
        </div>
      </main>
    );
  }

  const selectedRange =
    RANGE_OPTIONS.find((option) => option.id === range) ?? RANGE_OPTIONS[1];
  const visiblePointsRaw =
    selectedRange.points === Number.POSITIVE_INFINITY
      ? data.chart.points
      : data.chart.points.slice(-selectedRange.points);
  const visiblePoints =
    visiblePointsRaw.length > 0 ? visiblePointsRaw : [data.summary.totalEquity];
  const chartMin = Math.min(...visiblePoints);
  const chartMax = Math.max(...visiblePoints);
  const positiveNet = data.summary.netPnl >= 0;
  const totalPnlLabel = positiveNet ? "Net gain" : "Net drawdown";
  const nowUnixSeconds = Date.now() / 1000;
  const snapshotTimestampMs = data.summary.lastSnapshotAt
    ? Date.parse(data.summary.lastSnapshotAt)
    : Number.NaN;
  const snapshotAgeMinutes = Number.isFinite(snapshotTimestampMs)
    ? Math.max(0, (Date.now() - snapshotTimestampMs) / 60000)
    : null;
  const topExposureSymbol =
    [...data.positions].sort((left, right) => right.marketValue - left.marketValue)[0]
      ?.symbol ?? null;
  const topWinnerSymbol =
    [...data.positions]
      .filter((position) => position.unrealizedValue > 0)
      .sort((left, right) => right.unrealizedValue - left.unrealizedValue)[0]
      ?.symbol ?? null;
  const sortedSymbolControls = [...data.symbolControls].sort((left, right) => {
    const keyOf = (row: DashboardPayload["symbolControls"][number]) => {
      if (controlSort.key === "mode") {
        return (
          row.buyEnabled && row.sellEnabled
            ? "buy+sell"
            : row.buyEnabled
              ? "buy"
              : row.sellEnabled
                ? "sell"
                : "paused"
        );
      }
      if (controlSort.key === "configuredRegime") {
        return String(row.configuredRegime ?? "").toLowerCase();
      }
      if (controlSort.key === "regime") {
        return formatDetectedRegime(row.suggestedRegimeV2 ?? row.detectedRegime).toLowerCase();
      }
      if (controlSort.key === "confidence") {
        return Number(row.detectedRegimeConfidenceScore ?? confidenceScoreFromLabel(row.detectedRegimeConfidenceLabel));
      }
      if (controlSort.key === "volatility") {
        return String(row.detectedRegimeVolatilityState ?? "unknown").toLowerCase();
      }
      if (controlSort.key === "price") {
        return Number(row.price ?? -1);
      }
      if (controlSort.key === "change24h") {
        return Number(row.change24hPct ?? -999);
      }
      if (controlSort.key === "high24h") {
        return Number(row.high24h ?? -1);
      }
      if (controlSort.key === "low24h") {
        return Number(row.low24h ?? -1);
      }
      if (controlSort.key === "buyOpportunity") {
        return Number(row.buyOpportunityPct ?? -1);
      }
      if (controlSort.key === "buyExecutable") {
        return row.buyExecutable ? 1 : 0;
      }
      if (controlSort.key === "scalper") {
        return row.scalperEnabled ? 1 : 0;
      }
      if (controlSort.key === "buy") {
        return row.buyEnabled ? 1 : 0;
      }
      if (controlSort.key === "sell") {
        return row.sellEnabled ? 1 : 0;
      }
      if (controlSort.key === "dataQuality") {
        const regimeQuality = dataQualityRank(row.regimeDataQualityStatus);
        const volatilityQuality = dataQualityRank(row.volatilityDataQualityStatus);
        return Math.min(regimeQuality, volatilityQuality);
      }
      return row.symbol.toLowerCase();
    };
    const leftKey = keyOf(left);
    const rightKey = keyOf(right);
    const delta = leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0;
    if (delta !== 0) {
      return controlSort.direction === "asc" ? delta : -delta;
    }
    return left.symbol.localeCompare(right.symbol);
  });
  const sortedRotationRows = [...data.symbolControls].sort((left, right) => (
    Number(right.rotationShortTermScore ?? -1) - Number(left.rotationShortTermScore ?? -1)
  ) || (
    Number(right.rotationDelta ?? -999) - Number(left.rotationDelta ?? -999)
  ) || left.symbol.localeCompare(right.symbol));
  const sortedVolatilityRadarRows = [...data.symbolControls].sort((left, right) => {
    const keyOf = (row: DashboardPayload["symbolControls"][number]) => {
      if (volatilitySortKey === "stretch") {
        return Number(row.volatilityOpportunityStretchScore ?? -1);
      }
      if (volatilitySortKey === "volatility") {
        return Number(row.volatilityOpportunityVolatilitySpikeScore ?? -1);
      }
      if (volatilitySortKey === "bounce") {
        return Number(row.volatilityOpportunityBounceContextScore ?? -1);
      }
      return Number(row.volatilityOpportunityScore ?? -1);
    };
    const keyDelta = keyOf(right) - keyOf(left);
    if (keyDelta !== 0) {
      return keyDelta;
    }
    return left.symbol.localeCompare(right.symbol);
  });
  const symbolControlsBySymbol = new Map(
    data.symbolControls.map((control) => [control.symbol, control]),
  );
  const positionsWithMeta = data.positions.map((position) => {
    const control = symbolControlsBySymbol.get(position.symbol);
    const ageHours = position.entryTime
      ? Math.max(0, (nowUnixSeconds - position.entryTime) / 3600)
      : null;
    const bounceScore = control?.volatilityOpportunityScore ?? null;
    const attentionScore =
      (position.advisoryStaleLosingReview ? 120 : 0)
      + (position.unrealizedPct < 0 ? Math.min(60, Math.abs(position.unrealizedPct)) : 0)
      + (position.advisoryMaxDrawdownPctDuringTrade < 0
        ? Math.min(40, Math.abs(position.advisoryMaxDrawdownPctDuringTrade))
        : 0);
    const severity =
      attentionScore >= 140 || position.unrealizedPct <= -10
        ? "High"
        : attentionScore >= 90 || position.unrealizedPct <= -5
          ? "Medium"
          : "Low";

    return {
      ...position,
      price: control?.price ?? position.currentPrice ?? null,
      change24hPct: control?.change24hPct ?? null,
      high24h: control?.high24h ?? null,
      low24h: control?.low24h ?? null,
      ageHours,
      bounceScore,
      bounceLabel: volatilityLabel(control?.volatilityOpportunityLabel ?? null),
      trendShift: control?.rotationDelta ?? null,
      attentionScore,
      severity,
    };
  });
  const sortedPositions = [...positionsWithMeta].sort((left, right) => {
    const valueFor = (row: (typeof positionsWithMeta)[number]): number | string => {
      if (positionSort.key === "symbol") {
        return row.symbol.toLowerCase();
      }
      if (positionSort.key === "side") {
        return "long";
      }
      if (positionSort.key === "units") {
        return row.units;
      }
      if (positionSort.key === "entry") {
        return row.entryPrice;
      }
      if (positionSort.key === "price") {
        return row.price ?? -1;
      }
      if (positionSort.key === "change24h") {
        return row.change24hPct ?? -999;
      }
      if (positionSort.key === "high24h") {
        return row.high24h ?? -1;
      }
      if (positionSort.key === "low24h") {
        return row.low24h ?? -1;
      }
      if (positionSort.key === "value") {
        return row.marketValue;
      }
      if (positionSort.key === "allocation") {
        return row.allocationPct;
      }
      if (positionSort.key === "pnl") {
        return row.unrealizedValue;
      }
      if (positionSort.key === "pnlPct") {
        return row.unrealizedPct;
      }
      if (positionSort.key === "lock") {
        return row.profitLockPct ?? -999;
      }
      if (positionSort.key === "peak") {
        return row.peakPnlPct;
      }
      if (positionSort.key === "age") {
        return row.ageHours ?? -1;
      }
      if (positionSort.key === "worstDip") {
        return row.advisoryMaxDrawdownPctDuringTrade;
      }
      if (positionSort.key === "review") {
        return row.advisoryStaleLosingReview ? 1 : 0;
      }
      if (positionSort.key === "bounce") {
        return row.bounceScore ?? -1;
      }
      if (positionSort.key === "status") {
        return String(row.status ?? "").toLowerCase();
      }
      return row.attentionScore;
    };

    const leftKey = valueFor(left);
    const rightKey = valueFor(right);
    const delta = (
      typeof leftKey === "string" || typeof rightKey === "string"
    )
      ? String(leftKey).localeCompare(String(rightKey))
      : Number(leftKey) - Number(rightKey);
    if (delta !== 0) {
      return positionSort.direction === "asc" ? delta : -delta;
    }

    if (left.advisoryStaleLosingReview !== right.advisoryStaleLosingReview) {
      return left.advisoryStaleLosingReview ? -1 : 1;
    }

    return left.symbol.localeCompare(right.symbol);
  });
  const attentionItems: Array<{
    symbol: string | null;
    issue: string;
    severity: "High" | "Medium" | "Low";
    status: string;
    action: string;
  }> = [];
  if (data.summary.dailyBuyPaused) {
    attentionItems.push({
      symbol: null,
      issue: "Daily loss guard paused BUY",
      severity: "High",
      status: "Runtime",
      action: "Review risk settings",
    });
  }
  const staleSymbols = positionsWithMeta.filter((position) => position.advisoryStaleLosingReview);
  staleSymbols.slice(0, 2).forEach((position) => {
    attentionItems.push({
      symbol: position.symbol,
      issue: "Needs stale-loss review",
      severity: "High",
      status: `Age ${formatHours(position.ageHours)} | ${formatPercent(position.unrealizedPct)}`,
      action: "Open token page",
    });
  });
  const largestLoser =
    [...positionsWithMeta].sort((left, right) => left.unrealizedValue - right.unrealizedValue)[0] ??
    null;
  if (largestLoser && largestLoser.unrealizedValue < 0) {
    attentionItems.push({
      symbol: largestLoser.symbol,
      issue: "Largest open loser",
      severity: largestLoser.unrealizedPct <= -10 ? "High" : "Medium",
      status: `${formatCurrency(largestLoser.unrealizedValue)} (${formatPercent(largestLoser.unrealizedPct)})`,
      action: "Review position",
    });
  }
  const trapCandidate = sortedRotationRows.find(
    (control) => control.rotationStatus === "Capital Trap Risk" && control.hasOpenPosition,
  );
  if (trapCandidate) {
    attentionItems.push({
      symbol: trapCandidate.symbol,
      issue: "Capital trap risk",
      severity: "Medium",
      status: trapCandidate.rotationStatus,
      action: "Check trend shift",
    });
  }
  const topOpportunity = sortedVolatilityRadarRows.find(
    (control) => control.volatilityOpportunityScore !== null,
  );
  if (topOpportunity && topOpportunity.volatilityOpportunityLabel === "HIGH") {
    attentionItems.push({
      symbol: topOpportunity.symbol,
      issue: "Strong bounce setup",
      severity: "Low",
      status: `${topOpportunity.volatilityOpportunityScore?.toFixed(1) ?? "N/A"} score`,
      action: "Compare with open risk",
    });
  }
  if (snapshotAgeMinutes !== null && snapshotAgeMinutes > 10) {
    attentionItems.push({
      symbol: null,
      issue: "Snapshot feed stale",
      severity: snapshotAgeMinutes > 30 ? "High" : "Medium",
      status: `${snapshotAgeMinutes.toFixed(1)}m old`,
      action: "Check data feed",
    });
  }
  const sortedAttentionItems = [...attentionItems].sort((left, right) => {
    const rank = { High: 3, Medium: 2, Low: 1 };
    const delta = rank[right.severity] - rank[left.severity];
    if (delta !== 0) {
      return delta;
    }
    return (left.symbol ?? "").localeCompare(right.symbol ?? "");
  });
  const topStatusCards = [
    {
      label: "Bot Status",
      value: data.summary.enabled ? "Process Online" : "Process Offline",
      helper: `Trading ${data.summary.tradingEnabled ? "Armed" : "Disarmed"} | Mode ${String(data.summary.executionMode).toUpperCase()}`,
      tone: data.summary.enabled ? "text-emerald-200" : "text-rose-200",
    },
    {
      label: "Net P/L",
      value: `${formatCurrency(data.summary.netPnl)} (${formatPercent(data.summary.netReturnPct)})`,
      helper: `Realized ${formatCurrency(data.summary.realizedPnl)} | Open ${formatCurrency(
        data.summary.unrealizedPnl,
      )}`,
      tone: valueTone(data.summary.netPnl),
    },
    {
      label: "Cash Available",
      value: formatCurrency(data.summary.cashBalance),
      helper: `${percentFormatter.format(100 - data.summary.openExposurePct)}% undeployed`,
      tone: "text-white",
    },
    {
      label: "Capital Deployed",
      value: formatCurrency(data.summary.openValue),
      helper: `${percentFormatter.format(data.summary.openExposurePct)}% exposure`,
      tone: "text-white",
    },
    {
      label: "Open Positions",
      value: String(data.summary.openPositions),
      helper: `${data.summary.buyCount} buys | ${data.summary.sellCount} sells`,
      tone: "text-white",
    },
    {
      label: "Attention Alerts",
      value: String(sortedAttentionItems.length),
      helper:
        sortedAttentionItems.length > 0
          ? sortedAttentionItems[0].issue
          : "No active alerts",
      tone:
        sortedAttentionItems.length === 0
          ? "text-emerald-200"
          : sortedAttentionItems.some((item) => item.severity === "High")
            ? "text-rose-200"
            : "text-amber-200",
    },
  ];
  const performanceMetrics = [
    { label: "Net P/L", value: `${formatCurrency(data.summary.netPnl)} (${formatPercent(data.summary.netReturnPct)})`, tone: valueTone(data.summary.netPnl) },
    { label: "Realized P/L", value: formatCurrency(data.summary.realizedPnl), tone: valueTone(data.summary.realizedPnl) },
    { label: "Open P/L", value: formatCurrency(data.summary.unrealizedPnl), tone: valueTone(data.summary.unrealizedPnl) },
    {
      label: "Win Rate",
      value:
        data.summary.sellCount > 0
          ? `${percentFormatter.format((data.summary.sellCount / Math.max(data.summary.buyCount, 1)) * 100)}%`
          : "N/A",
      tone: "text-white",
    },
    { label: "Total Buys / Sells", value: `${data.summary.buyCount} / ${data.summary.sellCount}`, tone: "text-white" },
    {
      label: "Avg Closed Trade P/L",
      value:
        data.summary.sellCount > 0
          ? formatCurrency(data.summary.realizedPnl / Math.max(data.summary.sellCount, 1))
          : "N/A",
      tone:
        data.summary.sellCount > 0
          ? valueTone(data.summary.realizedPnl / Math.max(data.summary.sellCount, 1))
          : "text-slate-400",
    },
  ];
  const largestOpenLoser =
    [...positionsWithMeta].sort((left, right) => left.unrealizedValue - right.unrealizedValue)[0] ??
    null;
  const riskMetrics = [
    { label: "Cash", value: formatCurrency(data.summary.cashBalance), tone: "text-white" },
    { label: "Exposure", value: formatCurrency(data.summary.openValue), tone: "text-white" },
    { label: "Deployment %", value: `${percentFormatter.format(data.summary.openExposurePct)}%`, tone: "text-white" },
    { label: "Needs Review", value: `${data.summary.staleLosingReviewCount}`, tone: data.summary.staleLosingReviewCount > 0 ? "text-amber-200" : "text-emerald-200" },
    {
      label: "Worst Open Drawdown",
      value:
        data.summary.maxDrawdownDuringTradePct < 0
          ? `${data.summary.maxDrawdownDuringTradeSymbol ?? "N/A"} ${formatPercent(data.summary.maxDrawdownDuringTradePct)}`
          : "N/A",
      tone: data.summary.maxDrawdownDuringTradePct < 0 ? "text-rose-200" : "text-slate-400",
    },
    {
      label: "Largest Open Loser",
      value:
        largestOpenLoser && largestOpenLoser.unrealizedValue < 0
          ? `${largestOpenLoser.symbol} ${formatCurrency(largestOpenLoser.unrealizedValue)}`
          : "N/A",
      tone:
        largestOpenLoser && largestOpenLoser.unrealizedValue < 0
          ? "text-rose-200"
          : "text-slate-400",
    },
  ];
  const topRotationRows = sortedRotationRows.slice(0, 12);
  const topVolatilityRows = sortedVolatilityRadarRows.slice(0, 12);
  const sortIndicator = (key: PositionSortKey) => {
    if (positionSort.key !== key) {
      return "";
    }
    return positionSort.direction === "desc" ? "v" : "^";
  };
  const comparisonRows = [
    {
      metric: "Runtime",
      accountValue: `${data.summary.enabled ? "Running" : "Paused"} | ${String(
        data.summary.executionMode,
      ).toUpperCase()}`,
      accountTone: data.summary.enabled ? "text-emerald-300" : "text-rose-300",
      configValue: `${data.summary.cooldownSeconds}s cool | ${data.summary.maxConcurrentTrades} max | ${data.summary.maxConcurrentTradesPerToken}/token | ${data.summary.maxPortfolioExposurePct}% port | ${data.summary.maxExposurePerTokenPct}% token | ${formatCurrency(data.summary.maxTradeAmountUsd)} cap | ${formatCurrency(data.summary.tradeAmountUsd)} size`,
      configTone: "text-amber-200",
      stateValue: formatSnapshotTime(data.summary.lastSnapshotAt),
      stateTone: "text-sky-200",
    },
    {
      metric: "Performance",
      accountValue: `${formatCurrency(data.summary.netPnl)} | ${formatPercent(
        data.summary.netReturnPct,
      )}`,
      accountTone: valueTone(data.summary.netPnl),
      configValue: `${data.summary.lookback} lookback | ${data.summary.minTrades} min`,
      configTone: "text-white",
      stateValue: "Source: paper_state.json",
      stateTone: "text-slate-200",
    },
    {
      metric: "Activity",
      accountValue: `${data.summary.buyCount} buys | ${data.summary.sellCount} sells`,
      accountTone: "text-white",
      configValue: `${data.summary.activeSymbols} buy on | ${data.summary.sellEnabledSymbols} sell on | ${data.summary.openPositions} open`,
      configTone: "text-white",
      stateValue: formatRelativeTime(data.summary.lastTradeAt),
      stateTone: "text-slate-200",
    },
    {
      metric: "Locks",
      accountValue: `${formatCurrency(data.summary.realizedPnl)} / ${formatCurrency(
        data.summary.unrealizedPnl,
      )}`,
      accountTone: valueTone(data.summary.netPnl),
      configValue: `${percentFormatter.format(
        data.summary.firstActivationPct,
      )}% arm | ${percentFormatter.format(data.summary.trailingActivationPct)}% trail | ${percentFormatter.format(
        data.summary.trailingGapPct,
      )}% gap`,
      configTone: "text-amber-200",
      stateValue: "Clears stale locks and old SELL state",
      stateTone: "text-slate-200",
    },
  ];

  function openTopTab(next: "overview" | "advancedTables" | "riskControls") {
    setTopTab(next);
    if (next === "advancedTables" || next === "riskControls") {
      setAdvancedTab(next === "riskControls" ? "riskControls" : "analytics");
      requestAnimationFrame(() => {
        const panel = document.getElementById("advanced-panels") as HTMLDetailsElement | null;
        if (panel) {
          panel.open = true;
          panel.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });
      return;
    }
    setAdvancedTab("analytics");
    requestAnimationFrame(() => {
      document.getElementById("dashboard-overview")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  const controlActionLocked =
    busyAction !== null || busyCloseAll || busyCooldown || savingRisk;

  return (
    <main className="rb-page min-h-screen px-3 py-8 sm:px-4 lg:px-6">
      <div className="rb-shell mx-auto flex w-full max-w-[1720px] justify-center">
        <aside className="hidden">
          <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-[linear-gradient(135deg,#f8fafc,#93c5fd_45%,#f59e0b)] text-lg font-bold text-slate-950">
            R
          </div>
          <div className="mt-6 space-y-2.5 text-center text-[10px] font-medium text-slate-400">
            <div className="rounded-lg border border-white/10 bg-white/[0.06] px-2 py-2.5 text-white">
              Home
            </div>
            <div className="rounded-lg px-2 py-2.5">Portfolio</div>
            <div className="rounded-lg px-2 py-2.5">Control</div>
            <div className="rounded-lg px-2 py-2.5">Risk</div>
          </div>
          <div className="mt-auto rounded-lg border border-white/10 bg-white/[0.04] p-2.5 text-center">
            <p className="text-[10px] uppercase tracking-[0.24em] text-slate-500">
              Mode
            </p>
            <p className="mt-1.5 text-xs font-semibold uppercase text-white">
              {data.summary.executionMode}
            </p>
          </div>
        </aside>

        <div className="flex-1 space-y-8">
          <header className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="rb-kicker">
                RevBot desk
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <h1 className="rb-title text-4xl tracking-tight sm:text-5xl">
                  Portfolio Monitor
                </h1>
                <span
                  className={`rb-chip ${
                    data.summary.tradingEnabled
                      ? "rb-chip--positive"
                      : "rb-chip--negative"
                  }`}
                >
                  {data.summary.tradingEnabled ? "Trading armed" : "Trading disarmed"}
                </span>
              </div>
              <p className="rb-helper mt-3 max-w-2xl text-sm">
                A live paper-trading surface built from local state files,
                recent journal events, and the latest snapshot lines in
                <code className="mx-1 rounded bg-white/5 px-1.5 py-0.5 text-slate-100">
                  bot.log
                </code>
                .
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => runAction("start")}
                disabled={controlActionLocked}
                className="rb-action-btn rb-action-btn--positive"
              >
                {busyAction === "start" ? "Starting..." : "Start bot"}
              </button>
              <button
                type="button"
                onClick={() => runAction("stop")}
                disabled={controlActionLocked}
                className="rb-action-btn rb-action-btn--warning"
              >
                {busyAction === "stop" ? "Stopping..." : "Stop bot"}
              </button>
              <button
                type="button"
                onClick={() => runAction("kill")}
                disabled={controlActionLocked}
                className="rb-action-btn rb-action-btn--danger"
              >
                {busyAction === "kill" ? "Locking..." : "Emergency stop"}
              </button>
              <button
                type="button"
                onClick={() => runAction("refresh")}
                disabled={controlActionLocked}
                className="rb-action-btn rb-action-btn--neutral"
              >
                Refresh
              </button>
              <button
                type="button"
                onClick={closeAllPositions}
                disabled={controlActionLocked || data.positions.length === 0}
                className="rb-action-btn rb-action-btn--accent"
              >
                {busyCloseAll ? "Closing..." : "Close all"}
              </button>
              <Link
                href="/universe"
                className="rb-action-btn rb-action-btn--neutral"
              >
                Universe Manager
              </Link>
            </div>
          </header>

          <div id="dashboard-overview" className="flex flex-wrap gap-2 text-[10px] font-semibold uppercase tracking-[0.14em]">
            <button
              type="button"
              onClick={() => openTopTab("overview")}
              className={`rounded-full border px-3 py-1.5 transition ${
                topTab === "overview"
                  ? "border-sky-400/50 bg-sky-500/20 text-sky-100"
                  : "border-white/10 bg-white/[0.03] text-slate-300 hover:border-white/20 hover:text-slate-100"
              }`}
            >
              Overview
            </button>
            <button
              type="button"
              onClick={() => openTopTab("advancedTables")}
              className={`rounded-full border px-3 py-1.5 transition ${
                topTab === "advancedTables"
                  ? "border-sky-400/50 bg-sky-500/20 text-sky-100"
                  : "border-white/10 bg-white/[0.03] text-slate-300 hover:border-white/20 hover:text-slate-100"
              }`}
            >
              Advanced Tables
            </button>
            <button
              type="button"
              onClick={() => openTopTab("riskControls")}
              className={`rounded-full border px-3 py-1.5 transition ${
                topTab === "riskControls"
                  ? "border-sky-400/50 bg-sky-500/20 text-sky-100"
                  : "border-white/10 bg-white/[0.03] text-slate-300 hover:border-white/20 hover:text-slate-100"
              }`}
            >
              Risk Controls
            </button>
          </div>

          {error ? (
            <div className="rb-content-card border-rose-400/35 bg-rose-500/12 px-5 py-4 text-sm text-rose-100">
              {error}
            </div>
          ) : null}

          <section className="rb-section p-5 sm:p-6">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="rb-kicker">
                  Token Controls
                </p>
                <h2 className="mt-1 text-xl font-semibold text-slate-100">
                  Auto-Trade by Symbol
                </h2>
                <p className="rb-helper mt-1 text-sm">
                  First-action control surface for BUY/SELL/scalper toggles.
                </p>
              </div>
              <div className="flex flex-wrap gap-2 text-[10px] font-semibold uppercase tracking-[0.12em]">
                <span className="rb-chip rb-chip--positive">
                  Buy On {data.summary.activeSymbols}
                </span>
                <span className="rb-chip rb-chip--negative">
                  Buy Off {data.summary.disabledSymbols}
                </span>
                <span className="rb-chip rb-chip--positive">
                  Sell On {data.summary.sellEnabledSymbols}
                </span>
                <span className="rb-chip rb-chip--neutral">
                  {data.summary.trackedSymbols} tracked
                </span>
              </div>
            </div>

            <div className="rb-table-wrap mt-4 max-h-[560px] overflow-y-auto overflow-x-auto">
              <table className="min-w-[1420px] w-full">
                <thead className="sticky top-0 z-10 bg-slate-950/95">
                  <tr className="border-b border-white/8 text-left text-[10px] uppercase tracking-[0.12em] text-slate-400">
                    <th className="px-2 py-2 whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 text-left hover:text-sky-300" onClick={() => setControlSortKey("symbol")}>
                        Token {controlSortIndicator("symbol")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setControlSortKey("price")}>
                        Price {controlSortIndicator("price")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setControlSortKey("change24h")}>
                        24h Change {controlSortIndicator("change24h")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setControlSortKey("high24h")}>
                        24h High {controlSortIndicator("high24h")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setControlSortKey("low24h")}>
                        24h Low {controlSortIndicator("low24h")}
                      </button>
                    </th>
                    <th className="px-2 py-2 whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setControlSortKey("mode")}>
                        Mode {controlSortIndicator("mode")}
                      </button>
                    </th>
                    <th className="px-2 py-2 whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setControlSortKey("configuredRegime")}>
                        Configured Regime {controlSortIndicator("configuredRegime")}
                      </button>
                    </th>
                    <th className="px-2 py-2 whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 text-left hover:text-sky-300" onClick={() => setControlSortKey("regime")}>
                        Regime Routing {controlSortIndicator("regime")}
                      </button>
                    </th>
                    <th className="px-2 py-2 whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 text-left hover:text-sky-300" onClick={() => setControlSortKey("confidence")}>
                        Confidence {controlSortIndicator("confidence")}
                      </button>
                    </th>
                    <th className="px-2 py-2 whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 text-left hover:text-sky-300" onClick={() => setControlSortKey("volatility")}>
                        Volatility State {controlSortIndicator("volatility")}
                      </button>
                    </th>
                    <th className="px-2 py-2 whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 text-left hover:text-sky-300" onClick={() => setControlSortKey("dataQuality")}>
                        Data Quality {controlSortIndicator("dataQuality")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-center whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setControlSortKey("buyOpportunity")}>
                        Buy Opportunity {controlSortIndicator("buyOpportunity")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-center whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setControlSortKey("buyExecutable")}>
                        Buy Executable {controlSortIndicator("buyExecutable")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-center whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setControlSortKey("scalper")}>
                        Scalper {controlSortIndicator("scalper")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-center whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setControlSortKey("buy")}>
                        BUY {controlSortIndicator("buy")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-center whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setControlSortKey("sell")}>
                        SELL {controlSortIndicator("sell")}
                      </button>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/6 text-sm">
                  {sortedSymbolControls.map((control) => {
                    const busyBuy = busySymbol === `${control.symbol}:buy`;
                    const busySell = busySymbol === `${control.symbol}:sell`;
                    const busyScalperRow = busyScalper === control.symbol;
                    const buyOn = control.buyEnabled;
                    const sellOn = control.sellEnabled;
                    const scalperOn = control.scalperEnabled;
                    const detectedRegimeChipStyle = regimeStyle(control.detectedRegime);
                    const buyOpportunityChipStyle = opportunityStyle(control.buyOpportunityPct);
                    const executableChipStyle = executableStyle(control.buyExecutable);
                    const modeLabel = control.buyEnabled && control.sellEnabled
                      ? "BUY + SELL"
                      : control.buyEnabled
                        ? "BUY only"
                        : control.sellEnabled
                          ? "SELL only"
                          : "Paused";

                    return (
                      <tr key={`top-controls-${control.symbol}`} className="text-slate-200">
                        <td className="px-2 py-2.5 font-semibold">
                          <div className="flex items-center gap-2">
                            <Link
                              href={`/token/${encodeURIComponent(control.symbol)}`}
                              className="transition hover:text-sky-300"
                            >
                              {control.symbol}
                            </Link>
                            {control.hasOpenPosition ? (
                              <span className="rounded-md border border-sky-400/30 bg-sky-500/20 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.12em] text-sky-100">
                                Open
                              </span>
                            ) : null}
                          </div>
                        </td>
                        <td className="px-2 py-2.5 text-right font-semibold text-slate-200">
                          {control.price === null ? "N/A" : formatPrice(control.price)}
                        </td>
                        <td className={`px-2 py-2.5 text-right font-semibold ${valueTone(control.change24hPct ?? 0)}`}>
                          {control.change24hPct === null ? "N/A" : formatPercent(control.change24hPct)}
                        </td>
                        <td className="px-2 py-2.5 text-right text-slate-300">
                          {control.high24h === null ? "N/A" : formatPrice(control.high24h)}
                        </td>
                        <td className="px-2 py-2.5 text-right text-slate-300">
                          {control.low24h === null ? "N/A" : formatPrice(control.low24h)}
                        </td>
                        <td className="px-2 py-2.5 text-slate-300 whitespace-nowrap">{modeLabel}</td>
                        <td className="px-2 py-2.5">
                          <select
                            value={control.configuredRegime}
                            onChange={(event) =>
                              setTokenRegime(control.symbol, event.target.value)
                            }
                            disabled={
                              busyAction !== null
                              || busyRegime === control.symbol
                              || busyScalper !== null
                              || busySymbol !== null
                              || savingRisk
                            }
                            className="w-[132px] rounded-md border border-white/12 bg-white/[0.04] px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
                            title="Manual strategy mode per token"
                          >
                            {TOKEN_REGIME_OPTIONS.map((option) => (
                              <option key={`${control.symbol}-${option}`} value={option}>
                                {option}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="px-2 py-2.5">
                          <div className="flex max-w-[176px] flex-col items-start gap-1">
                            <span className="text-[10px] uppercase tracking-[0.12em] text-slate-500">
                              Detected (Legacy/Shadow)
                            </span>
                            <span
                              className="inline-flex min-w-[102px] justify-center rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]"
                              style={detectedRegimeChipStyle}
                              title={control.detectedRegimeExplanation}
                            >
                              {formatDetectedRegime(control.detectedRegime)}
                            </span>
                            <span
                              className="line-clamp-2 text-[10px] uppercase tracking-[0.12em] text-slate-500"
                              title={control.detectedRegimeExplanation}
                            >
                              Suggested Regime V2: {formatDetectedRegime(control.suggestedRegimeV2 ?? control.detectedRegime)}
                            </span>
                            <span
                              className="line-clamp-2 text-[10px] uppercase tracking-[0.12em] text-slate-500"
                              title={(control.fallbackReason ?? control.autoFallbackReason) ?? undefined}
                            >
                              Effective Route (After Gates): {formatDetectedRegime(control.effectiveRoute ?? control.effectiveStrategy)}
                            </span>
                            <span
                              className="line-clamp-2 text-[10px] uppercase tracking-[0.12em] text-amber-300"
                              title={(control.fallbackReason ?? control.autoFallbackReason) ?? undefined}
                            >
                              Failed Gates: {formatFailedGates(control.fallbackReason ?? control.autoFallbackReason)}
                            </span>
                          </div>
                        </td>
                        <td className="px-2 py-2.5">
                          <div className="flex items-center gap-2">
                            <span className="inline-flex min-w-[72px] justify-center rounded-md border border-white/15 bg-white/[0.04] px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-200">
                              {control.detectedRegimeConfidenceLabel}
                              {control.detectedRegimeConfidenceScore === null
                                ? ""
                                : ` ${control.detectedRegimeConfidenceScore.toFixed(1)}`}
                            </span>
                            <div className="h-2 w-20 overflow-hidden rounded-full bg-white/10">
                              <div
                                className="h-full rounded-full bg-sky-400"
                                style={{
                                  width: `${Math.max(
                                    0,
                                    Math.min(100, Number(control.detectedRegimeConfidenceScore ?? 0)),
                                  )}%`,
                                }}
                              />
                            </div>
                          </div>
                          <div className="mt-1 flex flex-wrap gap-1 text-[10px] uppercase tracking-[0.11em] text-slate-400">
                            <span>
                              Stability {control.detectedRegimeStabilityScore === null || control.detectedRegimeStabilityScore === undefined ? "n/a" : control.detectedRegimeStabilityScore.toFixed(1)}
                            </span>
                            <span>
                              Persistence {control.detectedRegimePersistenceScore === null || control.detectedRegimePersistenceScore === undefined ? "n/a" : control.detectedRegimePersistenceScore.toFixed(1)}
                            </span>
                          </div>
                          <div className="mt-1 text-[9px] uppercase tracking-[0.12em] text-slate-500">
                            Inputs C:{regimeInputFlag(
                              control.detectedRegimeConfidenceScore,
                              control.detectedRegimeConfidenceInferred,
                            )}
                            {" "}
                            S:{regimeInputFlag(
                              control.detectedRegimeStabilityScore,
                              control.detectedRegimeStabilityInferred,
                            )}
                            {" "}
                            P:{regimeInputFlag(
                              control.detectedRegimePersistenceScore,
                              control.detectedRegimePersistenceInferred,
                            )}
                          </div>
                        </td>
                        <td className="px-2 py-2.5">
                          <span
                            className="inline-flex min-w-[80px] justify-center rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]"
                            style={regimeStyle(control.detectedRegimeVolatilityState)}
                          >
                            {formatDetectedRegime(control.detectedRegimeVolatilityState)}
                          </span>
                        </td>
                        <td className="px-3 py-2.5">
                          <div className="flex flex-col gap-1">
                            <span
                              className="inline-flex min-w-[80px] justify-center rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]"
                              style={dataQualityStyle(control.regimeDataQualityStatus)}
                              title={control.regimeDataQualityReason}
                            >
                              Regime {control.regimeDataQualityStatus}
                            </span>
                            <span
                              className="inline-flex min-w-[80px] justify-center rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]"
                              style={dataQualityStyle(control.volatilityDataQualityStatus)}
                              title={control.volatilityDataQualityReason}
                            >
                              Volatility {control.volatilityDataQualityStatus}
                            </span>
                          </div>
                        </td>
                        <td className="px-2 py-2.5 text-center">
                          <span
                            className="inline-flex min-w-[80px] justify-center rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]"
                            style={buyOpportunityChipStyle}
                          >
                            {formatOpportunity(control.buyOpportunityPct)}
                          </span>
                        </td>
                        <td className="px-2 py-2.5 text-center">
                          <span
                            className="inline-flex min-w-[76px] justify-center rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]"
                            style={executableChipStyle}
                            title={control.buyExecutableReason}
                          >
                            {control.buyExecutable ? "Ready" : "Blocked"}
                          </span>
                        </td>
                        <td className="px-2 py-2.5 text-center">
                          <button
                            type="button"
                            onClick={() => setScalperMode(control.symbol, !scalperOn)}
                            disabled={
                              busyAction !== null
                              || busyScalperRow
                              || busySymbol !== null
                              || busyRegime !== null
                              || savingRisk
                            }
                            className="min-w-[56px] rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-white disabled:cursor-not-allowed disabled:opacity-60"
                            style={{
                              backgroundColor: scalperOn ? "#16a34a" : "#dc2626",
                              borderColor: scalperOn ? "#16a34a" : "#dc2626",
                            }}
                          >
                            {busyScalperRow ? "Saving..." : scalperOn ? "ON" : "OFF"}
                          </button>
                        </td>
                        <td className="px-2 py-2.5 text-center">
                          <button
                            type="button"
                            onClick={() =>
                              setSymbolAutoTrade(
                                control.symbol,
                                "buy",
                                !control.buyEnabled,
                              )
                            }
                            disabled={
                              busyAction !== null
                              || busySymbol !== null
                              || busyBuy
                              || savingRisk
                              || busyScalper !== null
                              || busyRegime !== null
                            }
                            className="min-w-[56px] rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-white disabled:cursor-not-allowed disabled:opacity-60"
                            style={{
                              backgroundColor: buyOn ? "#16a34a" : "#dc2626",
                              borderColor: buyOn ? "#16a34a" : "#dc2626",
                            }}
                          >
                            {busyBuy ? "Saving..." : buyOn ? "ON" : "OFF"}
                          </button>
                        </td>
                        <td className="px-2 py-2.5 text-center">
                          <button
                            type="button"
                            onClick={() =>
                              setSymbolAutoTrade(
                                control.symbol,
                                "sell",
                                !control.sellEnabled,
                              )
                            }
                            disabled={
                              busyAction !== null
                              || busySymbol !== null
                              || busySell
                              || savingRisk
                              || busyScalper !== null
                              || busyRegime !== null
                            }
                            className="min-w-[56px] rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-white disabled:cursor-not-allowed disabled:opacity-60"
                            style={{
                              backgroundColor: sellOn ? "#16a34a" : "#dc2626",
                              borderColor: sellOn ? "#16a34a" : "#dc2626",
                            }}
                          >
                            {busySell ? "Saving..." : sellOn ? "ON" : "OFF"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="rb-section p-4 sm:p-5">
            <p className="rb-kicker">
              Top Status
            </p>
            <div className="rb-table-wrap mt-3 overflow-x-auto">
              <table className="rb-table min-w-[860px] text-xs">
                <thead>
                  <tr className="border-b border-white/10 text-left uppercase tracking-[0.12em] text-slate-400">
                    <th className="px-3 py-2">Metric</th>
                    <th className="px-3 py-2">Value</th>
                    <th className="px-3 py-2">Context</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/8">
                  {topStatusCards.map((card) => (
                    <tr key={card.label}>
                      <td className="px-3 py-2 text-slate-300">{card.label}</td>
                      <td className={`px-3 py-2 font-semibold ${card.tone}`}>{card.value}</td>
                      <td className="px-3 py-2 text-slate-400">{card.helper}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="grid gap-4 xl:grid-cols-2">
            <article className="rb-section p-4 sm:p-5">
              <div className="flex items-end justify-between gap-3">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                    Performance
                  </p>
                  <h2 className="mt-1 text-base font-semibold text-white">
                    Performance Summary
                  </h2>
                </div>
                <span className="rounded-md border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] uppercase tracking-[0.12em] text-slate-400">
                  Realized + Open split
                </span>
              </div>
              <div className="rb-table-wrap mt-3 overflow-x-auto">
                <table className="rb-table min-w-full text-xs">
                  <thead>
                    <tr className="border-b border-white/10 text-left uppercase tracking-[0.12em] text-slate-400">
                      <th className="px-3 py-2">Metric</th>
                      <th className="px-3 py-2 text-right">Value</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/8">
                    {performanceMetrics.map((metric) => (
                      <tr key={metric.label}>
                        <td className="px-3 py-2 text-slate-300">{metric.label}</td>
                        <td className={`px-3 py-2 text-right font-semibold ${metric.tone}`}>{metric.value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </article>

            <article className="rb-section p-4 sm:p-5">
              <div className="flex items-end justify-between gap-3">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                    Risk
                  </p>
                  <h2 className="mt-1 text-base font-semibold text-white">
                    Risk & Exposure
                  </h2>
                </div>
                <span
                  className={`rounded-md border px-2.5 py-1 text-[10px] uppercase tracking-[0.12em] ${
                    data.summary.dailyBuyPaused
                      ? "border-rose-400/40 bg-rose-500/20 text-rose-100"
                      : "border-emerald-400/30 bg-emerald-500/15 text-emerald-100"
                  }`}
                >
                  Daily Guard {data.summary.dailyBuyPaused ? "Paused" : "Active"}
                </span>
              </div>
              <div className="rb-table-wrap mt-3 overflow-x-auto">
                <table className="rb-table min-w-full text-xs">
                  <thead>
                    <tr className="border-b border-white/10 text-left uppercase tracking-[0.12em] text-slate-400">
                      <th className="px-3 py-2">Metric</th>
                      <th className="px-3 py-2 text-right">Value</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/8">
                    {riskMetrics.map((metric) => (
                      <tr key={metric.label}>
                        <td className="px-3 py-2 text-slate-300">{metric.label}</td>
                        <td className={`px-3 py-2 text-right font-semibold ${metric.tone}`}>{metric.value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </article>
          </section>

          <section className="rb-section border-amber-300/35 p-4 sm:p-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-amber-200/80">
                  Needs Attention
                </p>
                <h2 className="mt-1 text-xl font-semibold text-white">
                  Priority Review Queue
                </h2>
              </div>
              <span className="rounded-md border border-amber-300/25 bg-amber-500/[0.15] px-3 py-1 text-xs font-semibold uppercase tracking-[0.12em] text-amber-100">
                {sortedAttentionItems.length} active items
              </span>
            </div>
            <div className="rb-table-wrap mt-4 max-h-[560px] overflow-y-auto overflow-x-auto rounded-lg border border-white/10 bg-black/25">
              <table className="min-w-[760px] w-full">
                <thead className="sticky top-0 z-10 bg-[#0b1220]">
                  <tr className="border-b border-white/8 text-left text-[10px] uppercase tracking-[0.12em] text-slate-400">
                    <th className="px-3 py-2">Token</th>
                    <th className="px-3 py-2">Issue</th>
                    <th className="px-3 py-2">Severity</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Action / View</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/6 text-sm">
                  {sortedAttentionItems.length === 0 ? (
                    <tr>
                      <td className="px-3 py-3 text-slate-300" colSpan={5}>
                        No active attention items right now.
                      </td>
                    </tr>
                  ) : (
                    sortedAttentionItems.map((item, index) => (
                      <tr key={`${item.symbol ?? "runtime"}-${index}`} className="text-slate-200">
                        <td className="px-3 py-2.5 font-semibold">
                          {item.symbol ? (
                            <Link
                              href={`/token/${encodeURIComponent(item.symbol)}`}
                              className="transition hover:text-sky-300"
                            >
                              {item.symbol}
                            </Link>
                          ) : (
                            <span className="text-slate-300">SYSTEM</span>
                          )}
                        </td>
                        <td className="px-3 py-2.5">{item.issue}</td>
                        <td className="px-3 py-2.5">
                          <span
                            className={`inline-flex min-w-[70px] justify-center rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${
                              item.severity === "High"
                                ? "border-rose-400/45 bg-rose-500/25 text-rose-100"
                                : item.severity === "Medium"
                                  ? "border-amber-400/45 bg-amber-500/25 text-amber-100"
                                  : "border-sky-400/35 bg-sky-500/20 text-sky-100"
                            }`}
                          >
                            {item.severity}
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-slate-300">{item.status}</td>
                        <td className="px-3 py-2.5 text-slate-300">{item.action}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="rb-section p-5 sm:p-6">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                  Open Positions
                </p>
                <h2 className="mt-1.5 text-2xl font-semibold tracking-tight text-white">
                  Main Position Table
                </h2>
                <p className="mt-2 text-sm text-slate-400">
                  Sorted for operator review. Token links open detailed advisory pages.
                </p>
              </div>
              <div className="flex flex-wrap gap-2 text-[10px] font-semibold uppercase tracking-[0.12em]">
                <span className="rounded-md border border-sky-500/40 bg-sky-500/18 px-3 py-1.5 text-sky-100">
                  {data.summary.openPositions} open
                </span>
                <span className="rounded-md border border-amber-400/35 bg-amber-500/18 px-3 py-1.5 text-amber-100">
                  {data.summary.staleLosingReviewCount} needs review
                </span>
                <span className="rounded-md border border-white/12 bg-white/[0.03] px-3 py-1.5 text-slate-300">
                  Click headers to sort
                </span>
              </div>
            </div>

            <div className="rb-table-wrap mt-5 max-h-[560px] overflow-y-auto overflow-x-auto">
              <table className="min-w-[1380px] w-full">
                <thead className="sticky top-0 z-10 bg-slate-950/95">
                  <tr className="border-b border-white/8 text-left text-[10px] uppercase tracking-[0.12em] text-slate-400">
                    <th className="px-2 py-2 whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 text-left hover:text-sky-300" onClick={() => setPositionSortKey("symbol")}>
                        Token {sortIndicator("symbol")}
                      </button>
                    </th>
                    <th className="px-2 py-2 whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("side")}>
                        Side {sortIndicator("side")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("price")}>
                        Price {sortIndicator("price")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("change24h")}>
                        24h Change {sortIndicator("change24h")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("high24h")}>
                        24h High {sortIndicator("high24h")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("low24h")}>
                        24h Low {sortIndicator("low24h")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("value")}>
                        Value {sortIndicator("value")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("allocation")}>
                        Alloc {sortIndicator("allocation")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("pnl")}>
                        P/L {sortIndicator("pnl")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("pnlPct")}>
                        P/L % {sortIndicator("pnlPct")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("age")}>
                        Age {sortIndicator("age")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-right whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("worstDip")}>
                        Worst Dip {sortIndicator("worstDip")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-center whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("review")}>
                        Needs Review {sortIndicator("review")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-center whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("bounce")}>
                        Bounce Setup {sortIndicator("bounce")}
                      </button>
                    </th>
                    <th className="px-2 py-2 whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("status")}>
                        Status {sortIndicator("status")}
                      </button>
                    </th>
                    <th className="px-2 py-2 text-center whitespace-nowrap">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("attention")}>
                        Action {sortIndicator("attention")}
                      </button>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/6 text-sm">
                  {sortedPositions.map((position) => {
                    const manualSellOnProfit = position.unrealizedValue >= 0;
                    const control = symbolControlsBySymbol.get(position.symbol);
                    return (
                      <tr key={`main-open-${position.symbol}`} className="text-slate-200">
                        <td className="px-2 py-2.5">
                          <div className="flex flex-col">
                            <Link
                              href={`/token/${encodeURIComponent(position.symbol)}`}
                              className="font-semibold text-white transition hover:text-sky-300"
                            >
                              {position.symbol}
                            </Link>
                            <span className="text-[10px] uppercase tracking-[0.12em] text-slate-500">
                              {coinName(position.symbol)}
                            </span>
                          </div>
                        </td>
                        <td className="px-2 py-2.5">
                          <span className="rounded-md border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em]">
                            LONG
                          </span>
                        </td>
                        <td className="px-2 py-2.5 text-right font-semibold text-slate-200">
                          {position.price === null ? "N/A" : formatPrice(position.price)}
                        </td>
                        <td className={`px-2 py-2.5 text-right font-semibold ${valueTone(position.change24hPct ?? 0)}`}>
                          {position.change24hPct === null ? "N/A" : formatPercent(position.change24hPct)}
                        </td>
                        <td className="px-2 py-2.5 text-right text-slate-300">
                          {position.high24h === null ? "N/A" : formatPrice(position.high24h)}
                        </td>
                        <td className="px-2 py-2.5 text-right text-slate-300">
                          {position.low24h === null ? "N/A" : formatPrice(position.low24h)}
                        </td>
                        <td className="px-2 py-2.5 text-right font-semibold">
                          {formatCurrency(position.marketValue)}
                        </td>
                        <td className="px-2 py-2.5 text-right font-medium text-slate-300">
                          {percentFormatter.format(position.allocationPct)}%
                        </td>
                        <td className={`px-2 py-2.5 text-right font-semibold ${valueTone(position.unrealizedValue)}`}>
                          {formatCurrency(position.unrealizedValue)}
                        </td>
                        <td className={`px-2 py-2.5 text-right font-semibold ${valueTone(position.unrealizedPct)}`}>
                          {formatPercent(position.unrealizedPct)}
                        </td>
                        <td className="px-2 py-2.5 text-right text-slate-300">
                          {formatHours(position.ageHours)}
                        </td>
                        <td className={`px-2 py-2.5 text-right ${valueTone(position.advisoryMaxDrawdownPctDuringTrade)}`}>
                          {formatPercent(position.advisoryMaxDrawdownPctDuringTrade)}
                        </td>
                        <td className="px-2 py-2.5 text-center">
                          <span
                            className={`inline-flex min-w-[76px] justify-center rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${
                              position.advisoryStaleLosingReview
                                ? "border-amber-400/45 bg-amber-500/25 text-amber-100"
                                : "border-emerald-400/35 bg-emerald-500/18 text-emerald-100"
                            }`}
                          >
                            {position.advisoryStaleLosingReview ? "Review" : "Clear"}
                          </span>
                        </td>
                        <td className="px-2 py-2.5 text-center">
                          <div className="flex flex-col items-center gap-1">
                            <span
                              className="inline-flex min-w-[84px] justify-center rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]"
                              style={radarLabelStyle(control?.volatilityOpportunityLabel ?? null)}
                            >
                              {position.bounceLabel}
                            </span>
                            <span className="text-[10px] text-slate-400">
                              {position.bounceScore === null ? "N/A" : position.bounceScore.toFixed(1)}
                            </span>
                          </div>
                        </td>
                        <td className="px-2 py-2.5">
                          <div className="flex flex-col gap-1">
                            <span
                              className={`inline-flex w-fit rounded-md px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${statusTone(position.status)}`}
                            >
                              {position.status}
                            </span>
                            <span className={`text-[10px] ${valueTone(position.trendShift ?? 0)}`}>
                              Trend Shift{" "}
                              {position.trendShift === null
                                ? "N/A"
                                : `${position.trendShift > 0 ? "+" : ""}${position.trendShift.toFixed(1)}`}
                            </span>
                          </div>
                        </td>
                        <td className="px-2 py-2.5 text-center">
                          <div className="mx-auto flex w-full max-w-[248px] flex-col gap-2 rounded-lg border border-white/10 bg-white/[0.03] p-2">
                            <button
                              onClick={() => manualSell(position)}
                              disabled={
                                busyAction !== null ||
                                busyManualSell !== null ||
                                busySymbol !== null ||
                                busyScalper !== null ||
                                savingRisk
                              }
                              className="rounded-md border px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-white transition disabled:cursor-not-allowed disabled:opacity-60"
                              style={{
                                backgroundColor: manualSellOnProfit ? "#16a34a" : "#dc2626",
                                borderColor: manualSellOnProfit ? "#16a34a" : "#dc2626",
                              }}
                            >
                              {busyManualSell === position.symbol ? "Selling..." : "Manual Sell"}
                            </button>
                            <div className="space-y-1.5 rounded-md border border-white/10 bg-slate-950/35 p-2 text-[10px]">
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-semibold uppercase tracking-[0.12em] text-slate-300">
                                  Stop Loss
                                </span>
                                <label className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.03] px-1.5 py-1 text-slate-200">
                                  <input
                                    type="checkbox"
                                    checked={manualStoplossDrafts[position.symbol]?.enabled ?? false}
                                    onChange={(event) =>
                                      updateManualStoplossDraft(position.symbol, {
                                        enabled: event.target.checked,
                                      })
                                    }
                                    disabled={busyManualStoploss !== null}
                                    className="h-3.5 w-3.5 accent-emerald-500"
                                  />
                                  <span>{(manualStoplossDrafts[position.symbol]?.enabled ?? false) ? "On" : "Off"}</span>
                                </label>
                              </div>
                              <div className="grid grid-cols-[74px_1fr_auto] items-center gap-1.5">
                                <select
                                  value={manualStoplossDrafts[position.symbol]?.type ?? "pct"}
                                  onChange={(event) =>
                                    updateManualStoplossDraft(position.symbol, {
                                      type: normalizeStoplossType(event.target.value),
                                    })
                                  }
                                  disabled={
                                    busyManualStoploss !== null ||
                                    !(manualStoplossDrafts[position.symbol]?.enabled ?? false)
                                  }
                                  className="rounded-md border border-white/10 bg-slate-950/70 px-2 py-1 text-[10px] text-slate-200"
                                >
                                  <option value="pct">Percent</option>
                                  <option value="price">Price</option>
                                </select>
                                <input
                                  type="number"
                                  inputMode="decimal"
                                  step="any"
                                  min="0"
                                  value={manualStoplossDrafts[position.symbol]?.valueText ?? ""}
                                  onChange={(event) =>
                                    updateManualStoplossDraft(position.symbol, {
                                      valueText: event.target.value,
                                    })
                                  }
                                  disabled={
                                    busyManualStoploss !== null ||
                                    !(manualStoplossDrafts[position.symbol]?.enabled ?? false)
                                  }
                                  placeholder={manualStoplossDrafts[position.symbol]?.type === "price" ? "Trigger price" : "Trigger %"}
                                  className="min-w-0 rounded-md border border-white/10 bg-slate-950/70 px-2 py-1 text-[10px] text-slate-100 placeholder:text-slate-500"
                                />
                                <button
                                  onClick={() => saveManualStoploss(position.symbol)}
                                  disabled={busyManualStoploss !== null}
                                  className="rounded-md border border-sky-400/40 bg-sky-500/20 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-sky-100 disabled:cursor-not-allowed disabled:opacity-60"
                                >
                                  {busyManualStoploss === position.symbol ? "Saving..." : "Save"}
                                </button>
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="rb-section p-4 sm:p-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                  Advisory Analytics
                </p>
                <h2 className="mt-1 text-xl font-semibold text-white">
                  Radar & Rotation (Advisory-Only)
                </h2>
                <p className="mt-1 text-sm text-slate-400">
                  Read-time operator intelligence only. No execution impact.
                </p>
              </div>
              <span className="rounded-md border border-white/12 bg-white/[0.04] px-3 py-1 text-xs uppercase tracking-[0.12em] text-slate-400">
                Advisory only
              </span>
            </div>

            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              <article className="rb-content-card p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold uppercase tracking-[0.14em] text-slate-300">
                    Volatility Opportunity Radar
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    <button
                      onClick={() => setVolatilitySortKey("score")}
                      className={`rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] ${
                        volatilitySortKey === "score"
                          ? "border-sky-400/40 bg-sky-500/20 text-sky-100"
                          : "border-white/12 bg-white/[0.03] text-slate-300"
                      }`}
                    >
                      Score
                    </button>
                    <button
                      onClick={() => setVolatilitySortKey("stretch")}
                      className={`rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] ${
                        volatilitySortKey === "stretch"
                          ? "border-sky-400/40 bg-sky-500/20 text-sky-100"
                          : "border-white/12 bg-white/[0.03] text-slate-300"
                      }`}
                    >
                      Stretch
                    </button>
                    <button
                      onClick={() => setVolatilitySortKey("volatility")}
                      className={`rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] ${
                        volatilitySortKey === "volatility"
                          ? "border-sky-400/40 bg-sky-500/20 text-sky-100"
                          : "border-white/12 bg-white/[0.03] text-slate-300"
                      }`}
                    >
                      Volatility
                    </button>
                    <button
                      onClick={() => setVolatilitySortKey("bounce")}
                      className={`rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] ${
                        volatilitySortKey === "bounce"
                          ? "border-sky-400/40 bg-sky-500/20 text-sky-100"
                          : "border-white/12 bg-white/[0.03] text-slate-300"
                      }`}
                    >
                      Bounce
                    </button>
                  </div>
                </div>
                <div className="rb-table-wrap mt-3 max-h-[440px] overflow-y-auto overflow-x-auto">
                  <table className="min-w-[760px] w-full">
                    <thead className="sticky top-0 z-10 bg-[#0b1220]">
                      <tr className="border-b border-white/8 text-left text-[10px] uppercase tracking-[0.11em] text-slate-400">
                        <th className="px-2 py-2">Symbol</th>
                        <th className="px-2 py-2 text-right">Score</th>
                        <th className="px-2 py-2">Label</th>
                        <th className="px-2 py-2 text-right">Stretch</th>
                        <th className="px-2 py-2 text-right">Vol Spike</th>
                        <th className="px-2 py-2 text-right">Bounce</th>
                        <th className="px-2 py-2 text-right">Confidence</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/6 text-sm">
                      {topVolatilityRows.length === 0 ? (
                        <tr>
                          <td className="px-2 py-3 text-xs text-slate-400" colSpan={7}>
                            No tracked symbols available yet for volatility radar.
                          </td>
                        </tr>
                      ) : topVolatilityRows.map((control) => (
                        <tr key={`top-radar-${control.symbol}`} className="text-slate-200">
                          <td className="px-2 py-2">
                            <Link
                              href={`/token/${encodeURIComponent(control.symbol)}`}
                              className="font-semibold transition hover:text-sky-300"
                            >
                              {control.symbol}
                            </Link>
                          </td>
                          <td className="px-2 py-2 text-right">
                            {control.volatilityOpportunityScore === null
                              ? "N/A"
                              : control.volatilityOpportunityScore.toFixed(1)}
                          </td>
                          <td className="px-2 py-2">
                            <span
                              className="inline-flex min-w-[90px] justify-center rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]"
                              style={radarLabelStyle(control.volatilityOpportunityLabel)}
                            >
                              {volatilityLabel(control.volatilityOpportunityLabel)}
                            </span>
                          </td>
                          <td className="px-2 py-2 text-right">
                            {control.volatilityOpportunityStretchScore === null
                              ? "N/A"
                              : control.volatilityOpportunityStretchScore.toFixed(1)}
                          </td>
                          <td className="px-2 py-2 text-right">
                            {control.volatilityOpportunityVolatilitySpikeScore === null
                              ? "N/A"
                              : control.volatilityOpportunityVolatilitySpikeScore.toFixed(1)}
                          </td>
                          <td className="px-2 py-2 text-right">
                            {control.volatilityOpportunityBounceContextScore === null
                              ? "N/A"
                              : control.volatilityOpportunityBounceContextScore.toFixed(1)}
                          </td>
                          <td className="px-2 py-2 text-right">
                            {confidenceLabel(control.volatilityOpportunityConfidenceLabel)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </article>

              <article className="rb-content-card p-3">
                <h3 className="text-sm font-semibold uppercase tracking-[0.14em] text-slate-300">
                  Rolling Symbol Rotation
                </h3>
                <div className="rb-table-wrap mt-3 max-h-[440px] overflow-y-auto overflow-x-auto">
                  <table className="min-w-[720px] w-full">
                    <thead className="sticky top-0 z-10 bg-[#0b1220]">
                      <tr className="border-b border-white/8 text-left text-[10px] uppercase tracking-[0.11em] text-slate-400">
                        <th className="px-2 py-2">Symbol</th>
                        <th className="px-2 py-2">Status</th>
                        <th className="px-2 py-2 text-right">Short Score</th>
                        <th className="px-2 py-2 text-right">Medium Score</th>
                        <th className="px-2 py-2 text-right">Trend Shift</th>
                        <th className="px-2 py-2 text-right">Win Rate</th>
                        <th className="px-2 py-2 text-right">Avg P/L</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/6 text-sm">
                      {topRotationRows.map((control) => (
                        <tr key={`top-rotation-${control.symbol}`} className="text-slate-200">
                          <td className="px-2 py-2">
                            <Link
                              href={`/token/${encodeURIComponent(control.symbol)}`}
                              className="font-semibold transition hover:text-sky-300"
                            >
                              {control.symbol}
                            </Link>
                          </td>
                          <td className="px-2 py-2">
                            <span
                              className="inline-flex min-w-[100px] justify-center rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]"
                              style={rotationStatusStyle(control.rotationStatus)}
                            >
                              {control.rotationStatus}
                            </span>
                          </td>
                          <td className="px-2 py-2 text-right">
                            {control.rotationShortTermScore === null
                              ? "N/A"
                              : control.rotationShortTermScore.toFixed(1)}
                          </td>
                          <td className="px-2 py-2 text-right">
                            {control.rotationMediumTermScore === null
                              ? "N/A"
                              : control.rotationMediumTermScore.toFixed(1)}
                          </td>
                          <td className={`px-2 py-2 text-right ${valueTone(control.rotationDelta ?? 0)}`}>
                            {control.rotationDelta === null
                              ? "N/A"
                              : `${control.rotationDelta > 0 ? "+" : ""}${control.rotationDelta.toFixed(1)}`}
                          </td>
                          <td className="px-2 py-2 text-right">
                            {control.rotationShortTermWinRatePct === null
                              ? "N/A"
                              : `${control.rotationShortTermWinRatePct.toFixed(1)}%`}
                          </td>
                          <td className={`px-2 py-2 text-right ${valueTone(control.rotationShortTermAvgRealizedPnlUsd ?? 0)}`}>
                            {control.rotationShortTermAvgRealizedPnlUsd === null
                              ? "N/A"
                              : formatCurrency(control.rotationShortTermAvgRealizedPnlUsd)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </article>
            </div>
          </section>

          <details id="advanced-panels" className="rb-content-card p-4">
            <summary className="cursor-pointer text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
              Advanced Panels (Full Controls and Full Tables)
            </summary>
            <div className="mt-4 space-y-6">
              <div className="flex flex-wrap gap-2 text-[10px] font-semibold uppercase tracking-[0.14em]">
                <button
                  type="button"
                  onClick={() => {
                    setTopTab("advancedTables");
                    setAdvancedTab("analytics");
                  }}
                  className={`rounded-full border px-3 py-1.5 transition ${
                    advancedTab === "analytics"
                      ? "border-sky-400/50 bg-sky-500/20 text-sky-100"
                      : "border-white/10 bg-white/[0.03] text-slate-300 hover:border-white/20 hover:text-slate-100"
                  }`}
                >
                  Advanced Tables
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setTopTab("riskControls");
                    setAdvancedTab("riskControls");
                  }}
                  className={`rounded-full border px-3 py-1.5 transition ${
                    advancedTab === "riskControls"
                      ? "border-sky-400/50 bg-sky-500/20 text-sky-100"
                      : "border-white/10 bg-white/[0.03] text-slate-300 hover:border-white/20 hover:text-slate-100"
                  }`}
                >
                  Risk Controls
                </button>
              </div>

            {advancedTab === "riskControls" ? (
            <div className="mt-5 rb-content-card p-4">
              <div className="flex flex-wrap gap-2 text-[10px] font-semibold uppercase tracking-[0.14em]">
                <span className={`rounded-md border px-3 py-1.5 ${data.summary.dailyBuyPaused ? "border-rose-500 bg-rose-600 text-white" : "border-emerald-500 bg-emerald-600 text-white"}`}>
                  Daily guard: {data.summary.dailyBuyPaused ? "Paused" : "Active"}
                </span>
                <span className="rounded-md border border-white/10 bg-white/[0.03] px-3 py-1.5 text-slate-300">
                  Daily PnL: {formatCurrency(data.summary.dailyRealizedPnlUsd)}
                </span>
                <span className="rounded-md border border-white/10 bg-white/[0.03] px-3 py-1.5 text-slate-300">
                  UTC window: {data.summary.tradeWindowEnabled ? `${data.summary.tradeWindowStartHourUtc}:00-${data.summary.tradeWindowEndHourUtc}:00` : "Disabled"}
                </span>
              </div>

              <div className="rb-table-wrap mt-4 overflow-x-auto">
                <div className="min-w-[1160px]">
                  <div className="border-b border-white/8 bg-white/[0.04] px-4 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Risk Controls
                  </div>

                  <div className="grid grid-cols-5 gap-3 border-b border-white/6 px-4 py-3">
                    <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-slate-400">
                      Max Concurrent Trades
                      <input
                        type="number"
                        min={1}
                        value={riskDraft?.maxConcurrentTrades ?? ""}
                        onChange={(event) => {
                          const value = Number(event.target.value);
                          applyRiskDraft({ maxConcurrentTrades: Number.isFinite(value) ? value : 1 });
                        }}
                        className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-white outline-none ring-sky-300/40 focus:ring-2"
                      />
                    </label>

                    <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-slate-400">
                      Max Concurrent Trades Per Token
                      <input
                        type="number"
                        min={1}
                        value={riskDraft?.maxConcurrentTradesPerToken ?? ""}
                        onChange={(event) => {
                          const value = Number(event.target.value);
                          applyRiskDraft({ maxConcurrentTradesPerToken: Number.isFinite(value) ? value : 1 });
                        }}
                        className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-white outline-none ring-sky-300/40 focus:ring-2"
                      />
                    </label>

                    <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-slate-400">
                      Max Trade Amount (USD)
                      <input
                        type="number"
                        min={1}
                        step={1}
                        value={riskDraft?.maxTradeAmountUsd ?? ""}
                        onChange={(event) => {
                          const value = Number(event.target.value);
                          applyRiskDraft({ maxTradeAmountUsd: Number.isFinite(value) ? value : 0 });
                        }}
                        className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-white outline-none ring-sky-300/40 focus:ring-2"
                      />
                    </label>

                    <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-slate-400">
                      Trade Amount (USD)
                      <input
                        type="number"
                        min={1}
                        step={1}
                        value={riskDraft?.tradeAmountUsd ?? ""}
                        onChange={(event) => {
                          const value = Number(event.target.value);
                          applyRiskDraft({ tradeAmountUsd: Number.isFinite(value) ? value : 0 });
                        }}
                        className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-white outline-none ring-sky-300/40 focus:ring-2"
                      />
                    </label>

                    <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-slate-400">
                      Max Portfolio Exposure (%)
                      <input
                        type="number"
                        min={1}
                        max={100}
                        step={0.5}
                        value={riskDraft?.maxPortfolioExposurePct ?? ""}
                        onChange={(event) => {
                          const value = Number(event.target.value);
                          applyRiskDraft({ maxPortfolioExposurePct: Number.isFinite(value) ? value : 100 });
                        }}
                        className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-white outline-none ring-sky-300/40 focus:ring-2"
                      />
                    </label>
                  </div>

                  <div className="grid grid-cols-5 gap-3 border-b border-white/6 px-4 py-3">
                    <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-slate-400">
                      Max Token Exposure (%)
                      <input
                        type="number"
                        min={1}
                        max={100}
                        step={0.5}
                        value={riskDraft?.maxExposurePerTokenPct ?? ""}
                        onChange={(event) => {
                          const value = Number(event.target.value);
                          applyRiskDraft({ maxExposurePerTokenPct: Number.isFinite(value) ? value : 100 });
                        }}
                        className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-white outline-none ring-sky-300/40 focus:ring-2"
                      />
                    </label>

                    <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-slate-400">
                      Signal Confirmation (Cycles)
                      <input
                        type="number"
                        min={1}
                        step={1}
                        value={riskDraft?.signalConfirmationCycles ?? ""}
                        onChange={(event) => {
                          const value = Number(event.target.value);
                          applyRiskDraft({ signalConfirmationCycles: Number.isFinite(value) ? value : 1 });
                        }}
                        className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-white outline-none ring-sky-300/40 focus:ring-2"
                      />
                    </label>

                    <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-slate-400">
                      Trade Window
                      <button
                        onClick={() => applyRiskDraft({ tradeWindowEnabled: !(riskDraft?.tradeWindowEnabled ?? false) })}
                        className="rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.12em] text-white"
                        style={{
                          backgroundColor: (riskDraft?.tradeWindowEnabled ?? false) ? "#16a34a" : "#dc2626",
                          borderColor: (riskDraft?.tradeWindowEnabled ?? false) ? "#16a34a" : "#dc2626",
                        }}
                      >
                        {(riskDraft?.tradeWindowEnabled ?? false) ? "Enabled" : "Disabled"}
                      </button>
                    </label>

                    <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-slate-400">
                      Window Start (UTC)
                      <input
                        type="number"
                        min={0}
                        max={23}
                        step={1}
                        value={riskDraft?.tradeWindowStartHourUtc ?? ""}
                        onChange={(event) => {
                          const value = Number(event.target.value);
                          applyRiskDraft({ tradeWindowStartHourUtc: Number.isFinite(value) ? value : 0 });
                        }}
                        className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-white outline-none ring-sky-300/40 focus:ring-2"
                      />
                    </label>

                    <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-slate-400">
                      Window End (UTC)
                      <input
                        type="number"
                        min={0}
                        max={23}
                        step={1}
                        value={riskDraft?.tradeWindowEndHourUtc ?? ""}
                        onChange={(event) => {
                          const value = Number(event.target.value);
                          applyRiskDraft({ tradeWindowEndHourUtc: Number.isFinite(value) ? value : 23 });
                        }}
                        className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-white outline-none ring-sky-300/40 focus:ring-2"
                      />
                    </label>
                  </div>

                  <div className="grid grid-cols-5 gap-3 px-4 py-3">
                    <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-slate-400">
                      Daily Loss Limit (USD)
                      <input
                        type="number"
                        min={0}
                        step={1}
                        value={riskDraft?.dailyLossLimitUsd ?? ""}
                        onChange={(event) => {
                          const value = Number(event.target.value);
                          applyRiskDraft({ dailyLossLimitUsd: Number.isFinite(value) ? value : 0 });
                        }}
                        className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-white outline-none ring-sky-300/40 focus:ring-2"
                      />
                    </label>

                    <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-slate-400">
                      Daily Auto Pause
                      <button
                        onClick={() => applyRiskDraft({ dailyLossAutoPause: !(riskDraft?.dailyLossAutoPause ?? false) })}
                        className="rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.12em] text-white"
                        style={{
                          backgroundColor: (riskDraft?.dailyLossAutoPause ?? false) ? "#16a34a" : "#dc2626",
                          borderColor: (riskDraft?.dailyLossAutoPause ?? false) ? "#16a34a" : "#dc2626",
                        }}
                      >
                        {(riskDraft?.dailyLossAutoPause ?? false) ? "Enabled" : "Disabled"}
                      </button>
                    </label>

                    <label className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-slate-400">
                      Daily Close All
                      <button
                        onClick={() => applyRiskDraft({ dailyLossCloseAll: !(riskDraft?.dailyLossCloseAll ?? false) })}
                        className="rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.12em] text-white"
                        style={{
                          backgroundColor: (riskDraft?.dailyLossCloseAll ?? false) ? "#16a34a" : "#dc2626",
                          borderColor: (riskDraft?.dailyLossCloseAll ?? false) ? "#16a34a" : "#dc2626",
                        }}
                      >
                        {(riskDraft?.dailyLossCloseAll ?? false) ? "Enabled" : "Disabled"}
                      </button>
                    </label>

                    <div className="flex flex-col gap-1 text-xs uppercase tracking-[0.14em] text-slate-400">
                      Save Risk
                      <button
                        onClick={saveRiskSettings}
                        disabled={
                          !riskDirty
                          || savingRisk
                          || busyAction !== null
                          || busySymbol !== null
                          || busyScalper !== null
                          || busyCooldown
                        }
                        className="w-full rounded-full border border-sky-400/25 bg-sky-500/12 px-5 py-2.5 text-xs font-semibold uppercase tracking-[0.14em] text-sky-100 transition hover:bg-sky-500/18 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {savingRisk ? "Saving..." : "Save Risk"}
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <div className="mt-4 rounded-md border border-white/8 bg-black/25 p-3">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                  Per-token cooldown override
                </p>
                <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4 xl:items-end">
                  <label className="flex flex-col gap-1 rounded-md bg-white/[0.02] p-3 text-xs uppercase tracking-[0.14em] text-slate-400">
                    Token
                    <select
                      value={cooldownDraft?.symbol ?? ""}
                      onChange={(event) => {
                        const symbol = event.target.value;
                        const override = data.summary.symbolCooldownOverrides[symbol];
                        setCooldownDraft({
                          symbol,
                          cooldownSeconds: Number.isFinite(override)
                            ? override
                            : (data.summary.cooldownSeconds || 90),
                        });
                      }}
                      className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-white outline-none ring-sky-300/40 focus:ring-2"
                    >
                      {sortedSymbolControls.map((control) => (
                        <option key={control.symbol} value={control.symbol}>
                          {control.symbol}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="flex flex-col gap-1 rounded-md bg-white/[0.02] p-3 text-xs uppercase tracking-[0.14em] text-slate-400">
                    Cooldown (sec)
                    <input
                      type="number"
                      min={1}
                      value={cooldownDraft?.cooldownSeconds ?? ""}
                      onChange={(event) => {
                        const value = Number(event.target.value);
                        setCooldownDraft((prev) => ({
                          symbol: prev?.symbol ?? sortedSymbolControls[0]?.symbol ?? "",
                          cooldownSeconds: Number.isFinite(value) ? value : 1,
                        }));
                      }}
                      className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-white outline-none ring-sky-300/40 focus:ring-2"
                    />
                  </label>

                  <button
                    onClick={() => saveCooldownOverride(false)}
                    disabled={
                      busyCooldown
                      || savingRisk
                      || !cooldownDraft?.symbol
                    }
                    className="h-11 rounded-full border border-emerald-400/25 bg-emerald-500/12 px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-emerald-100 transition hover:bg-emerald-500/18 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {busyCooldown ? "Saving..." : "Set Override"}
                  </button>

                  <button
                    onClick={() => saveCooldownOverride(true)}
                    disabled={
                      busyCooldown
                      || savingRisk
                      || !cooldownDraft?.symbol
                    }
                    className="h-11 rounded-full border border-rose-400/25 bg-rose-500/10 px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-rose-100 transition hover:bg-rose-500/18 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Clear Override
                  </button>
                </div>
              </div>
            </div>
            ) : null}
          {advancedTab === "analytics" ? (
          <>
          <section className="rb-section p-5 sm:p-6">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                  Advisory Rotation Monitor
                </p>
                <h2 className="mt-1.5 text-2xl font-semibold tracking-tight text-white">
                  Rolling Symbol Rotation
                </h2>
                <p className="mt-2 text-sm text-slate-400">
                  Read-time advisory ranking for frozen mean-reversion behavior. No execution changes.
                </p>
              </div>
              <div className="flex flex-wrap gap-2 text-[10px] font-semibold uppercase tracking-[0.12em]">
                <span className="rounded-md border border-emerald-500 bg-emerald-600 px-3 py-1.5 text-white">
                  Rising {data.summary.rotationRisingCount}
                </span>
                <span className="rounded-md border border-sky-500 bg-sky-600 px-3 py-1.5 text-white">
                  Strong {data.summary.rotationStrongCount}
                </span>
                <span className="rounded-md border border-slate-500 bg-slate-600 px-3 py-1.5 text-white">
                  Neutral {data.summary.rotationNeutralCount}
                </span>
                <span className="rounded-md border border-amber-500 bg-amber-600 px-3 py-1.5 text-white">
                  Weakening {data.summary.rotationWeakeningCount}
                </span>
                <span className="rounded-md border border-rose-500 bg-rose-600 px-3 py-1.5 text-white">
                  Cold {data.summary.rotationColdCount}
                </span>
                <span className="rounded-md border border-red-700 bg-red-800 px-3 py-1.5 text-white">
                  Trap Risk {data.summary.rotationCapitalTrapRiskCount}
                </span>
              </div>
            </div>

            <div className="mt-3 flex flex-wrap gap-2 text-[10px] uppercase tracking-[0.12em] text-slate-400">
              <span className="rounded-md border border-white/10 bg-white/[0.03] px-2.5 py-1.5">
                Top Rising: {data.summary.rotationTopRisingSymbols.length > 0 ? data.summary.rotationTopRisingSymbols.join(", ") : "N/A"}
              </span>
              <span className="rounded-md border border-white/10 bg-white/[0.03] px-2.5 py-1.5">
                Top Cold: {data.summary.rotationTopColdSymbols.length > 0 ? data.summary.rotationTopColdSymbols.join(", ") : "N/A"}
              </span>
            </div>

            <div className="rb-table-wrap mt-4 max-h-[560px] overflow-y-auto overflow-x-auto">
              <table className="min-w-[1480px] w-full">
                <thead className="sticky top-0 z-10 bg-[#0b1220]">
                  <tr className="border-b border-white/8 text-left text-[10px] uppercase tracking-[0.14em] text-slate-400">
                    <th className="px-3 py-2">Symbol</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2 text-right">Short Score</th>
                    <th className="px-3 py-2 text-right">Medium Score</th>
                    <th className="px-3 py-2 text-right">Delta</th>
                    <th className="px-3 py-2 text-right">Short Win</th>
                    <th className="px-3 py-2 text-right">Short Avg PnL</th>
                    <th className="px-3 py-2 text-right">Short Hold</th>
                    <th className="px-3 py-2 text-right">Short Recovery</th>
                    <th className="px-3 py-2 text-right">Short Stale Freq</th>
                    <th className="px-3 py-2 text-right">Short Avg DD</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/6">
                  {sortedRotationRows.map((control) => (
                    <tr key={`rotation-${control.symbol}`} className="text-slate-200">
                      <td className="px-3 py-2 text-sm font-semibold">
                        <Link
                          href={`/token/${encodeURIComponent(control.symbol)}`}
                          className="transition hover:text-sky-300"
                        >
                          {control.symbol}
                        </Link>
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className="inline-flex min-w-[124px] justify-center rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]"
                          style={rotationStatusStyle(control.rotationStatus)}
                        >
                          {control.rotationStatus}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right">
                        {control.rotationShortTermScore === null ? "N/A" : control.rotationShortTermScore.toFixed(1)}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {control.rotationMediumTermScore === null ? "N/A" : control.rotationMediumTermScore.toFixed(1)}
                      </td>
                      <td className={`px-3 py-2 text-right ${valueTone(control.rotationDelta ?? 0)}`}>
                        {control.rotationDelta === null ? "N/A" : `${control.rotationDelta > 0 ? "+" : ""}${control.rotationDelta.toFixed(1)}`}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {control.rotationShortTermWinRatePct === null ? "N/A" : `${control.rotationShortTermWinRatePct.toFixed(1)}%`}
                      </td>
                      <td className={`px-3 py-2 text-right ${valueTone(control.rotationShortTermAvgRealizedPnlUsd ?? 0)}`}>
                        {control.rotationShortTermAvgRealizedPnlUsd === null ? "N/A" : formatCurrency(control.rotationShortTermAvgRealizedPnlUsd)}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {control.rotationShortTermAvgHoldHours === null ? "N/A" : `${control.rotationShortTermAvgHoldHours.toFixed(1)}h`}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {control.rotationShortTermAvgRecoveryHours === null ? "N/A" : `${control.rotationShortTermAvgRecoveryHours.toFixed(1)}h`}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {control.rotationShortTermStaleReviewFrequencyPct === null ? "N/A" : `${control.rotationShortTermStaleReviewFrequencyPct.toFixed(1)}%`}
                      </td>
                      <td className={`px-3 py-2 text-right ${valueTone(control.rotationShortTermAvgMaxDrawdownPct ?? 0)}`}>
                        {control.rotationShortTermAvgMaxDrawdownPct === null ? "N/A" : `${control.rotationShortTermAvgMaxDrawdownPct.toFixed(2)}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="rb-section p-5 sm:p-6">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                  Volatility Opportunity Radar
                </p>
                <h2 className="mt-1.5 text-2xl font-semibold tracking-tight text-white">
                  Near-Term Mean-Reversion Radar
                </h2>
                <p className="mt-2 text-sm text-slate-400">
                  Advisory-only scoring from recent observed snapshots. This does not change strategy or execution.
                </p>
              </div>
              <div className="flex flex-wrap gap-2 text-[10px] font-semibold uppercase tracking-[0.12em]">
                <span className="rounded-md border border-emerald-500 bg-emerald-600 px-3 py-1.5 text-white">
                  HIGH {data.summary.highOpportunitySymbolCount}
                </span>
                <span className="rounded-md border border-white/10 bg-white/[0.03] px-3 py-1.5 text-slate-300">
                  Top: {data.summary.topVolatilityOpportunitySymbols.length > 0
                    ? data.summary.topVolatilityOpportunitySymbols.join(", ")
                    : "N/A"}
                </span>
                <span className="rounded-md border border-white/10 bg-white/[0.03] px-3 py-1.5 text-slate-300">
                  Best score: {data.summary.highestVolatilityOpportunityScore === null
                    ? "N/A"
                    : `${data.summary.highestVolatilityOpportunityScore.toFixed(1)}`}
                </span>
              </div>
            </div>

            <div className="mt-3 flex flex-wrap gap-2">
              <button
                onClick={() => setVolatilitySortKey("score")}
                className={`rounded-md border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${
                  volatilitySortKey === "score"
                    ? "border-sky-400/40 bg-sky-500/20 text-sky-100"
                    : "border-white/12 bg-white/[0.03] text-slate-300"
                }`}
              >
                Sort Score
              </button>
              <button
                onClick={() => setVolatilitySortKey("stretch")}
                className={`rounded-md border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${
                  volatilitySortKey === "stretch"
                    ? "border-sky-400/40 bg-sky-500/20 text-sky-100"
                    : "border-white/12 bg-white/[0.03] text-slate-300"
                }`}
              >
                Sort Stretch
              </button>
              <button
                onClick={() => setVolatilitySortKey("volatility")}
                className={`rounded-md border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${
                  volatilitySortKey === "volatility"
                    ? "border-sky-400/40 bg-sky-500/20 text-sky-100"
                    : "border-white/12 bg-white/[0.03] text-slate-300"
                }`}
              >
                Sort Volatility
              </button>
              <button
                onClick={() => setVolatilitySortKey("bounce")}
                className={`rounded-md border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${
                  volatilitySortKey === "bounce"
                    ? "border-sky-400/40 bg-sky-500/20 text-sky-100"
                    : "border-white/12 bg-white/[0.03] text-slate-300"
                }`}
              >
                Sort Bounce
              </button>
            </div>

            <div className="rb-table-wrap mt-4 max-h-[560px] overflow-y-auto overflow-x-auto">
              <table className="min-w-[1320px] w-full">
                <thead className="sticky top-0 z-10 bg-[#0b1220]">
                  <tr className="border-b border-white/8 text-left text-[10px] uppercase tracking-[0.14em] text-slate-400">
                    <th className="px-3 py-2">Symbol</th>
                    <th className="px-3 py-2 text-right">Score</th>
                    <th className="px-3 py-2">Label</th>
                    <th className="px-3 py-2 text-right">Stretch</th>
                    <th className="px-3 py-2 text-right">Vol Spike</th>
                    <th className="px-3 py-2 text-right">Bounce</th>
                    <th className="px-3 py-2 text-right">Confidence</th>
                    <th className="px-3 py-2 text-right">Open</th>
                    <th className="px-3 py-2 text-right">Insufficient</th>
                    <th className="px-3 py-2">Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/6">
                  {sortedVolatilityRadarRows.length === 0 ? (
                    <tr>
                      <td className="px-3 py-3 text-xs text-slate-400" colSpan={10}>
                        No tracked symbols available yet for near-term radar scoring.
                      </td>
                    </tr>
                  ) : sortedVolatilityRadarRows.map((control) => (
                    <tr key={`radar-${control.symbol}`} className="text-slate-200">
                      <td className="px-3 py-2 text-sm font-semibold">
                        <Link
                          href={`/token/${encodeURIComponent(control.symbol)}`}
                          className="transition hover:text-sky-300"
                        >
                          {control.symbol}
                        </Link>
                      </td>
                      <td className="px-3 py-2 text-right">
                        {control.volatilityOpportunityScore === null
                          ? "N/A"
                          : control.volatilityOpportunityScore.toFixed(1)}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className="inline-flex min-w-[96px] justify-center rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]"
                          style={radarLabelStyle(control.volatilityOpportunityLabel)}
                        >
                          {control.volatilityOpportunityLabel ?? "N/A"}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right">
                        {control.volatilityOpportunityStretchScore === null
                          ? "N/A"
                          : control.volatilityOpportunityStretchScore.toFixed(1)}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {control.volatilityOpportunityVolatilitySpikeScore === null
                          ? "N/A"
                          : control.volatilityOpportunityVolatilitySpikeScore.toFixed(1)}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {control.volatilityOpportunityBounceContextScore === null
                          ? "N/A"
                          : control.volatilityOpportunityBounceContextScore.toFixed(1)}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {control.volatilityOpportunityConfidenceLabel}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {control.hasOpenPosition ? "Yes" : "No"}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {control.volatilityOpportunityInsufficientData ? "Yes" : "No"}
                      </td>
                      <td className="px-3 py-2 text-xs text-slate-300">
                        {control.volatilityOpportunityInsufficientData
                          ? (control.volatilityOpportunityInsufficientReasonMessage ?? "Insufficient data")
                          : control.volatilityOpportunityReason}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="space-y-6">
            <div className="rb-section p-5 sm:p-6">
              <div className="flex flex-col gap-5">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <p className="text-sm font-semibold uppercase tracking-[0.24em] text-slate-500">
                      Estimated equity
                    </p>
                    <div className="mt-3 flex flex-wrap items-end gap-4">
                      <h2 className="text-5xl font-semibold tracking-tight text-white sm:text-6xl">
                        {formatCurrency(data.summary.totalEquity)}
                      </h2>
                      <div className={curveTone(data.summary.netReturnPct)}>
                        <p className="text-2xl font-semibold">
                          {formatPercent(data.summary.netReturnPct)}
                        </p>
                        <p className="text-sm text-slate-400">{totalPnlLabel}</p>
                      </div>
                    </div>
                    <p className="mt-3 text-sm text-slate-400">
                      Snapshot feed: {formatSnapshotTime(data.summary.lastSnapshotAt)}
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 rounded-md border border-white/8 bg-white/[0.04] p-1">
                    {RANGE_OPTIONS.map((option) => (
                      <button
                        key={option.id}
                        onClick={() => setRange(option.id)}
                        className={`rounded-full px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] transition ${
                          option.id === range
                            ? "bg-white/14 text-white"
                            : "text-slate-400 hover:text-slate-200"
                        }`}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>

                </div>

                <MiniChart points={visiblePoints} min={chartMin} max={chartMax} />

                <div className="rb-table-wrap max-h-[420px] overflow-y-auto overflow-x-auto">
                  <table className="min-w-full table-fixed border-collapse">
                    <thead className="sticky top-0 z-10 bg-[#0b1220]">
                      <tr className="border-b border-white/8 bg-white/[0.05] text-left">
                        <th className="w-1/3 px-4 py-3.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-300">
                          Cash reserve
                        </th>
                        <th className="w-1/3 px-4 py-3.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-200">
                          Open exposure
                        </th>
                        <th className="w-1/3 px-4 py-3.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-300">
                          Risk cadence
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr className="border-b border-white/6 bg-white/[0.02]">
                        <td className="px-4 py-3 text-2xl font-semibold text-white sm:text-3xl">
                          {formatCurrency(data.summary.cashBalance)}
                        </td>
                        <td className="px-4 py-3 text-2xl font-semibold text-white sm:text-3xl">
                          {formatCurrency(data.summary.openValue)}
                        </td>
                        <td className="px-4 py-3 text-2xl font-semibold text-white sm:text-3xl">
                          {data.summary.cooldownSeconds}s
                        </td>
                      </tr>
                      <tr className="bg-white/[0.015]">
                        <td className="px-4 py-3 text-sm leading-6 text-slate-400">
                          <span className="font-medium text-sky-200">
                            {percentFormatter.format(
                              100 - data.summary.openExposurePct,
                            )}
                            %
                          </span>{" "}
                          of active capital is not deployed.
                        </td>
                        <td className="px-4 py-3 text-sm leading-6 text-slate-400">
                          <span className="font-medium text-amber-200">
                            {percentFormatter.format(data.summary.openExposurePct)}%
                          </span>{" "}
                          spread across{" "}
                          <span className="font-medium text-white">
                            {data.summary.openPositions}
                          </span>{" "}
                          positions.
                        </td>
                        <td className="px-4 py-3 text-sm leading-6 text-slate-400">
                          Loop{" "}
                          <span className="font-medium text-white">
                            {data.summary.loopSeconds}s
                          </span>
                          , lookback{" "}
                          <span className="font-medium text-white">
                            {data.summary.lookback}
                          </span>
                          , min trades{" "}
                          <span className="font-medium text-white">
                            {data.summary.minTrades}
                          </span>
                          .
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <div className="h-px w-full bg-gradient-to-r from-transparent via-white/10 to-transparent" />

                <div>
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
                    <div>
                      <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">
                        Desk Snapshot
                      </p>
                      <h3 className="mt-2 text-2xl font-semibold tracking-tight text-white">
                        Account, config, and sync comparison
                      </h3>
                      <p className="mt-2 text-sm text-slate-400">
                        One wide table for the current operating state.
                      </p>
                    </div>
                  </div>

                  <div className="rb-table-wrap mt-5 max-h-[420px] overflow-y-auto overflow-x-auto">
                    <table className="min-w-full table-fixed border-collapse">
                      <thead className="sticky top-0 z-10 bg-[#0b1220]">
                        <tr className="border-b border-white/8 bg-white/[0.05] text-left">
                          <th className="w-[16%] px-4 py-3.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                            Metric
                          </th>
                          <th className="w-[28%] px-4 py-3.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-300">
                            Account Status
                          </th>
                          <th className="w-[30%] px-4 py-3.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-200">
                            Config Snapshot
                          </th>
                          <th className="w-[26%] px-4 py-3.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-300">
                            State Sync
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/6">
                        {comparisonRows.map((row) => (
                          <tr key={row.metric} className="bg-white/[0.02]">
                            <td className="px-4 py-3 text-[11px] font-medium uppercase tracking-[0.14em] text-slate-500">
                              {row.metric}
                            </td>
                            <td className={`px-4 py-3 text-sm font-semibold ${row.accountTone}`}>
                              {row.accountValue}
                            </td>
                            <td className={`px-4 py-3 text-sm font-semibold ${row.configTone}`}>
                              {row.configValue}
                            </td>
                            <td className={`px-4 py-3 text-sm font-semibold ${row.stateTone}`}>
                              {row.stateValue}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2 text-[11px] font-medium uppercase tracking-[0.12em]">
                    <span className="rounded-md border border-emerald-400/15 bg-emerald-500/8 px-3 py-1.5 text-emerald-200">
                      {data.summary.buyCount} buys
                    </span>
                    <span className="rounded-md border border-rose-400/15 bg-rose-500/8 px-3 py-1.5 text-rose-200">
                      {data.summary.sellCount} sells
                    </span>
                    <span className="rounded-md border border-sky-400/15 bg-sky-500/[0.07] px-3 py-1.5 text-sky-100">
                      {data.summary.openPositions} open positions
                    </span>
                    {data.summary.staleLosingReviewCount > 0 ? (
                      <span className="rounded-md border border-amber-300/30 bg-amber-500/[0.12] px-3 py-1.5 text-amber-100">
                        {data.summary.staleLosingReviewCount} review flags
                      </span>
                    ) : null}
                    <span className="rounded-md border border-white/8 bg-white/[0.03] px-3 py-1.5 text-slate-300">
                      BUY on {data.summary.activeSymbols} / {data.summary.trackedSymbols}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section className="rb-section p-5 sm:p-6">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-sm font-semibold uppercase tracking-[0.24em] text-slate-500">
                  Open book
                </p>
                <h2 className="mt-2 text-3xl font-semibold tracking-tight text-white sm:text-4xl">
                  Current positions
                </h2>
                <p className="mt-2 text-sm text-slate-400">
                  Built from local paper positions, strategy state, and recent
                  market snapshots. Allocation is relative to deployed capital.
                </p>
              </div>

              <div className="flex flex-wrap gap-3 text-sm text-slate-400">
                <span className="rounded-md border border-sky-400/15 bg-sky-500/[0.07] px-4 py-2 text-sky-100">
                  {data.summary.openPositions} open positions
                </span>
                {data.summary.staleLosingReviewCount > 0 ? (
                  <span className="rounded-md border border-amber-300/30 bg-amber-500/[0.12] px-4 py-2 text-amber-100">
                    {data.summary.staleLosingReviewCount} stale-loss review
                  </span>
                ) : null}
                {data.summary.maxDrawdownDuringTradePct < 0 ? (
                  <span className="rounded-md border border-rose-300/30 bg-rose-500/[0.12] px-4 py-2 text-rose-100">
                    Worst DD: {data.summary.maxDrawdownDuringTradeSymbol ?? "n/a"}{" "}
                    {formatPercent(data.summary.maxDrawdownDuringTradePct)}
                  </span>
                ) : null}
                <span className="rounded-md border border-white/10 bg-white/[0.04] px-4 py-2 text-slate-300">
                  BUY on {data.summary.activeSymbols} / {data.summary.trackedSymbols}
                </span>
              </div>
            </div>

            <div className="rb-table-wrap mt-6 max-h-[620px] overflow-y-auto overflow-x-hidden">
              <table className="w-full table-fixed border-collapse">
                <thead className="sticky top-0 z-10 bg-[#0b1220]">
                  <tr className="border-b border-white/8 bg-white/[0.05] text-left text-[10px] uppercase tracking-[0.12em] text-slate-400">
                    <th className="px-3 py-2">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("symbol")}>
                        Asset {sortIndicator("symbol")}
                      </button>
                    </th>
                    <th className="px-3 py-2 text-right">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("units")}>
                        Units {sortIndicator("units")}
                      </button>
                    </th>
                    <th className="px-3 py-2 text-right">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("entry")}>
                        Entry {sortIndicator("entry")}
                      </button>
                    </th>
                    <th className="px-3 py-2 text-right">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("price")}>
                        Price {sortIndicator("price")}
                      </button>
                    </th>
                    <th className="px-3 py-2 text-right">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("change24h")}>
                        24h Change {sortIndicator("change24h")}
                      </button>
                    </th>
                    <th className="px-3 py-2 text-right">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("high24h")}>
                        24h High {sortIndicator("high24h")}
                      </button>
                    </th>
                    <th className="px-3 py-2 text-right">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("low24h")}>
                        24h Low {sortIndicator("low24h")}
                      </button>
                    </th>
                    <th className="px-3 py-2 text-right">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("value")}>
                        Value {sortIndicator("value")}
                      </button>
                    </th>
                    <th className="px-3 py-2 text-right">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("allocation")}>
                        Alloc {sortIndicator("allocation")}
                      </button>
                    </th>
                    <th className="px-3 py-2">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("lock")}>
                        Lock {sortIndicator("lock")}
                      </button>
                    </th>
                    <th className="px-3 py-2 text-right">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("peak")}>
                        Peak {sortIndicator("peak")}
                      </button>
                    </th>
                    <th className="px-3 py-2 text-right">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("pnl")}>
                        P&L {sortIndicator("pnl")}
                      </button>
                    </th>
                    <th className="px-3 py-2 text-center">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-sky-300" onClick={() => setPositionSortKey("attention")}>
                        Manual {sortIndicator("attention")}
                      </button>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/6">
                  {sortedPositions.map((position) => {
                    const manualSellOnProfit = position.unrealizedValue >= 0;
                    const assetName = coinName(position.symbol);

                    return (
                      <tr
                        key={position.symbol}
                        className={`text-[14px] text-slate-200 transition hover:bg-white/[0.045] ${
                          position.advisoryStaleLosingReview
                            ? "bg-amber-500/[0.05]"
                            : position.symbol === topWinnerSymbol
                            ? "bg-emerald-500/[0.04]"
                            : position.symbol === topExposureSymbol
                              ? "bg-sky-500/[0.035]"
                              : "bg-white/[0.025]"
                        }`}
                      >
                      <td className="px-3 py-2.5 align-middle">
                        <div className="flex items-center gap-3">
                          <div className="inline-flex min-h-9 min-w-[110px] items-center justify-center rounded-md bg-[linear-gradient(135deg,rgba(248,250,252,0.16),rgba(59,130,246,0.22))] px-2.5 text-[10px] font-semibold text-white">
                            {assetName}
                          </div>
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <Link
                                href={`/token/${encodeURIComponent(position.symbol)}`}
                                className="text-sm font-semibold text-white transition hover:text-sky-300"
                              >
                                {position.symbol}
                              </Link>
                              {position.symbol === topExposureSymbol ? (
                                <span className="rounded-md border border-sky-400/20 bg-sky-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-sky-200">
                                  Top size
                                </span>
                              ) : null}
                              {position.symbol === topWinnerSymbol ? (
                                <span className="rounded-md border border-emerald-400/20 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-emerald-200">
                                  Top gain
                                </span>
                              ) : null}
                              {position.advisoryStaleLosingReview ? (
                                <span className="rounded-md border border-amber-300/40 bg-amber-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-amber-100">
                                  Review
                                </span>
                              ) : null}
                            </div>
                            <p className="mt-1 truncate text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">
                              {position.thesis.replaceAll("_", " ")}
                            </p>
                            {position.advisoryStaleLosingReview ? (
                              <p className="mt-1 text-[10px] font-medium text-amber-200">
                                Age {position.advisoryReviewAgeHours?.toFixed(1) ?? "?"}h
                                {" · "}
                                {formatPercent(position.unrealizedPct)}
                                {" <= "}
                                {formatPercent(position.advisoryThresholdUnrealizedPnlPct)}
                              </p>
                            ) : null}
                            {position.advisoryMaxDrawdownPctDuringTrade < 0 ? (
                              <p className="mt-1 text-[10px] font-medium text-rose-200">
                                Max DD {formatPercent(position.advisoryMaxDrawdownPctDuringTrade)}
                                {position.advisoryMaxDrawdownPriceDuringTrade !== null
                                  ? ` @ ${formatPrice(position.advisoryMaxDrawdownPriceDuringTrade)}`
                                  : ""}
                                {position.advisoryMaxDrawdownAt
                                  ? ` (${formatRelativeTime(position.advisoryMaxDrawdownAt)})`
                                  : ""}
                              </p>
                            ) : null}
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-right font-medium text-slate-200">
                        {formatUnits(position.units)}
                      </td>
                      <td className="px-3 py-2.5 text-right font-medium text-slate-300">
                        {formatPrice(position.entryPrice)}
                      </td>
                      <td
                        className={`px-3 py-2.5 text-right font-semibold ${compareTone(
                          position.price ?? position.currentPrice,
                          position.entryPrice,
                        )}`}
                      >
                        {position.price === null ? "Pending" : formatPrice(position.price)}
                      </td>
                      <td className={`px-3 py-2.5 text-right font-semibold ${valueTone(position.change24hPct ?? 0)}`}>
                        {position.change24hPct === null ? "N/A" : formatPercent(position.change24hPct)}
                      </td>
                      <td className="px-3 py-2.5 text-right text-slate-300">
                        {position.high24h === null ? "N/A" : formatPrice(position.high24h)}
                      </td>
                      <td className="px-3 py-2.5 text-right text-slate-300">
                        {position.low24h === null ? "N/A" : formatPrice(position.low24h)}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <p className="text-sm font-semibold text-white">
                          {formatCurrency(position.marketValue)}
                        </p>
                        <p className="text-[10px] font-medium text-slate-500">
                          Cost {formatCurrency(position.costBasis)}
                        </p>
                      </td>
                      <td className="px-3 py-2.5 text-right font-medium text-slate-200">
                        {percentFormatter.format(position.allocationPct)}%
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex flex-col gap-1.5">
                          <span
                            className={`inline-flex w-fit rounded-md px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] ${statusTone(
                              position.status,
                            )}`}
                          >
                            {position.status}
                          </span>
                          <p
                            className={`text-[10px] font-medium ${
                              position.profitLockPct === null
                                ? "text-slate-400"
                                : "text-emerald-300"
                            }`}
                          >
                            {position.profitLockPct === null
                              ? "Waiting for activation"
                              : `${percentFormatter.format(
                                  position.profitLockPct,
                                )}% @ ${formatCurrency(
                                  position.lockPrice ?? position.entryPrice,
                                )}`}
                          </p>
                        </div>
                      </td>
                      <td className={`px-3 py-2.5 text-right font-semibold ${valueTone(position.peakPnlPct)}`}>
                        {percentFormatter.format(position.peakPnlPct)}%
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <p className={`text-sm font-semibold ${valueTone(position.unrealizedValue)}`}>
                          {formatCurrency(position.unrealizedValue)}
                        </p>
                        <p className={`text-[10px] font-medium ${valueTone(position.unrealizedPct)}`}>
                          {formatPercent(position.unrealizedPct)}
                        </p>
                      </td>
                        <td className="px-3 py-2.5 text-center">
                          <div className="mx-auto flex w-full max-w-[340px] flex-col gap-2 rounded-lg border border-white/10 bg-white/[0.03] p-2">
                            <button
                              onClick={() => manualSell(position)}
                              disabled={
                                busyAction !== null ||
                                busyManualSell !== null ||
                                busySymbol !== null ||
                                busyScalper !== null ||
                                savingRisk
                              }
                              className="rounded-md border px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-white transition disabled:cursor-not-allowed"
                              style={{
                                backgroundColor: manualSellOnProfit ? "#16a34a" : "#dc2626",
                                borderColor: manualSellOnProfit ? "#16a34a" : "#dc2626",
                                color: "#ffffff",
                              }}
                            >
                              {busyManualSell === position.symbol ? "Selling..." : "Manual Sell"}
                            </button>
                            <div className="space-y-1.5 rounded-md border border-white/10 bg-slate-950/35 p-2 text-[10px]">
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-semibold uppercase tracking-[0.12em] text-slate-300">
                                  Stop Loss
                                </span>
                                <label className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.03] px-1.5 py-1 text-slate-200">
                                  <input
                                    type="checkbox"
                                    checked={manualStoplossDrafts[position.symbol]?.enabled ?? false}
                                    onChange={(event) =>
                                      updateManualStoplossDraft(position.symbol, {
                                        enabled: event.target.checked,
                                      })
                                    }
                                    disabled={busyManualStoploss !== null}
                                    className="h-3.5 w-3.5 accent-emerald-500"
                                  />
                                  <span>{(manualStoplossDrafts[position.symbol]?.enabled ?? false) ? "On" : "Off"}</span>
                                </label>
                              </div>
                              <div className="grid grid-cols-[86px_1fr_auto] items-center gap-1.5">
                                <select
                                  value={manualStoplossDrafts[position.symbol]?.type ?? "pct"}
                                  onChange={(event) =>
                                    updateManualStoplossDraft(position.symbol, {
                                      type: normalizeStoplossType(event.target.value),
                                    })
                                  }
                                  disabled={
                                    busyManualStoploss !== null ||
                                    !(manualStoplossDrafts[position.symbol]?.enabled ?? false)
                                  }
                                  className="rounded-md border border-white/10 bg-slate-950/70 px-2 py-1 text-[10px] text-slate-200"
                                >
                                  <option value="pct">Percent</option>
                                  <option value="price">Price</option>
                                </select>
                                <input
                                  type="number"
                                  inputMode="decimal"
                                  step="any"
                                  min="0"
                                  value={manualStoplossDrafts[position.symbol]?.valueText ?? ""}
                                  onChange={(event) =>
                                    updateManualStoplossDraft(position.symbol, {
                                      valueText: event.target.value,
                                    })
                                  }
                                  disabled={
                                    busyManualStoploss !== null ||
                                    !(manualStoplossDrafts[position.symbol]?.enabled ?? false)
                                  }
                                  placeholder={manualStoplossDrafts[position.symbol]?.type === "price" ? "Trigger price" : "Trigger %"}
                                  className="min-w-0 rounded-md border border-white/10 bg-slate-950/70 px-2 py-1 text-[10px] text-slate-100 placeholder:text-slate-500"
                                />
                                <button
                                  onClick={() => saveManualStoploss(position.symbol)}
                                  disabled={busyManualStoploss !== null}
                                  className="rounded-md border border-sky-400/40 bg-sky-500/20 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-sky-100 disabled:cursor-not-allowed disabled:opacity-60"
                                >
                                  {busyManualStoploss === position.symbol ? "Saving..." : "Save"}
                                </button>
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex flex-wrap gap-2 text-[11px] font-medium uppercase tracking-[0.14em] text-slate-500">
              <span className="rounded-md border border-white/8 bg-white/[0.03] px-3 py-1.5">
                Sorted by {positionSort.key}
              </span>
              {topExposureSymbol ? (
                <span className="rounded-md border border-sky-400/15 bg-sky-500/8 px-3 py-1.5 text-sky-200">
                  Largest position: {topExposureSymbol}
                </span>
              ) : null}
              {topWinnerSymbol ? (
                <span className="rounded-md border border-emerald-400/15 bg-emerald-500/8 px-3 py-1.5 text-emerald-200">
                  Strongest winner: {topWinnerSymbol}
                </span>
              ) : null}
              {data.summary.staleLosingReviewCount > 0 ? (
                <span className="rounded-md border border-amber-300/20 bg-amber-500/10 px-3 py-1.5 text-amber-200">
                  Review rule: age {" >= "} {data.summary.staleLosingReviewThresholdAgeHours.toFixed(1)}h and P&L {" <= "} {formatPercent(data.summary.staleLosingReviewThresholdUnrealizedPnlPct)}
                </span>
              ) : null}
            </div>

            <div className="mt-6">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                    Exit Gates
                  </p>
                  <h3 className="mt-1 text-xl font-semibold tracking-tight text-white">
                    Why Not Exiting
                  </h3>
                </div>
                <p className="text-xs text-slate-400">
                  Per-position sell gate diagnostics from current lock and live snapshot state.
                </p>
              </div>
              <div className="rb-table-wrap mt-3 max-h-[320px] overflow-y-auto overflow-x-auto">
                <table className="min-w-full table-fixed border-collapse">
                  <thead className="sticky top-0 z-10 bg-[#0b1220]">
                    <tr className="border-b border-white/8 bg-white/[0.05] text-left">
                      <th className="w-[13%] px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-300">
                        Symbol
                      </th>
                      <th className="w-[10%] px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-300">
                        P&L
                      </th>
                      <th className="w-[18%] px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-300">
                        Blocked By
                      </th>
                      <th className="w-[20%] px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-300">
                        Next Gate
                      </th>
                      <th className="w-[21%] px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-300">
                        Lock State
                      </th>
                      <th className="w-[18%] px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-300">
                        Structural Break
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/6">
                    {data.positions.map((position) => {
                      const diag = position.exitDiagnostics;
                      return (
                        <tr key={`${position.symbol}-exit-diagnostics`} className="bg-white/[0.02]">
                          <td className="px-3 py-2 text-xs font-semibold text-white">
                            {position.symbol}
                          </td>
                          <td className={`px-3 py-2 text-right text-xs font-semibold ${valueTone(diag.pnlPct ?? 0)}`}>
                            {diag.pnlPct === null ? "n/a" : formatPercent(diag.pnlPct)}
                          </td>
                          <td className="px-3 py-2 text-xs text-slate-200">
                            {diag.canExitNow ? (
                              <span className="rounded-md border border-emerald-400/30 bg-emerald-500/12 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-emerald-200">
                                Exit Ready
                              </span>
                            ) : (
                              <span className="rounded-md border border-white/15 bg-white/[0.04] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-200">
                                {diag.blockedBy.replaceAll("_", " ")}
                              </span>
                            )}
                            <p className="mt-1 text-[10px] text-slate-400">{diag.reason}</p>
                          </td>
                          <td className="px-3 py-2 text-xs text-slate-200">
                            {diag.nextGate}
                            {diag.toFirstActivationPct !== null && diag.blockedBy === "waiting_for_first_lock" ? (
                              <p className="mt-1 text-[10px] text-slate-400">
                                Needs +{Math.max(diag.toFirstActivationPct, 0).toFixed(2)}%
                              </p>
                            ) : null}
                          </td>
                          <td className="px-3 py-2 text-xs text-slate-200">
                            {diag.currentLockPct === null
                              ? "No lock yet"
                              : `${formatPercent(diag.currentLockPct)} @ ${formatPrice(diag.lockPrice ?? position.entryPrice)}`}
                            <p className="mt-1 text-[10px] text-slate-400">
                              Peak {formatPercent(diag.peakPnlPct)} | Trailing {diag.trailingArmed ? "On" : "Off"}
                            </p>
                          </td>
                          <td className="px-3 py-2 text-xs text-slate-200">
                            {diag.zScore === null ? "z-score unavailable" : `z=${diag.zScore.toFixed(2)}`}
                            <p className="mt-1 text-[10px] text-slate-400">
                              threshold {diag.maxNegativeZScore.toFixed(2)} | {diag.structuralBreakEligible ? "eligible" : "not eligible"}
                            </p>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
          </>
          ) : null}
            </div>
          </details>
        </div>
      </div>
    </main>
  );
}


