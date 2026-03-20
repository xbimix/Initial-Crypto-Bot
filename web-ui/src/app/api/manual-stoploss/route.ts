import { NextResponse } from "next/server";
import { buildMutatingHeaders, requireMutatingAuth } from "../_lib/mutatingAuth";
import {
  formatRouteError,
  readManualStoplossLocal,
  runManualStoplossCheckLocal,
  shouldUseLocalFallback,
  updateManualStoplossLocal,
} from "../_lib/stateFallback";

const BACKEND = "http://127.0.0.1:8001";

type ManualStoplossBody = {
  symbol?: unknown;
  enabled?: unknown;
  type?: unknown;
  value?: unknown;
  action?: unknown;
};

export async function GET() {
  try {
    const response = await fetch(`${BACKEND}/manual-stoploss`, {
      cache: "no-store",
    });
    const text = await response.text();

    if (response.ok && text.trim()) {
      return new NextResponse(text, {
        status: response.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    if (shouldUseLocalFallback(response.status)) {
      const fallback = await readManualStoplossLocal();
      return NextResponse.json(fallback);
    }

    return NextResponse.json(
      {
        error: text.trim() ? text : `Manual stoploss request failed (${response.status})`,
      },
      { status: response.status || 500 },
    );
  } catch {
    try {
      const fallback = await readManualStoplossLocal();
      return NextResponse.json(fallback);
    } catch (error: unknown) {
      const formatted = formatRouteError(error);
      return NextResponse.json(formatted.payload, { status: formatted.status });
    }
  }
}

export async function POST(req: Request) {
  const auth = await requireMutatingAuth(req);
  if (!auth.ok) {
    return auth.response;
  }

  const body = (await req.json()) as ManualStoplossBody;
  const action = String(body.action ?? "").trim().toLowerCase();
  const endpoint = action === "check" ? "/manual-stoploss/check" : "/manual-stoploss";

  try {
    const response = await fetch(`${BACKEND}${endpoint}`, {
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
      const fallback = action === "check"
        ? await runManualStoplossCheckLocal()
        : await updateManualStoplossLocal(body);
      return NextResponse.json(fallback);
    }

    return NextResponse.json(
      {
        error: text.trim() ? text : `Manual stoploss update failed (${response.status})`,
      },
      { status: response.status || 500 },
    );
  } catch {
    try {
      const fallback = action === "check"
        ? await runManualStoplossCheckLocal()
        : await updateManualStoplossLocal(body);
      return NextResponse.json(fallback);
    } catch (error: unknown) {
      const formatted = formatRouteError(error);
      return NextResponse.json(formatted.payload, { status: formatted.status });
    }
  }
}
