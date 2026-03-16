"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

type TokenDetailPayload = {
  generatedAt: string;
  symbol: string;
  summary: {
    symbol: string;
    currentPrice: number | null;
    currentPriceAt: string | null;
    hasOpenPosition: boolean;
    openUnits: number;
    entryPrice: number | null;
    marketValue: number;
    unrealizedPnlUsd: number;
    unrealizedPnlPct: number;
    positionAgeHours: number | null;
    maxDrawdownSinceEntryPct: number;
    maxDrawdownSinceEntryPrice: number | null;
    maxDrawdownSinceEntryAt: number | null;
  };
  advisory: {
    staleLosingReview: boolean;
    staleReviewAgeHours: number | null;
    staleReviewThresholdAgeHours: number | null;
    staleReviewThresholdUnrealizedPnlPct: number | null;
    volatilityOpportunityScorePct: number | null;
    volatilityOpportunityLabel: string;
    volatilityOpportunity: {
      score: number | null;
      label: string | null;
      reason: string;
      confidenceLabel: string;
      stretchScore: number | null;
      volatilitySpikeScore: number | null;
      bounceContextScore: number | null;
      liquidityQualityScore: number | null;
      observedHistorySpanMinutes: number;
      observedPointCount: number;
      insufficientData: boolean;
      insufficientReasonCode: string | null;
      insufficientReasonMessage: string | null;
    };
    configuredRegime: string;
    detectedRegime: string;
    detectedRegimeConfidenceLabel: string;
    detectedRegimeConfidenceScore: number | null;
    detectedRegimeExplanation: string;
    detectedRegimeStructureBias: string;
    detectedRegimeVolatilityState: string;
    detectedRegimeParticipationState: string;
    effectiveStrategy?: string | null;
    autoFallbackReason?: string | null;
    regime: string | null;
    strategyScorePct: number | null;
    volatilityPct: number | null;
    buyExecutable: boolean | null;
    buyExecutableReason: string | null;
    capitalEfficiencyScore: number | null;
    capitalWasteRank: number | null;
    rotationMonitor: {
      shortTermScore: number | null;
      mediumTermScore: number | null;
      rotationDelta: number | null;
      status: string;
      shortTerm: {
        winRatePct: number | null;
        avgRealizedPnlUsd: number | null;
        avgHoldHours: number | null;
        avgRecoveryHours: number | null;
        staleReviewFrequencyPct: number | null;
        avgMaxDrawdownPct: number | null;
      };
      mediumTerm: {
        winRatePct: number | null;
        avgRealizedPnlUsd: number | null;
        avgHoldHours: number | null;
        avgRecoveryHours: number | null;
        staleReviewFrequencyPct: number | null;
        avgMaxDrawdownPct: number | null;
      };
    };
  };
  history: {
    buyCount: number;
    sellCount: number;
    realizedPnlUsd: number;
    recentTrades: Array<{
      time: number;
      side: string;
      price: number;
      size: number;
      reason: string;
      pnl: number | null;
      balance: number | null;
    }>;
  };
  chart: {
    pricePoints: Array<{ tsEpoch: number; price: number }>;
    tradeMarkers: Array<{ time: number; side: string; price: number }>;
  };
  waveZoneAnalyzer: {
    symbol: string;
    current_price: number;
    summary: {
      weighted_low_revisit_likelihood_pct: number;
      weighted_high_revisit_likelihood_pct: number;
      dominant_bias: "LOW_REVISIT_MORE_LIKELY" | "HIGH_REVISIT_MORE_LIKELY" | "BALANCED";
      strongest_overall_low_zone: { center: number; min: number; max: number } | null;
      strongest_overall_high_zone: { center: number; min: number; max: number } | null;
      analysis_anchor_at?: string | null;
      latest_snapshot_at?: string | null;
      latest_snapshot_age_minutes?: number | null;
      history_point_count?: number;
      data_quality_note: string;
    };
    timeframes: Record<string, {
      strongest_low_zone: {
        center: number;
        min: number;
        max: number;
        touch_count: number;
        last_touch_age_hours: number | null;
        reaction_strength: number;
        score: number;
      } | null;
      most_touched_low_zone: {
        center: number;
        min: number;
        max: number;
        touch_count: number;
        last_touch_age_hours: number | null;
        reaction_strength: number;
        score: number;
      } | null;
      strongest_high_zone: {
        center: number;
        min: number;
        max: number;
        touch_count: number;
        last_touch_age_hours: number | null;
        reaction_strength: number;
        score: number;
      } | null;
      most_touched_high_zone: {
        center: number;
        min: number;
        max: number;
        touch_count: number;
        last_touch_age_hours: number | null;
        reaction_strength: number;
        score: number;
      } | null;
      low_revisit_likelihood_pct: number;
      high_revisit_likelihood_pct: number;
      insufficient_data: boolean;
      insufficient_reason_code: string | null;
      insufficient_reason_message: string | null;
      observed_history_span_minutes: number;
      observed_candle_count: number;
    }>;
  };
  regimeAdvisory?: {
    suggestedRegime: string;
    confidenceScore: number;
    confidenceLabel: string;
    explanation: string;
    components: {
      structureBias: string;
      volatilityState: string;
      participationState: string;
    };
    timeframeSummary?: Record<string, {
      insufficientData?: boolean;
      confidenceScore?: number;
      confidenceLabel?: string;
      suggestedRegime?: string;
      structureClass?: string;
      volatilityState?: string;
      participationState?: string;
    }>;
    dataQualityNote?: string;
  };
};

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

