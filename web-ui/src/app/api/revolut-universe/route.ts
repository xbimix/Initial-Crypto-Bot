import { NextResponse } from "next/server";
import {
  formatRouteError,
  readRevolutUniverseLocal,
  shouldUseLocalFallback,
} from "../_lib/stateFallback";

const BACKEND = "http://127.0.0.1:8001";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const force = String(url.searchParams.get("force") ?? "").trim().toLowerCase();
  const forceFlag = force === "1" || force === "true" || force === "yes";
  const query = forceFlag ? "?force=1" : "";

  try {
    const response = await fetch(`${BACKEND}/revolut-universe${query}`, { cache: "no-store" });
    if (shouldUseLocalFallback(response.status)) {
      const fallback = await readRevolutUniverseLocal();
      return NextResponse.json(fallback);
    }

    const text = await response.text();
    if (!text.trim()) {
      const fallback = await readRevolutUniverseLocal();
      return NextResponse.json(fallback);
    }

    return new NextResponse(text, {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    try {
      const fallback = await readRevolutUniverseLocal();
      return NextResponse.json(fallback);
    } catch (error: unknown) {
      const formatted = formatRouteError(error);
      return NextResponse.json(formatted.payload, { status: formatted.status });
    }
  }
}
