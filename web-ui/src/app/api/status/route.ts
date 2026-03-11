import { NextResponse } from "next/server";

const BASE = "http://127.0.0.1:8001";

export async function GET() {
  try {
    const res = await fetch(`${BASE}/status`, { cache: "no-store" });
    const text = await res.text();

    if (!text.trim()) {
      return NextResponse.json(
        { error: "Empty response from control backend" },
        { status: 502 },
      );
    }

    return new NextResponse(text, {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
