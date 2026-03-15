"use client";

import { startTransition, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { buildMutatingAuthHeaders } from "../lib/mutatingAuthClient";

type DashboardPayload = {
  generatedAt: string;
  summary: {
    enabled: boolean;
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
    symbolCooldownOverrides: Record<string, number>;
  };
  symbolControls: Array<{
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
  }>;
};

function buildActionId(prefix: string): string {
  const random = Math.random().toString(36).slice(2, 10);
  return `${prefix}-${Date.now()}-${random}`;
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

type RangeId = (typeof RANGE_OPTIONS)[number]["id"];

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

function formatVolatility(value: number | null) {
  if (value === null) {
    return "N/A";
  }

  return `${value.toFixed(3)}%`;
}

function volatilityStyle(value: number | null) {
  if (value === null) {
    return {
      backgroundColor: "rgba(148, 163, 184, 0.14)",
      borderColor: "rgba(148, 163, 184, 0.35)",
      color: "#cbd5e1",
    };
  }

  if (value >= 1.2) {
    return {
      backgroundColor: "#dc2626",
      borderColor: "#dc2626",
      color: "#ffffff",
    };
  }

  if (value >= 0.6) {
    return {
      backgroundColor: "#d97706",
      borderColor: "#d97706",
      color: "#ffffff",
    };
  }

  if (value >= 0.25) {
    return {
      backgroundColor: "#0284c7",
      borderColor: "#0284c7",
      color: "#ffffff",
    };
  }

  return {
    backgroundColor: "#16a34a",
    borderColor: "#16a34a",
    color: "#ffffff",
  };
}

function formatCapitalEfficiency(value: number | null) {
  if (value === null) {
    return "N/A";
  }
  return `${value.toFixed(1)} / 100`;
}

function capitalEfficiencyStyle(value: number | null) {
  if (value === null) {
    return {
      backgroundColor: "rgba(148, 163, 184, 0.14)",
      borderColor: "rgba(148, 163, 184, 0.35)",
      color: "#cbd5e1",
    };
  }

  if (value >= 75) {
    return {
      backgroundColor: "#16a34a",
      borderColor: "#16a34a",
      color: "#ffffff",
    };
  }

  if (value >= 55) {
    return {
      backgroundColor: "#0284c7",
      borderColor: "#0284c7",
      color: "#ffffff",
    };
  }

  if (value >= 35) {
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
  const [busyManualSell, setBusyManualSell] = useState<string | null>(null);
  const [busyCloseAll, setBusyCloseAll] = useState(false);
  const [busyCooldown, setBusyCooldown] = useState(false);
  const [riskDraft, setRiskDraft] = useState<RiskDraft | null>(null);
  const [cooldownDraft, setCooldownDraft] = useState<{
    symbol: string;
    cooldownSeconds: number;
  } | null>(null);
  const [riskDirty, setRiskDirty] = useState(false);
  const [savingRisk, setSavingRisk] = useState(false);

  const loadDashboard = useCallback(async () => {
    try {
      const response = await fetch("/api/dashboard", { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`Dashboard request failed (${response.status})`);
      }

      const payload = (await response.json()) as DashboardPayload;
      startTransition(() => {
        setData(payload);
        setError(null);
      });

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
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Unable to load dashboard";
      setError(message);
    }
  }, [riskDirty]);

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
        throw new Error(`Action failed (${response.status})`);
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
    setBusySymbol(`${symbol}:${side}`);

    try {
      const response = await fetch("/api/symbols", {
        method: "POST",
        headers: buildMutatingAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ symbol, side, enabled }),
      });

      if (!response.ok) {
        throw new Error(`Symbol update failed (${response.status})`);
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
    setBusyScalper(symbol);

    try {
      const response = await fetch("/api/scalper", {
        method: "POST",
        headers: buildMutatingAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ symbol, enabled }),
      });

      if (!response.ok) {
        throw new Error(`Scalper update failed (${response.status})`);
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

  async function saveRiskSettings() {
    if (!riskDraft) {
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
        throw new Error(`Risk settings update failed (${response.status})`);
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
    if (!cooldownDraft?.symbol) {
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
      <main className="min-h-screen px-4 py-6 sm:px-6 lg:px-8">
        <div className="mx-auto flex w-full max-w-[1360px] justify-center">
          <div className="hidden w-20 shrink-0 rounded-md border border-white/8 bg-black/40 lg:block" />
          <div className="flex-1 space-y-6">
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
  const visiblePoints =
    selectedRange.points === Number.POSITIVE_INFINITY
      ? data.chart.points
      : data.chart.points.slice(-selectedRange.points);
  const chartMin = Math.min(...visiblePoints);
  const chartMax = Math.max(...visiblePoints);
  const positiveNet = data.summary.netPnl >= 0;
  const totalPnlLabel = positiveNet ? "Net gain" : "Net drawdown";
  const topExposureSymbol = data.positions[0]?.symbol ?? null;
  const topWinnerSymbol =
    [...data.positions]
      .filter((position) => position.unrealizedValue > 0)
      .sort((left, right) => right.unrealizedValue - left.unrealizedValue)[0]
      ?.symbol ?? null;
  const sortedSymbolControls = [...data.symbolControls].sort((left, right) => {
    if (left.hasOpenPosition !== right.hasOpenPosition) {
      return left.hasOpenPosition ? -1 : 1;
    }
    if (left.hasOpenPosition && right.hasOpenPosition) {
      const leftRank = left.capitalWasteRank ?? Number.MAX_SAFE_INTEGER;
      const rightRank = right.capitalWasteRank ?? Number.MAX_SAFE_INTEGER;
      if (leftRank !== rightRank) {
        return leftRank - rightRank;
      }
    }
    return left.symbol.localeCompare(right.symbol);
  });
  const worstCapitalWasteControl = sortedSymbolControls.find(
    (control) => control.hasOpenPosition && control.capitalWasteRank === 1,
  ) ?? null;
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

  return (
    <main className="min-h-screen px-4 py-6 sm:px-6 lg:px-8">
      <div className="mx-auto flex w-full max-w-[1360px] justify-center">
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

        <div className="flex-1 space-y-6">
          <header className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.28em] text-slate-500">
                RevBot desk
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <h1 className="text-4xl font-semibold tracking-tight text-white sm:text-5xl">
                  Portfolio Monitor
                </h1>
                <span
                  className={`rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] ${
                    data.summary.enabled
                      ? "bg-emerald-500/15 text-emerald-200 ring-1 ring-emerald-400/30"
                      : "bg-rose-500/15 text-rose-200 ring-1 ring-rose-400/30"
                  }`}
                >
                  {data.summary.enabled ? "Bot active" : "Bot paused"}
                </span>
              </div>
              <p className="mt-3 max-w-2xl text-sm text-slate-400">
                A live paper-trading surface built from local state files,
                recent journal events, and the latest snapshot lines in
                <code className="mx-1 rounded bg-white/5 px-1.5 py-0.5 text-slate-200">
                  bot.log
                </code>
                .
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              <button
                onClick={() => runAction("start")}
                disabled={busyAction !== null}
                className="rounded-full border border-emerald-400/25 bg-emerald-500/12 px-5 py-3 text-sm font-semibold text-emerald-200 transition hover:bg-emerald-500/18 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {busyAction === "start" ? "Starting..." : "Start bot"}
              </button>
              <button
                onClick={() => runAction("stop")}
                disabled={busyAction !== null}
                className="rounded-full border border-amber-300/20 bg-amber-400/10 px-5 py-3 text-sm font-semibold text-amber-100 transition hover:bg-amber-400/16 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {busyAction === "stop" ? "Stopping..." : "Stop bot"}
              </button>
              <button
                onClick={() => runAction("kill")}
                disabled={busyAction !== null}
                className="rounded-full border border-rose-400/20 bg-rose-500/10 px-5 py-3 text-sm font-semibold text-rose-100 transition hover:bg-rose-500/18 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {busyAction === "kill" ? "Locking..." : "Emergency stop"}
              </button>
              <button
                onClick={() => runAction("refresh")}
                disabled={busyAction !== null}
                className="rounded-full border border-white/10 bg-white/[0.05] px-5 py-3 text-sm font-semibold text-white transition hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-60"
              >
                Refresh
              </button>
              <button
                onClick={closeAllPositions}
                disabled={busyAction !== null || busyCloseAll || data.positions.length === 0}
                className="rounded-full border border-orange-400/25 bg-orange-500/12 px-5 py-3 text-sm font-semibold text-orange-100 transition hover:bg-orange-500/20 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {busyCloseAll ? "Closing..." : "Close all"}
              </button>
            </div>
          </header>

          {error ? (
            <div className="rounded-lg border border-rose-400/20 bg-rose-500/10 px-5 py-4 text-sm text-rose-100">
              {error}
            </div>
          ) : null}

          <section className="rounded-md border border-white/8 bg-[linear-gradient(160deg,rgba(9,14,24,0.94),rgba(4,8,14,0.96))] p-5 sm:p-6">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                  Token controls
                </p>
                <h2 className="mt-1.5 text-2xl font-semibold tracking-tight text-white">
                  Auto-trade by symbol
                </h2>
                <p className="mt-2 text-sm text-slate-400">
                  Turning a symbol off keeps scanning live but blocks BUY and SELL execution.
                </p>
              </div>
              <div className="flex flex-wrap gap-2 text-xs font-semibold uppercase tracking-[0.14em]">
                <span className="rounded-md border border-emerald-500 bg-emerald-600 px-3 py-1.5 text-white">
                  BUY on: {data.summary.activeSymbols}
                </span>
                <span className="rounded-md border border-rose-500 bg-rose-600 px-3 py-1.5 text-white">
                  BUY off: {data.summary.disabledSymbols}
                </span>
                <span className="rounded-md border border-emerald-500 bg-emerald-600 px-3 py-1.5 text-white">
                  SELL on: {data.summary.sellEnabledSymbols}
                </span>
                <span className="rounded-md border border-rose-500 bg-rose-600 px-3 py-1.5 text-white">
                  SELL off: {data.summary.sellDisabledSymbols}
                </span>
                <span className="rounded-md border border-white/10 bg-white/[0.03] px-3 py-1.5 text-slate-300">
                  {data.summary.trackedSymbols} total
                </span>
                {data.summary.bestBuySymbol && data.summary.bestBuyOpportunityPct !== null ? (
                  <span className="rounded-md border border-emerald-500/40 bg-emerald-500/20 px-3 py-1.5 text-emerald-100">
                    Best buy: {data.summary.bestBuySymbol} {formatOpportunity(data.summary.bestBuyOpportunityPct)}
                  </span>
                ) : (
                  <span className="rounded-md border border-white/10 bg-white/[0.03] px-3 py-1.5 text-slate-300">
                    Best buy: pending snapshots
                  </span>
                )}
                {worstCapitalWasteControl ? (
                  <span className="rounded-md border border-rose-500/35 bg-rose-500/18 px-3 py-1.5 text-rose-100">
                    Capital drag: {worstCapitalWasteControl.symbol} ({formatCapitalEfficiency(worstCapitalWasteControl.capitalEfficiencyScore)})
                  </span>
                ) : null}
              </div>
            </div>

            <div className="mt-4 overflow-x-auto rounded-lg border border-white/8 bg-black/20">
              <div className="min-w-[1960px]">
                <div className="grid grid-cols-[170px_minmax(190px,1fr)_170px_150px_170px_170px_190px_190px_190px_190px] border-b border-white/8 bg-white/[0.04] px-4 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                  <span>Token</span>
                  <span>Execution Status</span>
                  <span className="text-center">Regime / Trend</span>
                  <span className="text-center">Volatility</span>
                  <span className="text-center">Scalper</span>
                  <span className="text-center">Buy Opportunity</span>
                  <span className="text-center">Capital Efficiency</span>
                  <span className="text-center">Executable</span>
                  <span className="text-center">BUY</span>
                  <span className="text-center">SELL</span>
                </div>

                <div className="max-h-[360px] overflow-y-auto">
                  {sortedSymbolControls.map((control) => {
                    const busyBuy = busySymbol === `${control.symbol}:buy`;
                    const busySell = busySymbol === `${control.symbol}:sell`;
                    const modeLabel = control.buyEnabled && control.sellEnabled
                      ? "BUY + SELL enabled"
                      : control.buyEnabled
                        ? "BUY only"
                        : control.sellEnabled
                          ? "SELL only"
                          : "Execution paused";
                    const busyScalperRow = busyScalper === control.symbol;
                    const isBestBuy =
                      control.symbol === data.summary.bestBuySymbol
                      && control.buyOpportunityPct !== null
                      && !control.hasOpenPosition;
                    const regimeChipStyle = regimeStyle(control.regime);
                    const volatilityChipStyle = volatilityStyle(control.volatilityPct);
                    const buyOpportunityChipStyle = opportunityStyle(
                      control.buyOpportunityPct,
                    );
                    const capitalEfficiencyChipStyle = capitalEfficiencyStyle(
                      control.capitalEfficiencyScore,
                    );
                    const executableChipStyle = executableStyle(control.buyExecutable);

                    const buyOn = control.buyEnabled;
                    const sellOn = control.sellEnabled;
                    const scalperOn = control.scalperEnabled;

                    return (
                      <div
                        key={control.symbol}
                        className="grid grid-cols-[170px_minmax(190px,1fr)_170px_150px_170px_170px_190px_190px_190px_190px] items-center gap-3 border-b border-white/6 px-4 py-2.5 last:border-b-0"
                      >
                        <div className="flex items-center gap-2">
                          <Link
                            href={`/token/${encodeURIComponent(control.symbol)}`}
                            className="truncate text-sm font-semibold uppercase tracking-[0.08em] text-slate-100 transition hover:text-sky-300"
                          >
                            {control.symbol}
                          </Link>
                          {control.hasOpenPosition ? (
                            <span className="inline-flex rounded-md border border-sky-400/25 bg-sky-500/12 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-sky-200">
                              OPEN
                            </span>
                          ) : null}
                        </div>

                        <div className="flex flex-col">
                          <p className="truncate text-sm font-medium text-slate-300">
                            {modeLabel}
                          </p>
                          <p className="truncate text-[10px] uppercase tracking-[0.12em] text-slate-500">
                            Cooldown {control.cooldownOverrideSeconds === null ? "default" : `${control.cooldownOverrideSeconds.toFixed(0)}s`}
                          </p>
                        </div>

                        <div className="flex items-center justify-center">
                          <span
                            className="inline-flex min-w-[130px] justify-center rounded-md border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.12em]"
                            style={regimeChipStyle}
                          >
                            {control.regime ?? "Unknown"}
                          </span>
                        </div>

                        <div className="flex items-center justify-center">
                          <span
                            className="inline-flex min-w-[120px] justify-center rounded-md border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.12em]"
                            style={volatilityChipStyle}
                          >
                            {formatVolatility(control.volatilityPct)}
                          </span>
                        </div>

                        <div className="flex items-center justify-center">
                          <button
                            onClick={() => setScalperMode(control.symbol, !scalperOn)}
                            disabled={
                              busyAction !== null
                              || busyScalperRow
                              || busySymbol !== null
                              || savingRisk
                            }
                            className="min-w-[86px] rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] disabled:cursor-not-allowed disabled:opacity-60"
                            style={{
                              backgroundColor: scalperOn ? "#16a34a" : "#dc2626",
                              borderColor: scalperOn ? "#16a34a" : "#dc2626",
                              color: "#ffffff",
                            }}
                          >
                            {busyScalperRow ? "Saving..." : scalperOn ? "ON" : "OFF"}
                          </button>
                        </div>

                        <div className="flex items-center justify-center">
                          <div className="flex flex-col items-center">
                            <span
                              className="inline-flex min-w-[124px] justify-center rounded-md border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.12em]"
                              style={buyOpportunityChipStyle}
                            >
                              {formatOpportunity(control.buyOpportunityPct)}
                            </span>
                            <span className="mt-0.5 text-[9px] font-medium uppercase tracking-[0.12em] text-slate-400">
                              Score {control.strategyScorePct === null ? "N/A" : `${control.strategyScorePct.toFixed(1)}%`}
                            </span>
                          </div>
                          {isBestBuy ? (
                            <span className="ml-2 rounded-md border border-emerald-500/35 bg-emerald-500/15 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-emerald-200">
                              Best
                            </span>
                          ) : null}
                        </div>

                        <div className="flex items-center justify-center">
                          {control.hasOpenPosition ? (
                            <div className="flex flex-col items-center">
                              <span
                                className="inline-flex min-w-[146px] justify-center rounded-md border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.12em]"
                                style={capitalEfficiencyChipStyle}
                              >
                                {formatCapitalEfficiency(control.capitalEfficiencyScore)}
                              </span>
                              <span className="mt-0.5 max-w-[170px] truncate text-[9px] font-medium uppercase tracking-[0.12em] text-slate-400">
                                {`Rank #${control.capitalWasteRank ?? 0} | Alloc ${control.capitalWasteAllocationPct?.toFixed(1) ?? "0.0"}%`}
                              </span>
                              <span className="mt-0.5 max-w-[170px] truncate text-[9px] font-medium uppercase tracking-[0.12em] text-slate-400">
                                {`P&L ${control.capitalWasteUnrealizedPct?.toFixed(1) ?? "0.0"}% | Age ${control.capitalWasteAgeHours?.toFixed(1) ?? "0.0"}h`}
                              </span>
                            </div>
                          ) : (
                            <span className="inline-flex min-w-[146px] justify-center rounded-md border border-white/12 bg-white/[0.03] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">
                              No open capital
                            </span>
                          )}
                        </div>

                        <div className="flex items-center justify-center">
                          <div className="flex flex-col items-center">
                            <span
                              className="inline-flex min-w-[134px] justify-center rounded-md border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.12em]"
                              style={executableChipStyle}
                            >
                              {control.buyExecutable ? "Ready" : "Blocked"}
                            </span>
                            <span className="mt-0.5 max-w-[170px] truncate text-[9px] font-medium uppercase tracking-[0.12em] text-slate-400">
                              {control.buyExecutableReason}
                            </span>
                          </div>
                        </div>

                        <div className="flex items-center justify-center gap-3">
                          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
                            BUY
                          </span>
                          <button
                            onClick={() =>
                              setSymbolAutoTrade(
                                control.symbol,
                                "buy",
                                !control.buyEnabled,
                              )
                            }
                            disabled={
                              busyAction !== null
                              || busyBuy
                              || savingRisk
                              || busyScalper !== null
                            }
                            className="min-w-[76px] rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] disabled:cursor-not-allowed disabled:opacity-60"
                            style={{
                              backgroundColor: buyOn ? "#16a34a" : "#dc2626",
                              borderColor: buyOn ? "#16a34a" : "#dc2626",
                              color: "#ffffff",
                            }}
                          >
                            {busyBuy ? "Saving..." : buyOn ? "ON" : "OFF"}
                          </button>
                        </div>

                        <div className="flex items-center justify-center gap-3">
                          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
                            SELL
                          </span>
                          <button
                            onClick={() =>
                              setSymbolAutoTrade(
                                control.symbol,
                                "sell",
                                !control.sellEnabled,
                              )
                            }
                            disabled={
                              busyAction !== null
                              || busySell
                              || savingRisk
                              || busyScalper !== null
                            }
                            className="min-w-[76px] rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] disabled:cursor-not-allowed disabled:opacity-60"
                            style={{
                              backgroundColor: sellOn ? "#16a34a" : "#dc2626",
                              borderColor: sellOn ? "#16a34a" : "#dc2626",
                              color: "#ffffff",
                            }}
                          >
                            {busySell ? "Saving..." : sellOn ? "ON" : "OFF"}
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="mt-5 rounded-lg bg-black/20 p-4">
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

              <div className="mt-4 overflow-x-auto rounded-lg border border-white/8 bg-black/20">
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
          </section>

          <section className="space-y-6">
            <div className="rounded-md border border-white/8 bg-[linear-gradient(160deg,rgba(9,14,24,0.94),rgba(4,8,14,0.96))] p-5 sm:p-6">
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

                <div className="overflow-x-auto rounded-lg border border-white/8 bg-black/20">
                  <table className="min-w-full table-fixed border-collapse">
                    <thead>
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

                  <div className="mt-5 overflow-x-auto rounded-lg border border-white/8 bg-black/20">
                    <table className="min-w-full table-fixed border-collapse">
                      <thead>
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

          <section className="rounded-md border border-white/8 bg-[linear-gradient(160deg,rgba(9,14,24,0.94),rgba(4,8,14,0.96))] p-5 sm:p-6">
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

            <div className="mt-6 overflow-x-auto rounded-lg border border-white/8 bg-black/20">
              <table className="min-w-full table-fixed border-collapse">
                <thead>
                  <tr className="border-b border-white/8 bg-white/[0.05] text-left">
                    <th className="w-[22%] px-4 py-3.5 text-sm font-semibold uppercase tracking-[0.18em] text-slate-300">
                      Asset
                    </th>
                    <th className="w-[11%] px-4 py-3.5 text-right text-sm font-semibold uppercase tracking-[0.18em] text-slate-300">
                      Units
                    </th>
                    <th className="w-[11%] px-4 py-3.5 text-right text-sm font-semibold uppercase tracking-[0.18em] text-slate-300">
                      Entry
                    </th>
                    <th className="w-[11%] px-4 py-3.5 text-right text-sm font-semibold uppercase tracking-[0.18em] text-sky-300">
                      Spot
                    </th>
                    <th className="w-[12%] px-4 py-3.5 text-right text-sm font-semibold uppercase tracking-[0.18em] text-white">
                      Value v
                    </th>
                    <th className="w-[9%] px-4 py-3.5 text-right text-sm font-semibold uppercase tracking-[0.18em] text-sky-300">
                      Alloc
                    </th>
                    <th className="w-[14%] px-4 py-3.5 text-left text-sm font-semibold uppercase tracking-[0.18em] text-amber-200">
                      Lock
                    </th>
                    <th className="w-[8%] px-4 py-3.5 text-right text-sm font-semibold uppercase tracking-[0.18em] text-sky-300">
                      Peak
                    </th>
                    <th className="w-[12%] px-4 py-3.5 text-right text-sm font-semibold uppercase tracking-[0.18em] text-emerald-300">
                      P&L
                    </th>
                    <th className="w-[10%] px-4 py-3.5 text-center text-sm font-semibold uppercase tracking-[0.18em] text-rose-300">
                      Manual
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/6">
                  {data.positions.map((position) => {
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
                      <td className="px-4 py-3 align-middle">
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
                      <td className="px-4 py-3 text-right font-medium text-slate-200">
                        {formatUnits(position.units)}
                      </td>
                      <td className="px-4 py-3 text-right font-medium text-slate-300">
                        {formatPrice(position.entryPrice)}
                      </td>
                      <td
                        className={`px-4 py-3 text-right font-semibold ${compareTone(
                          position.currentPrice,
                          position.entryPrice,
                        )}`}
                      >
                        {position.currentPrice === null ? "Pending" : formatPrice(position.currentPrice)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <p className="text-sm font-semibold text-white">
                          {formatCurrency(position.marketValue)}
                        </p>
                        <p className="text-[10px] font-medium text-slate-500">
                          Cost {formatCurrency(position.costBasis)}
                        </p>
                      </td>
                      <td className="px-4 py-3 text-right font-medium text-slate-200">
                        {percentFormatter.format(position.allocationPct)}%
                      </td>
                      <td className="px-4 py-3">
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
                      <td className={`px-4 py-3 text-right font-semibold ${valueTone(position.peakPnlPct)}`}>
                        {percentFormatter.format(position.peakPnlPct)}%
                      </td>
                      <td className="px-4 py-3 text-right">
                        <p className={`text-sm font-semibold ${valueTone(position.unrealizedValue)}`}>
                          {formatCurrency(position.unrealizedValue)}
                        </p>
                        <p className={`text-[10px] font-medium ${valueTone(position.unrealizedPct)}`}>
                          {formatPercent(position.unrealizedPct)}
                        </p>
                      </td>
                        <td className="px-4 py-3 text-center">
                        <button
                          onClick={() => manualSell(position)}
                          disabled={
                            busyAction !== null ||
                            busyManualSell !== null ||
                            busySymbol !== null ||
                            busyScalper !== null ||
                            savingRisk
                          }
                          className="rounded-full border px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-white transition disabled:cursor-not-allowed"
                          style={{
                            backgroundColor: manualSellOnProfit ? "#16a34a" : "#dc2626",
                            borderColor: manualSellOnProfit ? "#16a34a" : "#dc2626",
                            color: "#ffffff",
                          }}
                        >
                          {busyManualSell === position.symbol ? "Selling..." : "Sell"}
                        </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex flex-wrap gap-2 text-[11px] font-medium uppercase tracking-[0.14em] text-slate-500">
              <span className="rounded-md border border-white/8 bg-white/[0.03] px-3 py-1.5">
                Sorted by value
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
          </section>
        </div>
      </div>
    </main>
  );
}
