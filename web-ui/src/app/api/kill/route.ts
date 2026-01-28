import { NextResponse } from "next/server";
const BASE = "http://127.0.0.1:8001";

export async function POST() {
  const res = await fetch(`${BASE}/kill`, { method: "POST" });
  return NextResponse.json(await res.json());
}
