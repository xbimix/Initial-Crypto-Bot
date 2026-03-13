import { NextResponse } from "next/server";
import {
  closeAllLocal,
  formatRouteError,
  shouldUseLocalFallback,
} from "../_lib/stateFallback";

const BACKEND = "http://127.0.0.1:8001";

export async function POST(req: Request) {
  const body = (await req.json().catch(() => ({}))) as { reason?: unknown };

  try {
    const response = await fetch(`${BACKEND}/close-all`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
      const fallback = await closeAllLocal(body);
      return NextResponse.json(fallback);
    }

    return NextResponse.json(
      {
        error: text.trim() ? text : `Close-all failed (${response.status})`,
      },
      { status: response.status || 500 },
    );
  } catch {
    try {
      const fallback = await closeAllLocal(body);
      return NextResponse.json(fallback);
    } catch (error: unknown) {
      const formatted = formatRouteError(error);
      return NextResponse.json(formatted.payload, { status: formatted.status });
    }
  }
}
