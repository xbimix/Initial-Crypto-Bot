"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { buildMutatingAuthHeaders } from "../lib/mutatingAuthClient";

type AccountAsset = {
  asset: string;
  available: number;
  locked: number;
  total: number;
  estimated_quote_value: number | null;
};

type AccountSnapshot = {
  last_sync_time?: number;
  sync_status?: string;
  sync_error?: string | null;
  assets?: AccountAsset[];
  estimated_total_quote_value?: number;
};

type UniverseRow = {
  symbol: string;
  eligible: boolean;
  reasons: string[];
  quote_asset: string | null;
  current_price?: number | null;
  change_24h_pct?: number | null;
  liquidity_score: number;
  volatility_score: number;
  market_quality_score: number;
  bounce_setup_score: number;
  trend_shift_score: number;
  regime_suggestion: string;
  overall_universe_score: number;
  tracked: boolean;
};

type UniversePayload = {
  generated_at?: number;
  sync_status?: string;
  sync_error?: string | null;
  rows?: UniverseRow[];
  summary?: {
    total_symbols: number;
    eligible_count: number;
    tracked_count: number;
    ineligible_count: number;
    top_score: number;
  };
};

type QuoteFilter = "USD_OR_EUR" | "USD_ONLY" | "EUR_ONLY";

const numberFmt = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
});

const currencyFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

type SortKey =
  | "symbol"
  | "eligible"
  | "current_price"
  | "change_24h_pct"
  | "overall_universe_score"
  | "liquidity_score"
  | "volatility_score"
  | "market_quality_score"
  | "bounce_setup_score"
  | "trend_shift_score"
  | "regime_suggestion"
  | "tracked"
  | "action";

function toneForValue(value: number) {
  if (value >= 70) {
    return "text-emerald-300";
  }
  if (value >= 40) {
    return "text-amber-300";
  }
  return "text-rose-300";
}

function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "N/A";
  }
  const abs = Math.abs(value);
  if (abs >= 1000) {
    return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  if (abs >= 1) {
    return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  }
  return value.toLocaleString("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 8 });
}

function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "N/A";
  }
  return `${value.toFixed(2)}%`;
}

function pctTone(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "text-slate-400";
  }
  if (value > 0) {
    return "text-emerald-300";
  }
  if (value < 0) {
    return "text-rose-300";
  }
  return "text-slate-300";
}

