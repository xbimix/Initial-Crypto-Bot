import { NextResponse } from "next/server";
const BASE = "http://127.0.0.1:8001";

export async function POST(req: Request) {
  const { enabled } = await req.json();
  const res = await fetch(`${BASE}/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ live_trading: enabled }),
  });
  return NextResponse.json(await res.json());
}
