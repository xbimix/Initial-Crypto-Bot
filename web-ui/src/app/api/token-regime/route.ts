import { NextResponse } from "next/server";
import { buildMutatingHeaders, requireMutatingAuth } from "../_lib/mutatingAuth";
import {
  formatRouteError,
  shouldUseLocalFallback,
  updateTokenRegimeLocal,
} from "../_lib/stateFallback";

const BACKEND = "http://127.0.0.1:8001";

export async function POST(req: Request) {
  const auth = await requireMutatingAuth(req);
  if (!auth.ok) {
    return auth.response;
  }

  const body = (await req.json()) as {
    symbol?: unknown;
    regime?: unknown;
  };

  try {
    const response = await fetch(`${BACKEND}/token-regime`, {
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
      const fallback = await updateTokenRegimeLocal(body);
      return NextResponse.json(fallback);
    }

    return NextResponse.json(
      {
        error: text.trim() ? text : `Token regime update failed (${response.status})`,
      },
      { status: response.status || 500 },
    );
  } catch {
    try {
      const fallback = await updateTokenRegimeLocal(body);
      return NextResponse.json(fallback);
    } catch (error: unknown) {
      const formatted = formatRouteError(error);
      return NextResponse.json(formatted.payload, { status: formatted.status });
    }
  }
}
