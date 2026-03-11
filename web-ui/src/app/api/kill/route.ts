import { NextResponse } from "next/server";
import {
  applyControlLocal,
  formatRouteError,
  shouldUseLocalFallback,
} from "../_lib/stateFallback";

const BASE = "http://127.0.0.1:8001";

export async function POST() {
  try {
    const res = await fetch(`${BASE}/kill`, { method: "POST" });
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
