"use client";

import { startTransition, useEffect, useState } from "react";

type DashboardPayload = {
  generatedAt: string;
  summary: {
    enabled: boolean;
    executionMode: string;
    trackedSymbols: number;
    cooldownSeconds: number;
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
    lastTradeAt: number | null;
    lastTradeReason: string | null;
    lastSnapshotAt: string | null;
    buyCount: number;
    sellCount: number;
  };
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
    thesis: string;
  }>;
};

const RANGE_OPTIONS = [
  { id: "recent", label: "Live", points: 8 },
  { id: "session", label: "Session", points: 14 },
  { id: "all", label: "All", points: Number.POSITIVE_INFINITY },
] as const;

type RangeId = (typeof RANGE_OPTIONS)[number]["id"];

const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
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
    <div className="relative h-[320px] overflow-hidden rounded-[28px] border border-white/6 bg-[radial-gradient(circle_at_top_left,_rgba(96,165,250,0.15),_transparent_40%),linear-gradient(180deg,rgba(255,255,255,0.03),rgba(255,255,255,0.01))] p-4">
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

      <div className="pointer-events-none absolute right-5 top-5 rounded-full bg-black/35 px-3 py-1 text-xs text-slate-300">
        High {formatCompactCurrency(max)}
      </div>
      <div className="pointer-events-none absolute bottom-5 right-5 rounded-full bg-black/35 px-3 py-1 text-xs text-slate-400">
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

  async function loadDashboard() {
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
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Unable to load dashboard";
      setError(message);
    }
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
          ? { method: "POST" }
          : {
              method: "POST",
              headers: { "Content-Type": "application/json" },
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
  }, []);

  if (!data) {
    return (
      <main className="min-h-screen px-4 py-6 sm:px-6 lg:px-8">
        <div className="mx-auto flex max-w-[1480px] gap-5">
          <div className="hidden w-20 shrink-0 rounded-[30px] border border-white/8 bg-black/40 lg:block" />
          <div className="flex-1 space-y-6">
            <div className="h-[420px] animate-pulse rounded-[36px] border border-white/8 bg-white/[0.04]" />
            <div className="grid gap-6 lg:grid-cols-3">
              <div className="h-40 animate-pulse rounded-[28px] border border-white/8 bg-white/[0.04]" />
              <div className="h-40 animate-pulse rounded-[28px] border border-white/8 bg-white/[0.04]" />
              <div className="h-40 animate-pulse rounded-[28px] border border-white/8 bg-white/[0.04]" />
            </div>
            <div className="h-[420px] animate-pulse rounded-[32px] border border-white/8 bg-white/[0.04]" />
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
  const comparisonRows = [
    {
      metric: "Runtime",
      accountValue: `${data.summary.enabled ? "Running" : "Paused"} | ${String(
        data.summary.executionMode,
      ).toUpperCase()}`,
      accountTone: data.summary.enabled ? "text-emerald-300" : "text-rose-300",
      configValue: `${data.summary.cooldownSeconds}s cool | ${data.summary.loopSeconds}s loop`,
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
      configValue: `${data.summary.trackedSymbols} tracked | ${data.summary.openPositions} open`,
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
      <div className="mx-auto flex max-w-[1480px] gap-5">
        <aside className="hidden w-20 shrink-0 flex-col rounded-[30px] border border-white/8 bg-black/45 p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)] lg:flex">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[linear-gradient(135deg,#f8fafc,#93c5fd_45%,#f59e0b)] text-lg font-bold text-slate-950">
            R
          </div>
          <div className="mt-6 space-y-2.5 text-center text-[10px] font-medium text-slate-400">
            <div className="rounded-2xl border border-white/10 bg-white/[0.06] px-2 py-2.5 text-white">
              Home
            </div>
            <div className="rounded-2xl px-2 py-2.5">Portfolio</div>
            <div className="rounded-2xl px-2 py-2.5">Control</div>
            <div className="rounded-2xl px-2 py-2.5">Risk</div>
          </div>
          <div className="mt-auto rounded-3xl border border-white/10 bg-white/[0.04] p-2.5 text-center">
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
                  className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] ${
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
            </div>
          </header>

          {error ? (
            <div className="rounded-[28px] border border-rose-400/20 bg-rose-500/10 px-5 py-4 text-sm text-rose-100">
              {error}
            </div>
          ) : null}

          <section className="space-y-6">
            <div className="rounded-[36px] border border-white/8 bg-[linear-gradient(135deg,rgba(15,23,42,0.94),rgba(9,9,11,0.96))] p-5 shadow-[0_20px_90px_rgba(0,0,0,0.35)] sm:p-6">
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

                  <div className="flex flex-wrap items-center gap-2 rounded-full border border-white/8 bg-white/[0.04] p-1">
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

                <div className="overflow-x-auto rounded-[26px] border border-white/8 bg-black/20">
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

                  <div className="mt-5 overflow-x-auto rounded-[26px] border border-white/8 bg-black/20">
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
                    <span className="rounded-full border border-emerald-400/15 bg-emerald-500/8 px-3 py-1.5 text-emerald-200">
                      {data.summary.buyCount} buys
                    </span>
                    <span className="rounded-full border border-rose-400/15 bg-rose-500/8 px-3 py-1.5 text-rose-200">
                      {data.summary.sellCount} sells
                    </span>
                    <span className="rounded-full border border-sky-400/15 bg-sky-500/[0.07] px-3 py-1.5 text-sky-100">
                      {data.summary.openPositions} open positions
                    </span>
                    <span className="rounded-full border border-white/8 bg-white/[0.03] px-3 py-1.5 text-slate-300">
                      {data.summary.trackedSymbols} tracked symbols
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section className="rounded-[36px] border border-white/8 bg-[linear-gradient(180deg,rgba(8,12,20,0.92),rgba(6,8,13,0.98))] p-5 shadow-[0_20px_90px_rgba(0,0,0,0.35)] sm:p-6">
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
                <span className="rounded-full border border-sky-400/15 bg-sky-500/[0.07] px-4 py-2 text-sky-100">
                  {data.summary.openPositions} open positions
                </span>
                <span className="rounded-full border border-white/10 bg-white/[0.04] px-4 py-2 text-slate-300">
                  {data.summary.trackedSymbols} tracked symbols
                </span>
              </div>
            </div>

            <div className="mt-6 overflow-x-auto rounded-[28px] border border-white/8 bg-black/20">
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
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/6">
                  {data.positions.map((position) => (
                    <tr
                      key={position.symbol}
                      className={`text-[14px] text-slate-200 transition hover:bg-white/[0.045] ${
                        position.symbol === topWinnerSymbol
                          ? "bg-emerald-500/[0.04]"
                          : position.symbol === topExposureSymbol
                            ? "bg-sky-500/[0.035]"
                            : "bg-white/[0.025]"
                      }`}
                    >
                      <td className="px-4 py-3 align-middle">
                        <div className="flex items-center gap-3">
                          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[linear-gradient(135deg,rgba(248,250,252,0.16),rgba(59,130,246,0.22))] text-xs font-semibold text-white">
                            {position.symbol.slice(0, 2)}
                          </div>
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="text-sm font-semibold text-white">
                                {position.symbol}
                              </p>
                              {position.symbol === topExposureSymbol ? (
                                <span className="rounded-full border border-sky-400/20 bg-sky-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-sky-200">
                                  Top size
                                </span>
                              ) : null}
                              {position.symbol === topWinnerSymbol ? (
                                <span className="rounded-full border border-emerald-400/20 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-emerald-200">
                                  Top gain
                                </span>
                              ) : null}
                            </div>
                            <p className="mt-1 truncate text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">
                              {position.thesis.replaceAll("_", " ")}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right font-medium text-slate-200">
                        {formatUnits(position.units)}
                      </td>
                      <td className="px-4 py-3 text-right font-medium text-slate-300">
                        {formatCurrency(position.entryPrice)}
                      </td>
                      <td
                        className={`px-4 py-3 text-right font-semibold ${compareTone(
                          position.currentPrice,
                          position.entryPrice,
                        )}`}
                      >
                        {position.currentPrice === null ? "Pending" : formatCurrency(position.currentPrice)}
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
                            className={`inline-flex w-fit rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] ${statusTone(
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
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex flex-wrap gap-2 text-[11px] font-medium uppercase tracking-[0.14em] text-slate-500">
              <span className="rounded-full border border-white/8 bg-white/[0.03] px-3 py-1.5">
                Sorted by value
              </span>
              {topExposureSymbol ? (
                <span className="rounded-full border border-sky-400/15 bg-sky-500/8 px-3 py-1.5 text-sky-200">
                  Largest position: {topExposureSymbol}
                </span>
              ) : null}
              {topWinnerSymbol ? (
                <span className="rounded-full border border-emerald-400/15 bg-emerald-500/8 px-3 py-1.5 text-emerald-200">
                  Strongest winner: {topWinnerSymbol}
                </span>
              ) : null}
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
