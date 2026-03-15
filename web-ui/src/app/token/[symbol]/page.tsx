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
    regime: string | null;
    strategyScorePct: number | null;
    volatilityPct: number | null;
    buyExecutable: boolean | null;
    buyExecutableReason: string | null;
    capitalEfficiencyScore: number | null;
    capitalWasteRank: number | null;
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
    }>;
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
      <div className="rounded-md border border-white/8 bg-black/20 px-4 py-6 text-center text-sm text-slate-400">
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
    <div className="rounded-md border border-white/8 bg-black/20 p-3">
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
      <main className="min-h-screen bg-[#04070f] px-4 py-6 text-slate-200 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-[1280px]">
          <div className="h-40 animate-pulse rounded-md border border-white/10 bg-white/[0.04]" />
        </div>
      </main>
    );
  }

  if (error || !data) {
    return (
      <main className="min-h-screen bg-[#04070f] px-4 py-6 text-slate-200 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-[1280px] space-y-4">
          <Link
            href="/"
            className="inline-flex rounded-md border border-white/12 bg-white/[0.04] px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-slate-200"
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
  const history = data.history;
  const wave = data.waveZoneAnalyzer;
  const timeframeOrder = ["1h", "4h", "8h", "16h", "24h", "3d", "7d"];

  return (
    <main className="min-h-screen bg-[#04070f] px-4 py-6 text-slate-200 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-[1280px] space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Link
            href="/"
            className="inline-flex rounded-md border border-white/12 bg-white/[0.04] px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-slate-200"
          >
            Back to dashboard
          </Link>
          <p className="text-[11px] uppercase tracking-[0.12em] text-slate-400">
            Updated {new Date(data.generatedAt).toLocaleString()}
          </p>
        </div>

        <section className="rounded-md border border-white/8 bg-[linear-gradient(160deg,rgba(9,14,24,0.94),rgba(4,8,14,0.96))] p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Token Detail</p>
              <h1 className="mt-2 text-4xl font-semibold text-white sm:text-5xl">
                {data.symbol}
              </h1>
              <p className="mt-2 text-sm text-slate-400">
                Advisory/operator view only. No automatic trading actions.
              </p>
            </div>
            <div className="rounded-md border border-white/10 bg-white/[0.03] px-4 py-3 text-right">
              <p className="text-xs uppercase tracking-[0.12em] text-slate-500">Current Price</p>
              <p className="mt-1 text-xl font-semibold text-sky-200">
                {formatPrice(summary.currentPrice)}
              </p>
            </div>
          </div>

          <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-md border border-white/8 bg-black/20 p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Open Size</p>
              <p className="mt-1 text-lg font-semibold text-white">{summary.openUnits.toFixed(6)}</p>
            </div>
            <div className="rounded-md border border-white/8 bg-black/20 p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Market Value</p>
              <p className="mt-1 text-lg font-semibold text-white">{formatCurrency(summary.marketValue)}</p>
            </div>
            <div className="rounded-md border border-white/8 bg-black/20 p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Unrealized PnL</p>
              <p className={`mt-1 text-lg font-semibold ${toneByValue(summary.unrealizedPnlUsd)}`}>
                {formatCurrency(summary.unrealizedPnlUsd)}
              </p>
              <p className={`text-xs ${toneByValue(summary.unrealizedPnlPct)}`}>
                {formatPercent(summary.unrealizedPnlPct)}
              </p>
            </div>
            <div className="rounded-md border border-white/8 bg-black/20 p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Position Age</p>
              <p className="mt-1 text-lg font-semibold text-white">{formatAgeHours(summary.positionAgeHours)}</p>
            </div>
            <div className="rounded-md border border-white/8 bg-black/20 p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Max Drawdown Since Entry</p>
              <p className={`mt-1 text-lg font-semibold ${toneByValue(summary.maxDrawdownSinceEntryPct)}`}>
                {formatPercent(summary.maxDrawdownSinceEntryPct)}
              </p>
            </div>
            <div className="rounded-md border border-white/8 bg-black/20 p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Regime</p>
              <p className="mt-1 text-lg font-semibold text-white">{advisory.regime ?? "N/A"}</p>
            </div>
            <div className="rounded-md border border-white/8 bg-black/20 p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Opportunity</p>
              <p className="mt-1 text-lg font-semibold text-emerald-200">
                {formatPercent(advisory.volatilityOpportunityScorePct)}
              </p>
              <p className="text-xs text-slate-400">{advisory.volatilityOpportunityLabel}</p>
            </div>
            <div className="rounded-md border border-white/8 bg-black/20 p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Capital Efficiency</p>
              <p className="mt-1 text-lg font-semibold text-white">
                {advisory.capitalEfficiencyScore === null
                  ? "N/A"
                  : `${advisory.capitalEfficiencyScore.toFixed(1)} / 100`}
              </p>
              <p className="text-xs text-slate-400">
                Rank {advisory.capitalWasteRank ?? "N/A"}
              </p>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap gap-2 text-[11px] font-semibold uppercase tracking-[0.12em]">
            <span className={`rounded-md border px-3 py-1.5 ${advisoryChipClass(advisory.staleLosingReview)}`}>
              {advisory.staleLosingReview ? "Stale losing review: flagged" : "Stale losing review: clear"}
            </span>
            <span className="rounded-md border border-sky-400/25 bg-sky-500/12 px-3 py-1.5 text-sky-100">
              Score {advisory.strategyScorePct === null ? "N/A" : `${advisory.strategyScorePct.toFixed(1)}%`}
            </span>
            <span className="rounded-md border border-white/12 bg-white/[0.04] px-3 py-1.5 text-slate-300">
              Volatility {advisory.volatilityPct === null ? "N/A" : `${advisory.volatilityPct.toFixed(3)}%`}
            </span>
            <span className="rounded-md border border-white/12 bg-white/[0.04] px-3 py-1.5 text-slate-300">
              Executable {advisory.buyExecutable === null ? "N/A" : advisory.buyExecutable ? "Ready" : "Blocked"}
            </span>
          </div>
        </section>

        <section className="rounded-md border border-white/8 bg-[linear-gradient(160deg,rgba(9,14,24,0.94),rgba(4,8,14,0.96))] p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">
                Wave Zone Analyzer
              </p>
              <p className="mt-2 text-sm text-slate-400">
                Advisory probabilities and observed zones from recent snapshot history. This does not change execution behavior.
              </p>
            </div>
            <div className={`rounded-md border px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] ${biasBadgeStyle(wave.summary.dominant_bias)}`}>
              {wave.summary.dominant_bias === "LOW_REVISIT_MORE_LIKELY"
                ? "LOW MAGNET"
                : wave.summary.dominant_bias === "HIGH_REVISIT_MORE_LIKELY"
                  ? "HIGH MAGNET"
                  : "BALANCED"}
            </div>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-md border border-white/8 bg-black/20 p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Current Price</p>
              <p className="mt-1 text-lg font-semibold text-sky-200">{formatPrice(wave.current_price)}</p>
            </div>
            <div className="rounded-md border border-white/8 bg-black/20 p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Weighted Low Revisit</p>
              <p className="mt-1 text-lg font-semibold text-emerald-200">
                {formatPercent(wave.summary.weighted_low_revisit_likelihood_pct)}
              </p>
            </div>
            <div className="rounded-md border border-white/8 bg-black/20 p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Weighted High Revisit</p>
              <p className="mt-1 text-lg font-semibold text-rose-200">
                {formatPercent(wave.summary.weighted_high_revisit_likelihood_pct)}
              </p>
            </div>
            <div className="rounded-md border border-white/8 bg-black/20 p-3">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Dominant Bias</p>
              <p className="mt-1 text-sm font-semibold text-white">{wave.summary.dominant_bias}</p>
            </div>
            <div className="rounded-md border border-white/8 bg-black/20 p-3 sm:col-span-2">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Strongest Overall Low Zone</p>
              <p className="mt-1 text-sm font-semibold text-emerald-200">
                {formatZoneRange(wave.summary.strongest_overall_low_zone)}
              </p>
            </div>
            <div className="rounded-md border border-white/8 bg-black/20 p-3 sm:col-span-2">
              <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Strongest Overall High Zone</p>
              <p className="mt-1 text-sm font-semibold text-rose-200">
                {formatZoneRange(wave.summary.strongest_overall_high_zone)}
              </p>
            </div>
          </div>

          <p className="mt-4 text-xs text-slate-400">
            {wave.summary.data_quality_note}
          </p>

          <div className="mt-4 overflow-x-auto rounded-md border border-white/8 bg-black/20">
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
                        <td className="px-3 py-2 text-slate-400" colSpan={10}>Insufficient data</td>
                      </tr>
                    );
                  }

                  if (row.insufficient_data) {
                    return (
                      <tr key={timeframeKey} className="text-slate-300">
                        <td className="px-3 py-2 font-semibold uppercase">{timeframeKey}</td>
                        <td className="px-3 py-2 text-slate-400" colSpan={10}>Insufficient data</td>
                      </tr>
                    );
                  }

                  return (
                    <tr key={timeframeKey} className="text-slate-200">
                      <td className="px-3 py-2 font-semibold uppercase">{timeframeKey}</td>
                      <td className="px-3 py-2 text-xs text-emerald-200">
                        <div>{formatZoneRange(row.strongest_low_zone)}</div>
                        {row.most_touched_low_zone
                          && row.strongest_low_zone
                          && row.most_touched_low_zone.center !== row.strongest_low_zone.center ? (
                            <div className="mt-0.5 text-[10px] text-slate-400">
                              Most touched: {formatZoneRange(row.most_touched_low_zone)}
                            </div>
                          ) : null}
                      </td>
                      <td className="px-3 py-2 text-right">{row.strongest_low_zone?.touch_count ?? "N/A"}</td>
                      <td className="px-3 py-2 text-right">
                        {formatAgeHours(row.strongest_low_zone?.last_touch_age_hours ?? null)}
                      </td>
                      <td className="px-3 py-2 text-right">{row.strongest_low_zone?.score.toFixed(1) ?? "N/A"}</td>
                      <td className="px-3 py-2 text-right text-emerald-200">
                        {formatPercent(row.low_revisit_likelihood_pct)}
                      </td>
                      <td className="px-3 py-2 text-xs text-rose-200">
                        <div>{formatZoneRange(row.strongest_high_zone)}</div>
                        {row.most_touched_high_zone
                          && row.strongest_high_zone
                          && row.most_touched_high_zone.center !== row.strongest_high_zone.center ? (
                            <div className="mt-0.5 text-[10px] text-slate-400">
                              Most touched: {formatZoneRange(row.most_touched_high_zone)}
                            </div>
                          ) : null}
                      </td>
                      <td className="px-3 py-2 text-right">{row.strongest_high_zone?.touch_count ?? "N/A"}</td>
                      <td className="px-3 py-2 text-right">
                        {formatAgeHours(row.strongest_high_zone?.last_touch_age_hours ?? null)}
                      </td>
                      <td className="px-3 py-2 text-right">{row.strongest_high_zone?.score.toFixed(1) ?? "N/A"}</td>
                      <td className="px-3 py-2 text-right text-rose-200">
                        {formatPercent(row.high_revisit_likelihood_pct)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        <section className="grid gap-6 lg:grid-cols-2">
          <div className="rounded-md border border-white/8 bg-[linear-gradient(160deg,rgba(9,14,24,0.94),rgba(4,8,14,0.96))] p-5 sm:p-6">
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">
              Price Snapshot Trail
            </p>
            <div className="mt-4">
              <PriceSparkline points={data.chart.pricePoints} />
            </div>
          </div>

          <div className="rounded-md border border-white/8 bg-[linear-gradient(160deg,rgba(9,14,24,0.94),rgba(4,8,14,0.96))] p-5 sm:p-6">
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">
              Token Trade Summary
            </p>
            <div className="mt-4 grid grid-cols-3 gap-3">
              <div className="rounded-md border border-emerald-500/25 bg-emerald-500/12 p-3 text-center">
                <p className="text-[11px] uppercase tracking-[0.12em] text-emerald-100">Buys</p>
                <p className="mt-1 text-lg font-semibold text-white">{history.buyCount}</p>
              </div>
              <div className="rounded-md border border-rose-500/25 bg-rose-500/12 p-3 text-center">
                <p className="text-[11px] uppercase tracking-[0.12em] text-rose-100">Sells</p>
                <p className="mt-1 text-lg font-semibold text-white">{history.sellCount}</p>
              </div>
              <div className="rounded-md border border-sky-500/25 bg-sky-500/12 p-3 text-center">
                <p className="text-[11px] uppercase tracking-[0.12em] text-sky-100">Realized</p>
                <p className={`mt-1 text-lg font-semibold ${toneByValue(history.realizedPnlUsd)}`}>
                  {formatCurrency(history.realizedPnlUsd)}
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="rounded-md border border-white/8 bg-[linear-gradient(160deg,rgba(9,14,24,0.94),rgba(4,8,14,0.96))] p-5 sm:p-6">
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">
            Recent Token Trades
          </p>
          <div className="mt-4 overflow-x-auto rounded-md border border-white/8 bg-black/20">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-white/8 text-left text-[11px] uppercase tracking-[0.14em] text-slate-400">
                  <th className="px-3 py-2">Time</th>
                  <th className="px-3 py-2">Side</th>
                  <th className="px-3 py-2 text-right">Price</th>
                  <th className="px-3 py-2 text-right">Size</th>
                  <th className="px-3 py-2 text-right">PnL</th>
                  <th className="px-3 py-2">Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/6">
                {history.recentTrades.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-3 py-4 text-center text-slate-400">
                      No recorded trades for this symbol.
                    </td>
                  </tr>
                ) : (
                  history.recentTrades.map((trade, index) => (
                    <tr key={`${trade.time}-${trade.side}-${index}`} className="text-slate-200">
                      <td className="px-3 py-2 text-xs text-slate-400">
                        {trade.time > 0 ? new Date(trade.time * 1000).toLocaleString() : "N/A"}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={`inline-flex rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] ${
                            trade.side === "BUY"
                              ? "border-emerald-400/35 bg-emerald-500/15 text-emerald-100"
                              : "border-rose-400/35 bg-rose-500/15 text-rose-100"
                          }`}
                        >
                          {trade.side}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right">{formatPrice(trade.price)}</td>
                      <td className="px-3 py-2 text-right">{trade.size.toFixed(6)}</td>
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
      </div>
    </main>
  );
}
