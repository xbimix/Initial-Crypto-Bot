import { promises as fs } from "fs";
import path from "path";
import { NextResponse } from "next/server";
import { analyzeWaveZones } from "../../../lib/waveZoneAnalyzer.mjs";

type DashboardSummary = {
  staleLosingReviewThresholdAgeHours?: number;
  staleLosingReviewThresholdUnrealizedPnlPct?: number;
};

type DashboardPosition = {
  symbol: string;
  units: number;
  entryPrice: number;
  currentPrice: number | null;
  marketValue: number;
  unrealizedValue: number;
  unrealizedPct: number;
  entryTime: number | null;
  advisoryStaleLosingReview?: boolean;
  advisoryReviewAgeHours?: number | null;
  advisoryMaxDrawdownPctDuringTrade?: number;
  advisoryMaxDrawdownPriceDuringTrade?: number | null;
  advisoryMaxDrawdownAt?: number | null;
};

type DashboardSymbolControl = {
  symbol: string;
  regime: string | null;
  volatilityPct: number | null;
  strategyScorePct: number | null;
  buyOpportunityPct: number | null;
  buyExecutable?: boolean;
  buyExecutableReason?: string;
  capitalEfficiencyScore?: number | null;
  capitalWasteRank?: number | null;
};

type DashboardPayload = {
  summary?: DashboardSummary;
  positions?: DashboardPosition[];
  symbolControls?: DashboardSymbolControl[];
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

type SnapshotPoint = {
  tsEpoch: number;
  price: number;
};

const STATE_DIR = path.resolve(process.cwd(), "..", "crypto_bot", "state");
const TRADES_PATH = path.join(STATE_DIR, "trades.json");
const LOG_PATH = path.join(STATE_DIR, "bot.log");
const LOG_TAIL_BYTES = 256 * 1024;

function normalizeSymbol(value: string) {
  return value.trim().toUpperCase();
}

function asNumber(value: unknown): number | null {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
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

function parseSnapshotHistory(symbol: string, logTail: string): SnapshotPoint[] {
  const rows: SnapshotPoint[] = [];
  const pattern =
    /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\|\s+INFO\s+\|\s+SNAPSHOT\s+([A-Z0-9-]+)\s+\|\s+(.+)$/;
  const pricePattern = /\bprice=([0-9.]+)/;

  for (const line of logTail.split(/\r?\n/)) {
    const match = line.match(pattern);
    if (!match) {
      continue;
    }
    if (match[2] !== symbol) {
      continue;
    }
    const priceMatch = match[3].match(pricePattern);
    const price = asNumber(priceMatch?.[1]);
    const tsEpoch = parseLogTimestampToEpoch(match[1]);
    if (price === null || price <= 0 || tsEpoch === null) {
      continue;
    }
    rows.push({ tsEpoch, price });
  }

  return rows;
}

function opportunityLabel(score: number | null) {
  if (score === null) {
    return "unknown";
  }
  if (score >= 70) {
    return "strong_setup";
  }
  if (score >= 45) {
    return "developing_setup";
  }
  if (score >= 25) {
    return "early_setup";
  }
  return "weak_setup";
}

export async function GET(
  req: Request,
  context: { params: Promise<{ symbol: string }> },
) {
  const { symbol: rawSymbol } = await context.params;
  const symbol = normalizeSymbol(decodeURIComponent(rawSymbol ?? ""));
  if (!symbol) {
    return NextResponse.json(
      { error: "Invalid symbol" },
      { status: 400 },
    );
  }

  const origin = new URL(req.url).origin;
  const [dashboardRes, trades, logTail] = await Promise.all([
    fetch(`${origin}/api/dashboard`, { cache: "no-store" }),
    readJson<TradeEntry[]>(TRADES_PATH, []),
    readLogTail(LOG_PATH, LOG_TAIL_BYTES),
  ]);

  if (!dashboardRes.ok) {
    const text = await dashboardRes.text();
    return NextResponse.json(
      { error: text || "Failed to read dashboard data" },
      { status: 502 },
    );
  }

  const dashboard = await dashboardRes.json() as DashboardPayload;
  const positions = Array.isArray(dashboard.positions) ? dashboard.positions : [];
  const symbolControls = Array.isArray(dashboard.symbolControls)
    ? dashboard.symbolControls
    : [];
  const position = positions.find((row) => row.symbol === symbol) ?? null;
  const control = symbolControls.find((row) => row.symbol === symbol) ?? null;
  const summary = dashboard.summary ?? {};

  const snapshotHistory = parseSnapshotHistory(symbol, logTail);
  const latestSnapshot = snapshotHistory[snapshotHistory.length - 1] ?? null;

  const currentPrice = position?.currentPrice ?? latestSnapshot?.price ?? null;
  const currentPriceAt = latestSnapshot
    ? new Date(latestSnapshot.tsEpoch * 1000).toISOString()
    : null;

  const symbolTrades = (Array.isArray(trades) ? trades : [])
    .filter((trade) => normalizeSymbol(String(trade.symbol ?? "")) === symbol)
    .sort((left, right) => Number(right.time ?? 0) - Number(left.time ?? 0));

  const buyCount = symbolTrades.filter(
    (trade) => String(trade.side ?? "").toUpperCase() === "BUY",
  ).length;
  const sellCount = symbolTrades.filter(
    (trade) => String(trade.side ?? "").toUpperCase() === "SELL",
  ).length;
  const realizedPnlUsd = symbolTrades
    .filter((trade) => String(trade.side ?? "").toUpperCase() === "SELL")
    .reduce((total, trade) => total + Number(trade.pnl ?? 0), 0);
  const waveZoneAnalyzer = analyzeWaveZones({
    symbol,
    pricePoints: snapshotHistory,
    currentPrice: currentPrice ?? 0,
    nowEpoch: Date.now() / 1000,
  });

  return NextResponse.json({
    generatedAt: new Date().toISOString(),
    symbol,
    summary: {
      symbol,
      currentPrice,
      currentPriceAt,
      hasOpenPosition: position !== null,
      openUnits: position?.units ?? 0,
      entryPrice: position?.entryPrice ?? null,
      marketValue: position?.marketValue ?? 0,
      unrealizedPnlUsd: position?.unrealizedValue ?? 0,
      unrealizedPnlPct: position?.unrealizedPct ?? 0,
      positionAgeHours: position?.advisoryReviewAgeHours ?? null,
      maxDrawdownSinceEntryPct: position?.advisoryMaxDrawdownPctDuringTrade ?? 0,
      maxDrawdownSinceEntryPrice: position?.advisoryMaxDrawdownPriceDuringTrade ?? null,
      maxDrawdownSinceEntryAt: position?.advisoryMaxDrawdownAt ?? null,
    },
    advisory: {
      staleLosingReview: position?.advisoryStaleLosingReview ?? false,
      staleReviewAgeHours: position?.advisoryReviewAgeHours ?? null,
      staleReviewThresholdAgeHours:
        summary.staleLosingReviewThresholdAgeHours ?? null,
      staleReviewThresholdUnrealizedPnlPct:
        summary.staleLosingReviewThresholdUnrealizedPnlPct ?? null,
      volatilityOpportunityScorePct: control?.buyOpportunityPct ?? null,
      volatilityOpportunityLabel: opportunityLabel(control?.buyOpportunityPct ?? null),
      regime: control?.regime ?? null,
      strategyScorePct: control?.strategyScorePct ?? null,
      volatilityPct: control?.volatilityPct ?? null,
      buyExecutable: control?.buyExecutable ?? null,
      buyExecutableReason: control?.buyExecutableReason ?? null,
      capitalEfficiencyScore: control?.capitalEfficiencyScore ?? null,
      capitalWasteRank: control?.capitalWasteRank ?? null,
    },
    history: {
      buyCount,
      sellCount,
      realizedPnlUsd,
      recentTrades: symbolTrades.slice(0, 40).map((trade) => ({
        time: Number(trade.time ?? 0),
        side: String(trade.side ?? "").toUpperCase(),
        price: Number(trade.price ?? 0),
        size: Number(trade.size ?? 0),
        reason: String(trade.reason ?? "unknown"),
        pnl: trade.pnl === undefined ? null : Number(trade.pnl),
        balance: trade.balance === undefined ? null : Number(trade.balance),
      })),
    },
    chart: {
      pricePoints: snapshotHistory.slice(-200),
      tradeMarkers: symbolTrades.slice(0, 40).map((trade) => ({
        time: Number(trade.time ?? 0),
        side: String(trade.side ?? "").toUpperCase(),
        price: Number(trade.price ?? 0),
      })),
    },
    waveZoneAnalyzer,
  });
}
