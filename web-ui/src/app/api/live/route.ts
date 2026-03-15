import { NextResponse } from "next/server";
import { buildMutatingHeaders, requireMutatingAuth } from "../_lib/mutatingAuth";
const BASE = "http://127.0.0.1:8001";

export async function POST(req: Request) {
  const auth = await requireMutatingAuth(req);
  if (!auth.ok) {
    return auth.response;
  }

  const { enabled } = await req.json();
  const res = await fetch(`${BASE}/config`, {
    method: "POST",
    headers: buildMutatingHeaders(auth),
    body: JSON.stringify({ live_trading: enabled }),
  });
  return NextResponse.json(await res.json());
}
