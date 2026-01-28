import { NextResponse } from "next/server";
const BASE = "http://127.0.0.1:8001";

export async function GET() {
  const res = await fetch(`${BASE}/config`, { cache: "no-store" });
  return NextResponse.json(await res.json());
}

export async function POST(req: Request) {
  const body = await req.json();
  const res = await fetch(`${BASE}/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return NextResponse.json(await res.json());
}