export default function UniversePage() {
  const [account, setAccount] = useState<AccountSnapshot | null>(null);
  const [universe, setUniverse] = useState<UniversePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [busySymbol, setBusySymbol] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"ALL" | "ELIGIBLE" | "TRACKED" | "INELIGIBLE">("ALL");
  const [quoteFilter, setQuoteFilter] = useState<QuoteFilter>("USD_OR_EUR");
  const [minScore, setMinScore] = useState<number>(0);
  const [sortKey, setSortKey] = useState<SortKey>("overall_universe_score");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const refresh = useCallback(async (force = false) => {
    setLoading(true);
    setError(null);
    try {
      const query = force ? "?force=1" : "";
      const [accountRes, universeRes] = await Promise.all([
        fetch(`/api/revolut-account${query}`, { cache: "no-store" }),
        fetch(`/api/revolut-universe${query}`, { cache: "no-store" }),
      ]);
      const accountJson = await accountRes.json();
      const universeJson = await universeRes.json();
      if (!accountRes.ok) {
        throw new Error(accountJson.error ?? `Account sync failed (${accountRes.status})`);
      }
      if (!universeRes.ok) {
        throw new Error(universeJson.error ?? `Universe load failed (${universeRes.status})`);
      }
      setAccount(accountJson);
      setUniverse(universeJson);
    } catch (requestError: unknown) {
      const message = requestError instanceof Error ? requestError.message : "Unknown error";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh(false);
  }, [refresh]);

  const filteredRows = useMemo(() => {
    const allRows = Array.isArray(universe?.rows) ? universe?.rows : [];
    return allRows.filter((row) => {
      const quoteAsset = String(row.quote_asset ?? "").trim().toUpperCase();
      const isTradable = !row.reasons.includes("not_tradable");

      if (!isTradable) {
        return false;
      }

      if (quoteFilter === "USD_ONLY" && quoteAsset !== "USD") {
        return false;
      }
      if (quoteFilter === "EUR_ONLY" && quoteAsset !== "EUR") {
        return false;
      }
      if (quoteFilter === "USD_OR_EUR" && quoteAsset !== "USD" && quoteAsset !== "EUR") {
        return false;
      }

      if (row.overall_universe_score < minScore) {
        return false;
      }
      if (filter === "ELIGIBLE") {
        return row.eligible;
      }
      if (filter === "TRACKED") {
        return row.tracked;
      }
      if (filter === "INELIGIBLE") {
        return !row.eligible;
      }
      return true;
    });
  }, [filter, minScore, quoteFilter, universe?.rows]);

  const rows = useMemo(() => {
    const sorted = [...filteredRows];
    const valueForSort = (row: UniverseRow): number | string | null => {
      switch (sortKey) {
        case "symbol":
          return String(row.symbol || "");
        case "eligible":
          return row.eligible ? 1 : 0;
        case "current_price":
          return Number.isFinite(Number(row.current_price)) ? Number(row.current_price) : null;
        case "change_24h_pct":
          return Number.isFinite(Number(row.change_24h_pct)) ? Number(row.change_24h_pct) : null;
        case "overall_universe_score":
          return Number.isFinite(Number(row.overall_universe_score)) ? Number(row.overall_universe_score) : null;
        case "liquidity_score":
          return Number.isFinite(Number(row.liquidity_score)) ? Number(row.liquidity_score) : null;
        case "volatility_score":
          return Number.isFinite(Number(row.volatility_score)) ? Number(row.volatility_score) : null;
        case "market_quality_score":
          return Number.isFinite(Number(row.market_quality_score)) ? Number(row.market_quality_score) : null;
        case "bounce_setup_score":
          return Number.isFinite(Number(row.bounce_setup_score)) ? Number(row.bounce_setup_score) : null;
        case "trend_shift_score":
          return Number.isFinite(Number(row.trend_shift_score)) ? Number(row.trend_shift_score) : null;
        case "regime_suggestion":
          return String(row.regime_suggestion || "");
        case "tracked":
          return row.tracked ? 1 : 0;
        case "action":
          return row.tracked ? "Remove" : "Add";
        default:
          return null;
      }
    };

    sorted.sort((left, right) => {
      const leftValue = valueForSort(left);
      const rightValue = valueForSort(right);
      if (leftValue === null && rightValue === null) {
        const symCmp = left.symbol.localeCompare(right.symbol);
        return sortDir === "asc" ? symCmp : -symCmp;
      }
      if (leftValue === null) {
        return 1;
      }
      if (rightValue === null) {
        return -1;
      }

      const cmp = typeof leftValue === "number" && typeof rightValue === "number"
        ? leftValue - rightValue
        : String(leftValue).localeCompare(String(rightValue));
      if (cmp === 0) {
        const symCmp = left.symbol.localeCompare(right.symbol);
        return sortDir === "asc" ? symCmp : -symCmp;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [filteredRows, sortDir, sortKey]);

  const toggleSort = useCallback((nextKey: SortKey, defaultDir: "asc" | "desc" = "desc") => {
    if (sortKey === nextKey) {
      setSortDir((prev) => (prev === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(nextKey);
    setSortDir(defaultDir);
  }, [sortKey]);

  const sortArrow = useCallback((key: SortKey) => {
    if (sortKey !== key) {
      return "-";
    }
    return sortDir === "asc" ? "^" : "v";
  }, [sortDir, sortKey]);

  const updateTracked = useCallback(async (symbol: string, tracked: boolean) => {
    setBusySymbol(symbol);
    setError(null);
    try {
      const response = await fetch("/api/universe-track", {
        method: "POST",
        headers: buildMutatingAuthHeaders({
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({ symbol, tracked }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error ?? `Track update failed (${response.status})`);
      }

      setUniverse((prev) => {
        if (!prev || !Array.isArray(prev.rows)) {
          return prev;
        }
        const nextRows = prev.rows.map((row) => (
          row.symbol === symbol
            ? {
              ...row,
              tracked,
              eligible: tracked ? row.eligible : row.eligible,
            }
            : row
        ));
        const summary = prev.summary ?? {
          total_symbols: nextRows.length,
          eligible_count: 0,
          tracked_count: 0,
          ineligible_count: 0,
          top_score: 0,
        };
        return {
          ...prev,
          rows: nextRows,
          summary: {
            ...summary,
            tracked_count: nextRows.filter((row) => row.tracked).length,
          },
        };
      });
    } catch (requestError: unknown) {
      const message = requestError instanceof Error ? requestError.message : "Unknown error";
      setError(message);
    } finally {
      setBusySymbol(null);
    }
  }, []);

  const accountAssets = Array.isArray(account?.assets) ? account.assets : [];

  return (
    <main className="rb-page min-h-screen px-4 py-8 sm:px-6 lg:px-8">
      <div className="rb-shell mx-auto w-full max-w-[1600px] space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="rb-kicker">Revolut X</p>
            <h1 className="rb-title text-3xl tracking-tight sm:text-4xl">Universe Manager</h1>
            <p className="rb-helper mt-2 text-sm">
              Ranked symbol universe with operator-controlled tracked toggles.
            </p>
          </div>
          <div className="flex gap-2">
            <button className="rb-action-btn rb-action-btn--neutral" onClick={() => void refresh(true)} disabled={loading}>
              {loading ? "Refreshing..." : "Refresh"}
            </button>
            <Link href="/" className="rb-action-btn rb-action-btn--neutral">
              Back to Dashboard
            </Link>
          </div>
        </header>

        {error ? (
          <section className="rb-content-card border-rose-400/35 bg-rose-500/12 px-5 py-4 text-sm text-rose-100">
            {error}
          </section>
        ) : null}

        <section className="grid gap-4 md:grid-cols-4">
          <div className="rb-summary-card">
            <p className="rb-metric-label">Eligible</p>
            <p className="rb-metric-value">{universe?.summary?.eligible_count ?? 0}</p>
          </div>
          <div className="rb-summary-card">
            <p className="rb-metric-label">Tracked</p>
            <p className="rb-metric-value">{universe?.summary?.tracked_count ?? 0}</p>
          </div>
          <div className="rb-summary-card">
            <p className="rb-metric-label">Ineligible</p>
            <p className="rb-metric-value">{universe?.summary?.ineligible_count ?? 0}</p>
          </div>
          <div className="rb-summary-card">
            <p className="rb-metric-label">Top Score</p>
            <p className="rb-metric-value">{numberFmt.format(universe?.summary?.top_score ?? 0)}</p>
          </div>
        </section>

        <section className="rb-content-card p-4 sm:p-5">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <button className={`rb-chip ${filter === "ALL" ? "rb-chip--positive" : "rb-chip--neutral"}`} onClick={() => setFilter("ALL")}>All</button>
            <button className={`rb-chip ${filter === "ELIGIBLE" ? "rb-chip--positive" : "rb-chip--neutral"}`} onClick={() => setFilter("ELIGIBLE")}>Eligible</button>
            <button className={`rb-chip ${filter === "TRACKED" ? "rb-chip--positive" : "rb-chip--neutral"}`} onClick={() => setFilter("TRACKED")}>Tracked</button>
            <button className={`rb-chip ${filter === "INELIGIBLE" ? "rb-chip--negative" : "rb-chip--neutral"}`} onClick={() => setFilter("INELIGIBLE")}>Ineligible</button>
            <span className="ml-2 text-[10px] uppercase tracking-[0.12em] text-slate-400">Quote:</span>
            <button className={`rb-chip ${quoteFilter === "USD_OR_EUR" ? "rb-chip--positive" : "rb-chip--neutral"}`} onClick={() => setQuoteFilter("USD_OR_EUR")}>USD + EUR</button>
            <button className={`rb-chip ${quoteFilter === "USD_ONLY" ? "rb-chip--positive" : "rb-chip--neutral"}`} onClick={() => setQuoteFilter("USD_ONLY")}>USD only</button>
            <button className={`rb-chip ${quoteFilter === "EUR_ONLY" ? "rb-chip--positive" : "rb-chip--neutral"}`} onClick={() => setQuoteFilter("EUR_ONLY")}>EUR only</button>
            <label className="ml-auto flex items-center gap-2 text-xs text-slate-300">
              Min Score
              <input
                type="number"
                min={0}
                max={100}
                value={minScore}
                onChange={(event) => setMinScore(Math.max(0, Math.min(100, Number(event.target.value) || 0)))}
                className="w-20 rounded border border-white/20 bg-slate-900 px-2 py-1 text-right text-sm text-slate-100"
              />
            </label>
          </div>
          <div className="rb-table-wrap max-h-[620px] overflow-y-auto overflow-x-auto">
            <table className="rb-table min-w-full text-xs sm:text-sm">
              <thead>
                <tr>
                  <th>
                    <button type="button" className="inline-flex items-center gap-1" onClick={() => toggleSort("symbol", "asc")}>
                      Symbol <span>{sortArrow("symbol")}</span>
                    </button>
                  </th>
                  <th>
                    <button type="button" className="inline-flex items-center gap-1" onClick={() => toggleSort("eligible", "desc")}>
                      Eligible <span>{sortArrow("eligible")}</span>
                    </button>
                  </th>
                  <th>
                    <button type="button" className="inline-flex items-center gap-1" onClick={() => toggleSort("current_price", "desc")}>
                      Current Price <span>{sortArrow("current_price")}</span>
                    </button>
                  </th>
                  <th>
                    <button type="button" className="inline-flex items-center gap-1" onClick={() => toggleSort("change_24h_pct", "desc")}>
                      24H % <span>{sortArrow("change_24h_pct")}</span>
                    </button>
                  </th>
                  <th>
                    <button type="button" className="inline-flex items-center gap-1" onClick={() => toggleSort("overall_universe_score", "desc")}>
                      Score <span>{sortArrow("overall_universe_score")}</span>
                    </button>
                  </th>
                  <th>
                    <button type="button" className="inline-flex items-center gap-1" onClick={() => toggleSort("liquidity_score", "desc")}>
                      Liquidity <span>{sortArrow("liquidity_score")}</span>
                    </button>
                  </th>
                  <th>
                    <button type="button" className="inline-flex items-center gap-1" onClick={() => toggleSort("volatility_score", "desc")}>
                      Volatility <span>{sortArrow("volatility_score")}</span>
                    </button>
                  </th>
                  <th>
                    <button type="button" className="inline-flex items-center gap-1" onClick={() => toggleSort("market_quality_score", "desc")}>
                      Quality <span>{sortArrow("market_quality_score")}</span>
                    </button>
                  </th>
                  <th>
                    <button type="button" className="inline-flex items-center gap-1" onClick={() => toggleSort("bounce_setup_score", "desc")}>
                      Bounce <span>{sortArrow("bounce_setup_score")}</span>
                    </button>
                  </th>
                  <th>
                    <button type="button" className="inline-flex items-center gap-1" onClick={() => toggleSort("trend_shift_score", "desc")}>
                      Trend <span>{sortArrow("trend_shift_score")}</span>
                    </button>
                  </th>
                  <th>
                    <button type="button" className="inline-flex items-center gap-1" onClick={() => toggleSort("regime_suggestion", "asc")}>
                      Regime <span>{sortArrow("regime_suggestion")}</span>
                    </button>
                  </th>
                  <th>
                    <button type="button" className="inline-flex items-center gap-1" onClick={() => toggleSort("tracked", "desc")}>
                      Tracked <span>{sortArrow("tracked")}</span>
                    </button>
                  </th>
                  <th>
                    <button type="button" className="inline-flex items-center gap-1" onClick={() => toggleSort("action", "asc")}>
                      Action <span>{sortArrow("action")}</span>
                    </button>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.symbol}>
                    <td className="font-medium text-slate-100">{row.symbol}</td>
                    <td>
                      {row.eligible
                        ? <span className="rb-chip rb-chip--positive">Yes</span>
                        : <span className="rb-chip rb-chip--negative" title={row.reasons.join(", ")}>{row.reasons[0] ?? "No"}</span>}
                    </td>
                    <td>{formatPrice(row.current_price ?? null)}</td>
                    <td className={pctTone(row.change_24h_pct ?? null)}>{formatPct(row.change_24h_pct ?? null)}</td>
                    <td className={toneForValue(row.overall_universe_score)}>{numberFmt.format(row.overall_universe_score)}</td>
                    <td>{numberFmt.format(row.liquidity_score)}</td>
                    <td>{numberFmt.format(row.volatility_score)}</td>
                    <td>{numberFmt.format(row.market_quality_score)}</td>
                    <td>{numberFmt.format(row.bounce_setup_score)}</td>
                    <td>{numberFmt.format(row.trend_shift_score)}</td>
                    <td>{row.regime_suggestion}</td>
                    <td>{row.tracked ? "ON" : "OFF"}</td>
                    <td>
                      <button
                        className={row.tracked ? "rb-action-btn rb-action-btn--warning" : "rb-action-btn rb-action-btn--positive"}
                        onClick={() => void updateTracked(row.symbol, !row.tracked)}
                        disabled={busySymbol === row.symbol}
                      >
                        {busySymbol === row.symbol
                          ? "Saving..."
                          : row.tracked
                            ? "Remove"
                            : "Add"}
                      </button>
                    </td>
                  </tr>
                ))}
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={13} className="py-4 text-center text-slate-400">No symbols for current filter.</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>

        <section className="rb-content-card p-4 sm:p-5">
          <h2 className="text-lg font-semibold text-slate-100">Revolut Account Snapshot</h2>
          <p className="rb-helper mt-1 text-xs">
            Sync status: {account?.sync_status ?? "unknown"}
            {account?.sync_error ? ` | ${account.sync_error}` : ""}
          </p>
          <div className="rb-table-wrap mt-3 max-h-[420px] overflow-y-auto overflow-x-auto">
            <table className="rb-table min-w-full text-xs sm:text-sm">
              <thead>
                <tr>
                  <th>Asset</th>
                  <th>Available</th>
                  <th>Locked</th>
                  <th>Total</th>
                  <th>Estimated USD Value</th>
                </tr>
              </thead>
              <tbody>
                {accountAssets.map((asset) => (
                  <tr key={asset.asset}>
                    <td className="font-medium text-slate-100">{asset.asset}</td>
                    <td>{numberFmt.format(asset.available)}</td>
                    <td>{numberFmt.format(asset.locked)}</td>
                    <td>{numberFmt.format(asset.total)}</td>
                    <td>{asset.estimated_quote_value === null ? "N/A" : currencyFmt.format(asset.estimated_quote_value)}</td>
                  </tr>
                ))}
                {accountAssets.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-4 text-center text-slate-400">No synced balances available.</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          <p className="rb-helper mt-3 text-xs">
            Estimated total value: {currencyFmt.format(account?.estimated_total_quote_value ?? 0)}
          </p>
        </section>
      </div>
    </main>
  );
}

