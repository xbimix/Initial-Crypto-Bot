import { NextResponse } from "next/server";
import { buildMutatingHeaders, requireMutatingAuth } from "../_lib/mutatingAuth";
import {
  applyControlLocal,
  formatRouteError,
  shouldUseLocalFallback,
} from "../_lib/stateFallback";

const BASE = "http://127.0.0.1:8001";

export async function POST(req: Request) {
  const auth = await requireMutatingAuth(req);
  if (!auth.ok) {
    return auth.response;
  }

  try {
    const res = await fetch(`${BASE}/kill`, {
      method: "POST",
      headers: buildMutatingHeaders(auth),
    });
    const text = await res.text();

    if (res.ok && text.trim()) {
      return new NextResponse(text, {
        status: res.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    if (shouldUseLocalFallback(res.status)) {
      const fallback = await applyControlLocal({ action: "KILL" });
      return NextResponse.json(fallback);
    }

    return NextResponse.json(
      { error: text.trim() ? text : `Kill request failed (${res.status})` },
      { status: res.status || 500 },
    );
  } catch {
    try {
      const fallback = await applyControlLocal({ action: "KILL" });
      return NextResponse.json(fallback);
    } catch (error: unknown) {
      const formatted = formatRouteError(error);
      return NextResponse.json(formatted.payload, { status: formatted.status });
    }
  }
}
