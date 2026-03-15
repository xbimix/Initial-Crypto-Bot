import { NextResponse } from "next/server";
import { buildMutatingHeaders, requireMutatingAuth } from "../_lib/mutatingAuth";
import {
  formatRouteError,
  shouldUseLocalFallback,
  updateRiskLocal,
} from "../_lib/stateFallback";

const BACKEND = "http://127.0.0.1:8001";

export async function POST(req: Request) {
  const auth = await requireMutatingAuth(req);
  if (!auth.ok) {
    return auth.response;
  }

  const body = (await req.json()) as {
    maxConcurrentTrades?: unknown;
    maxConcurrentTradesPerToken?: unknown;
    maxTradeAmountUsd?: unknown;
    tradeAmountUsd?: unknown;
    maxPortfolioExposurePct?: unknown;
    maxExposurePerTokenPct?: unknown;
    dailyLossLimitUsd?: unknown;
    dailyLossAutoPause?: unknown;
    dailyLossCloseAll?: unknown;
    signalConfirmationCycles?: unknown;
    tradeWindowEnabled?: unknown;
    tradeWindowStartHourUtc?: unknown;
    tradeWindowEndHourUtc?: unknown;
  };

  try {
    const response = await fetch(`${BACKEND}/risk`, {
      method: "POST",
      headers: buildMutatingHeaders(auth),
      body: JSON.stringify(body),
    });

    const text = await response.text();
    if (response.ok && text.trim()) {
      return new NextResponse(text, {
        status: response.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    if (shouldUseLocalFallback(response.status)) {
      const fallback = await updateRiskLocal(body);
      return NextResponse.json(fallback);
    }

    return NextResponse.json(
      { error: text.trim() ? text : `Risk update failed (${response.status})` },
      { status: response.status || 500 },
    );
  } catch {
    try {
      const fallback = await updateRiskLocal(body);
      return NextResponse.json(fallback);
    } catch (error: unknown) {
      const formatted = formatRouteError(error);
      return NextResponse.json(formatted.payload, { status: formatted.status });
    }
  }
}