const percentFormatter = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatCurrency(value: number) {
  return currencyFormatter.format(value);
}

function formatPrice(value: number | null) {
  if (value === null) {
    return "N/A";
  }
  return priceFormatter.format(value);
}

function formatPercent(value: number | null) {
  if (value === null) {
    return "N/A";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${percentFormatter.format(value)}%`;
}

function formatAgeHours(value: number | null) {
  if (value === null) {
    return "N/A";
  }
  return `${value.toFixed(1)}h`;
}

function formatUnits(value: number | null) {
  if (value === null || !Number.isFinite(value)) {
    return "N/A";
  }
  return value.toFixed(6);
}

function toneByValue(value: number) {
  if (value > 0) {
    return "text-emerald-300";
  }
  if (value < 0) {
    return "text-rose-300";
  }
  return "text-slate-300";
}

function advisoryChipClass(enabled: boolean) {
  return enabled
    ? "border-amber-300/40 bg-amber-500/20 text-amber-100"
    : "border-emerald-300/30 bg-emerald-500/15 text-emerald-100";
}

function rotationStatusClass(status: string) {
  if (status === "Rising") {
    return "border-emerald-400/35 bg-emerald-500/18 text-emerald-100";
  }
  if (status === "Strong") {
    return "border-sky-400/35 bg-sky-500/18 text-sky-100";
  }
  if (status === "Weakening") {
    return "border-amber-400/35 bg-amber-500/18 text-amber-100";
  }
  if (status === "Cold") {
    return "border-rose-400/35 bg-rose-500/18 text-rose-100";
  }
  if (status === "Capital Trap Risk") {
    return "border-red-500/45 bg-red-600/20 text-red-100";
  }
  return "border-white/12 bg-white/[0.04] text-slate-200";
}

function opportunityLabelClass(label: string | null) {
  if (label === "HIGH") {
    return "border-emerald-400/35 bg-emerald-500/18 text-emerald-100";
  }
  if (label === "MEDIUM") {
    return "border-sky-400/35 bg-sky-500/18 text-sky-100";
  }
  if (label === "LOW") {
    return "border-amber-400/35 bg-amber-500/18 text-amber-100";
  }
  return "border-white/12 bg-white/[0.04] text-slate-200";
}

function opportunityLabelText(label: string | null) {
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

function confidenceLabelText(label: string | null) {
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

function friendlyRegime(value: string | null | undefined) {
  if (!value) {
    return "N/A";
  }
  return value
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function friendlyInsufficientReason(code: string | null, message: string | null) {
  if (message) {
    return message;
  }
  if (code === "insufficient_point_count") {
    return "Not enough recent data points.";
  }
  if (code === "insufficient_history_span") {
    return "History window is too short.";
  }
  if (code === "stale_snapshot_history") {
    return "Recent snapshot history is stale.";
  }
  if (code === "insufficient_window_coverage") {
    return "Not enough recent data coverage.";
  }
  if (code === "invalid_price_window") {
    return "Recent price window is invalid.";
  }
  return "Not enough recent data.";
}

function formatZoneRange(zone: { min: number; max: number; center: number } | null) {
  if (!zone) {
    return "N/A";
  }
  return `${formatPrice(zone.min)} - ${formatPrice(zone.max)}`;
}

function biasBadgeStyle(
  bias: "LOW_REVISIT_MORE_LIKELY" | "HIGH_REVISIT_MORE_LIKELY" | "BALANCED",
) {
  if (bias === "LOW_REVISIT_MORE_LIKELY") {
    return "border-emerald-400/35 bg-emerald-500/18 text-emerald-100";
  }
  if (bias === "HIGH_REVISIT_MORE_LIKELY") {
    return "border-rose-400/35 bg-rose-500/18 text-rose-100";
  }
  return "border-sky-400/35 bg-sky-500/18 text-sky-100";
}

function PriceSparkline({
  points,
}: {
  points: Array<{ tsEpoch: number; price: number }>;
}) {
  if (points.length < 2) {
    return (
      <div className="rb-content-card px-4 py-6 text-center text-sm text-slate-400">
        Not enough snapshot points for chart.
      </div>
    );
  }

  const prices = points.map((point) => point.price);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const span = Math.max(max - min, 1e-9);
  const coords = points.map((point, index) => {
    const x = (index / (points.length - 1)) * 100;
    const y = 100 - (((point.price - min) / span) * 100);
    return `${x},${y}`;
  });

  return (
    <div className="rb-content-card p-3">
      <svg viewBox="0 0 100 100" className="h-36 w-full">
        <polyline
          fill="none"
          stroke="#38bdf8"
          strokeWidth="2.2"
          strokeLinejoin="round"
          strokeLinecap="round"
          points={coords.join(" ")}
        />
      </svg>
      <div className="mt-2 flex flex-wrap items-center justify-between text-[11px] uppercase tracking-[0.12em] text-slate-400">
        <span>Low {formatPrice(min)}</span>
        <span>High {formatPrice(max)}</span>
      </div>
    </div>
  );
}

export default function TokenDetailPage() {
  const params = useParams<{ symbol: string }>();
  const symbol = useMemo(
    () => decodeURIComponent(String(params?.symbol ?? "")).trim().toUpperCase(),
    [params],
  );
  const [data, setData] = useState<TokenDetailPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!symbol) {
      setError("Invalid symbol");
      setLoading(false);
      return;
    }

    let cancelled = false;
    const load = async () => {
      try {
        setLoading(true);
        const response = await fetch(`/api/token/${encodeURIComponent(symbol)}`, {
          cache: "no-store",
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(String(payload?.error ?? "Failed to load token detail"));
        }
        if (!cancelled) {
          setData(payload as TokenDetailPayload);
          setError(null);
        }
      } catch (loadError: unknown) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Unknown error");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    load();
    const timer = window.setInterval(load, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [symbol]);

  if (loading && !data) {
    return (
      <main className="rb-page min-h-screen px-4 py-8 text-slate-200 sm:px-6 lg:px-8">
        <div className="rb-shell mx-auto max-w-[1280px]">
          <div className="rb-content-card h-40 animate-pulse" />
        </div>
      </main>
    );
  }

  if (error || !data) {
    return (
      <main className="rb-page min-h-screen px-4 py-8 text-slate-200 sm:px-6 lg:px-8">
        <div className="rb-shell mx-auto max-w-[1280px] space-y-4">
          <Link
            href="/"
            className="rb-chip rb-chip--neutral inline-flex"
          >
            Back to dashboard
          </Link>
          <div className="rounded-md border border-rose-400/30 bg-rose-500/15 p-4 text-rose-100">
            {error ?? "Failed to load token detail."}
          </div>
        </div>
      </main>
    );
  }

  const summary = data.summary;
  const advisory = data.advisory;
  const rotation = advisory.rotationMonitor;
  const history = data.history;
  const wave = data.waveZoneAnalyzer;
  const regimeAdvisory = data.regimeAdvisory ?? null;
  const volatilityOpportunity = advisory.volatilityOpportunity;
  const timeframeOrder = ["1h", "4h", "8h", "16h", "24h", "3d", "7d"];
  const inPosition = summary.hasOpenPosition && summary.openUnits > 0;
  const allWaveInsufficient = timeframeOrder.every((timeframeKey) => {
    const row = wave.timeframes[timeframeKey];
    return !row || row.insufficient_data;
  });
  const allRegimeWindowsInsufficient = regimeAdvisory?.timeframeSummary
    ? Object.values(regimeAdvisory.timeframeSummary).every((row) => row?.insufficientData)
    : true;
  const rotationConfidence =
    rotation.shortTermScore !== null && rotation.mediumTermScore !== null
      ? "Medium Confidence"
      : "Low Confidence";
  const sortedRecentTrades = [...history.recentTrades].sort(
    (left, right) => right.time - left.time,
  );
  const currentDrawdownPct = summary.unrealizedPnlPct < 0 ? summary.unrealizedPnlPct : 0;

  return (
    <main className="rb-page min-h-screen px-4 py-8 text-slate-200 sm:px-6 lg:px-8">
      <div className="rb-shell mx-auto max-w-[1280px] space-y-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Link
            href="/"
            className="rb-chip rb-chip--neutral inline-flex"
          >
            Back to dashboard
          </Link>
          <p className="text-[11px] uppercase tracking-[0.12em] text-slate-400">
            Updated {new Date(data.generatedAt).toLocaleString()}
          </p>
        </div>

        <section className="rb-section p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="rb-kicker">Token / Symbol</p>
              <h1 className="rb-title mt-2 text-4xl sm:text-5xl">
                {data.symbol}
              </h1>
              <p className="rb-helper mt-2 text-sm">
                Current token state at a glance. Advisory insights are read-only.
              </p>
            </div>
            <div className="flex flex-wrap gap-2 text-[11px] font-semibold uppercase tracking-[0.12em]">
              <span className={`rounded-md border px-3 py-1.5 ${advisoryChipClass(advisory.staleLosingReview)}`}>
                Needs Review {advisory.staleLosingReview ? "Flagged" : "Clear"}
              </span>
              <span className={`rounded-md border px-3 py-1.5 ${opportunityLabelClass(volatilityOpportunity.label)}`}>
                Bounce Setup {opportunityLabelText(volatilityOpportunity.label)}
              </span>
              <span className={`rounded-md border px-3 py-1.5 ${rotationStatusClass(rotation.status)}`}>
                Symbol Suitability {rotation.status}
              </span>
            </div>
          </div>

          <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-9">
            <div className="rb-content-card p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Current Price</p>
              <p className="mt-1 text-base font-semibold text-sky-200">{formatPrice(summary.currentPrice)}</p>
            </div>
            <div className="rb-content-card p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Position Value</p>
              <p className="mt-1 text-base font-semibold text-white">{formatCurrency(summary.marketValue)}</p>
            </div>
            <div className="rb-content-card p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Open P/L</p>
              <p className={`mt-1 text-base font-semibold ${toneByValue(summary.unrealizedPnlUsd)}`}>
                {formatCurrency(summary.unrealizedPnlUsd)}
              </p>
            </div>
            <div className="rb-content-card p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">P/L %</p>
              <p className={`mt-1 text-base font-semibold ${toneByValue(summary.unrealizedPnlPct)}`}>
                {formatPercent(summary.unrealizedPnlPct)}
              </p>
            </div>
            <div className="rb-content-card p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Age</p>
              <p className="mt-1 text-base font-semibold text-white">{formatAgeHours(summary.positionAgeHours)}</p>
            </div>
            <div className="rb-content-card p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Needs Review</p>
              <p className={`mt-1 text-sm font-semibold ${advisory.staleLosingReview ? "text-amber-100" : "text-emerald-100"}`}>
                {advisory.staleLosingReview ? "Flagged" : "Clear"}
              </p>
            </div>
            <div className="rb-content-card p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Bounce Setup</p>
              <p className="mt-1 text-sm font-semibold text-sky-100">{opportunityLabelText(volatilityOpportunity.label)}</p>
            </div>
            <div className="rb-content-card p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Configured Regime</p>
              <p className="mt-1 text-sm font-semibold text-slate-100">{advisory.configuredRegime}</p>
            </div>
            <div className="rb-content-card p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Trend Shift</p>
              <p className={`mt-1 text-base font-semibold ${toneByValue(rotation.rotationDelta ?? 0)}`}>
                {rotation.rotationDelta === null
                  ? "N/A"
                  : `${rotation.rotationDelta > 0 ? "+" : ""}${rotation.rotationDelta.toFixed(1)}`}
              </p>
            </div>
          </div>

          {!inPosition ? (
            <p className="mt-4 rounded-md border border-sky-400/25 bg-sky-500/12 px-3 py-2 text-sm text-sky-100">
              No active open position for this token right now. Advisory cards still show current setup quality.
            </p>
          ) : null}
        </section>

        <section className="rb-section p-5 sm:p-6">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
              Current Position Snapshot
            </p>
            <h2 className="mt-1 text-2xl font-semibold text-white">Position and Risk Path</h2>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <article className="rb-content-card p-4">
              <p className="text-sm font-semibold uppercase tracking-[0.14em] text-slate-300">Position</p>
              <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                <div className="rb-summary-card p-3">
                  <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Entry Price</p>
                  <p className="mt-1 font-semibold text-white">{formatPrice(summary.entryPrice)}</p>
                </div>
                <div className="rb-summary-card p-3">
                  <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Current Price</p>
                  <p className="mt-1 font-semibold text-sky-200">{formatPrice(summary.currentPrice)}</p>
                </div>
                <div className="rb-summary-card p-3">
                  <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Size</p>
                  <p className="mt-1 font-semibold text-white">{formatUnits(summary.openUnits)}</p>
                </div>
                <div className="rb-summary-card p-3">
                  <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Market Value</p>
                  <p className="mt-1 font-semibold text-white">{formatCurrency(summary.marketValue)}</p>
                </div>
                <div className="rb-summary-card p-3">
                  <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Open P/L</p>
                  <p className={`mt-1 font-semibold ${toneByValue(summary.unrealizedPnlUsd)}`}>
                    {formatCurrency(summary.unrealizedPnlUsd)}
                  </p>
                </div>
                <div className="rb-summary-card p-3">
                  <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">P/L %</p>
                  <p className={`mt-1 font-semibold ${toneByValue(summary.unrealizedPnlPct)}`}>
                    {formatPercent(summary.unrealizedPnlPct)}
                  </p>
                </div>
              </div>
              <p className="mt-3 text-xs text-slate-400">Age: {formatAgeHours(summary.positionAgeHours)}</p>
            </article>

            <article className="rb-content-card p-4">
              <p className="text-sm font-semibold uppercase tracking-[0.14em] text-slate-300">Risk Path</p>
              <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                <div className="rb-summary-card p-3">
                  <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Worst Dip</p>
                  <p className={`mt-1 font-semibold ${toneByValue(summary.maxDrawdownSinceEntryPct)}`}>
                    {formatPercent(summary.maxDrawdownSinceEntryPct)}
                  </p>
                </div>
                <div className="rb-summary-card p-3">
                  <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Current Drawdown</p>
                  <p className={`mt-1 font-semibold ${toneByValue(currentDrawdownPct)}`}>
                    {formatPercent(currentDrawdownPct)}
                  </p>
                </div>
                <div className="rb-summary-card p-3">
                  <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Needs Review</p>
                  <p className={`mt-1 font-semibold ${advisory.staleLosingReview ? "text-amber-100" : "text-emerald-100"}`}>
                    {advisory.staleLosingReview ? "Flagged" : "Clear"}
                  </p>
                </div>
                <div className="rb-summary-card p-3">
                  <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Review Rule</p>
                  <p className="mt-1 font-semibold text-slate-200">
                    Age {formatAgeHours(advisory.staleReviewThresholdAgeHours)} and P/L {formatPercent(advisory.staleReviewThresholdUnrealizedPnlPct)}
                  </p>
                </div>
                <div className="rb-summary-card p-3">
                  <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Recovery (Short)</p>
                  <p className="mt-1 font-semibold text-slate-200">
                    {rotation.shortTerm.avgRecoveryHours === null ? "N/A" : `${rotation.shortTerm.avgRecoveryHours.toFixed(1)}h`}
                  </p>
                </div>
                <div className="rb-summary-card p-3">
                  <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Recovery (Medium)</p>
                  <p className="mt-1 font-semibold text-slate-200">
                    {rotation.mediumTerm.avgRecoveryHours === null ? "N/A" : `${rotation.mediumTerm.avgRecoveryHours.toFixed(1)}h`}
                  </p>
                </div>
              </div>
              <p className="mt-3 text-xs text-slate-400">
                Max drawdown context: {summary.maxDrawdownSinceEntryPrice === null ? "N/A" : formatPrice(summary.maxDrawdownSinceEntryPrice)}
                {" at "}
                {summary.maxDrawdownSinceEntryAt === null
                  ? "N/A"
                  : new Date(summary.maxDrawdownSinceEntryAt * 1000).toLocaleString()}
              </p>
            </article>
          </div>
        </section>

        <section className="rb-section p-5 sm:p-6">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                Advisory Intelligence
              </p>
              <h2 className="mt-1 text-2xl font-semibold text-white">Advisory Overview</h2>
            </div>
            <span className="rounded-md border border-white/12 bg-white/[0.04] px-3 py-1 text-xs uppercase tracking-[0.12em] text-slate-400">
              Advisory only
            </span>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
            <article className="rb-content-card p-4">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold uppercase tracking-[0.14em] text-slate-300">
                  Volatility Opportunity
                </p>
                <span className={`rounded-md border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${opportunityLabelClass(volatilityOpportunity.label)}`}>
                  {opportunityLabelText(volatilityOpportunity.label)}
                </span>
              </div>
              <p className="mt-3 text-2xl font-semibold text-emerald-200">{formatPercent(volatilityOpportunity.score)}</p>
              <p className="mt-1 text-xs text-sky-200">{confidenceLabelText(volatilityOpportunity.confidenceLabel)}</p>
              <p className="mt-3 text-sm text-slate-300">{volatilityOpportunity.reason}</p>
              <div className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
                <div className="rb-summary-card px-2 py-1.5 text-center">
                  Stretch {formatPercent(volatilityOpportunity.stretchScore)}
                </div>
                <div className="rb-summary-card px-2 py-1.5 text-center">
                  Vol {formatPercent(volatilityOpportunity.volatilitySpikeScore)}
                </div>
                <div className="rb-summary-card px-2 py-1.5 text-center">
                  Bounce {formatPercent(volatilityOpportunity.bounceContextScore)}
                </div>
              </div>
              {volatilityOpportunity.insufficientData ? (
                <p className="mt-3 text-xs text-amber-200">
                  Insufficient data: {friendlyInsufficientReason(volatilityOpportunity.insufficientReasonCode, volatilityOpportunity.insufficientReasonMessage)}
                </p>
              ) : null}
            </article>

            <article className="rb-content-card p-4">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold uppercase tracking-[0.14em] text-slate-300">
                  Wave Zone Analyzer
                </p>
                <span className={`rounded-md border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${biasBadgeStyle(wave.summary.dominant_bias)}`}>
                  {wave.summary.dominant_bias === "LOW_REVISIT_MORE_LIKELY"
                    ? "LOW MAGNET"
                    : wave.summary.dominant_bias === "HIGH_REVISIT_MORE_LIKELY"
                      ? "HIGH MAGNET"
                      : "BALANCED"}
                </span>
              </div>
              <p className="mt-3 text-[13px] text-slate-300">
                Strongest Low Zone: <span className="font-semibold text-emerald-200">{formatZoneRange(wave.summary.strongest_overall_low_zone)}</span>
              </p>
              <p className="mt-1 text-[13px] text-slate-300">
                Strongest High Zone: <span className="font-semibold text-rose-200">{formatZoneRange(wave.summary.strongest_overall_high_zone)}</span>
              </p>
              <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
                <div className="rb-summary-card px-2 py-1.5">
                  Low Revisit {formatPercent(wave.summary.weighted_low_revisit_likelihood_pct)}
                </div>
                <div className="rb-summary-card px-2 py-1.5">
                  High Revisit {formatPercent(wave.summary.weighted_high_revisit_likelihood_pct)}
                </div>
              </div>
              {allWaveInsufficient ? (
                <p className="mt-3 text-xs text-amber-200">Insufficient data for all wave windows.</p>
              ) : null}
            </article>

            <article className="rb-content-card p-4">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold uppercase tracking-[0.14em] text-slate-300">
                  Rolling Symbol Rotation Monitor
                </p>
                <span className={`rounded-md border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${rotationStatusClass(rotation.status)}`}>
                  {rotation.status}
                </span>
              </div>
              <div className="mt-3 grid gap-2 text-[12px] text-slate-300">
                <p>
                  Short-Term Score: <span className="font-semibold text-emerald-200">{rotation.shortTermScore === null ? "N/A" : rotation.shortTermScore.toFixed(1)}</span>
                </p>
                <p>
                  Medium-Term Score: <span className="font-semibold text-sky-200">{rotation.mediumTermScore === null ? "N/A" : rotation.mediumTermScore.toFixed(1)}</span>
                </p>
                <p>
                  Trend Shift: <span className={`font-semibold ${toneByValue(rotation.rotationDelta ?? 0)}`}>{rotation.rotationDelta === null ? "N/A" : `${rotation.rotationDelta > 0 ? "+" : ""}${rotation.rotationDelta.toFixed(1)}`}</span>
                </p>
                <p className="text-xs text-slate-400">{rotationConfidence}</p>
              </div>
            </article>

            <article className="rb-content-card p-4">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold uppercase tracking-[0.14em] text-slate-300">
                  Regime Analysis
                </p>
                <span className="rounded-md border border-sky-400/35 bg-sky-500/18 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-sky-100">
                  {confidenceLabelText(advisory.detectedRegimeConfidenceLabel)}
                </span>
              </div>
              <p className="mt-3 text-sm text-slate-300">
                Suggested: <span className="font-semibold text-sky-100">{friendlyRegime(advisory.detectedRegime)}</span>
              </p>
              <p className="mt-1 text-[12px] text-slate-400">
                Confidence Score: {advisory.detectedRegimeConfidenceScore === null ? "N/A" : advisory.detectedRegimeConfidenceScore.toFixed(1)}
              </p>
              <p className="mt-3 text-sm text-slate-300">{advisory.detectedRegimeExplanation}</p>
              <div className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
                <div className="rb-summary-card px-2 py-1.5 text-center">
                  Structure {friendlyRegime(advisory.detectedRegimeStructureBias)}
                </div>
                <div className="rb-summary-card px-2 py-1.5 text-center">
                  Volatility {friendlyRegime(advisory.detectedRegimeVolatilityState)}
                </div>
                <div className="rb-summary-card px-2 py-1.5 text-center">
                  Participation {friendlyRegime(advisory.detectedRegimeParticipationState)}
                </div>
              </div>
              {allRegimeWindowsInsufficient ? (
                <p className="mt-3 text-xs text-amber-200">
                  Not enough recent data for robust regime window coverage.
                </p>
              ) : null}
            </article>
          </div>
        </section>

        <section className="rb-section p-5 sm:p-6">
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">
            Recent Token Trade History
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <div className="rounded-md border border-emerald-500/25 bg-emerald-500/12 p-3 text-center">
              <p className="text-[11px] uppercase tracking-[0.12em] text-emerald-100">Buys</p>
              <p className="mt-1 text-lg font-semibold text-white">{history.buyCount}</p>
            </div>
            <div className="rounded-md border border-rose-500/25 bg-rose-500/12 p-3 text-center">
              <p className="text-[11px] uppercase tracking-[0.12em] text-rose-100">Sells</p>
              <p className="mt-1 text-lg font-semibold text-white">{history.sellCount}</p>
            </div>
            <div className="rounded-md border border-sky-500/25 bg-sky-500/12 p-3 text-center">
              <p className="text-[11px] uppercase tracking-[0.12em] text-sky-100">Realized P/L</p>
              <p className={`mt-1 text-lg font-semibold ${toneByValue(history.realizedPnlUsd)}`}>{formatCurrency(history.realizedPnlUsd)}</p>
            </div>
          </div>
          <div className="mt-4 rb-table-wrap overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-white/8 text-left text-[11px] uppercase tracking-[0.14em] text-slate-400">
                  <th className="px-3 py-2">Time</th>
                  <th className="px-3 py-2">Action</th>
                  <th className="px-3 py-2 text-right">Price</th>
                  <th className="px-3 py-2 text-right">Size</th>
                  <th className="px-3 py-2 text-right">P/L</th>
                  <th className="px-3 py-2">Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/6">
                {sortedRecentTrades.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-3 py-4 text-center text-slate-400">
                      No recorded trades for this symbol.
                    </td>
                  </tr>
                ) : (
                  sortedRecentTrades.map((trade, index) => (
                    <tr key={`${trade.time}-${trade.side}-${index}`} className="text-slate-200">
                      <td className="px-3 py-2 text-xs text-slate-400">
                        {trade.time > 0 ? new Date(trade.time * 1000).toLocaleString() : "N/A"}
                      </td>
                      <td className="px-3 py-2">
                        <span className={`inline-flex rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] ${
                          trade.side === "BUY"
                            ? "border-emerald-400/35 bg-emerald-500/15 text-emerald-100"
                            : "border-rose-400/35 bg-rose-500/15 text-rose-100"
                        }`}>
                          {trade.side}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right">{formatPrice(trade.price)}</td>
                      <td className="px-3 py-2 text-right">{formatUnits(trade.size)}</td>
                      <td className={`px-3 py-2 text-right ${toneByValue(trade.pnl ?? 0)}`}>
                        {trade.pnl === null ? "N/A" : formatCurrency(trade.pnl)}
                      </td>
                      <td className="px-3 py-2 text-xs text-slate-300">{trade.reason}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
        <section className="rb-section p-5 sm:p-6">
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">
            Detailed Analytics / Expanded Details
          </p>
          <p className="mt-1 text-sm text-slate-400">
            Lower-priority analyzer breakdowns and diagnostics.
          </p>
          <div className="mt-4 grid gap-6 lg:grid-cols-2">
            <div className="rb-content-card p-4">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Price Snapshot Trail</p>
              <div className="mt-3">
                <PriceSparkline points={data.chart.pricePoints} />
              </div>
              <p className="mt-2 text-[11px] text-slate-500">
                Last price timestamp: {summary.currentPriceAt ? new Date(summary.currentPriceAt).toLocaleString() : "N/A"}
              </p>
            </div>
            <div className="rb-content-card p-4 text-[12px] text-slate-300">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Execution Diagnostics</p>
              <p className="mt-2">Regime: {advisory.regime ?? "N/A"}</p>
              <p>Configured Regime: {advisory.configuredRegime}</p>
              <p>Detected Regime: {friendlyRegime(advisory.detectedRegime)}</p>
              <p>Effective Strategy: {friendlyRegime(advisory.effectiveStrategy)}</p>
              <p>Auto Fallback Reason: {advisory.autoFallbackReason ?? "N/A"}</p>
              <p>Strategy Score: {formatPercent(advisory.strategyScorePct)}</p>
              <p>Volatility: {advisory.volatilityPct === null ? "N/A" : `${advisory.volatilityPct.toFixed(3)}%`}</p>
              <p>Buy Executable: {advisory.buyExecutable === null ? "N/A" : advisory.buyExecutable ? "Ready" : "Blocked"}</p>
              <p>Executable Reason: {advisory.buyExecutableReason ?? "N/A"}</p>
              <p>Capital Efficiency: {advisory.capitalEfficiencyScore === null ? "N/A" : `${advisory.capitalEfficiencyScore.toFixed(1)} / 100`}</p>
              <p>Capital Waste Rank: {advisory.capitalWasteRank ?? "N/A"}</p>
            </div>
          </div>
          <details className="mt-4 rb-content-card p-3">
            <summary className="cursor-pointer text-xs font-semibold uppercase tracking-[0.14em] text-slate-300">
              Wave Zone Analyzer Breakdown
            </summary>
            <p className="mt-3 text-xs text-slate-400">{wave.summary.data_quality_note}</p>
            <p className="mt-1 text-[11px] text-slate-500">
              Anchor: {wave.summary.analysis_anchor_at ? new Date(wave.summary.analysis_anchor_at).toLocaleString() : "N/A"}
              {" | "}Latest snapshot age: {wave.summary.latest_snapshot_age_minutes === null || wave.summary.latest_snapshot_age_minutes === undefined ? "N/A" : `${wave.summary.latest_snapshot_age_minutes.toFixed(1)}m`}
              {" | "}Points: {wave.summary.history_point_count ?? 0}
            </p>
            <div className="mt-3 rb-table-wrap overflow-x-auto">
              <table className="min-w-[1200px] w-full text-sm">
                <thead>
                  <tr className="border-b border-white/8 text-left text-[11px] uppercase tracking-[0.14em] text-slate-400">
                    <th className="px-3 py-2">Window</th>
                    <th className="px-3 py-2">Strongest Low Zone</th>
                    <th className="px-3 py-2 text-right">Low Touches</th>
                    <th className="px-3 py-2 text-right">Low Age</th>
                    <th className="px-3 py-2 text-right">Low Score</th>
                    <th className="px-3 py-2 text-right">Low Revisit</th>
                    <th className="px-3 py-2">Strongest High Zone</th>
                    <th className="px-3 py-2 text-right">High Touches</th>
                    <th className="px-3 py-2 text-right">High Age</th>
                    <th className="px-3 py-2 text-right">High Score</th>
                    <th className="px-3 py-2 text-right">High Revisit</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/6">
                  {timeframeOrder.map((timeframeKey) => {
                    const row = wave.timeframes[timeframeKey];
                    if (!row) {
                      return (
                        <tr key={timeframeKey} className="text-slate-300">
                          <td className="px-3 py-2 font-semibold uppercase">{timeframeKey}</td>
                          <td className="px-3 py-2 text-slate-400" colSpan={10}>Insufficient data payload</td>
                        </tr>
                      );
                    }
                    if (row.insufficient_data) {
                      return (
                        <tr key={timeframeKey} className="text-slate-300">
                          <td className="px-3 py-2 font-semibold uppercase">{timeframeKey}</td>
                          <td className="px-3 py-2 text-slate-400" colSpan={10}>
                            <div className="text-xs">{friendlyInsufficientReason(row.insufficient_reason_code, row.insufficient_reason_message)}</div>
                            <div className="mt-1 text-[10px] uppercase tracking-[0.1em] text-slate-500">
                              Code: {row.insufficient_reason_code ?? "unknown"} | Span: {row.observed_history_span_minutes.toFixed(1)}m | Candles: {row.observed_candle_count}
                            </div>
                          </td>
                        </tr>
                      );
                    }
                    return (
                      <tr key={timeframeKey} className="text-slate-200">
                        <td className="px-3 py-2 font-semibold uppercase">{timeframeKey}</td>
                        <td className="px-3 py-2 text-xs text-emerald-200">{formatZoneRange(row.strongest_low_zone)}</td>
                        <td className="px-3 py-2 text-right">{row.strongest_low_zone?.touch_count ?? "N/A"}</td>
                        <td className="px-3 py-2 text-right">{formatAgeHours(row.strongest_low_zone?.last_touch_age_hours ?? null)}</td>
                        <td className="px-3 py-2 text-right">{row.strongest_low_zone?.score.toFixed(1) ?? "N/A"}</td>
                        <td className="px-3 py-2 text-right text-emerald-200">{formatPercent(row.low_revisit_likelihood_pct)}</td>
                        <td className="px-3 py-2 text-xs text-rose-200">{formatZoneRange(row.strongest_high_zone)}</td>
                        <td className="px-3 py-2 text-right">{row.strongest_high_zone?.touch_count ?? "N/A"}</td>
                        <td className="px-3 py-2 text-right">{formatAgeHours(row.strongest_high_zone?.last_touch_age_hours ?? null)}</td>
                        <td className="px-3 py-2 text-right">{row.strongest_high_zone?.score.toFixed(1) ?? "N/A"}</td>
                        <td className="px-3 py-2 text-right text-rose-200">{formatPercent(row.high_revisit_likelihood_pct)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </details>
        </section>
      </div>
    </main>
  );
}

