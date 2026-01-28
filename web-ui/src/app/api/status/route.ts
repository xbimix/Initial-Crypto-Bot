import { NextResponse } from "next/server";
const BASE = "http://127.0.0.1:8001";

export async function GET() {
  const res = await fetch(`${BASE}/config`, { cache: "no-store" });
  const cfg = await res.json();
  return NextResponse.json({
    enabled: cfg.enabled,
    symbols: cfg.symbols,
    cooldown: cfg.cooldown_seconds,
  });
}
