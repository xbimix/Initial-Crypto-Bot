import { NextResponse } from "next/server";

const BASE = "http://127.0.0.1:8001";

export async function POST(req: Request) {
  const { action } = await req.json(); // "start" | "stop"

  const res = await fetch(`${BASE}/${action}`, { method: "POST" });
  return NextResponse.json(await res.json());
}
