import { NextResponse } from "next/server";
import { buildMutatingHeaders, requireMutatingAuth } from "../_lib/mutatingAuth";

const BACKEND = "http://127.0.0.1:8001";

export async function GET() {
  try {
    const res = await fetch(`${BACKEND}/config`, {
      cache: "no-store",
    });

    const text = await res.text();

    if (!text) {
      return NextResponse.json(
        { error: "Empty response from Flask backend" },
        { status: 502 }
      );
    }

    return new NextResponse(text, {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err: unknown) {
    const message =
      err instanceof Error ? err.message : "Unknown backend error";
    return NextResponse.json(
      { error: message },
      { status: 500 }
    );
  }
}

export async function POST(req: Request) {
  const auth = await requireMutatingAuth(req);
  if (!auth.ok) {
    return auth.response;
  }

  try {
    const body = await req.json();

    const res = await fetch(`${BACKEND}/config`, {
      method: "POST",
      headers: buildMutatingHeaders(auth),
      body: JSON.stringify(body),
    });

    const text = await res.text();

    if (!text) {
      return NextResponse.json(
        { error: "Empty response from Flask backend" },
        { status: 502 }
      );
    }

    return new NextResponse(text, {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err: unknown) {
    const message =
      err instanceof Error ? err.message : "Unknown backend error";
    return NextResponse.json(
      { error: message },
      { status: 500 }
    );
  }
}
